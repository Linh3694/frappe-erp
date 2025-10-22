# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate


class SISBadge(Document):
	def validate(self):
		"""Validate the badge document"""
		# Validate that badge_id is unique
		if self.badge_id:
			existing = frappe.db.exists(
				"SIS Badge",
				{"badge_id": self.badge_id, "name": ["!=", self.name]}
			)
			if existing:
				frappe.throw(f"Badge ID '{self.badge_id}' already exists")

		# Validate required fields
		if not self.title_vn:
			frappe.throw("Title (Vietnamese) is required")

	def before_save(self):
		"""Set default values before saving"""
		if not self.is_active:
			self.is_active = 0

	def on_update(self):
		"""Called after document is updated"""
		pass

	def on_trash(self):
		"""Called before document is deleted"""
		# Check if badge is being used anywhere before deletion
		# This can be extended based on business logic
		pass
