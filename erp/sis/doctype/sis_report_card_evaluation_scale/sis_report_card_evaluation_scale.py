# -*- coding: utf-8 -*-
# Copyright (c) 2024, Wellspring Innovation Space and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document

class SISReportCardEvaluationScale(Document):
	def validate(self):
		# Validate that title is not empty
		if not self.title or not self.title.strip():
			frappe.throw(_("Thang đánh giá không được để trống"))

		# Allow special characters in title (including <, >, +, - etc.)
		# This overrides Frappe's default validation for title field

		# Validate that at least one option exists
		if not self.options or len(self.options) == 0:
			frappe.throw(_("Phải có ít nhất một tùy chọn đánh giá"))

		# Validate options
		for option in self.options:
			if not option.title or not option.title.strip():
				frappe.throw(_("Tên tùy chọn không được để trống"))

	def before_save(self):
		# Remove empty options before saving
		self.options = [opt for opt in self.options if opt.title and opt.title.strip()]

	def autoname(self):
		# Generate name based on title and campus, allowing special characters
		if self.title and self.campus_id:
			# Use title directly instead of slug to preserve special characters
			# Replace spaces and problematic characters for name generation
			base_name = self.title.strip().replace(" ", "-").replace("/", "-").replace("\\", "-")
			counter = 1
			name = f"{base_name}-{self.campus_id}"

			# Ensure unique name
			while frappe.db.exists("SIS Report Card Evaluation Scale", name):
				name = f"{base_name}-{self.campus_id}-{counter}"
				counter += 1

			self.name = name