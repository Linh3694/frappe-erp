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


def _normalize_crm_source_sub_rows(rows):
    """Chuẩn hóa dòng bảng con CRM Source Sub từ request JSON."""
    if not rows:
        return []
    if not isinstance(rows, (list, tuple)):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sub_name = (r.get("sub_source_name") or "").strip()
        if not sub_name:
            continue
        row = {"sub_source_name": sub_name}
        notes_val = r.get("notes")
        if notes_val is not None and str(notes_val).strip():
            row["notes"] = str(notes_val).strip()
        # Giữ name của dòng cũ khi cập nhật (Frappe merge/replace child table)
        row_id = r.get("name")
        if row_id:
            row["name"] = row_id
        out.append(row)
    return out


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
    """Danh sách nguồn cha kèm bảng con sub_sources (get_all không trả child table)."""
    check_crm_permission()
    names = frappe.get_all("CRM Source", pluck="name", order_by="creation desc")
    items = []
    for n in names:
        doc = frappe.get_doc("CRM Source", n)
        items.append(doc.as_dict())
    return list_response(items)


@frappe.whitelist(methods=["POST"])
def create_source():
    check_crm_permission()
    data = get_request_data()
    if not data.get("source_name"):
        return validation_error_response("Thieu source_name", {"source_name": ["Bat buoc"]})
    sub_rows = _normalize_crm_source_sub_rows(data.get("sub_sources"))
    try:
        doc = frappe.get_doc(
            {
                "doctype": "CRM Source",
                "source_name": (data.get("source_name") or "").strip(),
                "notes": data.get("notes"),
                "sub_sources": sub_rows,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tao thanh cong")
    except frappe.DuplicateEntryError:
        return error_response(f"{data.get('source_name')} da ton tai")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_source():
    check_crm_permission()
    data = get_request_data()
    name = data.get("name")
    if not frappe.db.exists("CRM Source", name):
        return not_found_response(f"Khong tim thay {name}")
    try:
        doc = frappe.get_doc("CRM Source", name)
        if "source_name" in data and data.get("source_name"):
            doc.source_name = (data.get("source_name") or "").strip()
        if "notes" in data:
            doc.notes = data.get("notes")
        if "sub_sources" in data:
            doc.set("sub_sources", _normalize_crm_source_sub_rows(data.get("sub_sources")))
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cap nhat thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")

@frappe.whitelist(methods=["POST"])
def delete_source():
    return _crud_delete("CRM Source", get_request_data().get("name"))


# --- CRM Promotion ---
@frappe.whitelist()
def get_promotions():
    return _crud_list("CRM Promotion")


@frappe.whitelist(methods=["POST"])
def create_promotion():
    return _crud_create("CRM Promotion", get_request_data(), "promotion_name")


@frappe.whitelist(methods=["POST"])
def update_promotion():
    data = get_request_data()
    return _crud_update("CRM Promotion", data.get("name"), data)


@frappe.whitelist(methods=["POST"])
def delete_promotion():
    return _crud_delete("CRM Promotion", get_request_data().get("name"))


# --- CRM Admission Profile Type (Hồ sơ nhập học) ---
@frappe.whitelist()
def get_admission_profile_types():
    return _crud_list("CRM Admission Profile Type")


@frappe.whitelist(methods=["POST"])
def create_admission_profile_type():
    return _crud_create("CRM Admission Profile Type", get_request_data(), "profile_type")


@frappe.whitelist(methods=["POST"])
def update_admission_profile_type():
    data = get_request_data()
    return _crud_update("CRM Admission Profile Type", data.get("name"), data)


@frappe.whitelist(methods=["POST"])
def delete_admission_profile_type():
    return _crud_delete("CRM Admission Profile Type", get_request_data().get("name"))


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
