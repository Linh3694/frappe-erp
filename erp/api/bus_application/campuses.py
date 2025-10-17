# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response, list_response
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist(allow_guest=False)
def get_campuses():
    """
    Get all campuses available for bus application
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get campuses - filter based on user permissions or show all for bus monitors
        campuses = frappe.get_all(
            "SIS Campus",
            fields=["name", "title_vn", "title_en", "short_title"],
            order_by="title_vn asc"
        )

        return list_response(campuses, "Campuses retrieved successfully")

    except Exception as e:
        frappe.log_error(f"Error getting campuses: {str(e)}")
        return error_response(f"Failed to get campuses: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_school_years():
    """
    Get school years for bus application
    Expected parameters:
    - campus_id: Optional campus ID to filter school years
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get campus_id from request (optional)
        campus_id = frappe.local.form_dict.get('campus_id') or frappe.request.args.get('campus_id')

        filters = {}
        if campus_id:
            filters["campus_id"] = campus_id

        school_years = frappe.get_all(
            "SIS School Year",
            filters=filters,
            fields=["name", "title_vn", "title_en", "start_date", "end_date", "is_enable"],
            order_by="start_date desc"
        )

        return list_response(school_years, "School years retrieved successfully")

    except Exception as e:
        frappe.log_error(f"Error getting school years: {str(e)}")
        return error_response(f"Failed to get school years: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_bus_students():
    """
    Get bus students for a specific campus and school year
    Expected parameters:
    - campus_id: Campus ID
    - school_year_id: School year ID
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        campus_id = frappe.local.form_dict.get('campus_id') or frappe.request.args.get('campus_id')
        school_year_id = frappe.local.form_dict.get('school_year_id') or frappe.request.args.get('school_year_id')

        if not campus_id:
            return error_response("Campus ID is required")

        if not school_year_id:
            return error_response("School year ID is required")

        # Get bus students with class and route information
        students = frappe.db.sql("""
            SELECT
                bs.name, bs.full_name, bs.student_code, bs.class_id,
                bs.route_id, bs.status, bs.campus_id, bs.school_year_id,
                bs.compreface_registered,
                c.title as class_name,
                r.route_name
            FROM `tabSIS Bus Student` bs
            LEFT JOIN `tabSIS Class` c ON bs.class_id = c.name
            LEFT JOIN `tabSIS Bus Route` r ON bs.route_id = r.name
            WHERE bs.campus_id = %s
                AND bs.school_year_id = %s
                AND bs.status = 'Active'
            ORDER BY bs.full_name ASC
        """, (campus_id, school_year_id), as_dict=True)

        return list_response(students, f"Found {len(students)} bus students")

    except Exception as e:
        frappe.log_error(f"Error getting bus students: {str(e)}")
        return error_response(f"Failed to get bus students: {str(e)}")
