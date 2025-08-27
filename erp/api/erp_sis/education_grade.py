# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_education_grades():
    """Get all education grades with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
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
        
        return {
            "success": True,
            "data": education_grades,
            "total_count": len(education_grades),
            "message": "Education grades fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching education grades: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education grades: {str(e)}",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def get_education_grade_by_id():
    """Get education grade details by ID"""
    try:
        # Debug: Print all request data
        print("=== DEBUG get_education_grade_by_id ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Query string: {frappe.request.query_string}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get grade_id from multiple sources (form data or JSON payload)
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_id = frappe.form_dict.get('grade_id')
        print(f"Grade ID from form_dict: {grade_id}")

        # If not found, try from JSON payload
        if not grade_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_id = json_data.get('grade_id')
                print(f"Grade ID from JSON payload: {grade_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        # Also try from request.args if available (for GET requests)
        if not grade_id and hasattr(frappe.request, 'args'):
            grade_id = frappe.request.args.get('grade_id')
            print(f"Grade ID from request.args: {grade_id}")

        # Parse query string manually for GET requests
        if not grade_id and frappe.request.query_string:
            try:
                from urllib.parse import parse_qs
                query_params = parse_qs(frappe.request.query_string.decode('utf-8'))
                grade_id = query_params.get('grade_id', [None])[0]
                print(f"Grade ID from query string: {grade_id}")
            except Exception as e:
                print(f"Query string parsing error: {e}")

        print(f"Final grade_id: {repr(grade_id)}")

        if not grade_id:
            return {
                "success": False,
                "message": "Grade ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "query_string": str(frappe.request.query_string),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "request_args": str(getattr(frappe.request, 'args', {})),
                    "grade_id_type": type(grade_id).__name__
                }
            }

        grade = frappe.get_doc("SIS Education Grade", grade_id)

        if not grade:
            return {
                "success": False,
                "message": "Education grade not found"
            }

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

        return {
            "success": True,
            "data": {
                "education_grade": grade_data
            },
            "message": "Education grade fetched successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education grade not found"
        }
    except Exception as e:
        frappe.log_error(f"Error fetching education grade {grade_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching education grade",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def create_education_grade():
    """Create a new education grade - SIMPLE VERSION"""
    try:
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
        
        # Validate required fields - map from frontend to backend fields
        required_fields = {
            "grade_name": "title_vn", 
            "grade_code": "grade_code",
            "education_stage": "education_stage_id",
            "sort_order": "sort_order"
        }
        
        backend_data = {}
        for frontend_field, backend_field in required_fields.items():
            if not data.get(frontend_field):
                frappe.throw(_(f"Field '{frontend_field}' is required"))
            backend_data[backend_field] = data.get(frontend_field)
        
        # Get campus from user roles or form data
        campus_id = data.get("campus_id")
        if not campus_id:
            campus_id = get_current_campus_from_context()
            if not campus_id:
                # Fallback to default if no campus found
                campus_id = "campus-1"
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        frappe.logger().info(f"Using campus_id: {campus_id}")
        
        # Check if grade_code already exists for this campus
        existing_grade = frappe.db.exists("SIS Education Grade", {
            "grade_code": data.get("grade_code"),
            "campus_id": campus_id
        })
        
        if existing_grade:
            frappe.throw(_("Mã khối học đã tồn tại cho trường học này"))
        
        # Create new education grade
        grade_doc = frappe.get_doc({
            "doctype": "SIS Education Grade",
            "title_vn": backend_data["title_vn"],
            "title_en": backend_data["title_vn"],  # Default to VN if EN not provided
            "grade_code": backend_data["grade_code"],
            "education_stage_id": backend_data["education_stage_id"],
            "sort_order": int(backend_data["sort_order"]),
            "campus_id": campus_id
        })
        
        grade_doc.insert(ignore_permissions=True)
        
        frappe.logger().info(f"Created education grade: {grade_doc.name}")
        
        return {
            "success": True,
            "data": grade_doc.as_dict(),
            "message": "Education grade created successfully"
        }
        
    except Exception as e:
        frappe.logger().error(f"Error creating education grade: {str(e)}")
        return {
            "success": False,
            "message": f"Error creating education grade: {str(e)}",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def update_education_grade():
    """Update an existing education grade"""
    try:
        # Debug: Print all available request data
        print("=== DEBUG update_education_grade ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Request args: {dict(frappe.request.args) if hasattr(frappe.request, 'args') else 'No args'}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")
        print(f"Request data type: {type(frappe.request.data)}")

        # Get grade_id from multiple sources (form data or JSON)
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_id = frappe.form_dict.get('grade_id')
        print(f"Grade ID from form_dict: {grade_id}")

        # Try from JSON payload if not found
        if not grade_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_id = json_data.get('grade_id')
                print(f"Grade ID from JSON payload: {grade_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final extracted grade_id: {grade_id}")

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
                print(f"Merged JSON data: {json_data}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON data merge failed: {e}")

        print(f"Final data to update: {data}")
        
        # Get existing grade
        grade_doc = frappe.get_doc("SIS Education Grade", grade_id)
        
        if not grade_doc:
            return {
                "success": False,
                "message": "Education grade not found"
            }
        
        # Check if grade_code already exists for this campus (excluding current grade)
        if data.get("grade_code") and data.get("grade_code") != grade_doc.grade_code:
            existing_grade = frappe.db.exists("SIS Education Grade", {
                "grade_code": data.get("grade_code"),
                "campus_id": grade_doc.campus_id,
                "name": ["!=", grade_id]
            })
            
            if existing_grade:
                return {
                    "success": False,
                    "message": "Mã khối học đã tồn tại cho trường học này"
                }
        
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
        
        return {
            "success": True,
            "data": {
                "education_grade": grade_doc.as_dict()
            },
            "message": "Education grade updated successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education grade not found"
        }
    except Exception as e:
        frappe.log_error(f"Error updating education grade {grade_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error updating education grade",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def delete_education_grade():
    """Delete an education grade"""
    try:
        # Debug: Print request data
        print("=== DEBUG delete_education_grade ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get grade_id from multiple sources (form data or JSON)
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_id = frappe.form_dict.get('grade_id')
        print(f"Grade ID from form_dict: {grade_id}")

        # If not found, try from JSON payload
        if not grade_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_id = json_data.get('grade_id')
                print(f"Grade ID from JSON payload: {grade_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final extracted grade_id: {grade_id}")

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
            return {
                "success": False,
                "message": "Education grade not found"
            }
        
        # TODO: Add validation to check if grade is being used by other documents
        # before deleting
        
        # Delete the grade
        frappe.delete_doc("SIS Education Grade", grade_id, ignore_permissions=True)
        
        return {
            "success": True,
            "message": "Education grade deleted successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education grade not found"
        }
    except Exception as e:
        frappe.log_error(f"Error deleting education grade {grade_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error deleting education grade",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def check_grade_code_availability():
    """Check if a grade code is available for the current campus"""
    try:
        # Debug: Print request data
        print("=== DEBUG check_grade_code_availability ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get parameters from multiple sources (form data or JSON payload)
        grade_code = None
        grade_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        grade_code = frappe.form_dict.get('grade_code')
        grade_id = frappe.form_dict.get('grade_id')
        print(f"Parameters from form_dict: grade_code={grade_code}, grade_id={grade_id}")

        # If not found, try from JSON payload
        if not grade_code and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                grade_code = json_data.get('grade_code')
                grade_id = json_data.get('grade_id')
                print(f"Parameters from JSON payload: grade_code={grade_code}, grade_id={grade_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        if not grade_code:
            return {
                "success": False,
                "message": "Grade code is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None
                }
            }
        
        # Get current user's campus from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return {
                "success": False,
                "message": "User campus not found in roles"
            }
        
        filters = {
            "grade_code": grade_code,
            "campus_id": campus_id
        }
        
        # Exclude current grade if updating
        if grade_id:
            filters["name"] = ["!=", grade_id]
        
        existing_grade = frappe.db.exists("SIS Education Grade", filters)
        
        return {
            "success": True,
            "data": {
                "is_available": not bool(existing_grade),
                "grade_code": grade_code
            },
            "message": "Grade code availability checked"
        }
        
    except Exception as e:
        frappe.log_error(f"Error checking grade code availability: {str(e)}")
        return {
            "success": False,
            "message": "Error checking grade code availability",
            "error": str(e)
        }

