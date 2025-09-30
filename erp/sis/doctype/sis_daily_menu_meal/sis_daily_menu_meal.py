# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISDailyMenuMeal(Document):
	def validate(self):
		"""Validate meal data and auto-populate items if meal_type_reference is selected"""
		self.auto_populate_items_from_meal_type()

	def auto_populate_items_from_meal_type(self):
		"""Auto-populate items from selected SIS Meal Type"""
		if self.meal_type_reference and not self.items:
			# Get menu categories from the referenced meal type
			menu_categories = frappe.get_all(
				"SIS Meal Type Menu Category",
				filters={
					"parent": self.meal_type_reference
				},
				fields=["menu_category_id", "display_name"],
				order_by="idx"
			)

			# Add items to this meal
			for category in menu_categories:
				self.append("items", {
					"menu_category_id": category.menu_category_id,
					"display_name": category.display_name or "",
					"display_name_en": "",
					"education_stage": "" if self.meal_type != "dinner" else ""
				})
