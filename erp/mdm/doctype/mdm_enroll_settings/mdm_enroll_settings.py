# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class MDMEnrollSettings(Document):
    def validate(self):
        if not self.site_check_in_key:
            self.rotate_key(save=False)

    @frappe.whitelist()
    def rotate_key(self, save=True):
        """Xoay site key. Máy đã enroll không bị ảnh hưởng — chúng dùng token riêng."""
        self.site_check_in_key = secrets.token_urlsafe(32)
        self.key_rotated_on = now_datetime()
        if save:
            self.save(ignore_permissions=True)
        return self.site_check_in_key


def get_settings() -> "MDMEnrollSettings":
    return frappe.get_single("MDM Enroll Settings")
