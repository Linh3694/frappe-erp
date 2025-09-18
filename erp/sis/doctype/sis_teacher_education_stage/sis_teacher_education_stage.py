# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISTeacherEducationStage(Document):
    def validate(self):
        # Ensure no duplicate active mappings for same teacher-stage combination
        if self.is_active:
            existing = frappe.db.exists(
                "SIS Teacher Education Stage",
                {
                    "teacher_id": self.teacher_id,
                    "education_stage_id": self.education_stage_id,
                    "is_active": 1,
                    "name": ["!=", self.name]
                }
            )
            if existing:
                frappe.throw(f"Active mapping already exists for this teacher and education stage")
        
        # Validate date range if provided
        if self.from_date and self.to_date:
            if self.from_date > self.to_date:
                frappe.throw("From Date cannot be after To Date")
