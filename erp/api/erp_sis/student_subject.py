# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subjects_by_classes():
    """
    Get unique subjects from SIS Student Subject based on selected classes/grades
    Returns subjects with their details for report card configuration
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Get class_ids from request
        class_ids = None
        
        # Try from form_dict first
        if frappe.form_dict.get('class_ids'):
            class_ids = frappe.form_dict.get('class_ids')
            if isinstance(class_ids, str):
                try:
                    class_ids = json.loads(class_ids)
                except json.JSONDecodeError:
                    class_ids = [class_ids]  # Single class ID as string
        
        # Try from JSON payload
        if not class_ids and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                class_ids = json_data.get('class_ids', [])
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass
        
        if not class_ids or len(class_ids) == 0:
            return validation_error_response("Validation failed", {"class_ids": ["At least one class ID is required"]})
        
        # Make sure class_ids is a list
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        # Query SIS Student Subject to get unique subjects for the given classes
        filters = {
            "campus_id": campus_id,
            "class_id": ["in", class_ids]
        }
        
        # Get unique subject_id and actual_subject_id combinations
        student_subjects = frappe.get_all(
            "SIS Student Subject",
            fields=["subject_id", "actual_subject_id"],
            filters=filters,
            distinct=True
        )
        
        # Collect all unique subject IDs (both subject_id and actual_subject_id)
        subject_ids = set()
        for record in student_subjects:
            if record.get("subject_id"):
                subject_ids.add(record["subject_id"])
            if record.get("actual_subject_id"):
                subject_ids.add(record["actual_subject_id"])
        
        if not subject_ids:
            return list_response([], "No subjects found for the selected classes")
        
        # Get subject details from SIS Subject table
        subjects_query = """
            SELECT DISTINCT
                s.name,
                s.title as title_vn,
                '' as title_en,
                s.education_stage,
                s.timetable_subject_id,
                s.actual_subject_id,
                s.campus_id,
                COALESCE(ts.title_vn, '') as timetable_subject_name,
                COALESCE(act.title_vn, '') as actual_subject_name
            FROM `tabSIS Subject` s
            LEFT JOIN `tabSIS Timetable Subject` ts ON s.timetable_subject_id = ts.name AND ts.campus_id = s.campus_id
            LEFT JOIN `tabSIS Actual Subject` act ON s.actual_subject_id = act.name AND act.campus_id = s.campus_id
            WHERE s.campus_id = %s AND s.name IN ({})
            ORDER BY s.title ASC
        """.format(','.join(['%s'] * len(subject_ids)))
        
        subjects = frappe.db.sql(
            subjects_query, 
            (campus_id,) + tuple(subject_ids), 
            as_dict=True
        )
        
        # Format the response to include both title variations
        formatted_subjects = []
        for subject in subjects:
            formatted_subjects.append({
                "name": subject["name"],
                "title": subject["title_vn"] or subject["name"],
                "title_vn": subject["title_vn"] or subject["name"],
                "title_en": subject["title_en"] or subject["title_vn"] or subject["name"],
                "education_stage": subject["education_stage"],
                "timetable_subject_id": subject["timetable_subject_id"],
                "actual_subject_id": subject["actual_subject_id"],
                "timetable_subject_name": subject["timetable_subject_name"],
                "actual_subject_name": subject["actual_subject_name"],
                "campus_id": subject["campus_id"]
            })
        
        return list_response(
            formatted_subjects, 
            f"Found {len(formatted_subjects)} unique subjects for {len(class_ids)} classes"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects by classes: {str(e)}")
        return error_response(f"Error fetching subjects by classes: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_students_by_classes():
    """
    Get unique students from SIS Student Subject based on selected classes/grades
    For debugging and verification purposes
    """
    try:
        campus_id = get_current_campus_from_context() or "campus-1"
        
        # Get class_ids from request (same logic as above)
        class_ids = None
        
        if frappe.form_dict.get('class_ids'):
            class_ids = frappe.form_dict.get('class_ids')
            if isinstance(class_ids, str):
                try:
                    class_ids = json.loads(class_ids)
                except json.JSONDecodeError:
                    class_ids = [class_ids]
        
        if not class_ids and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                class_ids = json_data.get('class_ids', [])
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass
        
        if not class_ids or len(class_ids) == 0:
            return validation_error_response("Validation failed", {"class_ids": ["At least one class ID is required"]})
        
        if not isinstance(class_ids, list):
            class_ids = [class_ids]
        
        # Query to get unique students
        filters = {
            "campus_id": campus_id,
            "class_id": ["in", class_ids]
        }
        
        students = frappe.get_all(
            "SIS Student Subject",
            fields=["student_id"],
            filters=filters,
            distinct=True
        )
        
        return list_response(
            [s["student_id"] for s in students], 
            f"Found {len(students)} unique students for {len(class_ids)} classes"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching students by classes: {str(e)}")
        return error_response(f"Error fetching students by classes: {str(e)}")
