# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, flt, cstr
import json


@frappe.whitelist()
def get_devices(page=1, limit=20, search=None, status=None, manufacturer=None, device_type=None, release_year=None):
    """Get devices with pagination and filters - equivalent to getLaptops in old system"""
    try:
        page = cint(page) or 1
        limit = cint(limit) or 20
        start = (page - 1) * limit
        
        # Build filters
        filters = {}
        if status:
            filters["status"] = status
        if manufacturer:
            filters["manufacturer"] = ["like", f"%{manufacturer}%"]
        if device_type:
            filters["device_type"] = device_type
        if release_year:
            filters["release_year"] = cint(release_year)
            
        # Build search conditions
        or_filters = []
        if search:
            or_filters = [
                ["device_name", "like", f"%{search}%"],
                ["serial_number", "like", f"%{search}%"],
                ["manufacturer", "like", f"%{search}%"]
            ]
        
        # Get devices
        devices = frappe.get_list(
            "ERP IT Inventory Device",
            filters=filters,
            or_filters=or_filters if or_filters else None,
            fields=[
                "name", "device_name", "device_type", "manufacturer", 
                "serial_number", "release_year", "status", "broken_reason", 
                "room", "assigned_to", "creation", "modified"
            ],
            start=start,
            limit=limit,
            order_by="modified desc"
        )
        
        # Get total count for pagination
        total_count = frappe.db.count(
            "ERP IT Inventory Device",
            filters=filters
        )
        
        # Enrich device data
        for device in devices:
            # Get room name
            if device.room:
                device.room_name = frappe.get_value("Room", device.room, "room_name")
            
            # Get assigned users (simplified - assuming you have assignment logic)
            if device.assigned_to:
                # This would need to be adjusted based on your actual assignment structure
                device.assigned_users = []
        
        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "devices": devices,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_items": total_count,
                "items_per_page": limit,
                "has_next": page < total_pages,
                "has_prev": page > 1
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_devices: {str(e)}", "Device API Error")
        frappe.throw(_("Error fetching devices: {0}").format(str(e)))


@frappe.whitelist()
def get_device(device_id):
    """Get single device details - equivalent to getLaptopById"""
    try:
        device = frappe.get_doc("ERP IT Inventory Device", device_id)
        
        # Get additional data
        device_dict = device.as_dict()
        
        # Get room name
        if device.room:
            device_dict["room_name"] = frappe.get_value("Room", device.room, "room_name")
        
        # Get assignment history
        device_dict["assignment_history"] = device.assignment_history
        
        # Get recent activities
        activities = frappe.get_list(
            "ERP IT Inventory Activity",
            filters={"entity_type": "ERP IT Inventory Device", "entity_id": device_id},
            fields=["name", "activity_type", "description", "activity_date", "updated_by"],
            limit=10,
            order_by="activity_date desc"
        )
        device_dict["recent_activities"] = activities
        
        # Get latest inspection
        latest_inspection = frappe.get_list(
            "ERP IT Inventory Inspect",
            filters={"device_id": device_id},
            fields=["name", "inspection_date", "overall_assessment", "passed"],
            limit=1,
            order_by="inspection_date desc"
        )
        device_dict["latest_inspection"] = latest_inspection[0] if latest_inspection else None
        
        return device_dict
        
    except Exception as e:
        frappe.log_error(f"Error in get_device: {str(e)}", "Device API Error")
        frappe.throw(_("Error fetching device: {0}").format(str(e)))


@frappe.whitelist()
def create_device(**kwargs):
    """Create new device - equivalent to createLaptop"""
    try:
        # Extract device data from kwargs
        device_data = {
            "doctype": "ERP IT Inventory Device",
            "device_name": kwargs.get("device_name"),
            "device_type": kwargs.get("device_type"),
            "manufacturer": kwargs.get("manufacturer"),
            "serial_number": kwargs.get("serial_number"),
            "release_year": cint(kwargs.get("release_year")) if kwargs.get("release_year") else None,
            "status": kwargs.get("status", "Active"),
            "room": kwargs.get("room"),
            "processor": kwargs.get("processor"),
            "ram": kwargs.get("ram"),
            "storage": kwargs.get("storage"),
            "display": kwargs.get("display"),
            "additional_specs": kwargs.get("additional_specs"),
            "notes": kwargs.get("notes")
        }
        
        # Create device
        device = frappe.get_doc(device_data)
        device.insert()
        
        return {
            "status": "success",
            "message": _("Device created successfully"),
            "device_id": device.name
        }
        
    except Exception as e:
        frappe.log_error(f"Error in create_device: {str(e)}", "Device API Error")
        frappe.throw(_("Error creating device: {0}").format(str(e)))


