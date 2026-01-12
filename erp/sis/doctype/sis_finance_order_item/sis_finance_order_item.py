# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now, getdate, nowdate


class SISFinanceOrderItem(Document):
    """
    Doctype quản lý chi tiết khoản phí của từng học sinh.
    Liên kết với SIS Finance Order và SIS Finance Student.
    """
    
    def before_insert(self):
        """Thiết lập các giá trị mặc định khi tạo mới"""
        if not self.created_at:
            self.created_at = now()
    
    def before_save(self):
        """Cập nhật thời gian sửa đổi và tính toán các giá trị"""
        self.updated_at = now()
        self.calculate_amounts()
        self.update_payment_status()
    
    def validate(self):
        """Validate dữ liệu trước khi lưu"""
        self.validate_unique_order_student()
        self.validate_amounts()
    
    def validate_unique_order_student(self):
        """Kiểm tra học sinh không trùng trong cùng đơn hàng"""
        existing = frappe.db.get_value(
            "SIS Finance Order Item",
            {
                "order_id": self.order_id,
                "finance_student_id": self.finance_student_id,
                "name": ("!=", self.name)
            },
            "name"
        )
        if existing:
            frappe.throw(f"Học sinh này đã tồn tại trong đơn hàng: {existing}")
    
    def validate_amounts(self):
        """Kiểm tra các giá trị tiền hợp lệ"""
        if self.amount and self.amount < 0:
            frappe.throw("Số tiền gốc không được âm")
        if self.paid_amount and self.paid_amount < 0:
            frappe.throw("Số tiền đã đóng không được âm")
        if self.discount_amount and self.discount_amount < 0:
            frappe.throw("Số tiền giảm giá không được âm")
    
    def calculate_amounts(self):
        """Tính toán số tiền phải đóng và còn nợ"""
        amount = self.amount or 0
        discount = self.discount_amount or 0
        late_fee = self.late_fee or 0
        paid = self.paid_amount or 0
        
        # Tính số tiền phải đóng
        self.final_amount = amount - discount + late_fee
        
        # Tính số tiền còn nợ
        self.outstanding_amount = max(0, self.final_amount - paid)
    
    def update_payment_status(self):
        """Cập nhật trạng thái thanh toán"""
        paid = self.paid_amount or 0
        final = self.final_amount or 0
        
        if paid <= 0:
            self.payment_status = 'unpaid'
        elif paid >= final:
            self.payment_status = 'paid'
        else:
            self.payment_status = 'partial'
    
    def after_insert(self):
        """Cập nhật thống kê sau khi thêm item"""
        self.update_related_statistics()
    
    def on_update(self):
        """Cập nhật thống kê sau khi sửa item"""
        self.update_related_statistics()
    
    def on_trash(self):
        """Cập nhật thống kê sau khi xóa item"""
        self.update_related_statistics()
    
    def update_related_statistics(self):
        """Cập nhật thống kê cho đơn hàng và học sinh"""
        try:
            # Cập nhật thống kê đơn hàng
            order = frappe.get_doc("SIS Finance Order", self.order_id)
            order.update_statistics()
            
            # Cập nhật tổng hợp tài chính của học sinh
            finance_student = frappe.get_doc("SIS Finance Student", self.finance_student_id)
            finance_student.update_finance_summary()
        except Exception:
            pass
    
    def record_payment(self, amount, payment_date=None, notes=None):
        """
        Ghi nhận thanh toán cho item.
        
        Args:
            amount: Số tiền thanh toán
            payment_date: Ngày thanh toán (mặc định là hôm nay)
            notes: Ghi chú
        """
        if not payment_date:
            payment_date = nowdate()
        
        self.paid_amount = (self.paid_amount or 0) + amount
        self.last_payment_date = payment_date
        
        if notes:
            current_notes = self.notes or ''
            self.notes = f"{current_notes}\n[{payment_date}] Đã thanh toán {amount:,.0f} VND" if current_notes else f"[{payment_date}] Đã thanh toán {amount:,.0f} VND"
        
        self.save()

