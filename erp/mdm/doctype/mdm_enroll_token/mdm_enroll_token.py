# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe.model.document import Document


class MDMEnrollToken(Document):
    def before_insert(self):
        if not self.token:
            # 32 byte ngẫu nhiên — token này được nhúng vào MSI phát hàng loạt
            self.token = secrets.token_urlsafe(32)

    def is_usable(self) -> bool:
        from frappe.utils import get_datetime, now_datetime

        if not self.is_active:
            return False
        if self.expires_on and get_datetime(self.expires_on) < now_datetime():
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True
