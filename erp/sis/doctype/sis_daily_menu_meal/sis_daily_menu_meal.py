# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISDailyMenuMeal(Document):
	def validate(self):
		"""Validate meal data and auto-populate items if meal_type_reference is selected"""
		self.validate_education_stage_for_meal_type()
		self.auto_populate_items_from_meal_type()
	
	def validate_education_stage_for_meal_type(self):
		"""Validate that education_stage is only set for dinner meals"""
		if self.meal_type != "dinner":
			# For non-dinner meals, clear education_stage if it exists
			for item in self.items:
				if item.education_stage:
					item.education_stage = ""

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
				# Only add education_stage for dinner meals
				education_stage = "" if self.meal_type != "dinner" else ""
				
				self.append("items", {
					"menu_category_id": category.menu_category_id,
					"display_name": category.display_name or "",
					"display_name_en": "",
					"education_stage": education_stage
				})
