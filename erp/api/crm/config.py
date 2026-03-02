"""
CRM Config API - CRUD cau hinh du lieu
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


def _crud_list(doctype):
    """Helper: lay danh sach"""
    check_crm_permission()
    items = frappe.get_all(doctype, fields=["*"], order_by="creation desc")
    return list_response(items)


def _crud_create(doctype, data, name_field):
    """Helper: tao moi"""
    check_crm_permission()
    
    if not data.get(name_field):
        return validation_error_response(f"Thieu {name_field}", {name_field: ["Bat buoc"]})
    
    try:
        doc = frappe.new_doc(doctype)
        for key, val in data.items():
            if hasattr(doc, key):
                doc.set(key, val)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), f"Tao thanh cong")
    except frappe.DuplicateEntryError:
        return error_response(f"{data[name_field]} da ton tai")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao: {str(e)}")


def _crud_update(doctype, name, data):
    """Helper: cap nhat"""
    check_crm_permission()
    
    if not frappe.db.exists(doctype, name):
        return not_found_response(f"Khong tim thay {name}")
    
    try:
        doc = frappe.get_doc(doctype, name)
        for key, val in data.items():
            if key != "name" and hasattr(doc, key):
                doc.set(key, val)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cap nhat thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")


def _crud_delete(doctype, name):
    """Helper: xoa"""
    check_crm_permission()
    
    if not frappe.db.exists(doctype, name):
        return not_found_response(f"Khong tim thay {name}")
    
    try:
        frappe.delete_doc(doctype, name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message=f"Da xoa {name}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa: {str(e)}")


# --- CRM Source ---
@frappe.whitelist()
def get_sources():
    return _crud_list("CRM Source")

@frappe.whitelist(methods=["POST"])
def create_source():
    return _crud_create("CRM Source", get_request_data(), "source_name")

@frappe.whitelist(methods=["POST"])
def update_source():
    data = get_request_data()
    return _crud_update("CRM Source", data.get("name"), data)

@frappe.whitelist(methods=["POST"])
def delete_source():
    return _crud_delete("CRM Source", get_request_data().get("name"))


# --- CRM Referrer ---
@frappe.whitelist()
def get_referrers():
    return _crud_list("CRM Referrer")

@frappe.whitelist(methods=["POST"])
def create_referrer():
    return _crud_create("CRM Referrer", get_request_data(), "referrer_name")

@frappe.whitelist(methods=["POST"])
def update_referrer():
    data = get_request_data()
    return _crud_update("CRM Referrer", data.get("name"), data)

@frappe.whitelist(methods=["POST"])
def delete_referrer():
    return _crud_delete("CRM Referrer", get_request_data().get("name"))


# --- CRM School ---
@frappe.whitelist()
def get_schools():
    return _crud_list("CRM School")

@frappe.whitelist(methods=["POST"])
def create_school():
    return _crud_create("CRM School", get_request_data(), "school_name")

@frappe.whitelist(methods=["POST"])
def update_school():
    data = get_request_data()
    return _crud_update("CRM School", data.get("name"), data)

@frappe.whitelist(methods=["POST"])
def delete_school():
    return _crud_delete("CRM School", get_request_data().get("name"))


# --- CRM Email Template ---
@frappe.whitelist()
def get_email_templates():
    return _crud_list("CRM Email Template")

@frappe.whitelist(methods=["POST"])
def create_email_template():
    return _crud_create("CRM Email Template", get_request_data(), "template_name")

@frappe.whitelist(methods=["POST"])
def update_email_template():
    data = get_request_data()
    return _crud_update("CRM Email Template", data.get("name"), data)

@frappe.whitelist(methods=["POST"])
def delete_email_template():
    return _crud_delete("CRM Email Template", get_request_data().get("name"))
