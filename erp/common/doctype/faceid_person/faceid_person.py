# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDPerson(Document):
    def validate(self):
        if self.person_type == "student" and not self.crm_student:
            frappe.throw("CRM Student là bắt buộc với loại học sinh")
        if self.person_type == "guardian" and not self.crm_guardian:
            frappe.throw("CRM Guardian là bắt buộc với loại phụ huynh")
        if self.person_type == "staff" and not self.user:
            frappe.throw("User là bắt buộc với loại nhân viên")
        if not self.external_code:
            self.external_code = self._resolve_external_code()

    def _resolve_external_code(self):
        if self.person_type == "student" and self.crm_student:
            return frappe.db.get_value("CRM Student", self.crm_student, "student_code")
        if self.person_type == "guardian" and self.crm_guardian:
            return frappe.db.get_value("CRM Guardian", self.crm_guardian, "guardian_id")
        if self.person_type == "staff" and self.user:
            return (
                frappe.db.get_value("User", self.user, "employee_code") or self.user
            )
        return self.external_code

    def on_trash(self):
        # Xóa doc → vẫn cần gỡ khỏi máy (operator-driven nhưng trash là ngoại lệ)
        from erp.api.faceid.sync_worker import create_device_sync_job

        create_device_sync_job(
            "delete_person",
            self.doctype,
            self.name,
            payload={"external_code": self.external_code},
            priority=8,
        )
