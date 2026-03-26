"""
API CRM Issue Module - Cau hinh loai van de (prefix, SLA, thanh vien)
"""

import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import check_crm_permission, get_request_data

CONFIG_ROLES = [
    "System Manager",
    "SIS Manager",
    "SIS Sales Care Admin",
    "SIS Sales Admin",
]


def _check_config_permission():
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(r in user_roles for r in CONFIG_ROLES):
        frappe.throw("Khong co quyen cau hinh loai van de", frappe.PermissionError)


@frappe.whitelist()
def get_modules():
    """Danh sach CRM Issue Module"""
    check_crm_permission()
    is_active = frappe.request.args.get("is_active")
    filters = {}
    if is_active is not None and is_active != "":
        filters["is_active"] = 1 if str(is_active).lower() in ("1", "true", "yes") else 0

    modules = frappe.get_all(
        "CRM Issue Module",
        filters=filters or None,
        fields=["name", "module_name", "code", "sla_hours", "description", "is_active", "modified"],
        order_by="module_name asc",
    )
    for m in modules:
        m["member_count"] = frappe.db.count(
            "CRM Issue Module Member", {"parent": m["name"], "parenttype": "CRM Issue Module"}
        )
    return success_response(modules)


@frappe.whitelist()
def get_module():
    """Chi tiet module kem members"""
    check_crm_permission()
    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Issue Module", name):
        return not_found_response("Khong tim thay module")
    doc = frappe.get_doc("CRM Issue Module", name)
    return single_item_response(doc.as_dict())


@frappe.whitelist(methods=["POST"])
def create_module():
    """Tao CRM Issue Module"""
    _check_config_permission()
    data = get_request_data()
    if not data.get("module_name") or not data.get("code"):
        return validation_error_response("Thieu thong tin", {"module_name": ["Bat buoc"], "code": ["Bat buoc"]})

    code = str(data["code"]).strip().upper()
    if frappe.db.exists("CRM Issue Module", {"code": code}):
        return validation_error_response("Ma da ton tai", {"code": ["Trung"]})

    try:
        doc = frappe.new_doc("CRM Issue Module")
        doc.module_name = data["module_name"]
        doc.code = code
        doc.sla_hours = float(data.get("sla_hours") or 0)
        doc.description = data.get("description") or ""
        doc.is_active = 1 if data.get("is_active", True) else 0
        for row in data.get("members") or []:
            if row.get("user"):
                doc.append("members", {"user": row["user"]})
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tao module thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))


@frappe.whitelist(methods=["POST"])
def update_module():
    """Cap nhat CRM Issue Module"""
    _check_config_permission()
    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue Module", name):
        return not_found_response("Khong tim thay module")

    try:
        doc = frappe.get_doc("CRM Issue Module", name)
        if "module_name" in data:
            doc.module_name = data["module_name"]
        if "code" in data:
            new_code = str(data["code"]).strip().upper()
            exists = frappe.db.exists("CRM Issue Module", {"code": new_code, "name": ["!=", name]})
            if exists:
                return validation_error_response("Ma da ton tai", {"code": ["Trung"]})
            doc.code = new_code
        if "sla_hours" in data:
            doc.sla_hours = float(data["sla_hours"] or 0)
        if "description" in data:
            doc.description = data.get("description") or ""
        if "is_active" in data:
            doc.is_active = 1 if data.get("is_active") else 0
        if "members" in data:
            doc.members = []
            for row in data.get("members") or []:
                if row.get("user"):
                    doc.append("members", {"user": row["user"]})
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Cap nhat thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))


@frappe.whitelist(methods=["POST"])
def delete_module():
    """Xoa module neu chua co issue"""
    _check_config_permission()
    data = get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Issue Module", name):
        return not_found_response("Khong tim thay module")

    cnt = frappe.db.count("CRM Issue", {"issue_module": name})
    if cnt:
        return error_response(f"Khong the xoa: dang co {cnt} van de su dung module nay")

    try:
        frappe.delete_doc("CRM Issue Module", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response({"deleted": True}, "Da xoa")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))
