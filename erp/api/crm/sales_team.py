"""
CRM Sales Team API - Quan ly nhom user nhan lead (auto-assign).

Nhom nay la nguon ung vien cho assign_pic_sales_weight_balance (erp.api.crm.assignment).
Khi bang rong -> auto-assign fallback ve role SIS Sales Admin.
"""

import frappe
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    list_response, validation_error_response, not_found_response,
)
from erp.api.crm.utils import check_crm_permission, get_request_data

DOCTYPE = "CRM Sales Team Member"

# Chi Manager / Sales Admin duoc chinh sua nhom nhan lead
_MANAGE_ROLES = ["System Manager", "SIS Manager", "SIS Sales Admin"]

# Role duoc phep them vao nhom nhan lead (ung vien PIC lead)
_RECEIVER_CANDIDATE_ROLES = ("SIS Sales", "SIS Sales Admin")


def _user_display(user_name):
    """Thong tin hien thi User cho danh sach nhom."""
    u = frappe.db.get_value(
        "User", user_name, ["name", "full_name", "email", "enabled", "user_image"], as_dict=True
    )
    if not u:
        return {
            "user": user_name, "full_name": user_name, "email": user_name,
            "enabled": 0, "user_image": "",
        }
    return {
        "user": u.get("name"),
        "full_name": (u.get("full_name") or u.get("email") or u.get("name")),
        "email": u.get("email") or u.get("name"),
        "enabled": 1 if u.get("enabled") else 0,
        "user_image": u.get("user_image") or "",
    }


@frappe.whitelist()
def get_sales_team():
    """Danh sach thanh vien nhom nhan lead (kem thong tin User)."""
    check_crm_permission()
    members = frappe.get_all(
        DOCTYPE,
        fields=["name", "user", "is_active"],
        order_by="creation asc",
    )
    out = []
    for m in members:
        info = _user_display(m.get("user"))
        out.append(
            {
                "name": m.get("name"),
                "user": m.get("user"),
                "is_active": 1 if m.get("is_active") else 0,
                "full_name": info["full_name"],
                "email": info["email"],
                "enabled": info["enabled"],
                "user_image": info["user_image"],
            }
        )
    return list_response(out)


@frappe.whitelist()
def get_eligible_sales_users():
    """User co the them vao nhom: co role Sales/Sales Admin, enabled, chua co trong nhom."""
    check_crm_permission()
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name, u.full_name, u.email, u.user_image
        FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role IN %(roles)s AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.full_name, u.name
        """,
        {"roles": _RECEIVER_CANDIDATE_ROLES},
        as_dict=True,
    )
    existing = set(frappe.get_all(DOCTYPE, pluck="user"))
    out = [
        {
            "user": r.get("name"),
            "full_name": r.get("full_name") or r.get("email") or r.get("name"),
            "email": r.get("email") or r.get("name"),
            "user_image": r.get("user_image") or "",
        }
        for r in rows
        if r.get("name") not in existing
    ]
    return list_response(out)


@frappe.whitelist(methods=["POST"])
def add_sales_team_member():
    """Them user vao nhom nhan lead."""
    check_crm_permission(_MANAGE_ROLES)
    data = get_request_data()
    user = (data.get("user") or "").strip()

    if not user:
        return validation_error_response("Thieu user", {"user": ["Bat buoc"]})
    if not frappe.db.exists("User", user):
        return not_found_response(f"Khong tim thay User {user}")
    if frappe.db.exists(DOCTYPE, user):
        return error_response("User da co trong nhom nhan lead")

    try:
        doc = frappe.new_doc(DOCTYPE)
        doc.user = user
        doc.is_active = 1 if data.get("is_active", 1) else 0
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Da them vao nhom nhan lead")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi them thanh vien: {str(e)}")


@frappe.whitelist(methods=["POST"])
def set_sales_team_member_active():
    """Bat/tat hoat dong 1 thanh vien (name = docname / user)."""
    check_crm_permission(_MANAGE_ROLES)
    data = get_request_data()
    name = (data.get("name") or "").strip()
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists(DOCTYPE, name):
        return not_found_response(f"Khong tim thay thanh vien {name}")

    try:
        doc = frappe.get_doc(DOCTYPE, name)
        doc.is_active = 1 if data.get("is_active") else 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Da cap nhat trang thai")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")


@frappe.whitelist(methods=["POST"])
def remove_sales_team_member():
    """Xoa 1 thanh vien khoi nhom nhan lead."""
    check_crm_permission(_MANAGE_ROLES)
    data = get_request_data()
    name = (data.get("name") or "").strip()
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists(DOCTYPE, name):
        return not_found_response(f"Khong tim thay thanh vien {name}")

    try:
        frappe.delete_doc(DOCTYPE, name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message=f"Da xoa {name} khoi nhom nhan lead")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa: {str(e)}")
