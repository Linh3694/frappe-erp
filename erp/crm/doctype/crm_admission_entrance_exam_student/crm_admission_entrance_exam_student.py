# Copyright (c) 2025, Frappe Technologies and contributors
# Học sinh trong kỳ khảo sát đầu vào

import frappe
from frappe import _
from frappe.model.document import Document


class CRMAdmissionEntranceExamStudent(Document):
    """Học sinh — kỳ khảo sát đầu vào; cập nhật student_count trên kỳ."""

    def validate(self):
        # Ràng buộc duy nhất (entrance_exam_id, crm_lead_id)
        if not self.entrance_exam_id or not self.crm_lead_id:
            return
        existing = frappe.db.exists(
            "CRM Admission Entrance Exam Student",
            {
                "entrance_exam_id": self.entrance_exam_id,
                "crm_lead_id": self.crm_lead_id,
            },
        )
        if existing and existing != self.name:
            frappe.throw(_("Học sinh đã có trong kỳ khảo sát này"))

    def _update_exam_student_count(self):
        if not self.entrance_exam_id:
            return
        count = frappe.db.count(
            "CRM Admission Entrance Exam Student",
            filters={"entrance_exam_id": self.entrance_exam_id},
        )
        frappe.db.set_value(
            "CRM Admission Entrance Exam",
            self.entrance_exam_id,
            "student_count",
            count,
            update_modified=False,
        )

    def after_insert(self):
        self._update_exam_student_count()

    def on_trash(self):
        if not self.entrance_exam_id:
            return
        count = frappe.db.count(
            "CRM Admission Entrance Exam Student",
            filters={"entrance_exam_id": self.entrance_exam_id},
        )
        frappe.db.set_value(
            "CRM Admission Entrance Exam",
            self.entrance_exam_id,
            "student_count",
            max(0, count - 1),
            update_modified=False,
        )
