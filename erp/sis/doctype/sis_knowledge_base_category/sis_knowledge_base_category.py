# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISKnowledgeBaseCategory(Document):
    def before_save(self):
        """Set audit fields"""
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name") or current_user

        if not self.created_at:
            self.created_at = frappe.utils.now()
        if not self.created_by:
            self.created_by = teacher

        self.updated_at = frappe.utils.now()
        self.updated_by = teacher

    def validate(self):
        """Ensure code is unique within campus and is a clean slug"""
        if self.code:
            self.code = self.code.strip().lower()
            existing = frappe.db.exists("SIS Knowledge Base Category", {
                "code": self.code,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing:
                frappe.throw(f"Category code '{self.code}' already exists for this campus")

        # Prevent a category from being its own parent
        if self.parent_category and self.parent_category == self.name:
            frappe.throw("A category cannot be its own parent")
