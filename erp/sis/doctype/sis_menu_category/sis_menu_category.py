# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SISMenuCategory(Document):
    """SIS Menu Category document class"""

    def validate(self):
        """Validate the document"""
        # Ensure title_vn and title_en are provided
        if not self.title_vn:
            frappe.throw(_("Menu Category Name (VN) is required"))

        if not self.title_en:
            frappe.throw(_("Menu Category Name (EN) is required"))

        if not self.code:
            frappe.throw(_("Menu Category Code is required"))

        # Check for duplicate title_vn
        if self.is_new():
            existing = frappe.db.exists("SIS Menu Category", {"title_vn": self.title_vn})
            if existing:
                frappe.throw(_("Menu Category with name '{0}' already exists").format(self.title_vn))
        else:
            # For updates, check if another document has the same title_vn
            existing = frappe.db.exists(
                "SIS Menu Category",
                {"title_vn": self.title_vn, "name": ["!=", self.name]}
            )
            if existing:
                frappe.throw(_("Menu Category with name '{0}' already exists").format(self.title_vn))

        # Check for duplicate code
        if self.is_new():
            existing_code = frappe.db.exists("SIS Menu Category", {"code": self.code})
            if existing_code:
                frappe.throw(_("Menu Category with code '{0}' already exists").format(self.code))
        else:
            # For updates, check if another document has the same code
            existing_code = frappe.db.exists(
                "SIS Menu Category",
                {"code": self.code, "name": ["!=", self.name]}
            )
            if existing_code:
                frappe.throw(_("Menu Category with code '{0}' already exists").format(self.code))

    def before_save(self):
        """Run before saving the document"""
        # You can add any preprocessing logic here
        pass

    def after_insert(self):
        """Run after inserting the document"""
        # You can add any post-processing logic here
        pass

    def on_update(self):
        """Run after updating the document"""
        # You can add any update logic here
        pass

    def on_trash(self):
        """Run before deleting the document"""
        # You can add validation before deletion here
        pass
