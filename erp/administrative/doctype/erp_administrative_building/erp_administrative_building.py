# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class ERPAdministrativeBuilding(Document):
    def validate(self):
        self.validate_building_name()
        
    def validate_building_name(self):
        """Validate that building name is unique"""
        if self.title_vn:
            existing = frappe.db.exists("ERP Administrative Building", {
                "title_vn": self.title_vn,
                "name": ("!=", self.name)
            })
            if existing:
                frappe.throw(_("Building Name (VN) {0} already exists").format(self.title_vn))
        
        # Also validate English name if provided
        if self.title_en:
            existing_en = frappe.db.exists("ERP Administrative Building", {
                "title_en": self.title_en,
                "name": ("!=", self.name)
            })
            if existing_en:
                frappe.throw(_("Building Name (EN) {0} already exists").format(self.title_en))
    
    @frappe.whitelist()
    def get_rooms_in_building(self):
        """Get all rooms in this building"""
        try:
            rooms = frappe.get_all(
                "ERP Administrative Room",
                filters={"building_id": self.name},
                fields=[
                    "name", "title_vn", "title_en", "short_title", "room_type",
                    "capacity", "is_homeroom", "description"
                ],
                order_by="title_vn asc"
            )
            
            return {
                "building_id": self.name,
                "building_name_vn": self.title_vn,
                "building_name_en": self.title_en,
                "campus": self.campus,
                "rooms": rooms,
                "total_rooms": len(rooms)
            }
            
        except Exception as e:
            frappe.log_error(f"Error fetching rooms for building {self.name}: {str(e)}")
            return {
                "building_id": self.name,
                "building_name_vn": self.title_vn,
                "building_name_en": self.title_en,
                "campus": self.campus,
                "rooms": [],
                "total_rooms": 0
            } 