# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Ghi nhận lỗi kỷ luật - Bản ghi vi phạm hàng ngày
"""

import frappe
from frappe import _
from frappe.model.document import Document

from erp.sis.discipline_record_permissions import (
    session_roles_normalized,
    user_can_create_discipline_record,
    user_can_write_existing_discipline_record,
)


class SISDisciplineRecord(Document):
    def validate(self):
        """Validate và set severity_level từ violation"""
        if self.violation:
            severity = frappe.db.get_value(
                "SIS Discipline Violation",
                self.violation,
                "severity_level",
            )
            if severity:
                self.severity_level = str(severity)

    def before_save(self):
        """
        DocType cấp write cho mọi SIS Supervisory — chặn tại Document để không ai sửa bản ghi người khác
        (kể cả REST / Desk / client khác ngoài API tùy chỉnh).
        """
        if frappe.flags.in_migrate or getattr(frappe.flags, "in_install", False):
            return
        if getattr(frappe.flags, "ignore_permissions", False):
            return
        roles = session_roles_normalized()
        if roles & {"System Manager", "SIS BOD", "Administrator"}:
            return
        if "SIS Supervisory Admin" in roles:
            return
        if "SIS Supervisory" not in roles:
            return
        if self.is_new():
            ok, msg = user_can_create_discipline_record()
            if not ok:
                frappe.throw(_(msg))
            return
        db_owner = frappe.db.get_value(self.doctype, self.name, "owner")
        allowed, msg = user_can_write_existing_discipline_record(db_owner)
        if not allowed:
            frappe.throw(_(msg))

    def on_trash(self):
        if frappe.flags.in_migrate or getattr(frappe.flags, "in_install", False):
            return
        if getattr(frappe.flags, "ignore_permissions", False):
            return
        roles = session_roles_normalized()
        if roles & {"System Manager", "SIS BOD", "Administrator"}:
            return
        if "SIS Supervisory Admin" in roles:
            return
        if "SIS Supervisory" not in roles:
            return
        db_owner = self.owner or frappe.db.get_value(self.doctype, self.name, "owner")
        allowed, msg = user_can_write_existing_discipline_record(db_owner)
        if not allowed:
            frappe.throw(_(msg))
