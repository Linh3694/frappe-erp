# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist()
def create_demo_campuses():
    """Create demo campuses for testing"""
    try:
        demo_campuses = [
            {
                "title_vn": "Cơ sở Hà Nội",
                "title_en": "Hanoi Campus", 
                "short_title": "HN"
            },
            {
                "title_vn": "Cơ sở Hồ Chí Minh",
                "title_en": "Ho Chi Minh Campus",
                "short_title": "HCM"
            },
            {
                "title_vn": "Cơ sở Đà Nẵng", 
                "title_en": "Da Nang Campus",
                "short_title": "DN"
            }
        ]
        
        created_campuses = []
        
        for campus_data in demo_campuses:
            # Check if campus already exists
            existing = frappe.db.exists("SIS Campus", {
                "title_en": campus_data["title_en"]
            })
            
            if not existing:
                campus = frappe.new_doc("SIS Campus")
                campus.update(campus_data)
                campus.flags.ignore_permissions = True
                campus.save()
                created_campuses.append(campus.name)
        
        return {
            "message": f"Created {len(created_campuses)} demo campuses",
            "campuses": created_campuses
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Create Demo Campuses Error")
        frappe.throw(_("Error creating demo campuses: {0}").format(str(e)))


@frappe.whitelist()
def setup_demo_users():
    """Setup demo users with campus access"""
    try:
        # Get all campuses
        campuses = frappe.get_all("SIS Campus", fields=["name", "title_en"])
        
        results = []
        
        # Assign current user to all campuses for testing
        current_user = frappe.session.user
        
        if current_user != "Administrator" and current_user != "Guest":
            for campus in campuses:
                try:
                    from ..utils.campus_permissions import assign_campus_role_to_user
                    assign_campus_role_to_user(current_user, campus.name)
                    results.append(f"Assigned {campus.title_en} access to {current_user}")
                except Exception as e:
                    results.append(f"Error assigning {campus.title_en}: {str(e)}")
        
        return {
            "message": "Demo user setup completed",
            "results": results
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Setup Demo Users Error")
        frappe.throw(_("Error setting up demo users: {0}").format(str(e)))


@frappe.whitelist()
def test_campus_permissions():
    """Test campus permission system"""
    try:
        from ..utils.campus_permissions import get_user_campuses, get_current_user_campus
        from ..api.campus_api import get_accessible_campuses, get_current_campus
        
        # Test permission functions
        user_campuses = get_user_campuses()
        current_campus = get_current_user_campus()
        accessible_campuses = get_accessible_campuses()
        current_campus_detail = get_current_campus()
        
        return {
            "user_campuses": user_campuses,
            "current_campus": current_campus,
            "accessible_campuses": accessible_campuses,
            "current_campus_detail": current_campus_detail,
            "user": frappe.session.user,
            "user_roles": frappe.get_roles()
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Test Campus Permissions Error")
        frappe.throw(_("Error testing campus permissions: {0}").format(str(e)))
