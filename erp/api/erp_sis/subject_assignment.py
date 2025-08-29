# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


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
        
        return list_response(subject_assignments_data, "Subject assignments fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject assignments: {str(e)}")
        return error_response(f"Error fetching subject assignments: {str(e)}")


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
            return validation_error_response({"assignment_id": ["Subject Assignment ID is required"]})
        
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
            frappe.logger().error(f"Subject assignment not found - ID: {assignment_id}, Campus: {campus_id}")
            return not_found_response(f"Subject assignment not found or access denied - ID: {assignment_id}, Campus: {campus_id}")

        assignment = assignment_data[0]

        assignment_data = {
            "name": assignment.name,
            "teacher_id": assignment.teacher_id,
            "subject_id": assignment.subject_id,
            "campus_id": assignment.campus_id,
            "teacher_name": assignment.teacher_name,
            "subject_title": assignment.subject_title
        }
        return single_item_response(assignment_data, "Subject assignment fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error fetching subject assignment: {str(e)}")


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
                else:
                    data = frappe.local.form_dict
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
        
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
            return not_found_response("Selected teacher does not exist or access denied")
        
        # Verify subject exists and belongs to same campus
        subject_exists = frappe.db.exists(
            "SIS Subject",
            {
                "name": subject_id,
                "campus_id": campus_id
            }
        )
        
        if not subject_exists:
            return not_found_response("Selected subject does not exist or access denied")
        
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
            assignment_data = {
                "name": result.name,
                "teacher_id": result.teacher_id,
                "subject_id": result.subject_id,
                "campus_id": result.campus_id,
                "teacher_name": result.teacher_name,
                "subject_title": result.subject_title
            }
            return single_item_response(assignment_data, "Subject assignment created successfully")
        else:
            assignment_data = {
                "name": assignment_doc.name,
                "teacher_id": assignment_doc.teacher_id,
                "subject_id": assignment_doc.subject_id,
                "campus_id": assignment_doc.campus_id
            }
            return single_item_response(assignment_data, "Subject assignment created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating subject assignment: {str(e)}")
        frappe.throw(_(f"Error creating subject assignment: {str(e)}"))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_subject_assignment(assignment_id=None, teacher_id=None, subject_id=None):
    """Update an existing subject assignment"""
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
            return validation_error_response({"assignment_id": ["Subject Assignment ID is required"]})
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            assignment_doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
            
            # Check campus permission
            if assignment_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to modify this subject assignment")
                
        except frappe.DoesNotExistError:
            return not_found_response("Subject assignment not found")
        
        # Update fields if provided
        frappe.logger().info(f"Before update - Current teacher_id: {assignment_doc.teacher_id}, subject_id: {assignment_doc.subject_id}")
        frappe.logger().info(f"Update requested - teacher_id: {teacher_id}, subject_id: {subject_id}")
        frappe.logger().info(f"Teacher check: teacher_id={teacher_id}, current={assignment_doc.teacher_id}, equal={teacher_id == assignment_doc.teacher_id}")
        frappe.logger().info(f"Subject check: subject_id={subject_id}, current={assignment_doc.subject_id}, equal={subject_id == assignment_doc.subject_id}")

        if teacher_id and teacher_id != assignment_doc.teacher_id:
            frappe.logger().info(f"Updating teacher_id from {assignment_doc.teacher_id} to {teacher_id}")
            # Verify teacher exists and belongs to same campus
            teacher_exists = frappe.db.exists(
                "SIS Teacher",
                {
                    "name": teacher_id,
                    "campus_id": campus_id
                }
            )

            frappe.logger().info(f"Teacher {teacher_id} exists in campus {campus_id}: {teacher_exists}")

            if not teacher_exists:
                frappe.logger().error(f"Teacher {teacher_id} does not exist in campus {campus_id}")
                return not_found_response("Selected teacher does not exist or access denied")

            assignment_doc.teacher_id = teacher_id
            frappe.logger().info(f"Teacher ID updated successfully to: {assignment_doc.teacher_id}")
        else:
            frappe.logger().info(f"Teacher ID not updated - condition not met: teacher_id={teacher_id}, current={assignment_doc.teacher_id}")

        if subject_id and subject_id != assignment_doc.subject_id:
            frappe.logger().info(f"Updating subject_id from {assignment_doc.subject_id} to {subject_id}")
            # Verify subject exists and belongs to same campus
            subject_exists = frappe.db.exists(
                "SIS Subject",
                {
                    "name": subject_id,
                    "campus_id": campus_id
                }
            )

            frappe.logger().info(f"Subject {subject_id} exists in campus {campus_id}: {subject_exists}")

            if not subject_exists:
                frappe.logger().error(f"Subject {subject_id} does not exist in campus {campus_id}")
                return not_found_response("Selected subject does not exist or access denied")

            assignment_doc.subject_id = subject_id
            frappe.logger().info(f"Subject ID updated successfully to: {assignment_doc.subject_id}")
        else:
            frappe.logger().info(f"Subject ID not updated - condition not met: subject_id={subject_id}, current={assignment_doc.subject_id}")
        
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
                return validation_error_response({"assignment": [f"This teacher is already assigned to this subject"]})
        
        frappe.logger().info(f"Before save - assignment_doc.teacher_id: {assignment_doc.teacher_id}, assignment_doc.subject_id: {assignment_doc.subject_id}")

        assignment_doc.save()
        frappe.db.commit()

        frappe.logger().info(f"After save - assignment_doc.teacher_id: {assignment_doc.teacher_id}, assignment_doc.subject_id: {assignment_doc.subject_id}")

        # Get updated data with display names
        frappe.logger().info(f"Querying updated data for assignment: {assignment_doc.name}")
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

        frappe.logger().info(f"SQL query result: {updated_data}")

        if updated_data:
            result = updated_data[0]
            frappe.logger().info(f"Final result - teacher_id: {result.teacher_id}, subject_id: {result.subject_id}")
            assignment_data = {
                "name": result.name,
                "teacher_id": result.teacher_id,
                "subject_id": result.subject_id,
                "campus_id": result.campus_id,
                "teacher_name": result.teacher_name,
                "subject_title": result.subject_title
            }
            return single_item_response(assignment_data, "Subject assignment updated successfully")
        else:
            assignment_data = {
                "name": assignment_doc.name,
                "teacher_id": assignment_doc.teacher_id,
                "subject_id": assignment_doc.subject_id,
                "campus_id": assignment_doc.campus_id
            }
            return single_item_response(assignment_data, "Subject assignment updated successfully")
        
    except Exception as e:
        frappe.log_error(f"Error updating subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error updating subject assignment: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"]) 
def delete_subject_assignment(assignment_id):
    """Delete a subject assignment"""
    try:
        if not assignment_id:
            return validation_error_response({"assignment_id": ["Subject Assignment ID is required"]})
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            assignment_doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
            
            # Check campus permission
            if assignment_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to delete this subject assignment")
                
        except frappe.DoesNotExistError:
            return not_found_response("Subject assignment not found")
        
        # Delete the document
        frappe.delete_doc("SIS Subject Assignment", assignment_id)
        frappe.db.commit()
        
        return success_response(message="Subject assignment deleted successfully")
        
    except Exception as e:
        frappe.log_error(f"Error deleting subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error deleting subject assignment: {str(e)}")


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
        
        return list_response(teachers, "Teachers fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching teachers for assignment: {str(e)}")
        return error_response(f"Error fetching teachers: {str(e)}")


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
        
        return list_response(subjects, "Subjects fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects for assignment: {str(e)}")
        return error_response(f"Error fetching subjects: {str(e)}")
