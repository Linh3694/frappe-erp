# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMMeeting(Document):
    def before_insert(self):
        """Tự động set created_by trước khi insert"""
        if not self.created_by:
            self.created_by = frappe.session.user

    def after_insert(self):
        """Log khi tạo meeting mới"""
        self.log_change("meeting_created")

    def on_update(self):
        """Log khi cập nhật meeting"""
        self.log_change("meeting_updated")

    def on_trash(self):
        """Log khi xóa meeting"""
        self.log_change("meeting_deleted")

    def log_change(self, action: str):
        """Helper function để log thay đổi"""
        try:
            log = frappe.get_doc({
                "doctype": "PM Change Log",
                "project_id": self.project_id,
                "action": action,
                "actor_id": frappe.session.user,
                "target_type": "meeting",
                "target_id": self.name
            })
            log.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error logging meeting change: {str(e)}")

