# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISNewsArticle(Document):
    def before_save(self):
        """Set audit fields and handle publish logic"""
        if not self.created_at:
            self.created_at = frappe.utils.now()
        if not self.created_by:
            self.created_by = frappe.session.user

        self.updated_at = frappe.utils.now()
        self.updated_by = frappe.session.user

        # Handle publish status change
        if self.status == "published" and not self.published_at:
            self.published_at = frappe.utils.now()
            self.published_by = frappe.session.user
        elif self.status == "draft":
            # Reset publish info when changing back to draft
            self.published_at = None
            self.published_by = None

    def validate(self):
        """Validate article data"""
        if self.title_en and self.title_vn:
            # Ensure uniqueness within campus
            existing_en = frappe.db.exists("SIS News Article", {
                "title_en": self.title_en,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing_en:
                frappe.throw(f"Article title (English) '{self.title_en}' already exists for this campus")

            existing_vn = frappe.db.exists("SIS News Article", {
                "title_vn": self.title_vn,
                "campus_id": self.campus_id,
                "name": ("!=", self.name if self.name else "")
            })
            if existing_vn:
                frappe.throw(f"Article title (Vietnamese) '{self.title_vn}' already exists for this campus")

        # Validate tags exist and belong to same campus
        if hasattr(self, 'tags') and self.tags:
            for tag in self.tags:
                if tag.news_tag_id:
                    tag_doc = frappe.get_doc("SIS News Tag", tag.news_tag_id)
                    if tag_doc.campus_id != self.campus_id:
                        frappe.throw(f"Tag '{tag_doc.name_en}' belongs to different campus")

    def after_insert(self):
        """Handle post-insert operations"""
        # Update tag display fields
        self._update_tag_display_fields()

    def on_update(self):
        """Handle post-update operations"""
        # Update tag display fields
        self._update_tag_display_fields()

    def _update_tag_display_fields(self):
        """Update display fields for tags"""
        if hasattr(self, 'tags') and self.tags:
            for tag in self.tags:
                if tag.news_tag_id:
                    try:
                        tag_doc = frappe.get_doc("SIS News Tag", tag.news_tag_id)
                        tag.tag_name_en = tag_doc.name_en
                        tag.tag_name_vn = tag_doc.name_vn
                        tag.tag_color = tag_doc.color
                    except:
                        pass  # Tag might be deleted
