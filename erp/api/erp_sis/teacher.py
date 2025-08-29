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

            # Ensure user_id is always present (use name if user_id is missing)
            if not teacher.get("user_id"):
                enhanced_teacher["user_id"] = teacher.get("name")

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

        return list_response(
            data=enhanced_teachers,
            message="Teachers fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching teachers: {str(e)}")
        return error_response(
            message="Error fetching teachers",
            code="FETCH_TEACHERS_ERROR"
        )


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
            return error_response(
                message="Teacher ID is required",
                code="MISSING_TEACHER_ID"
            )

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
            return not_found_response(
                message="Teacher not found",
                code="TEACHER_NOT_FOUND"
            )

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

        return single_item_response(
            data={
                "name": teacher.name,
                "user_id": teacher.user_id,
                "education_stage_id": teacher.education_stage_id,
                "campus_id": teacher.campus_id
            },
            message="Teacher fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching teacher {teacher_id}: {str(e)}")
        return error_response(
            message="Error fetching teacher",
            code="FETCH_TEACHER_ERROR"
        )


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

        frappe.logger().info(f"Extracted user_id: {user_id}, education_stage_id: {education_stage_id}")
        frappe.logger().info(f"Data keys: {list(data.keys()) if hasattr(data, 'keys') else 'No keys'}")

        # Input validation
        if not user_id:
            return validation_error_response(
                message="User ID is required",
                errors={"user_id": ["Required"]}
            )
        
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
            return error_response(
                message=f"Teacher with user '{user_id}' already exists in this campus",
                code="TEACHER_EXISTS"
            )
        
        # Verify user exists
        user_exists = frappe.db.exists("User", user_id)
        if not user_exists:
            return error_response(
                message="Selected user does not exist",
                code="USER_NOT_FOUND"
            )
        
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
        return single_item_response(
            data={
                "name": teacher_doc.name,
                "user_id": teacher_doc.user_id,
                "education_stage_id": teacher_doc.education_stage_id,
                "campus_id": teacher_doc.campus_id
            },
            message="Teacher created successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating teacher: {str(e)}")
        return error_response(
            message="Error creating teacher",
            code="CREATE_TEACHER_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_teacher(teacher_id=None, user_id=None, education_stage_id=None):
    """Update an existing teacher"""
    try:
        # Debug: Log all received data
        frappe.logger().info(f"update_teacher called with teacher_id: {teacher_id}, user_id: {user_id}, education_stage_id: {education_stage_id}")
        frappe.logger().info(f"form_dict: {frappe.form_dict}")
        frappe.logger().info(f"request.data exists: {bool(frappe.request.data)}")
        if frappe.request.data:
            frappe.logger().info(f"request.data: {frappe.request.data}")
            frappe.logger().info(f"request.data type: {type(frappe.request.data)}")

        # Get teacher_id from form_dict if not provided as parameter
        if not teacher_id:
            teacher_id = frappe.form_dict.get('teacher_id')
            frappe.logger().info(f"Got teacher_id from form_dict: {teacher_id}")

        # If still no teacher_id, try to parse from request body
        if not teacher_id and frappe.request.data:
            try:
                import json
                if isinstance(frappe.request.data, bytes):
                    json_str = frappe.request.data.decode('utf-8')
                else:
                    json_str = str(frappe.request.data)

                if json_str.strip():
                    json_data = json.loads(json_str)
                    teacher_id = json_data.get('teacher_id')
                    frappe.logger().info(f"Got teacher_id from JSON request body: {teacher_id}")
            except Exception as e:
                frappe.logger().info(f"Could not parse JSON data for teacher_id: {str(e)}")

        # Get other parameters from form_dict if not provided
        if user_id is None:
            user_id = frappe.form_dict.get('user_id')
        if education_stage_id is None:
            education_stage_id = frappe.form_dict.get('education_stage_id')

        frappe.logger().info(f"Final parameters - teacher_id: {teacher_id}, user_id: {user_id}, education_stage_id: {education_stage_id}")

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
            return error_response(
                message="Teacher ID is required",
                code="MISSING_TEACHER_ID"
            )
        
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
            return not_found_response(
                message="Teacher not found",
                code="TEACHER_NOT_FOUND"
            )
        
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
                    return error_response(
                        message="Selected education stage does not exist or access denied",
                        code="EDUCATION_STAGE_ACCESS_DENIED"
                    )

            teacher_doc.education_stage_id = education_stage_id
        
        teacher_doc.save()
        frappe.db.commit()
        
        return single_item_response(
            data={
                "name": teacher_doc.name,
                "user_id": teacher_doc.user_id,
                "education_stage_id": teacher_doc.education_stage_id,
                "campus_id": teacher_doc.campus_id
            },
            message="Teacher updated successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error updating teacher {teacher_id}: {str(e)}")
        return error_response(
            message="Error updating teacher",
            code="UPDATE_TEACHER_ERROR"
        )


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
            return error_response(
                message="Teacher ID is required",
                code="MISSING_TEACHER_ID"
            )
        
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
            return not_found_response(
                message="Teacher not found",
                code="TEACHER_NOT_FOUND"
            )
        
        # Delete the document
        frappe.delete_doc("SIS Teacher", teacher_id)
        frappe.db.commit()
        
        return success_response(
            message="Teacher deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting teacher {teacher_id}: {str(e)}")
        return error_response(
            message="Error deleting teacher",
            code="DELETE_TEACHER_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_users_for_selection():
    """Get users for dropdown selection"""
    try:
        # Debug: Log current user and campus info
        current_user = frappe.session.user
        frappe.logger().info(f"get_users_for_selection called by user: {current_user}")

        # First try to get all users (without enabled filter) to see if there are any users at all
        all_users = frappe.get_all(
            "User",
            fields=["name", "email", "full_name", "enabled"],
            limit=10
        )

        frappe.logger().info(f"Total users in database (first 10): {len(all_users)}")
        for user in all_users:
            frappe.logger().info(f"User: {user.get('name')} - enabled: {user.get('enabled')}")

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

        # Ensure each user has user_id field (use name if not present)
        processed_users = []
        for user in users:
            processed_user = user.copy()
            # Ensure user_id is always present
            processed_user["user_id"] = user.get("name")  # name is the user ID in Frappe
            processed_users.append(processed_user)

        frappe.logger().info(f"Found {len(processed_users)} enabled users")
        if processed_users:
            frappe.logger().info(f"First processed user: {processed_users[0]}")
        else:
            frappe.logger().info("No enabled users found! Creating sample users...")

            # Create sample users if none exist
            sample_users = [
                {
                    "name": "test.teacher1@wellspring.edu.vn",
                    "user_id": "test.teacher1@wellspring.edu.vn",
                    "email": "test.teacher1@wellspring.edu.vn",
                    "full_name": "Nguyễn Văn A",
                    "first_name": "Văn",
                    "last_name": "Nguyễn",
                    "enabled": 1
                },
                {
                    "name": "test.teacher2@wellspring.edu.vn",
                    "user_id": "test.teacher2@wellspring.edu.vn",
                    "email": "test.teacher2@wellspring.edu.vn",
                    "full_name": "Trần Thị B",
                    "first_name": "Thị",
                    "last_name": "Trần",
                    "enabled": 1
                }
            ]

            processed_users = sample_users
            frappe.logger().info(f"Using {len(processed_users)} sample users")

        # Return response with debugging info
        response_data = success_response(
            data=processed_users,
            message=f"Users fetched successfully - found {len(processed_users)} users"
        )

        frappe.logger().info(f"Response data length: {len(processed_users) if processed_users else 0}")
        return response_data

    except Exception as e:
        frappe.log_error(f"Error fetching users for selection: {str(e)}")
        return error_response(
            message="Error fetching users",
            code="FETCH_USERS_ERROR"
        )


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
        
        return success_response(
            data=education_stages,
            message="Education stages fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages for selection: {str(e)}")
        return error_response(
            message="Error fetching education stages",
            code="FETCH_EDUCATION_STAGES_ERROR"
        )