@frappe.whitelist()
def update_device(device_id, **kwargs):
    """Update device - equivalent to updateLaptop"""
    try:
        device = frappe.get_doc("ERP IT Inventory Device", device_id)
        
        # Update fields
        for field, value in kwargs.items():
            if hasattr(device, field) and field != "name":
                if field == "release_year":
                    setattr(device, field, cint(value) if value else None)
                else:
                    setattr(device, field, value)
        
        device.save()
        
        return {
            "status": "success",
            "message": _("Device updated successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in update_device: {str(e)}", "Device API Error")
        frappe.throw(_("Error updating device: {0}").format(str(e)))


@frappe.whitelist()
def delete_device(device_id):
    """Delete device - equivalent to deleteLaptop"""
    try:
        # Check if device is assigned
        device = frappe.get_doc("ERP IT Inventory Device", device_id)
        if device.assigned_to:
            frappe.throw(_("Cannot delete device that is currently assigned"))
        
        frappe.delete_doc("ERP IT Inventory Device", device_id)
        
        return {
            "status": "success",
            "message": _("Device deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in delete_device: {str(e)}", "Device API Error")
        frappe.throw(_("Error deleting device: {0}").format(str(e)))


@frappe.whitelist()
def assign_device(device_id, user_id, notes=None):
    """Assign device to user - equivalent to assignLaptop"""
    try:
        return frappe.call("erp.it.doctype.erp_it_inventory_device.erp_it_inventory_device.assign_device",
                          device_name=device_id, user_id=user_id, notes=notes)
    except Exception as e:
        frappe.log_error(f"Error in assign_device: {str(e)}", "Device API Error")
        frappe.throw(_("Error assigning device: {0}").format(str(e)))


@frappe.whitelist()
def assign_device_with_handover(device_id, user_id, notes=None, handover_file_content=None, handover_file_name=None, username=None):
    """Assign device to user with handover document upload"""
    try:
        # First, assign the device
        device_type = get_device_type_from_id(device_id)
        result = frappe.call("erp.it.doctype.erp_it_inventory_device.erp_it_inventory_device.assign_device",
                          device_name=device_id, user_id=user_id, notes=notes)
        
        # If handover document is provided, upload it
        if handover_file_content and handover_file_name:
            from erp.inventory.api.file_upload import upload_handover_document
            upload_result = upload_handover_document(
                device_id=device_id,
                device_type=device_type,
                file_content=handover_file_content,
                file_name=handover_file_name,
                username=username
            )
            
            # Add file info to result
            result.update({
                "handover_file_uploaded": True,
                "file_url": upload_result.get("file_url"),
                "file_name": upload_result.get("file_name")
            })
        
        return result
        
    except Exception as e:
        frappe.log_error(f"Error in assign_device_with_handover: {str(e)}", "Device API Error")
        frappe.throw(_("Error assigning device with handover: {0}").format(str(e)))


def get_device_type_from_id(device_id):
    """Get device type from device ID"""
    try:
        device = frappe.get_doc("ERP IT Inventory Device", device_id)
        return device.device_type
    except Exception:
        # Fallback: try to determine from device_id pattern or return generic type
        return "Device"


@frappe.whitelist()
def revoke_device(device_id, user_id, reason=None):
    """Revoke device from user - equivalent to revokeLaptop"""
    try:
        return frappe.call("erp.it.doctype.erp_it_inventory_device.erp_it_inventory_device.revoke_device",
                          device_name=device_id, user_id=user_id, reason=reason)
    except Exception as e:
        frappe.log_error(f"Error in revoke_device: {str(e)}", "Device API Error")
        frappe.throw(_("Error revoking device: {0}").format(str(e)))


@frappe.whitelist()
def revoke_device_with_handover(device_id, user_id, reason=None, handover_file_content=None, handover_file_name=None, username=None):
    """Revoke device from user with handover document upload"""
    try:
        # First, revoke the device
        device_type = get_device_type_from_id(device_id)
        result = frappe.call("erp.it.doctype.erp_it_inventory_device.erp_it_inventory_device.revoke_device",
                          device_name=device_id, user_id=user_id, reason=reason)
        
        # If handover document is provided, upload it
        if handover_file_content and handover_file_name:
            from erp.inventory.api.file_upload import upload_handover_document
            upload_result = upload_handover_document(
                device_id=device_id,
                device_type=device_type,
                file_content=handover_file_content,
                file_name=handover_file_name,
                username=username
            )
            
            # Add file info to result
            result.update({
                "handover_file_uploaded": True,
                "file_url": upload_result.get("file_url"),
                "file_name": upload_result.get("file_name")
            })
        
        return result
        
    except Exception as e:
        frappe.log_error(f"Error in revoke_device_with_handover: {str(e)}", "Device API Error")
        frappe.throw(_("Error revoking device with handover: {0}").format(str(e)))


@frappe.whitelist()
def update_device_status(device_id, status, broken_reason=None):
    """Update device status - equivalent to updateLaptopStatus"""
    try:
        device = frappe.get_doc("ERP IT Inventory Device", device_id)
        device.status = status
        
        if status == "Broken" and broken_reason:
            device.broken_reason = broken_reason
        elif status != "Broken":
            device.broken_reason = None
            
        device.save()
        
        return {
            "status": "success",
            "message": _("Device status updated successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in update_device_status: {str(e)}", "Device API Error")
        frappe.throw(_("Error updating device status: {0}").format(str(e)))


@frappe.whitelist()
def get_device_filter_options():
    """Get filter options for devices - equivalent to getLaptopFilterOptions"""
    try:
        # Get unique manufacturers
        manufacturers = frappe.db.sql("""
            SELECT DISTINCT manufacturer 
            FROM `tabERP IT Inventory Device` 
            WHERE manufacturer IS NOT NULL AND manufacturer != ''
            ORDER BY manufacturer
        """, as_dict=True)
        
        # Get device types
        device_types = frappe.db.sql("""
            SELECT DISTINCT device_type 
            FROM `tabERP IT Inventory Device` 
            WHERE device_type IS NOT NULL AND device_type != ''
            ORDER BY device_type
        """, as_dict=True)
        
        # Get release years
        release_years = frappe.db.sql("""
            SELECT DISTINCT release_year 
            FROM `tabERP IT Inventory Device` 
            WHERE release_year IS NOT NULL
            ORDER BY release_year DESC
        """, as_dict=True)
        
        # Get status options
        status_options = ["Active", "Standby", "Broken", "PendingDocumentation"]
        
        return {
            "manufacturers": [m.manufacturer for m in manufacturers],
            "device_types": [d.device_type for d in device_types],
            "release_years": [r.release_year for r in release_years],
            "status_options": status_options
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_device_filter_options: {str(e)}", "Device API Error")
        frappe.throw(_("Error fetching filter options: {0}").format(str(e)))


@frappe.whitelist()
def bulk_upload_devices(devices_data):
    """Bulk upload devices - equivalent to bulkUploadLaptops"""
    try:
        if isinstance(devices_data, str):
            devices_data = json.loads(devices_data)
            
        success_count = 0
        error_count = 0
        errors = []
        
        for device_data in devices_data:
            try:
                # Create device
                device = frappe.get_doc({
                    "doctype": "ERP IT Inventory Device",
                    **device_data
                })
                device.insert()
                success_count += 1
                
            except Exception as e:
                error_count += 1
                errors.append(f"Row {len(errors) + 1}: {str(e)}")
        
        return {
            "status": "success" if error_count == 0 else "partial",
            "message": f"Processed {len(devices_data)} devices. Success: {success_count}, Errors: {error_count}",
            "success_count": success_count,
            "error_count": error_count,
            "errors": errors[:10]  # Limit to first 10 errors
        }
        
    except Exception as e:
        frappe.log_error(f"Error in bulk_upload_devices: {str(e)}", "Device API Error")
        frappe.throw(_("Error in bulk upload: {0}").format(str(e)))


@frappe.whitelist()
def get_device_stats():
    """Get device statistics - dashboard data"""
    try:
        return frappe.call("erp.it.doctype.erp_it_inventory_device.erp_it_inventory_device.get_device_stats")
    except Exception as e:
        frappe.log_error(f"Error in get_device_stats: {str(e)}", "Device API Error")
        frappe.throw(_("Error fetching device statistics: {0}").format(str(e)))