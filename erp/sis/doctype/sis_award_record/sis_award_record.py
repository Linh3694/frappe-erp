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
		
		# Check for duplicates within the same record
		if self.student_entries:
			student_ids = [entry.student_id for entry in self.student_entries]
			if len(student_ids) != len(set(student_ids)):
				frappe.throw("Có học sinh bị trùng lặp trong danh sách")
		
		if self.class_entries:
			class_ids = [entry.class_id for entry in self.class_entries]
			if len(class_ids) != len(set(class_ids)):
				frappe.throw("Có lớp bị trùng lặp trong danh sách")
