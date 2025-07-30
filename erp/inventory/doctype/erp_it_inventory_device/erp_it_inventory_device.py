# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class ERPITInventoryDevice(Document):
    def validate(self):
        self.validate_serial_number()
        self.validate_broken_reason()
        
    def validate_serial_number(self):
        """Validate that serial number is unique"""
        if self.serial_number:
            existing = frappe.db.exists("ERP IT Inventory Device", {
                "serial_number": self.serial_number,
                "name": ("!=", self.name)
            })
            if existing:
                frappe.throw(_("Serial Number {0} already exists").format(self.serial_number))
    
    def validate_broken_reason(self):
        """Validate that broken reason is provided if status is Broken"""
        if self.status == "Broken" and not self.broken_reason:
            frappe.throw(_("Broken Reason is required when status is Broken"))
    
    def before_save(self):
        """Auto-update assignment history when device is assigned"""
        # This will be implemented when we create the assignment functionality
        pass
    
    def on_update(self):
        """Log activities when device is updated"""
        # Create activity log
        self.create_activity_log("update", "Device information updated")
    
    def create_activity_log(self, activity_type, description, details=None):
        """Create activity log for this device"""
        try:
            activity = frappe.get_doc({
                "doctype": "ERP IT Inventory Activity",
                "entity_type": "ERP IT Inventory Device",
                "entity_id": self.name,
                "activity_type": activity_type,
                "description": description,
                "details": details or "",
                "updated_by": frappe.session.user
            })
            activity.insert(ignore_permissions=True)
        except Exception as e:
            # Don't fail the main operation if activity logging fails
            frappe.log_error(f"Failed to create activity log: {str(e)}", "Device Activity Log Error")


@frappe.whitelist()
def get_device_stats():
    """Get device statistics for dashboard"""
    stats = {}
    
    # Total devices by type
    device_types = frappe.db.sql("""
        SELECT device_type, COUNT(*) as count
        FROM `tabERP IT Inventory Device`
        GROUP BY device_type
    """, as_dict=True)
    
    stats['by_type'] = {item['device_type']: item['count'] for item in device_types}
    
    # Devices by status
    device_status = frappe.db.sql("""
        SELECT status, COUNT(*) as count
        FROM `tabERP IT Inventory Device`
        GROUP BY status
    """, as_dict=True)
    
    stats['by_status'] = {item['status']: item['count'] for item in device_status}
    
    # Total count
    stats['total'] = frappe.db.count("ERP IT Inventory Device")
    
    return stats


@frappe.whitelist()
def assign_device(device_name, user_id, notes=None):
    """Assign device to a user"""
    device = frappe.get_doc("ERP IT Inventory Device", device_name)
    
    # Add to current assignment
    if user_id not in [str(u) for u in device.assigned_to]:
        device.append("assigned_to", {"user": user_id})
    
    # Add to assignment history
    device.append("assignment_history", {
        "user": user_id,
        "start_date": frappe.utils.nowdate(),
        "notes": notes or "",
        "assigned_by": frappe.session.user
    })
    
    device.save()
    device.create_activity_log("assign", f"Device assigned to {frappe.get_value('User', user_id, 'full_name')}")
    
    return {"status": "success", "message": _("Device assigned successfully")}


@frappe.whitelist()
def revoke_device(device_name, user_id, reason=None):
    """Revoke device from a user"""
    device = frappe.get_doc("ERP IT Inventory Device", device_name)
    
    # Remove from current assignment
    device.assigned_to = [row for row in device.assigned_to if str(row.user) != str(user_id)]
    
    # Update assignment history
    for history in device.assignment_history:
        if str(history.user) == str(user_id) and not history.end_date:
            history.end_date = frappe.utils.nowdate()
            history.revoked_by = frappe.session.user
            if reason:
                history.revoked_reason = reason
            break
    
    device.save()
    device.create_activity_log("revoke", f"Device revoked from {frappe.get_value('User', user_id, 'full_name')}")
    
    return {"status": "success", "message": _("Device revoked successfully")}