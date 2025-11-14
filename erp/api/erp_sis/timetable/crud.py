# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable CRUD Operations

Handles timetable list, detail, and deletion operations.
"""

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)


@frappe.whitelist(allow_guest=False)
def get_timetables():
    """Get list of timetables with filtering"""
    try:
        # Get query parameters
        page = int(frappe.local.form_dict.get("page", 1))
        limit = int(frappe.local.form_dict.get("limit", 20))
        campus_id = frappe.local.form_dict.get("campus_id")
        school_year_id = frappe.local.form_dict.get("school_year_id")

        # Build filters
        filters = {}
        if campus_id:
            filters["campus_id"] = campus_id
        if school_year_id:
            filters["school_year_id"] = school_year_id

        # Get campus from user context
        user_campus = get_current_campus_from_context()
        if user_campus:
            filters["campus_id"] = user_campus

        # Query timetables
        timetables = frappe.get_all(
            "SIS Timetable",
            fields=["name", "title_vn", "title_en", "campus_id", "school_year_id", "education_stage_id", "start_date", "end_date", "created_by"],
            filters=filters,
            start=(page - 1) * limit,
            page_length=limit,
            order_by="creation desc"
        )

        # Get total count
        total_count = frappe.db.count("SIS Timetable", filters=filters)

        result = {
            "data": timetables,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit
            }
        }

        return single_item_response(result, "Timetables fetched successfully")

    except Exception as e:

        return error_response(f"Error fetching timetables: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_detail():
    """Get detailed timetable information"""
    try:
        timetable_id = frappe.local.form_dict.get("name")
        if not timetable_id:
            return validation_error_response("Validation failed", {"name": ["Timetable ID is required"]})

        # Get timetable
        timetable = frappe.get_doc("SIS Timetable", timetable_id)

        # Check campus permission
        user_campus = get_current_campus_from_context()
        if user_campus and timetable.campus_id != user_campus:
            return forbidden_response("Access denied: Campus mismatch")

        # Get instances
        instances = frappe.get_all(
            "SIS Timetable Instance",
            fields=["name", "class_id", "start_date", "end_date", "is_locked"],
            filters={"timetable_id": timetable_id},
            order_by="class_id"
        )

        result = {
            "timetable": {
                "name": timetable.name,
                "title_vn": timetable.title_vn,
                "title_en": timetable.title_en,
                "campus_id": timetable.campus_id,
                "school_year_id": timetable.school_year_id,
                "education_stage_id": timetable.education_stage_id,
                "start_date": timetable.start_date,
                "end_date": timetable.end_date,
                "upload_source": timetable.upload_source,
                "created_by": timetable.created_by
            },
            "instances": instances
        }

        return single_item_response(result, "Timetable detail fetched successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Timetable not found")
    except Exception as e:

        return error_response(f"Error fetching timetable detail: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_timetable():
    """Delete a timetable and all its instances"""
    try:
        timetable_id = frappe.local.form_dict.get("name")
        if not timetable_id:
            return validation_error_response("Validation failed", {"name": ["Timetable ID is required"]})

        # Get timetable
        timetable = frappe.get_doc("SIS Timetable", timetable_id)

        # Check campus permission
        user_campus = get_current_campus_from_context()
        if user_campus and timetable.campus_id != user_campus:
            return forbidden_response("Access denied: Campus mismatch")

        # Delete timetable (this will cascade delete instances due to foreign key)
        frappe.delete_doc("SIS Timetable", timetable_id)
        frappe.db.commit()

        return success_response("Timetable deleted successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Timetable not found")
    except Exception as e:

        return error_response(f"Error deleting timetable: {str(e)}")


@frappe.whitelist(allow_guest=False)
def test_class_week_api(class_id: str = None, week_start: str = None):
    """Test function for get_class_week API"""
    try:

        if not class_id:
            class_id = "SIS-CLASS-00385"  # Default test class
        if not week_start:
            week_start = "2025-08-25"  # Default test date

        # Call the actual get_class_week function
        from .weeks import get_class_week
        result = get_class_week(class_id, week_start, None)
        return {
            "success": True,
            "message": "Test class week API successful",
            "test_params": {"class_id": class_id, "week_start": week_start},
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Test failed: {str(e)}",
            "test_params": {"class_id": class_id, "week_start": week_start}
        }

