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
        
        old_payment_status = self.payment_status
        
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
        
        # Nếu payment_status thay đổi, sync lên Re-enrollment (nếu có)
        if old_payment_status != self.payment_status:
            self.sync_payment_to_reenrollment()
    
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
    
    def sync_payment_to_reenrollment(self):
        """
        Tự động sync payment_status từ Finance Student lên Re-enrollment (nếu có link).
        
        Đồng bộ chính xác trạng thái (không mapping):
        - Finance "paid" → Re-enrollment "paid"
        - Finance "partial" → Re-enrollment "partial"
        - Finance "unpaid" → Re-enrollment "unpaid"
        - Finance "no_fee" → Re-enrollment "unpaid"
        """
        try:
            # Tìm Re-enrollment có link với Finance Student này
            reenrollment = frappe.db.get_value(
                "SIS Re-enrollment",
                {"finance_student_id": self.name},
                ["name", "payment_status"],
                as_dict=True
            )
            
            if not reenrollment:
                return  # Không có Re-enrollment liên kết
            
            # Map payment status - giữ nguyên trạng thái, chỉ chuyển no_fee → unpaid
            new_status = self.payment_status if self.payment_status in ['paid', 'partial', 'unpaid'] else 'unpaid'
            
            # Chỉ update nếu khác
            if reenrollment.payment_status != new_status:
                frappe.db.set_value(
                    "SIS Re-enrollment",
                    reenrollment.name,
                    "payment_status",
                    new_status,
                    update_modified=False
                )
                frappe.db.commit()
                
        except Exception as e:
            # Log error nhưng không làm fail transaction chính
            frappe.log_error(
                f"Lỗi sync payment to re-enrollment: {str(e)}",
                "Finance Student Payment Sync"
            )

