# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISNewsTag(Document):
    def before_save(self):
        """Set audit fields"""
        if not self.created_at:
            self.created_at = frappe.utils.now()
        if not self.created_by:
            self.created_by = frappe.session.user

        self.updated_at = frappe.utils.now()
        self.updated_by = frappe.session.user

    def validate(self):
        """Validate tag data"""
        if self.name_en and self.name_vn:
            # Ensure uniqueness within campus
            existing = frappe.db.exists("SIS News Tag", {
                "name_en": self.name_en,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing:
                frappe.throw(f"Tag name (English) '{self.name_en}' already exists for this campus")

            existing_vn = frappe.db.exists("SIS News Tag", {
                "name_vn": self.name_vn,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing_vn:
                frappe.throw(f"Tag name (Vietnamese) '{self.name_vn}' already exists for this campus")
