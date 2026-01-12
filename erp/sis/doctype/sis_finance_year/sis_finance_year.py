# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SISFinanceYear(Document):
    """
    Doctype quản lý năm tài chính.
    Liên kết với SIS School Year để quản lý các khoản phí theo năm học.
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
        self.validate_dates()
        self.validate_unique_school_year_campus()
    
    def validate_dates(self):
        """Kiểm tra ngày bắt đầu phải trước ngày kết thúc"""
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                frappe.throw("Ngày bắt đầu phải trước ngày kết thúc")
    
    def validate_unique_school_year_campus(self):
        """Kiểm tra không có năm tài chính trùng school_year + campus"""
        existing = frappe.db.get_value(
            "SIS Finance Year",
            {
                "school_year_id": self.school_year_id,
                "campus_id": self.campus_id,
                "name": ("!=", self.name)
            },
            "name"
        )
        if existing:
            frappe.throw(f"Đã tồn tại năm tài chính cho năm học và campus này: {existing}")
    
    def update_statistics(self):
        """Cập nhật thống kê cho năm tài chính"""
        # Đếm số học sinh
        self.total_students = frappe.db.count(
            "SIS Finance Student",
            {"finance_year_id": self.name}
        )
        
        # Đếm số đơn hàng
        self.total_orders = frappe.db.count(
            "SIS Finance Order",
            {"finance_year_id": self.name}
        )
        
        # Tính tổng số tiền và đã thu
        order_items = frappe.db.sql("""
            SELECT 
                COALESCE(SUM(foi.amount), 0) as total_amount,
                COALESCE(SUM(foi.paid_amount), 0) as total_paid
            FROM `tabSIS Finance Order Item` foi
            INNER JOIN `tabSIS Finance Order` fo ON foi.order_id = fo.name
            WHERE fo.finance_year_id = %s
        """, (self.name,), as_dict=True)
        
        if order_items:
            self.total_amount = order_items[0].get('total_amount', 0)
            self.total_paid = order_items[0].get('total_paid', 0)
        
        self.db_update()

