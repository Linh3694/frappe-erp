# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISSubject(Document):
    def validate(self):
        """
        Validate SIS Subject before saving.
        
        Enforces:
        1. timetable_subject_id is required (for Excel import mapping)
        2. actual_subject_id is required (for teacher assignment & grading)
        3. No duplicate mapping for same timetable_subject + education_stage
        """
        self.validate_timetable_subject_link()
        self.validate_actual_subject_link()
        self.validate_unique_mapping()
    
    def validate_timetable_subject_link(self):
        """Ensure timetable_subject_id is set"""
        if not self.timetable_subject_id:
            frappe.throw(
                "Timetable Subject is required. "
                "Please link this subject to a Timetable Subject for Excel import mapping.",
                frappe.ValidationError
            )
    
    def validate_actual_subject_link(self):
        """Ensure actual_subject_id is set"""
        if not self.actual_subject_id:
            frappe.throw(
                "Actual Subject is required. "
                "Please link this subject to an Actual Subject for teacher assignment and grading.",
                frappe.ValidationError
            )
    
    def validate_unique_mapping(self):
        """
        Prevent duplicate mappings of the same Timetable Subject for same education stage.
        
        Business rule: One Timetable Subject can only map to one SIS Subject per education stage.
        """
        existing = frappe.db.exists("SIS Subject", {
            "timetable_subject_id": self.timetable_subject_id,
            "education_stage": self.education_stage,
            "campus_id": self.campus_id,
            "name": ["!=", self.name]
        })
        
        if existing:
            timetable_subject_title = frappe.db.get_value(
                "SIS Timetable Subject", 
                self.timetable_subject_id, 
                "title_vn"
            )
            frappe.throw(
                f"Duplicate mapping detected. Timetable Subject '{timetable_subject_title}' "
                f"is already mapped to another SIS Subject for education stage '{self.education_stage}'.",
                frappe.DuplicateEntryError
            )
