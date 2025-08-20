# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from ..utils.campus_permissions import (
    get_user_campuses, 
    get_current_user_campus, 
    set_current_user_campus,
    assign_campus_role_to_user,
    remove_campus_role_from_user
)


@frappe.whitelist()
def get_accessible_campuses():
    """Get all campuses that current user has access to"""
    try:
        user_campuses = get_user_campuses()
        
        if not user_campuses:
            return []
        
        # Get campus details
        campuses = frappe.get_all("SIS Campus", 
            filters={"name": ["in", user_campuses]},
            fields=["name", "title_vn", "title_en", "short_title"])
        
        return campuses
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Accessible Campuses Error")
        frappe.throw(_("Error getting accessible campuses: {0}").format(str(e)))


@frappe.whitelist()
def get_current_campus():
    """Get current user's selected campus"""
    try:
        current_campus = get_current_user_campus()
        
        if not current_campus:
            return None
        
        campus_doc = frappe.get_doc("SIS Campus", current_campus)
        return {
            "name": campus_doc.name,
            "title_vn": campus_doc.title_vn,
            "title_en": campus_doc.title_en,
            "short_title": campus_doc.short_title
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Current Campus Error")
        frappe.throw(_("Error getting current campus: {0}").format(str(e)))


@frappe.whitelist()
def set_current_campus(campus):
    """Set current user's selected campus"""
    try:
        if set_current_user_campus(campus):
            campus_doc = frappe.get_doc("SIS Campus", campus)
            return {
                "message": f"Đã chuyển sang campus: {campus_doc.title_vn}",
                "campus": {
                    "name": campus_doc.name,
                    "title_vn": campus_doc.title_vn,
                    "title_en": campus_doc.title_en,
                    "short_title": campus_doc.short_title
                }
            }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Set Current Campus Error")
        frappe.throw(_("Error setting current campus: {0}").format(str(e)))


@frappe.whitelist()
def assign_campus_access(user, campus, role_type="staff"):
    """Assign campus access to a user"""
    try:
        # Check if current user has permission to manage campus access
        if not frappe.has_permission("SIS Campus", "write"):
            frappe.throw(_("You don't have permission to manage campus access"))
        
        assign_campus_role_to_user(user, campus, role_type)
        
        return {
            "message": f"Đã gán quyền truy cập campus {campus} cho user {user}"
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Assign Campus Access Error")
        frappe.throw(_("Error assigning campus access: {0}").format(str(e)))


@frappe.whitelist()
def remove_campus_access(user, campus):
    """Remove campus access from a user"""
    try:
        # Check if current user has permission to manage campus access
        if not frappe.has_permission("SIS Campus", "write"):
            frappe.throw(_("You don't have permission to manage campus access"))
        
        remove_campus_role_from_user(user, campus)
        
        return {
            "message": f"Đã xóa quyền truy cập campus {campus} khỏi user {user}"
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Remove Campus Access Error")
        frappe.throw(_("Error removing campus access: {0}").format(str(e)))


@frappe.whitelist()
def get_campus_users(campus):
    """Get all users who have access to a specific campus"""
    try:
        if not frappe.has_permission("SIS Campus", "read"):
            frappe.throw(_("You don't have permission to view campus users"))
        
        campus_doc = frappe.get_doc("SIS Campus", campus)
        role_name = campus_doc.get_campus_role_name()
        
        # Get users with this campus role
        users = frappe.get_all("Has Role",
            filters={"role": role_name},
            fields=["parent as user"])
        
        user_list = [u.user for u in users]
        
        if user_list:
            user_details = frappe.get_all("User",
                filters={"name": ["in", user_list], "enabled": 1},
                fields=["name", "full_name", "email"])
            return user_details
        
        return []
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Campus Users Error")
        frappe.throw(_("Error getting campus users: {0}").format(str(e)))
