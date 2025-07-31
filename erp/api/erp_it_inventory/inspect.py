# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint, getdate
import json


@frappe.whitelist()
def get_inspections(page=1, limit=20, device_id=None, inspector_id=None, start_date=None, end_date=None):
    """Get inspections with filters - equivalent to getAllInspections"""
    try:
        page = cint(page) or 1
        limit = cint(limit) or 20
        start = (page - 1) * limit
        
        # Build filters
        filters = {}
        if device_id:
            filters["device_id"] = device_id
        if inspector_id:
            filters["inspector_id"] = inspector_id
        if start_date and end_date:
            filters["inspection_date"] = ["between", [getdate(start_date), getdate(end_date)]]
            
        # Get inspections
        inspections = frappe.get_list(
            "ERP IT Inventory Inspect",
            filters=filters,
            fields=[
                "name", "device_id", "device_type", "inspector_id", 
                "inspection_date", "overall_assessment", "passed",
                "recommendations", "technical_conclusion"
            ],
            start=start,
            limit=limit,
            order_by="inspection_date desc"
        )
        
        # Enrich data
        for inspection in inspections:
            # Get device name
            if inspection.device_id:
                inspection.device_name = frappe.get_value("ERP IT Inventory Device", inspection.device_id, "device_name")
            
            # Get inspector name
            if inspection.inspector_id:
                inspection.inspector_name = frappe.get_value("User", inspection.inspector_id, "full_name")
        
        # Get total count
        total_count = frappe.db.count("ERP IT Inventory Inspect", filters)
        
        return {
            "inspections": inspections,
            "pagination": {
                "current_page": page,
                "total_pages": (total_count + limit - 1) // limit,
                "total_items": total_count,
                "items_per_page": limit
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_inspections: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error fetching inspections: {0}").format(str(e)))


@frappe.whitelist()
def get_inspection(inspection_id):
    """Get single inspection details - equivalent to getInspectionById"""
    try:
        inspection = frappe.get_doc("ERP IT Inventory Inspect", inspection_id)
        inspection_dict = inspection.as_dict()
        
        # Get device details
        if inspection.device_id:
            device = frappe.get_doc("ERP IT Inventory Device", inspection.device_id)
            inspection_dict["device_details"] = {
                "device_name": device.device_name,
                "device_type": device.device_type,
                "manufacturer": device.manufacturer,
                "serial_number": device.serial_number
            }
        
        # Get inspector name
        if inspection.inspector_id:
            inspection_dict["inspector_name"] = frappe.get_value("User", inspection.inspector_id, "full_name")
        
        return inspection_dict
        
    except Exception as e:
        frappe.log_error(f"Error in get_inspection: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error fetching inspection: {0}").format(str(e)))


@frappe.whitelist()
def create_inspection(**kwargs):
    """Create new inspection - equivalent to createInspection"""
    try:
        # Validate required fields
        device_id = kwargs.get("device_id")
        if not device_id:
            frappe.throw(_("Device ID is required"))
            
        if not frappe.db.exists("ERP IT Inventory Device", device_id):
            frappe.throw(_("Device {0} does not exist").format(device_id))
        
        # Get device type
        device_type = frappe.get_value("ERP IT Inventory Device", device_id, "device_type")
        
        # Build inspection data
        inspection_data = {
            "doctype": "ERP IT Inventory Inspect",
            "device_id": device_id,
            "device_type": device_type,
            "inspector_id": kwargs.get("inspector_id") or frappe.session.user,
            "overall_assessment": kwargs.get("overall_assessment", ""),
            "passed": kwargs.get("passed", True),
            "recommendations": kwargs.get("recommendations", ""),
            "technical_conclusion": kwargs.get("technical_conclusion", ""),
            "follow_up_recommendation": kwargs.get("follow_up_recommendation", "")
        }
        
        # Add inspection results
        inspection_fields = [
            "external_condition_overall", "external_condition_notes",
            "cpu_performance", "cpu_temperature", "cpu_overall_condition", "cpu_notes",
            "ram_consumption", "ram_overall_condition", "ram_notes",
            "storage_remaining_capacity", "storage_overall_condition", "storage_notes",
            "battery_capacity", "battery_performance", "battery_charge_cycles", 
            "battery_overall_condition", "battery_notes",
            "display_color_brightness", "display_overall_condition", "display_notes",
            "connectivity_overall_condition", "connectivity_notes",
            "software_overall_condition", "software_notes"
        ]
        
        for field in inspection_fields:
            if kwargs.get(field):
                inspection_data[field] = kwargs.get(field)
        
        # Create inspection
        inspection = frappe.get_doc(inspection_data)
        inspection.insert()
        
        return {
            "status": "success",
            "message": _("Inspection created successfully"),
            "inspection_id": inspection.name
        }
        
    except Exception as e:
        frappe.log_error(f"Error in create_inspection: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error creating inspection: {0}").format(str(e)))


