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
                sa.class_id,
                sa.campus_id,
                sa.creation,
                sa.modified,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title,
                c.title as class_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
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
        # Get assignment_id from multiple sources (URL path, query params, form_dict, JSON payload, or direct parameter)
        if not assignment_id:
            # Try to get from URL path first (e.g., /api/method/.../SIS-SUBJECT_ASSIGNMENT-00001)
            try:
                request_path = frappe.local.request.path if hasattr(frappe.local, 'request') else frappe.request.path
                if request_path:
                    # Extract the last part of the URL path
                    path_parts = request_path.strip('/').split('/')
                    if len(path_parts) > 0:
                        last_part = path_parts[-1]
                        # Check if it looks like an assignment ID (contains assignment identifier)
                        if 'SUBJECT_ASSIGNMENT' in last_part or last_part.startswith('SIS-'):
                            assignment_id = last_part
            except Exception:
                pass

        # Try to get from URL query parameters (for GET requests)
        if not assignment_id:
            assignment_id = frappe.request.args.get('assignment_id')

        # Try to get from form_dict
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
            return validation_error_response(
                message="Subject Assignment ID is required",
                errors={"assignment_id": ["Subject Assignment ID is required"]}
            )

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
                sa.class_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title,
                c.title as class_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
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
            "class_id": assignment.class_id,
            "campus_id": assignment.campus_id,
            "teacher_name": assignment.teacher_name,
            "subject_title": assignment.subject_title,
            "class_title": assignment.class_title
        }
        return single_item_response(assignment_data, "Subject assignment fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error fetching subject assignment: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def create_subject_assignment():
    """Create new subject assignments. Supports single or bulk creation.
    - Single: { teacher_id, subject_id, class_id? }
    - Bulk: { teacher_id, class_id, subject_ids: [subject_id, ...] }
    """
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
        class_id = data.get("class_id")
        subject_ids = data.get("subject_ids")
        
        # Input validation
        if not teacher_id:
            frappe.throw(_("Teacher ID is required"))
        if not subject_id and not subject_ids:
            frappe.throw(_("Subject ID or subject_ids is required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Optional class validation
        if class_id:
            class_exists = frappe.db.exists(
                "SIS Class",
                {"name": class_id, "campus_id": campus_id}
            )
            if not class_exists:
                return not_found_response("Selected class does not exist or access denied")
        
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
        
        created_names = []
        create_list = subject_ids if isinstance(subject_ids, list) else [subject_id] if subject_id else []
        for sid in create_list:
            # Verify subject exists and belongs to same campus
            subject_exists = frappe.db.exists(
                "SIS Subject",
                {"name": sid, "campus_id": campus_id}
            )
            if not subject_exists:
                return not_found_response(f"Selected subject does not exist or access denied: {sid}")

            # Duplicate check, include class if provided
            filters = {
                "teacher_id": teacher_id,
                "subject_id": sid,
                "campus_id": campus_id,
            }
            if class_id:
                filters["class_id"] = class_id
            existing = frappe.db.exists("SIS Subject Assignment", filters)
            if existing:
                continue

            assignment_doc = frappe.get_doc({
                "doctype": "SIS Subject Assignment",
                "teacher_id": teacher_id,
                "subject_id": sid,
                "class_id": class_id,
                "campus_id": campus_id
            })
            assignment_doc.insert()
            created_names.append(assignment_doc.name)

        frappe.db.commit()

        # Get created data with display names
        created_data = []
        if created_names:
            created_data = frappe.db.sql("""
                SELECT
                    sa.name,
                    sa.teacher_id,
                    sa.subject_id,
                    sa.class_id,
                    sa.campus_id,
                    COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                    s.title as subject_title,
                    c.title as class_title
                FROM `tabSIS Subject Assignment` sa
                LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
                LEFT JOIN `tabUser` u ON t.user_id = u.name
                LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
                LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
                WHERE sa.name in %s
            """, (tuple(created_names),), as_dict=True)

        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Subject assignment created successfully"))

        frappe.msgprint(_("Subject assignment created successfully"))
        if created_data and len(created_data) == 1:
            result = created_data[0]
            return single_item_response({
                "name": result.name,
                "teacher_id": result.teacher_id,
                "subject_id": result.subject_id,
                "class_id": result.class_id,
                "campus_id": result.campus_id,
                "teacher_name": result.teacher_name,
                "subject_title": result.subject_title,
                "class_title": result.class_title
            }, "Subject assignment created successfully")
        else:
            return list_response(created_data, "Subject assignments created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating subject assignment: {str(e)}")
        frappe.throw(_(f"Error creating subject assignment: {str(e)}"))


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_subject_assignment(assignment_id=None, teacher_id=None, subject_id=None):
    """Update an existing subject assignment"""
    try:
        frappe.logger().info(f"UPDATE DEBUG - API called with assignment_id={assignment_id}, teacher_id={teacher_id}, subject_id={subject_id}")

        # Get data from POST body first (JSON payload)
        if frappe.request.data:
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
                    frappe.logger().info(f"UPDATE DEBUG - Raw JSON string: {json_str}")
                    frappe.logger().info(f"UPDATE DEBUG - Parsed JSON data: {json_data}")
                    frappe.logger().info(f"UPDATE DEBUG - JSON keys: {list(json_data.keys())}")

                    assignment_id = json_data.get('assignment_id') or assignment_id
                    teacher_id = json_data.get('teacher_id') or teacher_id
                    subject_id = json_data.get('subject_id') or subject_id

                    # Try different possible field names for class_id
                    class_id = (json_data.get('class_id') or
                               json_data.get('class') or
                               json_data.get('classId') or
                               (json_data.get('data', {}).get('class_id') if json_data.get('data') else None))

                    frappe.logger().info(f"UPDATE DEBUG - Final values: assignment_id={assignment_id}, teacher_id={teacher_id}, subject_id={subject_id}, class_id={class_id}")
                    frappe.logger().info(f"UPDATE DEBUG - class_id sources checked: class_id={json_data.get('class_id')}, class={json_data.get('class')}, classId={json_data.get('classId')}")
            except Exception as e:
                # Silently handle JSON parse errors
                pass

        # Get assignment_id from multiple sources if not found in JSON
        if not assignment_id:
            # Try to get from URL path first (e.g., /api/method/.../SIS-SUBJECT_ASSIGNMENT-00001)
            try:
                request_path = frappe.local.request.path if hasattr(frappe.local, 'request') else frappe.request.path
                if request_path:
                    # Extract the last part of the URL path
                    path_parts = request_path.strip('/').split('/')
                    if len(path_parts) > 0:
                        last_part = path_parts[-1]
                        # Check if it looks like an assignment ID (contains assignment identifier)
                        if 'SUBJECT_ASSIGNMENT' in last_part or last_part.startswith('SIS-'):
                            assignment_id = last_part
            except Exception:
                pass

        # Try to get from URL query parameters (for GET requests)
        if not assignment_id:
            assignment_id = frappe.request.args.get('assignment_id')

        # Try to get from form_dict
        if not assignment_id:
            assignment_id = frappe.form_dict.get('assignment_id')
        if not teacher_id:
            teacher_id = frappe.form_dict.get('teacher_id')
        if not subject_id:
            subject_id = frappe.form_dict.get('subject_id')
        class_id = frappe.form_dict.get('class_id') if 'class_id' in frappe.form_dict else None

        if not assignment_id:
            return validation_error_response(
    message="Subject Assignment ID is required",
    errors={"assignment_id": ["Subject Assignment ID is required"]}
)
        
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
        
        # Debug log received data
        frappe.logger().info(f"UPDATE DEBUG - Received data: teacher_id={teacher_id}, subject_id={subject_id}, class_id={class_id}")
        frappe.logger().info(f"UPDATE DEBUG - Current assignment: teacher={assignment_doc.teacher_id}, subject={assignment_doc.subject_id}, class={assignment_doc.class_id}")

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
                return not_found_response("Selected teacher does not exist or access denied")

            assignment_doc.teacher_id = teacher_id
            frappe.logger().info(f"UPDATE DEBUG - Updated teacher_id to: {teacher_id}")

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
                return not_found_response("Selected subject does not exist or access denied")

            assignment_doc.subject_id = subject_id
            frappe.logger().info(f"UPDATE DEBUG - Updated subject_id to: {subject_id}")
        
        # Update class_id if provided
        # Debug class_id update - also add to response
        current_class_id = getattr(assignment_doc, 'class_id', 'NOT_SET')
        debug_info = {
            'current_class_id': current_class_id,
            'new_class_id': class_id,
            'will_update': class_id is not None and class_id != current_class_id
        }
        frappe.logger().info(f"UPDATE DEBUG - About to update class_id: {debug_info}")

        if class_id is not None and class_id != current_class_id:
            frappe.logger().info(f"UPDATE DEBUG - Setting class_id to: {class_id}")
            assignment_doc.class_id = class_id
            updated_class_id = getattr(assignment_doc, 'class_id', 'NOT_SET')
            frappe.logger().info(f"UPDATE DEBUG - After setting, class_id is: {updated_class_id}")
            debug_info['updated_class_id'] = updated_class_id

        # Check for duplicate assignment after updates
        if teacher_id or subject_id or class_id is not None:
            final_teacher_id = teacher_id or assignment_doc.teacher_id
            final_subject_id = subject_id or assignment_doc.subject_id
            final_class_id = class_id if class_id is not None else getattr(assignment_doc, 'class_id', None)

            frappe.logger().info(f"UPDATE DEBUG - Checking duplicates: teacher={final_teacher_id}, subject={final_subject_id}, class={final_class_id}")

            filters = {
                "teacher_id": final_teacher_id,
                "subject_id": final_subject_id,
                "campus_id": campus_id,
                "name": ["!=", assignment_id]
            }
            if final_class_id:
                filters["class_id"] = final_class_id
            existing = frappe.db.exists("SIS Subject Assignment", filters)
            if existing:
                frappe.logger().info(f"UPDATE DEBUG - Duplicate found: {existing}")
                return validation_error_response(
                    message="Teacher already assigned to this subject",
                    errors={"assignment": [f"This teacher is already assigned to this subject" ]}
                )

        frappe.logger().info(f"UPDATE DEBUG - Saving assignment with final values: teacher={assignment_doc.teacher_id}, subject={assignment_doc.subject_id}, class={getattr(assignment_doc, 'class_id', None)}")

        try:
            assignment_doc.save()
            frappe.db.commit()
            frappe.logger().info(f"UPDATE DEBUG - Successfully saved assignment: {assignment_doc.name}")

            # Check if class_id was actually saved
            saved_doc = frappe.get_doc("SIS Subject Assignment", assignment_doc.name)
            saved_class_id = getattr(saved_doc, 'class_id', None)
            frappe.logger().info(f"UPDATE DEBUG - After reload, saved class_id: {saved_class_id}")

            debug_info['saved_class_id'] = saved_class_id
            debug_info['save_successful'] = True

        except Exception as save_error:
            frappe.logger().error(f"UPDATE DEBUG - Error saving assignment: {str(save_error)}")
            debug_info['save_error'] = str(save_error)
            debug_info['save_successful'] = False
            raise save_error

        # Get updated data with display names
        updated_data = frappe.db.sql("""
            SELECT
                sa.name,
                sa.teacher_id,
                sa.subject_id,
                sa.class_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title as subject_title,
                c.title as class_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Subject` s ON sa.subject_id = s.name
            LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
            WHERE sa.name = %s
        """, (assignment_doc.name,), as_dict=True)

        if updated_data:
            result = updated_data[0]
            assignment_data = {
                "name": result.name,
                "teacher_id": result.teacher_id,
                "subject_id": result.subject_id,
                "class_id": result.class_id,
                "campus_id": result.campus_id,
                "teacher_name": result.teacher_name,
                "subject_title": result.subject_title,
                "class_title": result.class_title,
                "debug_info": debug_info if 'debug_info' in locals() else None
            }
            return single_item_response(assignment_data, "Subject assignment updated successfully")
        else:
            assignment_data = {
                "name": assignment_doc.name,
                "teacher_id": assignment_doc.teacher_id,
                "subject_id": assignment_doc.subject_id,
                "campus_id": assignment_doc.campus_id,
                "debug_info": debug_info if 'debug_info' in locals() else None
            }
            return single_item_response(assignment_data, "Subject assignment updated successfully")
        
    except Exception as e:
        frappe.log_error(f"Error updating subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error updating subject assignment: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def delete_subject_assignment(assignment_id=None):
    """Delete a subject assignment"""
    try:
        # Get assignment_id from multiple sources (URL path, query params, form_dict, JSON payload, or direct parameter)
        if not assignment_id:
            # Try to get from URL path first (e.g., /api/method/.../SIS-SUBJECT_ASSIGNMENT-00001)
            try:
                request_path = frappe.local.request.path if hasattr(frappe.local, 'request') else frappe.request.path
                if request_path:
                    # Extract the last part of the URL path
                    path_parts = request_path.strip('/').split('/')
                    if len(path_parts) > 0:
                        last_part = path_parts[-1]
                        # Check if it looks like an assignment ID (contains assignment identifier)
                        if 'SUBJECT_ASSIGNMENT' in last_part or last_part.startswith('SIS-'):
                            assignment_id = last_part
            except Exception:
                pass

        # Try to get from URL query parameters (for GET requests)
        if not assignment_id:
            assignment_id = frappe.request.args.get('assignment_id')

        # Try to get from form_dict
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
            return validation_error_response(
                message="Subject Assignment ID is required",
                errors={"assignment_id": ["Subject Assignment ID is required"]}
            )

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
    """Get subjects for dropdown selection.
    Optional: pass teacher_id to filter by teacher's education_stage_id.
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        filters = {"campus_id": campus_id}
        # If teacher_id provided, restrict subjects by teacher's education stage
        teacher_id = frappe.request.args.get('teacher_id') or frappe.form_dict.get('teacher_id')
        if teacher_id:
            teacher_stage = frappe.db.get_value("SIS Teacher", teacher_id, "education_stage_id")
            if teacher_stage:
                filters["education_stage"] = teacher_stage

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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_education_grades_for_teacher():
    """Get education grades for teacher selection.
    Pass teacher_id to filter by teacher's education_stage_id.
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get teacher_id from request
        teacher_id = frappe.request.args.get('teacher_id') or frappe.form_dict.get('teacher_id')
        if not teacher_id:
            return validation_error_response(
                message="Teacher ID is required",
                errors={"teacher_id": ["Teacher ID is required"]}
            )

        # Get teacher's education stage
        teacher_stage = frappe.db.get_value("SIS Teacher", teacher_id, "education_stage_id")
        if not teacher_stage:
            return list_response([], "No education grades found for this teacher")

        filters = {
            "campus_id": campus_id,
            "education_stage_id": teacher_stage
        }

        education_grades = frappe.get_all(
            "SIS Education Grade",
            fields=[
                "name",
                "title_vn as grade_name",
                "title_en",
                "grade_code",
                "education_stage_id as education_stage",
                "sort_order"
            ],
            filters=filters,
            order_by="sort_order asc, title_vn asc"
        )

        return list_response(education_grades, "Education grades fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching education grades for teacher: {str(e)}")
        return error_response(f"Error fetching education grades: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_classes_for_education_grade():
    """Get classes for education grade selection.
    Pass education_grade_id to filter classes by education_grade field.
    Also supports school_year_id for filtering.
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get education_grade_id from request
        education_grade_id = frappe.request.args.get('education_grade_id') or frappe.form_dict.get('education_grade_id')
        if not education_grade_id:
            return validation_error_response(
                message="Education grade is required",
                errors={"education_grade_id": ["Education grade is required"]}
            )

        # Get school_year_id from request (optional)
        school_year_id = frappe.request.args.get('school_year_id') or frappe.form_dict.get('school_year_id')

        filters = {
            "campus_id": campus_id,
            "education_grade": education_grade_id
        }

        # Add school year filter if provided
        if school_year_id:
            filters["school_year_id"] = school_year_id

        classes = frappe.get_all(
            "SIS Class",
            fields=[
                "name",
                "title"
            ],
            filters=filters,
            order_by="title asc"
        )

        frappe.logger().info(f"Classes for education_grade '{education_grade_id}' in campus '{campus_id}': {len(classes)} found")
        return list_response(classes, "Classes fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching classes for education grade: {str(e)}")
        return error_response(f"Error fetching classes: {str(e)}")
