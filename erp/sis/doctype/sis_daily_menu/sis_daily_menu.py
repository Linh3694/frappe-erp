# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISDailyMenu(Document):
	def validate(self):
		"""Validate daily menu data"""
		self.validate_unique_date()
		self.validate_meals()

	def validate_unique_date(self):
		"""Ensure menu_date is unique"""
		if self.menu_date:
			existing = frappe.db.exists("SIS Daily Menu", {
				"menu_date": self.menu_date,
				"name": ["!=", self.name]
			})
			if existing:
				frappe.throw(f"Ngày {self.menu_date} đã có thực đơn")

	def validate_meals(self):
		"""Validate meals data"""
		if self.meals:
			meal_types = []
			for meal in self.meals:
				if meal.meal_type in meal_types:
					frappe.throw(f"Bữa ăn '{meal.meal_type}' bị trùng lặp")
				meal_types.append(meal.meal_type)

				# Validate meal items
				if meal.items:
					menu_category_ids = []
					for item in meal.items:
						if item.menu_category_id in menu_category_ids:
							frappe.throw(f"Món ăn '{item.menu_category_id}' bị trùng lặp trong bữa {meal.meal_type}")
						menu_category_ids.append(item.menu_category_id)
