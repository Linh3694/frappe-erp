# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMAdmissionEventStudent(Document):
    """Học sinh đăng ký sự kiện tuyển sinh"""

    def _update_event_student_count(self):
        """Cập nhật student_count cho CRM Admission Event"""
        if not self.event_id:
            return
        count = frappe.db.count(
            "CRM Admission Event Student",
            filters={"event_id": self.event_id}
        )
        frappe.db.set_value(
            "CRM Admission Event",
            self.event_id,
            "student_count",
            count,
            update_modified=False
        )

    def after_insert(self):
        self._update_event_student_count()

    def on_trash(self):
        if not self.event_id:
            return
        count = frappe.db.count(
            "CRM Admission Event Student",
            filters={"event_id": self.event_id}
        )
        frappe.db.set_value(
            "CRM Admission Event",
            self.event_id,
            "student_count",
            max(0, count - 1),
            update_modified=False
        )
