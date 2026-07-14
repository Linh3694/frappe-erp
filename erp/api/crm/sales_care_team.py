"""
CRM Sales Care Team API - Quan ly nhom user cham soc (auto-assign QLead->Enrolled theo Lop du tuyen).

Nguon ung vien cho assign_pic_sales_care_weight_balance (erp.api.crm.assignment):
chon theo lop du tuyen cua ho so. Khong cau hinh / khong ai phu trach lop -> fallback SIS Sales Care Admin.
"""

import frappe
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    list_response, validation_error_response, not_found_response,
)
from erp.api.crm.utils import check_crm_permission, get_request_data

DOCTYPE = "CRM Sales Care Member"

# Chi Manager / Sales Care Admin duoc chinh sua nhom cham soc
_MANAGE_ROLES = ["System Manager", "SIS Manager", "SIS Sales Care Admin"]

# Role duoc phep them vao nhom cham soc
_CARE_CANDIDATE_ROLES = ("SIS Sales Care", "SIS Sales Care Admin")

# Lop du tuyen hop le (khop CRM Lead.target_grade)
_VALID_TARGET_GRADES = [str(n) for n in range(1, 13)]


def _user_display(user_name):
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


def _member_grades(member_name):
    """Danh sach lop du tuyen (chuoi) cua 1 thanh vien, sap xep theo so."""
    rows = frappe.get_all(
        "CRM Sales Care Member Grade",
        filters={"parent": member_name, "parenttype": DOCTYPE},
        pluck="target_grade",
    )
    grades = [str(g).strip() for g in rows if str(g).strip()]
    return sorted(set(grades), key=lambda g: int(g) if g.isdigit() else 99)


def _clean_grades(raw):
    """Chuan hoa list lop du tuyen tu request -> chuoi hop le, khong trung."""
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for g in raw:
        s = str(g).strip()
        if s in _VALID_TARGET_GRADES and s not in out:
            out.append(s)
    return sorted(out, key=lambda g: int(g))


def _apply_grades(doc, grades):
    doc.set("target_grades", [])
    for g in grades:
        doc.append("target_grades", {"target_grade": g})


@frappe.whitelist()
def get_sales_care_team():
    """Danh sach thanh vien nhom cham soc (kem User + lop du tuyen phu trach)."""
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
                "target_grades": _member_grades(m.get("name")),
            }
        )
    return list_response(out)


@frappe.whitelist()
def get_eligible_sales_care_users():
    """User co the them: role Sales Care / Sales Care Admin, enabled, chua co trong nhom."""
    check_crm_permission()
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name, u.full_name, u.email, u.user_image
        FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role IN %(roles)s AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.full_name, u.name
        """,
        {"roles": _CARE_CANDIDATE_ROLES},
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
def add_sales_care_member():
    """Them user vao nhom cham soc (kem lop du tuyen tuy chon)."""
    check_crm_permission(_MANAGE_ROLES)
    data = get_request_data()
    user = (data.get("user") or "").strip()

    if not user:
        return validation_error_response("Thieu user", {"user": ["Bat buoc"]})
    if not frappe.db.exists("User", user):
        return not_found_response(f"Khong tim thay User {user}")
    if frappe.db.exists(DOCTYPE, user):
        return error_response("User da co trong nhom cham soc")

    try:
        doc = frappe.new_doc(DOCTYPE)
        doc.user = user
        doc.is_active = 1 if data.get("is_active", 1) else 0
        _apply_grades(doc, _clean_grades(data.get("target_grades")))
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Da them vao nhom cham soc")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi them thanh vien: {str(e)}")


@frappe.whitelist(methods=["POST"])
def set_sales_care_member_active():
    """Bat/tat hoat dong 1 thanh vien cham soc."""
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
def set_sales_care_member_grades():
    """Cap nhat danh sach Lop du tuyen phu trach cua 1 thanh vien (ghi de)."""
    check_crm_permission(_MANAGE_ROLES)
    data = get_request_data()
    name = (data.get("name") or "").strip()
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    if not frappe.db.exists(DOCTYPE, name):
        return not_found_response(f"Khong tim thay thanh vien {name}")

    try:
        doc = frappe.get_doc(DOCTYPE, name)
        _apply_grades(doc, _clean_grades(data.get("target_grades")))
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(doc.as_dict(), "Da cap nhat lop du tuyen phu trach")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat lop du tuyen: {str(e)}")


@frappe.whitelist(methods=["POST"])
def remove_sales_care_member():
    """Xoa 1 thanh vien khoi nhom cham soc."""
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
        return success_response(message=f"Da xoa {name} khoi nhom cham soc")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa: {str(e)}")
