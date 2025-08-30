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


@frappe.whitelist()
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

        # Get campus filter from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters['campus_id'] = campus_id
            frappe.logger().info(f"Adding campus filter: {campus_id}")
        else:
            frappe.logger().info("No campus context found - querying without campus filter")

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
        frappe.logger().info(f"Total count from db.count: {total_count}")
        if class_students:
            frappe.logger().info(f"First record class_id: {class_students[0].get('class_id')}")
            frappe.logger().info(f"All class_ids in result: {[r.get('class_id') for r in class_students]}")
            frappe.logger().info(f"All campus_ids in result: {[r.get('campus_id') for r in class_students]}")
            frappe.logger().info(f"Sample records: {class_students[:2]}")
        else:
            frappe.logger().info("No records found in main query")

        # Double-check the actual database state
        actual_count = frappe.db.count("SIS Class Student", filters=filters)
        frappe.logger().info(f"Double-check actual count: {actual_count}")

        # Test query without campus filter to see if that's the issue
        if class_id:
            test_filters = {'class_id': class_id}
            test_count = frappe.db.count("SIS Class Student", filters=test_filters)
            frappe.logger().info(f"Test query without campus filter - count for class {class_id}: {test_count}")

            if test_count > 0:
                test_records = frappe.get_all("SIS Class Student", filters=test_filters, limit=5)
                frappe.logger().info(f"Test query records: {[r.get('class_id') for r in test_records]}")

        # If no records found, try query without any filters to check if table has data
        if actual_count == 0:
            total_count_all = frappe.db.count("SIS Class Student")
            frappe.logger().info(f"Total records in SIS Class Student table: {total_count_all}")

            if total_count_all > 0:
                sample_records = frappe.get_all("SIS Class Student", limit=3)
                frappe.logger().info(f"Sample records from table: {sample_records}")
        
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


@frappe.whitelist()
def debug_class_students():
    """Simple debug function to check class students data"""
    try:
        # Get class_id from query parameters directly
        import urllib.parse
        query_string = frappe.local.request.query_string
        frappe.logger().info(f"Debug: Raw query_string: {query_string}")

        if query_string:
            parsed_params = urllib.parse.parse_qs(query_string.decode('utf-8'))
            class_id = parsed_params.get('class_id', [None])[0]
            frappe.logger().info(f"Debug: Parsed class_id: {class_id}")
        else:
            class_id = None

        if not class_id:
            frappe.logger().info("Debug: No class_id found in query string")
            return error_response("class_id is required")

        # Check all records for this class_id
        all_records = frappe.get_all(
            "SIS Class Student",
            filters={'class_id': class_id},
            fields=["name", "class_id", "student_id", "campus_id", "creation"]
        )

        # Check records without campus filter
        all_records_no_campus = frappe.get_all(
            "SIS Class Student",
            filters={'class_id': class_id},
            fields=["name", "class_id", "student_id", "campus_id", "creation"]
        )

        return success_response(
            data={
                "class_id_requested": class_id,
                "total_records_without_campus_filter": len(all_records_no_campus),
                "total_records_with_campus_filter": len(all_records),
                "records_without_campus_filter": all_records_no_campus[:5],  # First 5 records
                "records_with_campus_filter": all_records[:5]
            },
            message="Debug data retrieved successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error in debug_class_students: {str(e)}")
        return error_response(
            message=f"Error in debug: {str(e)}",
            code="DEBUG_ERROR"
        )


@frappe.whitelist()
def simple_test():
    """Simple test function to check if API is working"""
    try:
        # Just return success
        return success_response(
            data={"test": "ok"},
            message="API is working"
        )
    except Exception as e:
        return error_response(
            message=f"Test failed: {str(e)}",
            code="TEST_ERROR"
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
