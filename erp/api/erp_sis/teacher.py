# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_teachers():
    """Get all teachers with detailed information including user profile data"""
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

        # Enhance teachers with user information
        enhanced_teachers = []
        for teacher in teachers:
            enhanced_teacher = teacher.copy()

            # Get user information
            if teacher.get("user_id"):
                user_info = frappe.get_all(
                    "User",
                    fields=[
                        "name",
                        "email",
                        "full_name",
                        "first_name",
                        "last_name",
                        "user_image",
                        "employee_code",
                        "employee_id"
                    ],
                    filters={"name": teacher["user_id"]},
                    limit=1
                )

                if user_info:
                    user = user_info[0]
                    enhanced_teacher.update({
                        "email": user.get("email"),
                        "full_name": user.get("full_name"),
                        "first_name": user.get("first_name"),
                        "last_name": user.get("last_name"),
                        "user_image": user.get("user_image"),
                        "employee_code": user.get("employee_code"),
                        "employee_id": user.get("employee_id"),
                        "teacher_name": user.get("full_name") or user.get("name")
                    })

                # Try to get employee information from Employee doctype (if available)
                try:
                    employee_info = frappe.get_all(
                        "Employee",
                        fields=[
                            "name",
                            "employee_number",
                            "employee_name",
                            "designation",
                            "department",
                            "branch"
                        ],
                        filters={"user_id": teacher["user_id"]},
                        limit=1
                    )

                    if employee_info:
                        employee = employee_info[0]
                        enhanced_teacher.update({
                            "employee_code": employee.get("name"),  # Use 'name' field as employee code (like get_current_user.py)
                            "employee_id": employee.get("name"),    # Alias for compatibility
                            "employee_number": employee.get("employee_number"),  # Keep original field
                            "employee_name": employee.get("employee_name"),
                            "designation": employee.get("designation"),
                            "department": employee.get("department"),
                            "branch": employee.get("branch")
                        })
                except Exception:
                    # Employee doctype might not exist or be accessible
                    pass

            enhanced_teachers.append(enhanced_teacher)

        return {
            "success": True,
            "data": enhanced_teachers,
            "total_count": len(enhanced_teachers),
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


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def get_teacher_by_id(teacher_id=None):
    """Get a specific teacher by ID"""
    try:
        # Debug: Log form_dict to see what's being sent
        frappe.logger().info(f"get_teacher_by_id called with teacher_id: {teacher_id}")
        frappe.logger().info(f"form_dict: {frappe.form_dict}")

        # Get teacher_id from form_dict if not provided as parameter
        if not teacher_id:
            teacher_id = frappe.form_dict.get('teacher_id')
            frappe.logger().info(f"Got teacher_id from form_dict: {teacher_id}")

        # If still no teacher_id, try to parse JSON from request body
        if not teacher_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                teacher_id = json_data.get('teacher_id')
                frappe.logger().info(f"Got teacher_id from JSON body: {teacher_id}")
            except Exception as e:
                frappe.logger().info(f"Could not parse JSON data: {str(e)}")

        if not teacher_id:
            frappe.logger().info("No teacher_id found")
            return {
                "success": False,
                "data": {},
                "message": "Teacher ID is required"
            }

        # Get current user's campus
        campus_id = get_current_campus_from_context()
        frappe.logger().info(f"Current user campus_id: {campus_id}")

        if not campus_id:
            campus_id = "campus-1"

        # Try to find teacher by name first (without campus filter)
        try:
            teacher = frappe.get_doc("SIS Teacher", teacher_id)
            frappe.logger().info(f"Teacher found: {teacher.name}, campus: {teacher.campus_id}")
        except frappe.DoesNotExistError:
            frappe.logger().info(f"Teacher {teacher_id} not found at all")
            return {
                "success": False,
                "data": {},
                "message": f"Teacher {teacher_id} not found"
            }

        # Check if teacher belongs to user's campus (if campus filtering is needed)
        if teacher.campus_id != campus_id:
            frappe.logger().info(f"Teacher campus {teacher.campus_id} != user campus {campus_id}")
            # For now, allow access but log the mismatch
            frappe.logger().warning(f"Teacher {teacher_id} campus mismatch: {teacher.campus_id} != {campus_id}")

        # Return teacher data
        if not teacher:
            return {
                "success": False,
                "data": {},
                "message": f"Teacher {teacher_id} not found or access denied"
            }

        return {
            "success": True,
            "data": {
                "teacher": {
                    "name": teacher.name,
                    "user_id": teacher.user_id,
                    "education_stage_id": teacher.education_stage_id,
                    "campus_id": teacher.campus_id
                }
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


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_teacher(teacher_id=None, user_id=None, education_stage_id=None):
    """Update an existing teacher"""
    try:
        # Debug: Log form_dict to see what's being sent
        frappe.logger().info(f"update_teacher called with teacher_id: {teacher_id}, user_id: {user_id}, education_stage_id: {education_stage_id}")
        frappe.logger().info(f"form_dict: {frappe.form_dict}")

        # Get teacher_id from form_dict if not provided as parameter
        if not teacher_id:
            teacher_id = frappe.form_dict.get('teacher_id')
            frappe.logger().info(f"Got teacher_id from form_dict: {teacher_id}")

        # Get other parameters from form_dict if not provided
        if user_id is None:
            user_id = frappe.form_dict.get('user_id')
        if education_stage_id is None:
            education_stage_id = frappe.form_dict.get('education_stage_id')

        # If parameters not found in form_dict, try to parse JSON from request body
        if (not teacher_id or user_id is None or education_stage_id is None) and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                frappe.logger().info(f"Parsed JSON data: {json_data}")

                if not teacher_id:
                    teacher_id = json_data.get('teacher_id')
                    frappe.logger().info(f"Got teacher_id from JSON body: {teacher_id}")

                if user_id is None:
                    user_id = json_data.get('user_id')
                    frappe.logger().info(f"Got user_id from JSON body: {user_id}")

                if education_stage_id is None:
                    education_stage_id = json_data.get('education_stage_id')
                    frappe.logger().info(f"Got education_stage_id from JSON body: {education_stage_id}")

            except Exception as e:
                frappe.logger().info(f"Could not parse JSON data: {str(e)}")

        if not teacher_id:
            frappe.logger().info("No teacher_id found for update")
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
            frappe.logger().info(f"Update teacher - Teacher campus: {teacher_doc.campus_id}, User campus: {campus_id}")

            # Check campus permission
            if teacher_doc.campus_id != campus_id:
                frappe.logger().warning(f"Campus mismatch for update: Teacher={teacher_doc.campus_id}, User={campus_id}")

                # Handle case sensitivity - try to normalize campus IDs
                teacher_campus_normalized = teacher_doc.campus_id.upper().replace("-", "")
                user_campus_normalized = campus_id.upper().replace("-", "")

                if teacher_campus_normalized != user_campus_normalized:
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
            frappe.logger().info(f"Update teacher - Checking education_stage_id: {education_stage_id}, campus_id: {campus_id}")

            # Verify education stage exists and belongs to same campus (if provided)
            if education_stage_id:
                # First try without campus restriction
                education_stage_exists = frappe.db.exists("SIS Education Stage", education_stage_id)
                frappe.logger().info(f"Education stage exists (without campus check): {education_stage_exists}")

                if not education_stage_exists:
                    return {
                        "success": False,
                        "data": {},
                        "message": "Selected education stage does not exist"
                    }

                # Try with campus restriction
                education_stage_with_campus = frappe.db.exists(
                    "SIS Education Stage",
                    {
                        "name": education_stage_id,
                        "campus_id": campus_id
                    }
                )
                frappe.logger().info(f"Education stage exists (with campus check): {education_stage_with_campus}")

                if not education_stage_with_campus:
                    frappe.logger().warning(f"Education stage {education_stage_id} exists but campus mismatch: expected {campus_id}")
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
                "teacher": {
                    "name": teacher_doc.name,
                    "user_id": teacher_doc.user_id,
                    "education_stage_id": teacher_doc.education_stage_id,
                    "campus_id": teacher_doc.campus_id
                }
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


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_teacher(teacher_id=None):
    """Delete a teacher"""
    try:
        # Debug: Log what we received
        frappe.logger().info(f"delete_teacher called with teacher_id: {teacher_id}")
        frappe.logger().info(f"form_dict: {frappe.form_dict}")
        frappe.logger().info(f"request.data exists: {bool(frappe.request.data)}")
        if frappe.request.data:
            frappe.logger().info(f"request.data type: {type(frappe.request.data)}")
            frappe.logger().info(f"request.data content: {frappe.request.data}")

        # Get teacher_id from form_dict if not provided as parameter
        if not teacher_id:
            teacher_id = frappe.form_dict.get('teacher_id')
            frappe.logger().info(f"Got teacher_id from form_dict: {teacher_id}")

        # If still no teacher_id, try to parse JSON from request body
        if not teacher_id and frappe.request.data:
            try:
                import json
                # Handle both bytes and string data
                if isinstance(frappe.request.data, bytes):
                    json_str = frappe.request.data.decode('utf-8')
                else:
                    json_str = str(frappe.request.data)

                # Skip if data is empty or just whitespace
                if json_str.strip():
                    json_data = json.loads(json_str)
                    teacher_id = json_data.get('teacher_id')
                    frappe.logger().info(f"Got teacher_id from JSON body: {teacher_id}")
            except Exception as e:
                frappe.logger().info(f"Could not parse JSON data: {str(e)}, data: {frappe.request.data}")

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
                frappe.logger().warning(f"Campus mismatch for delete: Teacher={teacher_doc.campus_id}, User={campus_id}")

                # Handle case sensitivity - try to normalize campus IDs
                teacher_campus_normalized = teacher_doc.campus_id.upper().replace("-", "")
                user_campus_normalized = campus_id.upper().replace("-", "")

                if teacher_campus_normalized != user_campus_normalized:
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
        # Get all enabled users with avatar information
        users = frappe.get_all(
            "User",
            fields=[
                "name",
                "email",
                "full_name",
                "first_name",
                "last_name",
                "user_image",
                "employee_code",
                "employee_id",
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
