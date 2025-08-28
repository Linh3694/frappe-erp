# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_all_subject_assignments():
    """Get all subject assignments with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        # Get subject assignments with display names
        subject_assignments_data = frappe.db.sql("""
            SELECT
                sa.name,
                sa.teacher_id,
                sa.subject_id,
                sa.campus_id,
                sa.creation,
                sa.modified,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            WHERE sa.campus_id = %s
            ORDER BY sa.teacher_id asc
        """, (campus_id,), as_dict=True)
        
        return {
            "success": True,
            "data": subject_assignments_data,
            "total_count": len(subject_assignments_data),
            "message": "Subject assignments fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject assignments: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching subject assignments: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subject_assignment_by_id(assignment_id=None):
    """Get a specific subject assignment by ID"""
    try:
        # Get assignment_id from multiple sources (form_dict, JSON payload, or direct parameter)
        if not assignment_id:
            assignment_id = frappe.form_dict.get('assignment_id')

        # Try to get from JSON payload if not in form_dict
        if not assignment_id and frappe.request.data:
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
                    assignment_id = json_data.get('assignment_id')
            except Exception as e:
                # Silently handle JSON parse errors
                pass

        if not assignment_id:
            return {
                "success": False,
                "data": {},
                "message": "Subject Assignment ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": assignment_id,
            "campus_id": campus_id
        }
        
        # Get assignment with display names
        assignment_data = frappe.db.sql("""
            SELECT
                sa.name,
                sa.teacher_id,
                sa.subject_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            WHERE sa.name = %s AND sa.campus_id = %s
        """, (assignment_id, campus_id), as_dict=True)

        if not assignment_data or len(assignment_data) == 0:
            return {
                "success": False,
                "data": {},
                "message": "Subject assignment not found or access denied"
            }

        assignment = assignment_data[0]

        return {
            "success": True,
            "data": {
                "subject_assignment": {
                    "name": assignment.name,
                    "teacher_id": assignment.teacher_id,
                    "subject_id": assignment.subject_id,
                    "campus_id": assignment.campus_id,
                    "teacher_name": assignment.teacher_name,
                    "subject_title": assignment.subject_title
                }
            },
            "message": "Subject assignment fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject assignment {assignment_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching subject assignment: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def create_subject_assignment():
    """Create a new subject assignment - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_subject_assignment: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_subject_assignment: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_subject_assignment: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_subject_assignment: {data}")
        
        # Extract values from data
        teacher_id = data.get("teacher_id")
        subject_id = data.get("subject_id")
        
        # Input validation
        if not teacher_id or not subject_id:
            frappe.throw(_("Teacher ID and Subject ID are required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if assignment already exists
        existing = frappe.db.exists(
            "SIS Subject Assignment",
            {
                "teacher_id": teacher_id,
                "subject_id": subject_id,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_("This teacher is already assigned to this subject"))
        
        # Verify teacher exists and belongs to same campus
        teacher_exists = frappe.db.exists(
            "SIS Teacher",
            {
                "name": teacher_id,
                "campus_id": campus_id
            }
        )
        
        if not teacher_exists:
            return {
                "success": False,
                "data": {},
                "message": "Selected teacher does not exist or access denied"
            }
        
        # Verify subject exists and belongs to same campus
        subject_exists = frappe.db.exists(
            "SIS Subject",
            {
                "name": subject_id,
                "campus_id": campus_id
            }
        )
        
        if not subject_exists:
            return {
                "success": False,
                "data": {},
                "message": "Selected subject does not exist or access denied"
            }
        
        # Create new subject assignment
        assignment_doc = frappe.get_doc({
            "doctype": "SIS Subject Assignment",
            "teacher_id": teacher_id,
            "subject_id": subject_id,
            "campus_id": campus_id
        })
        
        assignment_doc.insert()
        frappe.db.commit()

        # Get created data with display names
        created_data = frappe.db.sql("""
            SELECT
                sa.name,
                sa.teacher_id,
                sa.subject_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            WHERE sa.name = %s
        """, (assignment_doc.name,), as_dict=True)

        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Subject assignment created successfully"))

        if created_data:
            result = created_data[0]
            return {
                "success": True,
                "data": {
                    "subject_assignment": {
                        "name": result.name,
                        "teacher_id": result.teacher_id,
                        "subject_id": result.subject_id,
                        "campus_id": result.campus_id,
                        "teacher_name": result.teacher_name,
                        "subject_title": result.subject_title
                    }
                },
                "message": "Subject assignment created successfully"
            }
        else:
            return {
                "success": True,
                "data": {
                    "subject_assignment": {
                        "name": assignment_doc.name,
                        "teacher_id": assignment_doc.teacher_id,
                        "subject_id": assignment_doc.subject_id,
                        "campus_id": assignment_doc.campus_id
                    }
                },
                "message": "Subject assignment created successfully"
            }
        
    except Exception as e:
        frappe.log_error(f"Error creating subject assignment: {str(e)}")
        frappe.throw(_(f"Error creating subject assignment: {str(e)}"))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_subject_assignment(assignment_id, teacher_id=None, subject_id=None):
    """Update an existing subject assignment"""
    try:
        if not assignment_id:
            return {
                "success": False,
                "data": {},
                "message": "Subject Assignment ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            assignment_doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
            
            # Check campus permission
            if assignment_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this subject assignment"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Subject assignment not found"
            }
        
        # Update fields if provided
        if teacher_id and teacher_id != assignment_doc.teacher_id:
            # Verify teacher exists and belongs to same campus
            teacher_exists = frappe.db.exists(
                "SIS Teacher",
                {
                    "name": teacher_id,
                    "campus_id": campus_id
                }
            )
            
            if not teacher_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected teacher does not exist or access denied"
                }
            
            assignment_doc.teacher_id = teacher_id
        
        if subject_id and subject_id != assignment_doc.subject_id:
            # Verify subject exists and belongs to same campus
            subject_exists = frappe.db.exists(
                "SIS Subject",
                {
                    "name": subject_id,
                    "campus_id": campus_id
                }
            )
            
            if not subject_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected subject does not exist or access denied"
                }
            
            assignment_doc.subject_id = subject_id
        
        # Check for duplicate assignment after updates
        if teacher_id or subject_id:
            final_teacher_id = teacher_id or assignment_doc.teacher_id
            final_subject_id = subject_id or assignment_doc.subject_id
            
            existing = frappe.db.exists(
                "SIS Subject Assignment",
                {
                    "teacher_id": final_teacher_id,
                    "subject_id": final_subject_id,
                    "campus_id": campus_id,
                    "name": ["!=", assignment_id]
                }
            )
            
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"This teacher is already assigned to this subject"
                }
        
        assignment_doc.save()
        frappe.db.commit()

        # Get updated data with display names
        updated_data = frappe.db.sql("""
            SELECT
                sa.name,
                sa.teacher_id,
                sa.subject_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            WHERE sa.name = %s
        """, (assignment_doc.name,), as_dict=True)

        if updated_data:
            result = updated_data[0]
            return {
                "success": True,
                "data": {
                    "subject_assignment": {
                        "name": result.name,
                        "teacher_id": result.teacher_id,
                        "subject_id": result.subject_id,
                        "campus_id": result.campus_id,
                        "teacher_name": result.teacher_name,
                        "subject_title": result.subject_title
                    }
                },
                "message": "Subject assignment updated successfully"
            }
        else:
            return {
                "success": True,
                "data": {
                    "subject_assignment": {
                        "name": assignment_doc.name,
                        "teacher_id": assignment_doc.teacher_id,
                        "subject_id": assignment_doc.subject_id,
                        "campus_id": assignment_doc.campus_id
                    }
                },
                "message": "Subject assignment updated successfully"
            }
        
    except Exception as e:
        frappe.log_error(f"Error updating subject assignment {assignment_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating subject assignment: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"]) 
def delete_subject_assignment(assignment_id):
    """Delete a subject assignment"""
    try:
        if not assignment_id:
            return {
                "success": False,
                "data": {},
                "message": "Subject Assignment ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            assignment_doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
            
            # Check campus permission
            if assignment_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this subject assignment"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Subject assignment not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Subject Assignment", assignment_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Subject assignment deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting subject assignment {assignment_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting subject assignment: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_teachers_for_assignment():
    """Get teachers for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        teachers = frappe.get_all(
            "SIS Teacher",
            fields=[
                "name",
                "user_id"
            ],
            filters=filters,
            order_by="user_id asc"
        )
        
        return {
            "success": True,
            "data": teachers,
            "message": "Teachers fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching teachers for assignment: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching teachers: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subjects_for_assignment():
    """Get subjects for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        subjects = frappe.get_all(
            "SIS Subject",
            fields=[
                "name",
                "title"
            ],
            filters=filters,
            order_by="title asc"
        )
        
        return {
            "success": True,
            "data": subjects,
            "message": "Subjects fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects for assignment: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching subjects: {str(e)}"
        }
