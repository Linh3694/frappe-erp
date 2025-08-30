# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


@frappe.whitelist(allow_guest=False)
def get_all_class_students(page=1, limit=20, school_year_id=None, class_id=None):
    """Get all class students with pagination and filters"""
    try:
        page = int(page)
        limit = int(limit)

        # Build filters
        filters = {}
        if school_year_id:
            filters['school_year_id'] = school_year_id
        if class_id:
            filters['class_id'] = class_id

        # Get campus filter from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters['campus_id'] = campus_id

        # Debug logging
        frappe.logger().info(f"get_all_class_students filters: {filters}")
        frappe.logger().info(f"Parameters - page: {page}, limit: {limit}, school_year_id: {school_year_id}, class_id: {class_id}, campus_id: {campus_id}")

        # Calculate offset
        offset = (page - 1) * limit

        # Get class students
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=[
                "name", "class_id", "student_id", "school_year_id",
                "class_type", "campus_id", "creation", "modified"
            ],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=limit
        )

        # Debug logging for results
        frappe.logger().info(f"get_all_class_students returned {len(class_students)} records")
        if class_students:
            frappe.logger().info(f"Sample class_ids: {[cs.get('class_id') for cs in class_students[:3]]}")
        
        # Get total count
        total_count = frappe.db.count("SIS Class Student", filters=filters)
        
        # Calculate pagination
        total_pages = (total_count + limit - 1) // limit
        
        return paginated_response(
            data=class_students,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Class students fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error getting class students: {str(e)}")
        return error_response(
            message="Error fetching class students",
            code="FETCH_CLASS_STUDENTS_ERROR"
        )




@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def assign_student(class_id=None, student_id=None, school_year_id=None, class_type="regular"):
    """Assign a student to a class"""
    try:
        # Get parameters from form_dict if not provided (following Frappe pattern)
        if not class_id:
            class_id = frappe.local.form_dict.get("class_id")
        if not student_id:
            student_id = frappe.local.form_dict.get("student_id")
        if not school_year_id:
            school_year_id = frappe.local.form_dict.get("school_year_id")
        if not class_type:
            class_type = frappe.local.form_dict.get("class_type", "regular")

        # Fallback to JSON data if form_dict is empty
        if not class_id and hasattr(frappe, 'request') and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                class_id = json_data.get('class_id') or class_id
                student_id = json_data.get('student_id') or student_id
                school_year_id = json_data.get('school_year_id') or school_year_id
                class_type = json_data.get('class_type') or class_type or 'regular'
            except:
                pass

        # Debug logging
        frappe.logger().info(f"Final parameters - class_id={class_id}, student_id={student_id}, school_year_id={school_year_id}, class_type={class_type}")
        
        # Validate required parameters
        if not class_id or not student_id or not school_year_id:
            return validation_error_response(
                message="Missing required parameters",
                errors={
                    "class_id": ["Required"] if not class_id else [],
                    "student_id": ["Required"] if not student_id else [],
                    "school_year_id": ["Required"] if not school_year_id else []
                }
            )
        
        # Get campus from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"  # Default fallback
        
        # Check if assignment already exists
        existing = frappe.db.exists("SIS Class Student", {
            "class_id": class_id,
            "student_id": student_id,
            "school_year_id": school_year_id
        })
        
        if existing:
            return error_response(
                message="Student is already assigned to this class",
                code="STUDENT_ALREADY_ASSIGNED"
            )
        
        # Create new class student assignment
        class_student = frappe.get_doc({
            "doctype": "SIS Class Student",
            "class_id": class_id,
            "student_id": student_id,
            "school_year_id": school_year_id,
            "class_type": class_type,
            "campus_id": campus_id
        })
        
        class_student.insert()
        frappe.db.commit()
        
        frappe.logger().info(f"Successfully assigned student {student_id} to class {class_id}")
        
        return single_item_response(
            data={
                "name": class_student.name,
                "class_id": class_student.class_id,
                "student_id": class_student.student_id,
                "school_year_id": class_student.school_year_id,
                "class_type": class_student.class_type,
                "campus_id": class_student.campus_id
            },
            message="Student assigned to class successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error assigning student to class: {str(e)}")
        frappe.db.rollback()
        return error_response(
            message="Error assigning student to class",
            code="ASSIGN_STUDENT_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def unassign_student(name=None):
    """Remove a student from a class"""
    try:
        # Get parameters from form_dict if not provided
        form = frappe.local.form_dict or {}
        if not name:
            name = form.get('name')
            
        frappe.logger().info(f"unassign_student called with: name={name}")
        
        if not name:
            return error_response(
                message="Missing required parameter: name",
                code="MISSING_NAME"
            )
        
        # Check if class student exists
        if not frappe.db.exists("SIS Class Student", name):
            return not_found_response(
                message="Class student assignment not found",
                code="CLASS_STUDENT_NOT_FOUND"
            )
        
        # Delete the assignment
        frappe.delete_doc("SIS Class Student", name)
        frappe.db.commit()
        
        frappe.logger().info(f"Successfully unassigned class student: {name}")
        
        return success_response(
            message="Student unassigned from class successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error unassigning student from class: {str(e)}")
        frappe.db.rollback()
        return error_response(
            message="Error unassigning student from class",
            code="UNASSIGN_STUDENT_ERROR"
        )
