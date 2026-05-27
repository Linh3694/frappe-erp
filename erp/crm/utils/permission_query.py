"""
CRM Permission Query - Filter CRM doctypes theo campus_id
"""

import frappe


def crm_lead_query(user):
    """Filter CRM Lead theo campus_id cua user"""
    if "System Manager" in frappe.get_roles(user):
        return ""
    
    campus_ids = _get_user_campus_ids(user)
    if not campus_ids:
        return "1=0"
    
    campus_list = ", ".join([f"'{c}'" for c in campus_ids])
    return f"`tabCRM Lead`.campus_id IN ({campus_list})"


def crm_exam_query(user):
    """Filter CRM Exam theo campus_id cua user"""
    if "System Manager" in frappe.get_roles(user):
        return ""
    
    campus_ids = _get_user_campus_ids(user)
    if not campus_ids:
        return "1=0"
    
    campus_list = ", ".join([f"'{c}'" for c in campus_ids])
    return f"`tabCRM Exam`.campus_id IN ({campus_list})"


def crm_issue_query(user):
    """Filter CRM Issue - hien thi tat ca cho roles CRM"""
    if "System Manager" in frappe.get_roles(user):
        return ""
    
    allowed_roles = [
        "SIS Manager",
        "Registrar",
        "SIS Sales",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
        "SIS BOD",
    ]
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in allowed_roles):
        return ""
    
    return "1=0"


def has_crm_permission(doc, ptype, user):
    """Kiem tra quyen truy cap CRM doctype"""
    if "System Manager" in frappe.get_roles(user):
        return True
    
    allowed_roles = [
        "SIS Manager",
        "Registrar",
        "SIS Sales",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
        "SIS BOD",
    ]
    user_roles = frappe.get_roles(user)
    if any(role in user_roles for role in allowed_roles):
        return True
    
    return False


def _get_user_campus_ids(user):
    """Lấy danh sách campus_id của user — nguồn truth thống nhất qua Role Campus *"""
    from erp.sis.utils.campus_permissions import get_user_campuses

    return get_user_campuses(user) or []
