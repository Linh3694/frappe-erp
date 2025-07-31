# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.inventory.api.device import *


# Laptop-specific API endpoints - compatible with old backend
@frappe.whitelist()
def get_laptops(**kwargs):
    """Get laptops - equivalent to old getLaptops endpoint"""
    kwargs['device_type'] = 'Laptop'
    return get_devices(**kwargs)


@frappe.whitelist()
def create_laptop(**kwargs):
    """Create laptop - equivalent to old createLaptop endpoint"""
    kwargs['device_type'] = 'Laptop'
    return create_device(**kwargs)


@frappe.whitelist()
def update_laptop(laptop_id, **kwargs):
    """Update laptop - equivalent to old updateLaptop endpoint"""
    return update_device(laptop_id, **kwargs)


@frappe.whitelist()
def delete_laptop(laptop_id):
    """Delete laptop - equivalent to old deleteLaptop endpoint"""
    return delete_device(laptop_id)


@frappe.whitelist()
def get_laptop_by_id(laptop_id):
    """Get laptop by ID - equivalent to old getLaptopById endpoint"""
    return get_device(laptop_id)


@frappe.whitelist()
def assign_laptop(laptop_id, user_id, notes=None):
    """Assign laptop - equivalent to old assignLaptop endpoint"""
    return assign_device(laptop_id, user_id, notes)


@frappe.whitelist()
def revoke_laptop(laptop_id, user_id, reason=None):
    """Revoke laptop - equivalent to old revokeLaptop endpoint"""
    return revoke_device(laptop_id, user_id, reason)


@frappe.whitelist()
def update_laptop_status(laptop_id, status, broken_reason=None):
    """Update laptop status - equivalent to old updateLaptopStatus endpoint"""
    return update_device_status(laptop_id, status, broken_reason)


@frappe.whitelist()
def update_laptop_specs(laptop_id, **kwargs):
    """Update laptop specs - equivalent to old updateLaptopSpecs endpoint"""
    return update_device(laptop_id, **kwargs)


@frappe.whitelist()
def get_laptop_filter_options():
    """Get laptop filter options - equivalent to old getLaptopFilterOptions endpoint"""
    return get_device_filter_options()


@frappe.whitelist()
def bulk_upload_laptops(laptops_data):
    """Bulk upload laptops - equivalent to old bulkUploadLaptops endpoint"""
    # Ensure all laptops have device_type set
    if isinstance(laptops_data, list):
        for laptop in laptops_data:
            laptop['device_type'] = 'Laptop'
    return bulk_upload_devices(laptops_data)


@frappe.whitelist()
def upload_handover_report(laptop_id, file_url):
    """Upload handover report for laptop"""
    try:
        # This would be handled by file upload functionality
        # For now, just update the device with a note
        device = frappe.get_doc("ERP IT Inventory Device", laptop_id)
        if not device.notes:
            device.notes = ""
        device.notes += f"\nHandover report uploaded: {file_url}"
        device.save()
        
        return {
            "status": "success",
            "message": _("Handover report uploaded successfully")
        }
    except Exception as e:
        frappe.log_error(f"Error uploading handover report: {str(e)}", "Laptop API Error")
        frappe.throw(_("Error uploading handover report: {0}").format(str(e)))


@frappe.whitelist()
def get_handover_report(filename):
    """Get handover report file"""
    try:
        # This would return the file from the file system
        # Implementation depends on your file storage setup
        return {
            "status": "success",
            "file_url": f"/files/{filename}"
        }
    except Exception as e:
        frappe.log_error(f"Error getting handover report: {str(e)}", "Laptop API Error")
        frappe.throw(_("Error getting handover report: {0}").format(str(e)))