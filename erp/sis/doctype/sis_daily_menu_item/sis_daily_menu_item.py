# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISDailyMenuItem(Document):
    def validate(self):
        """Validate menu item data"""
        self.validate_education_stage_for_meal_type()
        self.validate_menu_category()

    def validate_education_stage_for_meal_type(self):
        """Validate that education_stage is only set for dinner meals"""
        if self.meal_type != "dinner" and self.education_stage:
            self.education_stage = ""
            
    def validate_menu_category(self):
        """Validate that menu category exists"""
        if self.menu_category_id:
            if not frappe.db.exists("SIS Menu Category", self.menu_category_id):
                frappe.throw(f"Món ăn '{self.menu_category_id}' không tồn tại")
