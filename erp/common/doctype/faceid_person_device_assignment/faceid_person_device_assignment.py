# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDPersonDeviceAssignment(Document):
    def validate(self):
        dup = frappe.db.get_value(
            "FaceID Person Device Assignment",
            {"person": self.person, "device": self.device, "name": ["!=", self.name or ""]},
            "name",
        )
        if dup:
            frappe.throw(f"Đã có dòng phân bổ {self.person} trên máy {self.device}")
