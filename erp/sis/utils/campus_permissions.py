# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def get_user_campuses(user=None):
    """Get all campuses that a user has access to based on their roles"""
    if not user:
        user = frappe.session.user
    
    if user == "Administrator":
        # Administrator can see all campuses
        return frappe.get_all("SIS Campus", pluck="name")
    
    # Get user roles
    user_roles = frappe.get_roles(user)
    
    # Find campus roles (roles that start with "Campus ")
    campus_roles = [role for role in user_roles if role.startswith("Campus ")]
    
    if not campus_roles:
        return []
    
    # Extract campus names from roles
    campus_names = []
    for role in campus_roles:
        campus_title = role.replace("Campus ", "")
        # Find campus by title_en or title_vn
        campus = frappe.db.get_value("SIS Campus", 
            {"title_en": campus_title}, "name") or frappe.db.get_value("SIS Campus", 
            {"title_vn": campus_title}, "name")
        if campus:
            campus_names.append(campus)
    
    return campus_names


def has_campus_permission(doc, ptype="read", user=None):
    """Check if user has permission to access a document based on campus_id"""
    if not user:
        user = frappe.session.user
    
    if user == "Administrator":
        return True
    
    # Check if document has campus_id field
    if not hasattr(doc, "campus_id") or not doc.campus_id:
        return True  # Allow access if no campus restriction
    
    # Get user's accessible campuses
    user_campuses = get_user_campuses(user)
    
    # Check if document's campus is in user's accessible campuses
    return doc.campus_id in user_campuses


def get_campus_filter(doctype, user=None):
    """Get filter conditions for campus-based access"""
    if not user:
        user = frappe.session.user
        
    if user == "Administrator":
        return {}  # No filter for Administrator
    
    # Check if doctype has campus_id field
    meta = frappe.get_meta(doctype)
    has_campus_field = any(field.fieldname == "campus_id" for field in meta.fields)
    
    if not has_campus_field:
        return {}  # No campus filter for doctypes without campus_id
    
    # Get user's accessible campuses
    user_campuses = get_user_campuses(user)
    
    if not user_campuses:
        return {"campus_id": ""}  # Return impossible condition if no campus access
    
    return {"campus_id": ["in", user_campuses]}


def assign_campus_role_to_user(user, campus, role_type="staff"):
    """Assign campus role to a user"""
    campus_doc = frappe.get_doc("SIS Campus", campus)
    role_name = campus_doc.get_campus_role_name()
    
    if not frappe.db.exists("Role", role_name):
        frappe.throw(f"Campus role {role_name} does not exist")
    
    # Check if user already has this role
    if not frappe.db.exists("Has Role", {"parent": user, "role": role_name}):
        user_doc = frappe.get_doc("User", user)
        user_doc.append("roles", {
            "role": role_name
        })
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        # Create User Permissions for this campus
        create_user_campus_permissions(user, campus)
        
        frappe.msgprint(f"Đã gán role {role_name} cho user {user}")


def remove_campus_role_from_user(user, campus):
    """Remove campus role from a user"""
    campus_doc = frappe.get_doc("SIS Campus", campus)
    role_name = campus_doc.get_campus_role_name()
    
    # Remove role from user
    frappe.db.delete("Has Role", {"parent": user, "role": role_name})
    
    # Remove user permissions for this campus
    frappe.db.delete("User Permission", {
        "user": user,
        "allow": "SIS Campus",
        "for_value": campus
    })
    
    frappe.msgprint(f"Đã xóa role {role_name} khỏi user {user}")


def create_user_campus_permissions(user, campus):
    """Create User Permissions for all SIS doctypes for a specific campus"""
    sis_doctypes = [
        "SIS Campus", "SIS School Year", "SIS Education Stage", "SIS Education Grade",
        "SIS Academic Program", "SIS Timetable Subject", "SIS Curriculum", "SIS Actual Subject",
        "SIS Subject", "SIS Timetable Column", "SIS Calendar", "SIS Class", "SIS Teacher",
        "SIS Subject Assignment", "SIS Timetable", "SIS Timetable Instance", "SIS Event",
        "SIS Event Student", "SIS Event Teacher", "SIS Student Timetable", "SIS Class Student",
        "SIS Photo"
    ]
    
    for doctype in sis_doctypes:
        if frappe.db.exists("DocType", doctype):
            # Check if permission already exists
            if not frappe.db.exists("User Permission", {
                "user": user,
                "allow": "SIS Campus",
                "for_value": campus,
                "applicable_for": doctype
            }):
                user_perm = frappe.new_doc("User Permission")
                user_perm.user = user
                user_perm.allow = "SIS Campus"
                user_perm.for_value = campus
                user_perm.applicable_for = doctype
                user_perm.flags.ignore_permissions = True
                user_perm.save()


def get_current_user_campus():
    """Get current user's selected campus from user preference"""
    from ..doctype.sis_user_campus_preference.sis_user_campus_preference import SISUserCampusPreference
    return SISUserCampusPreference.get_current_campus()


def set_current_user_campus(campus):
    """Set current user's selected campus"""
    from ..doctype.sis_user_campus_preference.sis_user_campus_preference import SISUserCampusPreference
    return SISUserCampusPreference.set_current_campus(campus)
