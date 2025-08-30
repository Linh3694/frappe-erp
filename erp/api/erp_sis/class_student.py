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

        # Debug logging
        frappe.logger().info(f"get_all_class_students called with: page={page}, limit={limit}, school_year_id={school_year_id}, class_id={class_id}")

        # Build filters
        filters = {}
        if school_year_id:
            filters['school_year_id'] = school_year_id
        if class_id:
            filters['class_id'] = class_id
            frappe.logger().info(f"Adding class_id filter: {class_id}")

        frappe.logger().info(f"Filters before campus: {filters}")

        # TEMP: Disable campus filter for debugging
        # from erp.utils.campus_utils import get_current_campus_from_context
        # campus_id = get_current_campus_from_context()
        # if campus_id:
        #     filters['campus_id'] = campus_id
        #     frappe.logger().info(f"Adding campus filter: {campus_id}")
        # else:
        frappe.logger().info("Campus filter temporarily disabled for debugging")

        frappe.logger().info(f"Final filters: {filters}")
        
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

        frappe.logger().info(f"Query result count: {len(class_students)}")
        if class_students:
            frappe.logger().info(f"First record class_id: {class_students[0].get('class_id')}")
            frappe.logger().info(f"All class_ids in result: {[r.get('class_id') for r in class_students]}")
            frappe.logger().info(f"Sample records: {class_students[:2]}")

        # Test query without campus filter to see if that's the issue
        if class_id:
            test_filters = {'class_id': class_id}
            test_count = frappe.db.count("SIS Class Student", filters=test_filters)
            frappe.logger().info(f"Test query without campus filter - count for class {class_id}: {test_count}")

            if test_count > 0:
                test_records = frappe.get_all("SIS Class Student", filters=test_filters, limit=5)
                frappe.logger().info(f"Test query records: {[r.get('class_id') for r in test_records]}")
        
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
def debug_class_students(class_id=None):
    """Debug function to check class students data"""
    try:
        # Try to get class_id from various sources
        if not class_id:
            class_id = frappe.local.form_dict.get("class_id")

        if not class_id:
            # Try from request JSON body
            try:
                if frappe.request.data:
                    import json
                    json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    class_id = json_data.get('class_id')
            except Exception:
                pass

        if not class_id:
            frappe.logger().info(f"Debug: No class_id found. form_dict: {frappe.local.form_dict}, request_data: {frappe.request.data}")
            # Try from URL parameters for GET requests
            class_id = frappe.local.form_dict.get("class_id")
            frappe.logger().info(f"Debug: Trying class_id from form_dict: {class_id}")

        if not class_id:
            return error_response("class_id is required")

        # Check all records for this class_id
        all_records = frappe.get_all(
            "SIS Class Student",
            filters={'class_id': class_id},
            fields=["name", "class_id", "student_id"]
        )

        # Check total count
        total_count = len(all_records)

        # Check records with campus filter
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()

        campus_records = []
        if campus_id:
            campus_records = frappe.get_all(
                "SIS Class Student",
                filters={'class_id': class_id, 'campus_id': campus_id},
                fields=["name", "class_id", "student_id", "campus_id"]
            )

        return {
            "class_id_requested": class_id,
            "current_campus": campus_id,
            "total_records_without_campus_filter": total_count,
            "records_without_campus_filter": all_records,
            "total_records_with_campus_filter": len(campus_records),
            "records_with_campus_filter": campus_records
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Debug Class Students Error")
        return error_response(f"Error: {str(e)}")


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
