"""
CRM History API - Lich su chuyen buoc va thay doi thong tin
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission


@frappe.whitelist()
def get_step_history():
    """Lich su chuyen buoc"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    history = frappe.get_all(
        "CRM Lead Step History",
        filters={"lead": lead_name},
        fields=["old_step", "new_step", "old_status", "new_status", "changed_by", "changed_at"],
        order_by="changed_at asc"
    )
    
    return list_response(history)


@frappe.whitelist()
def get_change_history():
    """Lich su thay doi thong tin (dung Frappe Version)"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    versions = frappe.get_all(
        "Version",
        filters={"ref_doctype": "CRM Lead", "docname": lead_name},
        fields=["name", "owner", "creation", "data"],
        order_by="creation desc",
        limit_page_length=50
    )
    
    changes = []
    for v in versions:
        try:
            import json
            version_data = json.loads(v.get("data", "{}"))
            changed_fields = version_data.get("changed", [])
            changes.append({
                "version": v["name"],
                "changed_by": v["owner"],
                "changed_at": str(v["creation"]),
                "changes": changed_fields
            })
        except Exception:
            pass
    
    return list_response(changes)
