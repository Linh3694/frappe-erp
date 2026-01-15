# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SISMenuRegistration(Document):
    """
    Đăng ký suất ăn Á/Âu của học sinh
    Lưu trữ lựa chọn của phụ huynh cho từng ngày Thứ 4 trong kỳ
    """

    def before_insert(self):
        """Thiết lập thông tin khi tạo mới"""
        self.registration_date = now_datetime()
        self.registered_by = frappe.session.user
        self.last_modified_by = frappe.session.user
        self.last_modified_at = now_datetime()

    def before_save(self):
        """Cập nhật thông tin khi lưu"""
        self.last_modified_by = frappe.session.user
        self.last_modified_at = now_datetime()
        self.validate_registrations()

    def validate_registrations(self):
        """Kiểm tra chi tiết đăng ký"""
        if not self.registrations or len(self.registrations) == 0:
            frappe.throw("Vui lòng chọn suất ăn cho ít nhất một ngày")

        # Kiểm tra không có ngày trùng lặp
        dates = [item.date for item in self.registrations]
        if len(dates) != len(set(dates)):
            frappe.throw("Không được đăng ký trùng ngày")

        # Kiểm tra lựa chọn hợp lệ
        valid_choices = ["A", "AU"]
        for item in self.registrations:
            if item.choice not in valid_choices:
                frappe.throw(f"Lựa chọn '{item.choice}' không hợp lệ. Chỉ chấp nhận: {', '.join(valid_choices)}")
