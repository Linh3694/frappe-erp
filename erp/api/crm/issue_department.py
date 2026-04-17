"""
API CRM Issue Department - Cau hinh phong ban lien quan
"""

import frappe
from erp.utils.api_response import (
    success_response,
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import get_request_data


def _enrich_members_user_image(data):
    """Gắn user_image (User) cho từng dòng members — mobile cần full URL qua resolve."""
    members = data.get("members") or []
    if not members:
        return
    emails = [m.get("user") for m in members if m.get("user")]
    if not emails:
        return
    users = {
        u.name: u
        for u in frappe.get_all(
            "User",
            filters={"name": ["in", emails]},
            fields=["name", "user_image"],
        )
    }
    for m in members:
        u = users.get(m.get("user") or "")
        m["user_image"] = (u.user_image if u else "") or ""


CONFIG_ROLES = [
    "System Manager",
    "SIS Manager",
    "SIS Sales Care Admin",
    "SIS Sales Admin",
]


def _check_config_permission():
    user_roles = frappe.get_roles(frappe.session.user)
    if not any(r in user_roles for r in CONFIG_ROLES):
        frappe.throw("Khong co quyen cau hinh phong ban", frappe.PermissionError)


@frappe.whitelist()
def get_departments():
    """Danh sach CRM Issue Department"""
    is_active = frappe.request.args.get("is_active")
    filters = {}
    if is_active is not None and is_active != "":
        filters["is_active"] = 1 if str(is_active).lower() in ("1", "true", "yes") else 0

    rows = frappe.get_all(
        "CRM Issue Department",
        filters=filters or None,
        fields=["name", "department_name", "is_active", "modified"],
        order_by="department_name asc",
    )
    for r in rows:
        r["member_count"] = frappe.db.count(
            "CRM Issue Dept Member", {"parent": r["name"], "parenttype": "CRM Issue Department"}
        )
    return success_response(rows)


@frappe.whitelist()
def get_department():
    """Chi tiet phong ban"""
    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Issue Department", name):
        return not_found_response("Khong tim thay phong ban")
    doc = frappe.get_doc("CRM Issue Department", name)
    payload = doc.as_dict()
    _enrich_members_user_image(payload)
    return single_item_response(payload)


@frappe.whitelist(methods=["POST"])
def create_department():
    """Tao phong ban"""
    _check_config_permission()
    data = get_request_data()
    if not data.get("department_name"):
        return validation_error_response("Thieu department_name", {"department_name": ["Bat buoc"]})

    try:
        doc = frappe.new_doc("CRM Issue Department")
        doc.department_name = data["department_name"]
        doc.is_active = 1 if data.get("is_active", True) else 0
        for row in data.get("members") or []:
            if row.get("user"):
                doc.append("members", {"user": row["user"]})
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Tao phong ban thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))


@frappe.whitelist(methods=["POST"])
def update_department():
    """Cap nhat phong ban"""
    _check_config_permission()
    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue Department", name):
        return not_found_response("Khong tim thay phong ban")

    try:
        doc = frappe.get_doc("CRM Issue Department", name)
        if "department_name" in data:
            doc.department_name = data["department_name"]
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
def delete_department():
    """Xoa phong ban neu chua issue gan"""
    _check_config_permission()
    data = get_request_data()
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists("CRM Issue Department", name):
        return not_found_response("Khong tim thay phong ban")

    n_direct = frappe.get_all("CRM Issue", filters={"department": name}, pluck="name")
    n_child = frappe.get_all(
        "CRM Issue Related Department",
        filters={"department": name, "parenttype": "CRM Issue"},
        pluck="parent",
    )
    cnt = len(set(n_direct or []) | set(n_child or []))
    if cnt:
        return error_response(f"Khong the xoa: dang co {cnt} van de gan phong ban nay")

    try:
        frappe.delete_doc("CRM Issue Department", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response({"deleted": True}, "Da xoa")
    except Exception as e:
        frappe.db.rollback()
        return error_response(str(e))
