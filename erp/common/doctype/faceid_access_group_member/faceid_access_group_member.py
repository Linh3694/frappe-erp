# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDAccessGroupMember(Document):
    def validate(self):
        dup = frappe.db.get_value(
            "FaceID Access Group Member",
            {"group": self.group, "person": self.person, "name": ["!=", self.name or ""]},
            "name",
        )
        if dup:
            frappe.throw(f"Person {self.person} đã có trong nhóm {self.group}")
