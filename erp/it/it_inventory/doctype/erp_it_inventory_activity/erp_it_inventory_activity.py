# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class ERPITInventoryActivity(Document):
    def validate(self):
        self.validate_activity_type()
        
    def validate_activity_type(self):
        """Validate activity type"""
        valid_types = ["repair", "update", "assign", "revoke", "create", "delete"]
        if self.activity_type not in valid_types:
            frappe.throw(_("Invalid activity type. Must be one of: {0}").format(", ".join(valid_types)))
    
    def before_insert(self):
        """Set default values before insert"""
        if not self.updated_by:
            self.updated_by = frappe.session.user
        if not self.activity_date:
            self.activity_date = frappe.utils.now()


@frappe.whitelist()
def get_activities(entity_type, entity_id, limit=20):
    """Get activities for a specific entity"""
    activities = frappe.get_list("ERP IT Inventory Activity",
        filters={
            "entity_type": entity_type,
            "entity_id": entity_id
        },
        fields=[
            "name", "activity_type", "description", "details", 
            "activity_date", "updated_by"
        ],
        order_by="activity_date desc",
        limit=limit
    )
    
    # Get user full names
    for activity in activities:
        if activity.updated_by:
            activity.updated_by_name = frappe.get_value("User", activity.updated_by, "full_name")
    
    return activities


@frappe.whitelist()
def add_activity(entity_type, entity_id, activity_type, description, details=None):
    """Add new activity"""
    activity = frappe.get_doc({
        "doctype": "ERP IT Inventory Activity",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity_type": activity_type,
        "description": description,
        "details": details or "",
        "updated_by": frappe.session.user
    })
    activity.insert(ignore_permissions=True)
    return activity