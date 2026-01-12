# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SISFinanceOrder(Document):
    """
    Doctype quản lý đơn hàng/khoản phí trong năm tài chính.
    Mỗi đơn hàng đại diện cho một loại khoản phí (học phí, phí dịch vụ, etc.)
    """
    
    def before_insert(self):
        """Thiết lập các giá trị mặc định khi tạo mới"""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.created_at:
            self.created_at = now()
    
    def before_save(self):
        """Cập nhật thời gian sửa đổi"""
        self.updated_at = now()
    
    def validate(self):
        """Validate dữ liệu trước khi lưu"""
        self.validate_installment_count()
        self.validate_amount()
    
    def validate_installment_count(self):
        """Kiểm tra số kỳ thanh toán"""
        if self.payment_type == 'installment':
            if not self.installment_count or self.installment_count < 2:
                frappe.throw("Số kỳ thanh toán phải >= 2 nếu chọn thanh toán chia kỳ")
        else:
            self.installment_count = 1
    
    def validate_amount(self):
        """Kiểm tra số tiền hợp lệ"""
        if self.total_amount and self.total_amount < 0:
            frappe.throw("Số tiền không được âm")
    
    def update_statistics(self):
        """Cập nhật thống kê cho đơn hàng"""
        # Đếm số học sinh trong đơn hàng
        self.total_students = frappe.db.count(
            "SIS Finance Order Item",
            {"order_id": self.name}
        )
        
        # Tính tổng đã thu và còn phải thu
        summary = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(amount), 0) as total_amount,
                COALESCE(SUM(paid_amount), 0) as total_paid
            FROM `tabSIS Finance Order Item`
            WHERE order_id = %s
        """, (self.name,), as_dict=True)
        
        if summary:
            total_amount = summary[0].get('total_amount', 0)
            self.total_collected = summary[0].get('total_paid', 0)
            self.total_outstanding = total_amount - self.total_collected
            
            # Tính tỷ lệ thu
            if total_amount > 0:
                self.collection_rate = (self.total_collected / total_amount) * 100
            else:
                self.collection_rate = 0
        
        self.db_update()
    
    def after_insert(self):
        """Cập nhật thống kê năm tài chính sau khi thêm đơn hàng"""
        self.update_finance_year_statistics()
    
    def on_trash(self):
        """Cập nhật thống kê năm tài chính sau khi xóa đơn hàng"""
        self.update_finance_year_statistics()
    
    def update_finance_year_statistics(self):
        """Cập nhật thống kê cho năm tài chính"""
        try:
            finance_year = frappe.get_doc("SIS Finance Year", self.finance_year_id)
            finance_year.update_statistics()
        except Exception:
            pass

