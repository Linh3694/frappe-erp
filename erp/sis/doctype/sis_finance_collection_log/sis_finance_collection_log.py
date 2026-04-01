# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISFinanceCollectionLog(Document):
    """Nhật ký thu phí — ghi nhận liên hệ nhắc đóng tiền theo Order Student."""

    def before_insert(self):
        # Gán người ghi từ session nếu chưa có
        if not self.logged_by:
            self.logged_by = frappe.session.user
        # Form chỉ nhập nội dung — giữ giá trị mặc định cho tương thích DB
        if not getattr(self, "activity_type", None):
            self.activity_type = "other"
        if not getattr(self, "outcome", None):
            self.outcome = "other"
        self._set_logged_by_name()

    def before_save(self):
        self._set_logged_by_name()

    def _set_logged_by_name(self):
        if self.logged_by:
            full_name = frappe.db.get_value("User", self.logged_by, "full_name")
            self.logged_by_name = full_name or self.logged_by
        else:
            self.logged_by_name = None