@frappe.whitelist()
def update_inspection(inspection_id, **kwargs):
    """Update inspection"""
    try:
        inspection = frappe.get_doc("ERP IT Inventory Inspect", inspection_id)
        
        # Update fields
        for field, value in kwargs.items():
            if hasattr(inspection, field) and field != "name":
                setattr(inspection, field, value)
        
        inspection.save()
        
        return {
            "status": "success",
            "message": _("Inspection updated successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in update_inspection: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error updating inspection: {0}").format(str(e)))


@frappe.whitelist()
def delete_inspection(inspection_id):
    """Delete inspection"""
    try:
        frappe.delete_doc("ERP IT Inventory Inspect", inspection_id)
        
        return {
            "status": "success",
            "message": _("Inspection deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in delete_inspection: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error deleting inspection: {0}").format(str(e)))


@frappe.whitelist()
def get_device_inspections(device_id, limit=10):
    """Get inspection history for a device - equivalent to getLatestInspectionByDeviceId"""
    try:
        return frappe.call(
            "erp.inventory.doctype.erp_it_inventory_inspect.erp_it_inventory_inspect.get_device_inspections",
            device_id=device_id,
            limit=limit
        )
    except Exception as e:
        frappe.log_error(f"Error in get_device_inspections: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error fetching device inspections: {0}").format(str(e)))


@frappe.whitelist()
def get_latest_inspection(device_id):
    """Get latest inspection for a device"""
    try:
        return frappe.call(
            "erp.inventory.doctype.erp_it_inventory_inspect.erp_it_inventory_inspect.get_latest_inspection",
            device_id=device_id
        )
    except Exception as e:
        frappe.log_error(f"Error in get_latest_inspection: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error fetching latest inspection: {0}").format(str(e)))


@frappe.whitelist()
def upload_inspection_report(inspection_id, file_url):
    """Upload inspection report file"""
    try:
        inspection = frappe.get_doc("ERP IT Inventory Inspect", inspection_id)
        inspection.report_file = file_url
        inspection.report_file_path = file_url
        inspection.save()
        
        return {
            "status": "success",
            "message": _("Report uploaded successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in upload_inspection_report: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error uploading report: {0}").format(str(e)))


@frappe.whitelist()
def get_inspection_report(inspection_id):
    """Generate inspection report data"""
    try:
        return frappe.call(
            "erp.inventory.doctype.erp_it_inventory_inspect.erp_it_inventory_inspect.create_inspection_report",
            inspection_id=inspection_id
        )
    except Exception as e:
        frappe.log_error(f"Error in get_inspection_report: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error generating inspection report: {0}").format(str(e)))


@frappe.whitelist()
def get_inspection_stats():
    """Get inspection statistics"""
    try:
        return frappe.call(
            "erp.inventory.doctype.erp_it_inventory_inspect.erp_it_inventory_inspect.get_inspection_stats"
        )
    except Exception as e:
        frappe.log_error(f"Error in get_inspection_stats: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error fetching inspection statistics: {0}").format(str(e)))


@frappe.whitelist()
def get_inspection_dashboard():
    """Get inspection dashboard data"""
    try:
        # Get basic stats
        stats = get_inspection_stats()
        
        # Get devices needing inspection (no inspection in last 90 days)
        from frappe.utils import add_days, nowdate
        ninety_days_ago = add_days(nowdate(), -90)
        
        devices_needing_inspection = frappe.db.sql("""
            SELECT d.name, d.device_name, d.device_type, d.status
            FROM `tabERP IT Inventory Device` d
            LEFT JOIN `tabERP IT Inventory Inspect` i ON d.name = i.device_id 
                AND i.inspection_date >= %s
            WHERE d.status = 'Active' AND i.name IS NULL
            ORDER BY d.device_name
            LIMIT 10
        """, (ninety_days_ago,), as_dict=True)
        
        # Get recent failed inspections
        failed_inspections = frappe.get_list(
            "ERP IT Inventory Inspect",
            filters={"passed": 0},
            fields=[
                "name", "device_id", "inspection_date", "overall_assessment", 
                "inspector_id", "recommendations"
            ],
            limit=5,
            order_by="inspection_date desc"
        )
        
        # Enrich failed inspections data
        for inspection in failed_inspections:
            if inspection.device_id:
                inspection.device_name = frappe.get_value("ERP IT Inventory Device", inspection.device_id, "device_name")
            if inspection.inspector_id:
                inspection.inspector_name = frappe.get_value("User", inspection.inspector_id, "full_name")
        
        return {
            "stats": stats,
            "devices_needing_inspection": devices_needing_inspection,
            "failed_inspections": failed_inspections
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_inspection_dashboard: {str(e)}", "Inspect API Error")
        frappe.throw(_("Error fetching inspection dashboard: {0}").format(str(e)))