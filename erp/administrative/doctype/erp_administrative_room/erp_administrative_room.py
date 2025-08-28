# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime


class ERPAdministrativeRoom(Document):
    def validate(self):
        self.validate_room_name()
        self.validate_capacity()
        self.set_timestamps()
        
    def validate_room_name(self):
        """Validate that room name is unique"""
        if self.title_vn:
            existing = frappe.db.exists("ERP Administrative Room", {
                "title_vn": self.title_vn,
                "name": ("!=", self.name)
            })
            if existing:
                frappe.throw(_("Room Name {0} already exists").format(self.title_vn))

        # Also validate English name if provided
        if self.title_en:
            existing_en = frappe.db.exists("ERP Administrative Room", {
                "title_en": self.title_en,
                "name": ("!=", self.name)
            })
            if existing_en:
                frappe.throw(_("English Room Name {0} already exists").format(self.title_en))
    
    def validate_capacity(self):
        """Validate capacity is positive number"""
        if self.capacity and self.capacity <= 0:
            frappe.throw(_("Capacity must be a positive number"))
    
    def set_timestamps(self):
        """Set created_at and updated_at timestamps"""
        now = frappe.utils.now()
        if self.is_new():
            self.created_at = now
        self.updated_at = now
    
    def before_save(self):
        """Operations before saving"""
        # Ensure periods_per_day has default value
        if not self.periods_per_day:
            self.periods_per_day = 10
    
    def on_update(self):
        """Operations after update"""
        # Log the update activity
        self.create_activity_log("update", f"Room {self.title_vn} information updated")
    
    def create_activity_log(self, activity_type, description, details=None):
        """Create activity log for this room"""
        try:
            # This will be implemented when we have activity logging system 
            # For now, just log to system
            frappe.log_error(
                title=f"Room Activity: {activity_type}",
                message=f"{description} - Room: {self.title_vn}",
                reference_doctype=self.doctype,
                reference_name=self.name
            )
        except Exception as e:
            frappe.log_error(f"Failed to create activity log: {str(e)}")
    
    @frappe.whitelist()
    def get_devices_by_room(self):
        """Get all devices assigned to this room"""
        # Initialize devices structure
        devices = {
            "laptops": [],
            "monitors": [],
            "projectors": [],
            "printers": [],
            "tools": [],
            "phones": []
        }
        
        # Note: IT Inventory module has been removed, so device tracking is disabled
        # This would populate devices from IT inventory if the module existed
        
        return {
            "room_id": self.name,
            "title_vn": self.title_vn,
            "title_en": self.title_en,
            "building_id": self.building_id,
            "devices": devices
        }
    
    @frappe.whitelist()
    def get_room_utilization(self):
        """Get room utilization statistics"""
        # This will calculate room usage, schedules, etc.
        return {
            "room_id": self.name,
            "title_vn": self.title_vn,
            "capacity": self.capacity,
            "periods_per_day": self.periods_per_day,
            "is_homeroom": self.is_homeroom,
            "utilization_percentage": 0  # To be calculated
        }