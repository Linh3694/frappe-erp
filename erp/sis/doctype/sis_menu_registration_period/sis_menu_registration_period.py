# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SISMenuRegistrationPeriod(Document):
    """
    Kỳ đăng ký suất ăn Á/Âu
    Quản lý các kỳ đăng ký suất ăn cho học sinh Tiểu học
    """

    def before_insert(self):
        """Thiết lập thông tin khi tạo mới"""
        self.created_by = frappe.session.user
        self.created_at = now_datetime()
        self.updated_at = now_datetime()

    def before_save(self):
        """Cập nhật thời gian khi lưu"""
        self.updated_at = now_datetime()
        self.validate_dates()
        self.validate_month_year()

    def validate_dates(self):
        """Kiểm tra ngày bắt đầu phải trước ngày kết thúc"""
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                frappe.throw("Ngày bắt đầu phải trước ngày kết thúc")

    def validate_month_year(self):
        """Kiểm tra tháng trong khoảng 1-12"""
        if self.month and (self.month < 1 or self.month > 12):
            frappe.throw("Tháng phải trong khoảng từ 1 đến 12")
