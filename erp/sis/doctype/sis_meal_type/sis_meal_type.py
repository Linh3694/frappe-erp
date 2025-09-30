# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISMealType(Document):
	def validate(self):
		"""Validate meal type data"""
		self.validate_unique_title()
		self.validate_menu_categories()
	
	def validate_unique_title(self):
		"""Ensure title_vn is unique"""
		if self.title_vn:
			existing = frappe.db.exists("SIS Meal Type", {
				"title_vn": self.title_vn,
				"name": ["!=", self.name]
			})
			if existing:
				frappe.throw(f"Tên bữa ăn '{self.title_vn}' đã tồn tại")
	
	def validate_menu_categories(self):
		"""Validate menu categories"""
		if self.menu_categories:
			menu_category_ids = []
			for item in self.menu_categories:
				if item.menu_category_id in menu_category_ids:
					frappe.throw(f"Món ăn '{item.menu_category_id}' bị trùng lặp")
				menu_category_ids.append(item.menu_category_id)
