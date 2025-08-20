# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def bulk_assign_campus_roles():
    """Bulk assign campus roles to existing users"""
    try:
        # Get all campuses
        campuses = frappe.get_all("SIS Campus", fields=["name", "title_vn", "title_en"])
        
        # Get all users with System Manager role (or other relevant roles)
        system_managers = frappe.get_all("Has Role", 
            filters={"role": "System Manager"},
            fields=["parent as user"])
        
        results = []
        
        for campus in campuses:
            campus_doc = frappe.get_doc("SIS Campus", campus.name)
            role_name = campus_doc.get_campus_role_name()
            
            # Create role if it doesn't exist
            if not frappe.db.exists("Role", role_name):
                campus_doc.create_campus_role()
            
            # Assign role to system managers
            for user_record in system_managers:
                user = user_record.user
                if user != "Administrator" and user != "Guest":
                    if not frappe.db.exists("Has Role", {"parent": user, "role": role_name}):
                        user_doc = frappe.get_doc("User", user)
                        user_doc.append("roles", {"role": role_name})
                        user_doc.flags.ignore_permissions = True
                        user_doc.save()
                        results.append(f"Assigned {role_name} to {user}")
        
        return {
            "message": "Bulk campus role assignment completed",
            "results": results
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Bulk Assign Campus Roles Error")
        frappe.throw(_("Error in bulk campus role assignment: {0}").format(str(e)))


@frappe.whitelist()
def create_campus_roles_for_existing():
    """Create campus roles for all existing campuses"""
    try:
        campuses = frappe.get_all("SIS Campus", fields=["name"])
        results = []
        
        for campus in campuses:
            campus_doc = frappe.get_doc("SIS Campus", campus.name)
            try:
                campus_doc.create_campus_role()
                results.append(f"Created role for campus: {campus_doc.title_vn}")
            except Exception as e:
                results.append(f"Error creating role for {campus_doc.title_vn}: {str(e)}")
        
        return {
            "message": "Campus role creation completed",
            "results": results
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Create Campus Roles Error")
        frappe.throw(_("Error creating campus roles: {0}").format(str(e)))


@frappe.whitelist()
def get_campus_role_summary():
    """Get summary of campus roles and their assignments"""
    try:
        campuses = frappe.get_all("SIS Campus", fields=["name", "title_vn", "title_en"])
        summary = []
        
        for campus in campuses:
            campus_doc = frappe.get_doc("SIS Campus", campus.name)
            role_name = campus_doc.get_campus_role_name()
            
            # Check if role exists
            role_exists = frappe.db.exists("Role", role_name)
            
            # Count users with this role
            user_count = 0
            if role_exists:
                user_count = frappe.db.count("Has Role", {"role": role_name})
            
            summary.append({
                "campus": campus.name,
                "campus_title": campus.title_vn,
                "role_name": role_name,
                "role_exists": bool(role_exists),
                "user_count": user_count
            })
        
        return summary
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Get Campus Role Summary Error")
        frappe.throw(_("Error getting campus role summary: {0}").format(str(e)))
