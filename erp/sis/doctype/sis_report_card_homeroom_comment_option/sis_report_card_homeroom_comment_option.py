# -*- coding: utf-8 -*-
# Copyright (c) 2024, Wellspring Innovation Space and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.model.document import Document
import re

class SISReportCardHomeroomCommentOption(Document):
	def validate(self):
		if not self.title or not self.title.strip():
			frappe.throw(_("Tên tùy chọn không được để trống"))
		
		# Allow special characters in title (including <, >, +, -, etc.)
		# This overrides Frappe's default validation for title field

	def autoname(self):
		# Generate name based on title, allowing special characters
		if self.title:
			# Replace problematic characters for name generation
			# Keep alphanumeric, Vietnamese characters, spaces, and common symbols like +, -, etc.
			# Only replace characters that cause database issues: /, \, <, >, :, ", |, ?, *
			base_name = self.title.strip()
			base_name = re.sub(r'[/<>:"\\|?*]', '-', base_name)  # Replace problematic chars with hyphen
			base_name = base_name.replace(' ', '-')  # Replace spaces with hyphen
			base_name = re.sub(r'-+', '-', base_name)  # Replace multiple hyphens with single hyphen
			base_name = base_name.strip('-')  # Remove leading/trailing hyphens
			
			# If base_name is empty after sanitization, use a default
			if not base_name:
				base_name = "option"
			
			counter = 1
			name = base_name

			# Ensure unique name
			while frappe.db.exists("SIS Report Card Homeroom Comment Option", name):
				name = f"{base_name}-{counter}"
				counter += 1

			self.name = name
