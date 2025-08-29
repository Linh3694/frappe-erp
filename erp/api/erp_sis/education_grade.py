# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response, error_response, list_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


@frappe.whitelist(allow_guest=False)
def get_all_education_grades():
    """Get all education grades with basic information - SIMPLE VERSION"""
    try:
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        education_grades = frappe.get_all(
            "SIS Education Grade",
            fields=[
                "name",
                "title_vn as grade_name",
                "title_en", 
                "grade_code",
                "education_stage_id as education_stage",
                "sort_order",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="sort_order asc, title_vn asc"
        )
        
        return list_response(
            data=education_grades,
            message="Education grades fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching education grades: {str(e)}")
        return error_response(
            message="Error fetching education grades",
            code="FETCH_EDUCATION_GRADES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_education_grade_by_id():
    """Get education grade details by ID"""
    try:

        # Get grade_id from multiple sources (form data or JSON payload)
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_id = frappe.form_dict.get('grade_id')

        # If not found, try from JSON payload
        if not grade_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_id = json_data.get('grade_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        # Also try from request.args if available (for GET requests)
        if not grade_id and hasattr(frappe.request, 'args'):
            grade_id = frappe.request.args.get('grade_id')

        # Parse query string manually for GET requests
        if not grade_id and frappe.request.query_string:
            try:
                from urllib.parse import parse_qs
                query_params = parse_qs(frappe.request.query_string.decode('utf-8'))
                grade_id = query_params.get('grade_id', [None])[0]
            except Exception as e:
                pass

        if not grade_id:
            return error_response(
                message="Grade ID is required",
                code="MISSING_GRADE_ID"
            )

        grade = frappe.get_doc("SIS Education Grade", grade_id)

        if not grade:
            return not_found_response(
                message="Education grade not found",
                code="EDUCATION_GRADE_NOT_FOUND"
            )

        # Convert to dict with consistent field names (same as get_all_education_grades)
        grade_dict = grade.as_dict()


        grade_data = {
            "name": grade_dict.get("name"),
            "grade_name": grade_dict.get("title_vn"),  # Use consistent field name
            "title_en": grade_dict.get("title_en"),
            "grade_code": grade_dict.get("grade_code"),
            "education_stage": grade_dict.get("education_stage_id"),  # Use consistent field name
            "sort_order": grade_dict.get("sort_order"),
            "campus_id": grade_dict.get("campus_id"),
            "creation": grade_dict.get("creation"),
            "modified": grade_dict.get("modified")
        }

        return single_item_response(
            data=grade_data,
            message="Education grade fetched successfully"
        )
        
    except frappe.DoesNotExistError:
        return not_found_response(
            message="Education grade not found",
            code="EDUCATION_GRADE_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"Error fetching education grade {grade_id}: {str(e)}")
        return error_response(
            message="Error fetching education grade",
            code="FETCH_EDUCATION_GRADE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_education_grade():
    """Create a new education grade - SIMPLE VERSION"""
    try:
        frappe.logger().info("=== START create_education_grade ===")

        # Get data from request - support both JSON and form data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_education_grade: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_education_grade: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_education_grade: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_education_grade: {data}")

        frappe.logger().info(f"Final data for processing: {data}")
        
        # Validate required fields - map from frontend to backend fields
        frappe.logger().info("=== VALIDATION STEP ===")
        required_fields = {
            "grade_name": "title_vn",
            "grade_code": "grade_code",
            "education_stage": "education_stage_id",
            "sort_order": "sort_order"
        }

        backend_data = {}
        for frontend_field, backend_field in required_fields.items():
            if not data.get(frontend_field):
                frappe.logger().error(f"Missing required field: {frontend_field}")
                return validation_error_response(
                    message=f"Field '{frontend_field}' is required",
                    errors={frontend_field: ["Required"]}
                )
            backend_data[backend_field] = data.get(frontend_field)

        frappe.logger().info(f"Backend data mapping successful: {backend_data}")
        
        # Get campus from user roles or form data
        frappe.logger().info("=== CAMPUS LOOKUP STEP ===")
        campus_id = data.get("campus_id")
        frappe.logger().info(f"Campus from data: {campus_id}")

        if not campus_id:
            campus_id = get_current_campus_from_context()
            frappe.logger().info(f"Campus from context: {campus_id}")
            if not campus_id:
                # Fallback to default if no campus found
                campus_id = "campus-1"
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        frappe.logger().info(f"Final campus_id: {campus_id}")
        
        # Check if grade_code already exists for this campus
        frappe.logger().info("=== DUPLICATE CHECK STEP ===")
        existing_grade = frappe.db.exists("SIS Education Grade", {
            "grade_code": data.get("grade_code"),
            "campus_id": campus_id
        })
        frappe.logger().info(f"Checking for existing grade_code '{data.get('grade_code')}' in campus '{campus_id}': {existing_grade}")

        if existing_grade:
            frappe.logger().warning(f"Grade code already exists: {existing_grade}")
            return error_response(
                message="Mã khối học đã tồn tại cho trường học này",
                code="GRADE_CODE_EXISTS"
            )
        
        # Create new education grade
        frappe.logger().info("=== INSERT STEP ===")
        grade_data = {
            "doctype": "SIS Education Grade",
            "title_vn": backend_data["title_vn"],
            "title_en": backend_data["title_vn"],  # Default to VN if EN not provided
            "grade_code": backend_data["grade_code"],
            "education_stage_id": backend_data["education_stage_id"],
            "sort_order": int(backend_data["sort_order"]),
            "campus_id": campus_id
        }
        frappe.logger().info(f"Grade data to insert: {grade_data}")

        grade_doc = frappe.get_doc(grade_data)
        frappe.logger().info("Created frappe doc object successfully")

        grade_doc.insert(ignore_permissions=True)
        frappe.logger().info(f"Insert operation completed: {grade_doc.name}")

        frappe.logger().info(f"Created education grade: {grade_doc.name}")
        
        return single_item_response(
            data=grade_doc.as_dict(),
            message="Education grade created successfully"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error creating education grade: {str(e)}")
        import traceback
        frappe.logger().error(f"Traceback: {traceback.format_exc()}")

        # Check if grade was actually created despite the exception
        if data.get("grade_code"):
            created_grade = frappe.db.exists("SIS Education Grade", {
                "grade_code": data.get("grade_code"),
                "campus_id": campus_id if 'campus_id' in locals() else None
            })
            if created_grade:
                frappe.logger().info(f"Grade was actually created despite exception: {created_grade}")
                # Return success response if grade exists
                grade_doc = frappe.get_doc("SIS Education Grade", created_grade)
                return single_item_response(
                    data=grade_doc.as_dict(),
                    message="Education grade created successfully"
                )

        return error_response(
            message=f"Error creating education grade: {str(e)}",
            code="CREATE_EDUCATION_GRADE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_education_grade():
    """Update an existing education grade"""
    try:
        
        # Get grade_id from multiple sources (form data or JSON)
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_id = frappe.form_dict.get('grade_id')

        # Try from JSON payload if not found
        if not grade_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_id = json_data.get('grade_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        if not grade_id:
            return {
                "success": False,
                "message": "Grade ID is required",
                "debug": {
                    "request_method": frappe.request.method,
                    "content_type": frappe.request.headers.get('Content-Type'),
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "grade_id_value": repr(grade_id),
                    "grade_id_type": type(grade_id).__name__
                }
            }

        # Get data from request (support both form data and JSON)
        data = {}

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # If JSON payload exists, merge it (JSON takes precedence)
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                data.update(json_data)
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        # Get existing grade
        grade_doc = frappe.get_doc("SIS Education Grade", grade_id)
        
        if not grade_doc:
            return not_found_response(
                message="Education grade not found",
                code="EDUCATION_GRADE_NOT_FOUND"
            )
        
        # Check if grade_code already exists for this campus (excluding current grade)
        if data.get("grade_code") and data.get("grade_code") != grade_doc.grade_code:
            existing_grade = frappe.db.exists("SIS Education Grade", {
                "grade_code": data.get("grade_code"),
                "campus_id": grade_doc.campus_id,
                "name": ["!=", grade_id]
            })
            
            if existing_grade:
                return error_response(
                    message="Mã khối học đã tồn tại cho trường học này",
                    code="GRADE_CODE_EXISTS"
                )
        
        # Update fields - map from frontend to backend fields
        field_mapping = {
            "grade_name": "title_vn",
            "grade_code": "grade_code", 
            "education_stage": "education_stage_id",
            "sort_order": "sort_order"
        }
        
        for frontend_field, backend_field in field_mapping.items():
            if frontend_field in data:
                if frontend_field == "sort_order":
                    setattr(grade_doc, backend_field, int(data.get(frontend_field)))
                else:
                    setattr(grade_doc, backend_field, data.get(frontend_field))
        
        grade_doc.save(ignore_permissions=True)
        
        return single_item_response(
            data=grade_doc.as_dict(),
            message="Education grade updated successfully"
        )
        
    except frappe.DoesNotExistError:
        return not_found_response(
            message="Education grade not found",
            code="EDUCATION_GRADE_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"Error updating education grade {grade_id}: {str(e)}")
        return error_response(
            message="Error updating education grade",
            code="UPDATE_EDUCATION_GRADE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_education_grade():
    """Delete an education grade"""
    try:
    
        # Get grade_id from multiple sources (form data or JSON)
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_id = frappe.form_dict.get('grade_id')

        # If not found, try from JSON payload
        if not grade_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_id = json_data.get('grade_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        if not grade_id:
            return {
                "success": False,
                "message": "Grade ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "grade_id_value": repr(grade_id)
                }
            }
        
        # Check if grade exists
        grade_doc = frappe.get_doc("SIS Education Grade", grade_id)
        
        if not grade_doc:
            return not_found_response(
                message="Education grade not found",
                code="EDUCATION_GRADE_NOT_FOUND"
            )
        
        # TODO: Add validation to check if grade is being used by other documents
        # before deleting
        
        # Delete the grade
        frappe.delete_doc("SIS Education Grade", grade_id, ignore_permissions=True)
        
        return success_response(
            message="Education grade deleted successfully"
        )
        
    except frappe.DoesNotExistError:
        return not_found_response(
            message="Education grade not found",
            code="EDUCATION_GRADE_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"Error deleting education grade {grade_id}: {str(e)}")
        return error_response(
            message="Error deleting education grade",
            code="DELETE_EDUCATION_GRADE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def check_grade_code_availability():
    """Check if a grade code is available for the current campus"""
    try:


        # Get parameters from multiple sources (form data or JSON payload)
        grade_code = None
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_code = frappe.form_dict.get('grade_code')
        grade_id = frappe.form_dict.get('grade_id')

        # If not found, try from JSON payload
        if not grade_code and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_code = json_data.get('grade_code')
                grade_id = json_data.get('grade_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

        if not grade_code:
            return error_response(
                message="Grade code is required",
                code="MISSING_GRADE_CODE"
            )
        
        # Get current user's campus from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return error_response(
                message="User campus not found in roles",
                code="CAMPUS_NOT_FOUND"
            )
        
        filters = {
            "grade_code": grade_code,
            "campus_id": campus_id
        }
        
        # Exclude current grade if updating
        if grade_id:
            filters["name"] = ["!=", grade_id]
        
        existing_grade = frappe.db.exists("SIS Education Grade", filters)
        
        return success_response(
            data={
                "is_available": not bool(existing_grade),
                "grade_code": grade_code
            },
            message="Grade code availability checked"
        )
        
    except Exception as e:
        frappe.log_error(f"Error checking grade code availability: {str(e)}")
        return error_response(
            message="Error checking grade code availability",
            code="CHECK_AVAILABILITY_ERROR"
        )

