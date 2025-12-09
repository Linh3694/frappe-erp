# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISAwardRecord(Document):
	def validate(self):
		"""Validation before saving"""
		# Ensure at least one entry (student or class) exists
		if not self.student_entries and not self.class_entries:
			frappe.throw("Phải có ít nhất một học sinh hoặc một lớp")
		
		# NOTE: Removed duplicate checks - allow multiple records for same student/class
