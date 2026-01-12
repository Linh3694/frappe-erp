# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISFinanceStudent(Document):
    """
    Doctype quản lý học sinh thuộc năm tài chính.
    Được đồng bộ từ SIS Class Student.
    """
    
    def validate(self):
        """Validate dữ liệu trước khi lưu"""
        self.validate_unique_student_in_year()
    
    def validate_unique_student_in_year(self):
        """Kiểm tra học sinh không trùng trong cùng năm tài chính"""
        existing = frappe.db.get_value(
            "SIS Finance Student",
            {
                "finance_year_id": self.finance_year_id,
                "student_id": self.student_id,
                "name": ("!=", self.name)
            },
            "name"
        )
        if existing:
            frappe.throw(f"Học sinh này đã tồn tại trong năm tài chính: {existing}")
    
    def update_finance_summary(self):
        """Cập nhật tổng hợp tài chính cho học sinh"""
        # Lấy tổng các khoản phí từ Order Items
        summary = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(amount), 0) as total_amount,
                COALESCE(SUM(paid_amount), 0) as paid_amount
            FROM `tabSIS Finance Order Item`
            WHERE finance_student_id = %s
        """, (self.name,), as_dict=True)
        
        if summary:
            self.total_amount = summary[0].get('total_amount', 0)
            self.paid_amount = summary[0].get('paid_amount', 0)
            self.outstanding_amount = self.total_amount - self.paid_amount
            
            # Cập nhật trạng thái thanh toán
            if self.paid_amount <= 0:
                self.payment_status = 'unpaid'
            elif self.paid_amount >= self.total_amount:
                self.payment_status = 'paid'
            else:
                self.payment_status = 'partial'
        
        self.db_update()
    
    def after_insert(self):
        """Cập nhật thống kê năm tài chính sau khi thêm học sinh"""
        self.update_finance_year_statistics()
    
    def on_trash(self):
        """Cập nhật thống kê năm tài chính sau khi xóa học sinh"""
        self.update_finance_year_statistics()
    
    def update_finance_year_statistics(self):
        """Cập nhật thống kê cho năm tài chính"""
        try:
            finance_year = frappe.get_doc("SIS Finance Year", self.finance_year_id)
            finance_year.update_statistics()
        except Exception:
            pass  # Bỏ qua nếu không tìm thấy năm tài chính

