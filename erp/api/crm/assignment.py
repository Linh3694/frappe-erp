"""
CRM PIC Assignment API - Phan bo PIC round-robin (CRM PIC Config) + can bang tai SIS Sales (assign_pic_sales_weight_balance)
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    validation_error_response, not_found_response, list_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


@frappe.whitelist()
def get_pic_config():
    """Lay cau hinh PIC hien tai"""
    check_crm_permission()
    campus_id = frappe.request.args.get("campus_id")
    
    if not campus_id:
        return validation_error_response("Thieu campus_id", {"campus_id": ["Bat buoc"]})
    
    config = frappe.db.get_value("CRM PIC Config", {"campus_id": campus_id}, "name")
    if not config:
        return success_response({"campus_id": campus_id, "pic_list": [], "current_index": 0})
    
    doc = frappe.get_doc("CRM PIC Config", config)
    return single_item_response(doc.as_dict())


@frappe.whitelist(methods=["POST"])
def update_pic_config():
    """Cap nhat danh sach PIC (Manager only)"""
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()
    
    campus_id = data.get("campus_id")
    pic_list = data.get("pic_list", [])
    
    if not campus_id:
        return validation_error_response("Thieu campus_id", {"campus_id": ["Bat buoc"]})
    
    try:
        config_name = frappe.db.get_value("CRM PIC Config", {"campus_id": campus_id}, "name")
        
        if config_name:
            doc = frappe.get_doc("CRM PIC Config", config_name)
        else:
            doc = frappe.new_doc("CRM PIC Config")
            doc.campus_id = campus_id
            doc.current_index = 0
        
        doc.set("pic_list", [])
        for item in pic_list:
            doc.append("pic_list", {
                "user": item.get("user"),
                "is_active": item.get("is_active", 1)
            })
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Da cap nhat cau hinh PIC")
    
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat cau hinh PIC: {str(e)}")


def _get_active_sis_sales_user_names():
    """Danh sach User (name) co role SIS Sales va enabled=1."""
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role = 'SIS Sales' AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.name
        """
    )
    return [r[0] for r in rows] if rows else []


def assign_pic_sales_weight_balance(lead_name, campus_id=None):
    """
    Gan PIC mac dinh: user SIS Sales dang dam nhan it ho so CRM Lead nhat (can bang tai / least-loaded).
    Khong ghi de neu ho so da co pic. campus_id: chi dem ho so cung campus khi co gia tri.
    """
    existing = frappe.db.get_value("CRM Lead", lead_name, "pic")
    if existing:
        return None

    users = _get_active_sis_sales_user_names()
    if not users:
        return None

    counts = {}
    for u in users:
        filters = {"pic": u, "docstatus": ["<", 2]}
        if campus_id:
            filters["campus_id"] = campus_id
        counts[u] = frappe.db.count("CRM Lead", filters=filters)

    # Chon user co count nho nhat; hoa: sap xep theo name
    chosen = min(users, key=lambda x: (counts.get(x, 0), x))
    frappe.db.set_value("CRM Lead", lead_name, "pic", chosen)
    return chosen


def assign_pic_internal(lead_name, campus_id):
    """Phan bo PIC tu dong theo round-robin (internal, khong can whitelist)"""
    config_name = frappe.db.get_value("CRM PIC Config", {"campus_id": campus_id}, "name")
    if not config_name:
        return None
    
    config = frappe.get_doc("CRM PIC Config", config_name)
    active_pics = [item for item in config.pic_list if item.is_active]
    
    if not active_pics:
        return None
    
    current_index = config.current_index or 0
    if current_index >= len(active_pics):
        current_index = 0
    
    assigned_pic = active_pics[current_index].user
    
    # Cap nhat index
    config.current_index = (current_index + 1) % len(active_pics)
    config.save(ignore_permissions=True)
    
    # Cap nhat lead
    frappe.db.set_value("CRM Lead", lead_name, "pic", assigned_pic)
    
    return assigned_pic


@frappe.whitelist(methods=["POST"])
def assign_pic():
    """Phan bo PIC tu dong"""
    check_crm_permission()
    data = get_request_data()
    
    lead_name = data.get("lead_name")
    campus_id = data.get("campus_id")
    
    if not lead_name or not campus_id:
        return validation_error_response("Thieu tham so", {
            "lead_name": ["Bat buoc"] if not lead_name else [],
            "campus_id": ["Bat buoc"] if not campus_id else []
        })
    
    assigned = assign_pic_internal(lead_name, campus_id)
    if assigned:
        frappe.db.commit()
        return success_response({"pic": assigned}, f"Da phan bo PIC: {assigned}")
    
    return error_response("Khong tim thay cau hinh PIC hoac khong co PIC active")


@frappe.whitelist(methods=["POST"])
def reassign_pic():
    """Chuyen PIC thu cong"""
    check_crm_permission()
    data = get_request_data()
    
    lead_name = data.get("lead_name")
    new_pic = data.get("new_pic")
    
    if not lead_name or not new_pic:
        return validation_error_response("Thieu tham so", {
            "lead_name": ["Bat buoc"] if not lead_name else [],
            "new_pic": ["Bat buoc"] if not new_pic else []
        })
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    frappe.db.set_value("CRM Lead", lead_name, "pic", new_pic)
    frappe.db.commit()
    
    return success_response({"pic": new_pic}, f"Da chuyen PIC sang {new_pic}")
