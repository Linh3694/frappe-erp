# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISContactLogView(Document):
	"""Track when parents view contact logs"""
	
	def before_insert(self):
		"""Increment viewed count on parent class log student"""
		if self.class_log_student:
			frappe.db.set_value(
				"SIS Class Log Student",
				self.class_log_student,
				"contact_log_viewed_count",
				frappe.db.get_value("SIS Class Log Student", self.class_log_student, "contact_log_viewed_count") + 1,
				update_modified=False
			)

