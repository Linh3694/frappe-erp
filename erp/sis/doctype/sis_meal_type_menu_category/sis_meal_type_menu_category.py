# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISMealTypeMenuCategory(Document):
	def validate(self):
		"""Validate meal type menu category data"""
		if self.menu_category_id:
			# Check if menu category exists
			if not frappe.db.exists("SIS Menu Category", self.menu_category_id):
				frappe.throw(f"Món ăn '{self.menu_category_id}' không tồn tại")
