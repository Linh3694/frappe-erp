# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_teachers():
    """Get all teachers with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        teachers = frappe.get_all(
            "SIS Teacher",
            fields=[
                "name",
                "user_id",
                "education_stage_id",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="user_id asc"
        )
        
        return {
            "success": True,
            "data": teachers,
            "total_count": len(teachers),
            "message": "Teachers fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching teachers: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching teachers: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_teacher_by_id(teacher_id):
    """Get a specific teacher by ID"""
    try:
        if not teacher_id:
            return {
                "success": False,
                "data": {},
                "message": "Teacher ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": teacher_id,
            "campus_id": campus_id
        }
        
        teacher = frappe.get_doc("SIS Teacher", filters)
        
        if not teacher:
            return {
                "success": False,
                "data": {},
                "message": "Teacher not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": teacher.name,
                "user_id": teacher.user_id,
                "education_stage_id": teacher.education_stage_id,
                "campus_id": teacher.campus_id
            },
            "message": "Teacher fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching teacher {teacher_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching teacher: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_teacher():
    """Create a new teacher - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_teacher: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_teacher: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_teacher: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_teacher: {data}")
        
        # Extract values from data
        user_id = data.get("user_id")
        education_stage_id = data.get("education_stage_id")
        
        # Input validation
        if not user_id:
            frappe.throw(_("User ID is required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if teacher with this user already exists for this campus
        existing = frappe.db.exists(
            "SIS Teacher",
            {
                "user_id": user_id,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Teacher with user '{user_id}' already exists in this campus"))
        
        # Verify user exists
        user_exists = frappe.db.exists("User", user_id)
        if not user_exists:
            return {
                "success": False,
                "data": {},
                "message": "Selected user does not exist"
            }
        
        # Verify education stage exists and belongs to same campus (if provided)
        if education_stage_id:
            education_stage_exists = frappe.db.exists(
                "SIS Education Stage",
                {
                    "name": education_stage_id,
                    "campus_id": campus_id
                }
            )
            
            if not education_stage_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected education stage does not exist or access denied"
                }
        
        # Create new teacher
        teacher_doc = frappe.get_doc({
            "doctype": "SIS Teacher",
            "user_id": user_id,
            "education_stage_id": education_stage_id,
            "campus_id": campus_id
        })
        
        teacher_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Teacher created successfully"))
        return {
            "name": teacher_doc.name,
            "user_id": teacher_doc.user_id,
            "education_stage_id": teacher_doc.education_stage_id,
            "campus_id": teacher_doc.campus_id
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating teacher: {str(e)}")
        frappe.throw(_(f"Error creating teacher: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_teacher(teacher_id, user_id=None, education_stage_id=None):
    """Update an existing teacher"""
    try:
        if not teacher_id:
            return {
                "success": False,
                "data": {},
                "message": "Teacher ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            teacher_doc = frappe.get_doc("SIS Teacher", teacher_id)
            
            # Check campus permission
            if teacher_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this teacher"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Teacher not found"
            }
        
        # Update fields if provided
        if user_id and user_id != teacher_doc.user_id:
            # Check for duplicate teacher user
            existing = frappe.db.exists(
                "SIS Teacher",
                {
                    "user_id": user_id,
                    "campus_id": campus_id,
                    "name": ["!=", teacher_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Teacher with user '{user_id}' already exists in this campus"
                }
            
            # Verify user exists
            user_exists = frappe.db.exists("User", user_id)
            if not user_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected user does not exist"
                }
            
            teacher_doc.user_id = user_id
        
        if education_stage_id is not None and education_stage_id != teacher_doc.education_stage_id:
            # Verify education stage exists and belongs to same campus (if provided)
            if education_stage_id:
                education_stage_exists = frappe.db.exists(
                    "SIS Education Stage",
                    {
                        "name": education_stage_id,
                        "campus_id": campus_id
                    }
                )
                
                if not education_stage_exists:
                    return {
                        "success": False,
                        "data": {},
                        "message": "Selected education stage does not exist or access denied"
                    }
            
            teacher_doc.education_stage_id = education_stage_id
        
        teacher_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": teacher_doc.name,
                "user_id": teacher_doc.user_id,
                "education_stage_id": teacher_doc.education_stage_id,
                "campus_id": teacher_doc.campus_id
            },
            "message": "Teacher updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating teacher {teacher_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating teacher: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_teacher(teacher_id):
    """Delete a teacher"""
    try:
        if not teacher_id:
            return {
                "success": False,
                "data": {},
                "message": "Teacher ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            teacher_doc = frappe.get_doc("SIS Teacher", teacher_id)
            
            # Check campus permission
            if teacher_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this teacher"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Teacher not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Teacher", teacher_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Teacher deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting teacher {teacher_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting teacher: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_users_for_selection():
    """Get users for dropdown selection"""
    try:
        # Get all enabled users
        users = frappe.get_all(
            "User",
            fields=[
                "name",
                "email",
                "full_name",
                "first_name",
                "last_name"
            ],
            filters={"enabled": 1},
            order_by="full_name asc"
        )
        
        return {
            "success": True,
            "data": users,
            "message": "Users fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching users for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching users: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_education_stages_for_teacher():
    """Get education stages for teacher dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        education_stages = frappe.get_all(
            "SIS Education Stage",
            fields=[
                "name",
                "title_vn",
                "title_en"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": education_stages,
            "message": "Education stages fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education stages: {str(e)}"
        }
