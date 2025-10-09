# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISDailyMenu(Document):
	def validate(self):
		"""Validate daily menu data"""
		self.validate_unique_date()
		self.validate_items()

	def validate_unique_date(self):
		"""Ensure menu_date is unique"""
		if self.menu_date:
			existing = frappe.db.exists("SIS Daily Menu", {
				"menu_date": self.menu_date,
				"name": ["!=", self.name]
			})
			if existing:
				frappe.throw(f"Ngày {self.menu_date} đã có thực đơn")

	def validate_items(self):
		"""Validate menu items data"""
		if self.items:
			# Track items per meal type to prevent duplicates
			meal_items = {}

			for item in self.items:
				# Initialize meal tracking
				if item.meal_type not in meal_items:
					meal_items[item.meal_type] = []

				# Check for duplicate menu categories within same meal
				# Skip duplicate check for breakfast and dinner meals (allow multiple items)
				if item.meal_type == "lunch":
					if item.menu_category_id in meal_items[item.meal_type]:
						frappe.throw(f"Món ăn '{item.menu_category_id}' bị trùng lặp trong bữa {item.meal_type}")
					meal_items[item.meal_type].append(item.menu_category_id)

				# Validate that education_stage is only set for dinner meals
				if item.education_stage and item.meal_type != "dinner":
					frappe.throw(f"Trường học chỉ được đặt cho bữa xế (dinner), không phải bữa {item.meal_type}")
