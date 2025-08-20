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
def get_education_grade_by_id(grade_id):
    """Get education grade details by ID"""
    try:
        if not grade_id:
            return {
                "success": False,
                "message": "Grade ID is required"
            }
            
        grade = frappe.get_doc("SIS Education Grade", grade_id)
        
        if not grade:
            return {
                "success": False,
                "message": "Education grade not found"
            }
            
        return {
            "success": True,
            "data": {
                "education_grade": grade.as_dict()
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
def update_education_grade(grade_id):
    """Update an existing education grade"""
    try:
        if not grade_id:
            return {
                "success": False,
                "message": "Grade ID is required"
            }
        
        # Get data from request
        data = frappe.local.form_dict
        
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
def delete_education_grade(grade_id):
    """Delete an education grade"""
    try:
        if not grade_id:
            return {
                "success": False,
                "message": "Grade ID is required"
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
def check_grade_code_availability(grade_code, grade_id=None):
    """Check if a grade code is available for the current campus"""
    try:
        if not grade_code:
            return {
                "success": False,
                "message": "Grade code is required"
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
