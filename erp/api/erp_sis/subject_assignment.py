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
                sa.actual_subject_id,
                sa.class_id,
                sa.campus_id,
                sa.creation,
                sa.modified,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title_vn as subject_title,
                c.title as class_title,
                c.education_grade as education_grade_id,
                eg.title_vn as education_grade_name
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Actual Subject` s ON sa.actual_subject_id = s.name
            LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
            LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
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
                sa.actual_subject_id,
                sa.class_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title_vn as subject_title,
                c.title as class_title,
                c.education_grade as education_grade_id,
                eg.title_vn as education_grade_name
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Actual Subject` s ON sa.actual_subject_id = s.name
            LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
            LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            WHERE sa.name = %s AND sa.campus_id = %s
        """, (assignment_id, campus_id), as_dict=True)

        if not assignment_data or len(assignment_data) == 0:
            frappe.logger().error(f"Subject assignment not found - ID: {assignment_id}, Campus: {campus_id}")
            return not_found_response(f"Subject assignment not found or access denied - ID: {assignment_id}, Campus: {campus_id}")

        assignment = assignment_data[0]

        assignment_data = {
            "name": assignment.name,
            "teacher_id": assignment.teacher_id,
            "actual_subject_id": assignment.actual_subject_id,
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
    """Create new subject assignments.

    Supported payloads (backward compatible):
    - Single: { teacher_id, subject_id, class_id? }
    - Bulk by subjects for one class: { teacher_id, class_id, subject_ids: [subject_id, ...] }
    - Bulk by classes and subjects: { teacher_id, assignments: [ { class_id, subject_ids: [...] }, ... ] }
      Also supports: { teacher_id, classes: [class_id, ...], subject_ids: [...] } (applies same subjects to many classes)
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
        actual_subject_id = data.get("actual_subject_id")
        class_id = data.get("class_id")
        actual_subject_ids = data.get("actual_subject_ids")
        assignments = data.get("assignments") or []
        classes = data.get("classes") or []
        
        # Input validation
        if not teacher_id:
            frappe.throw(_("Teacher ID is required"))
        if not actual_subject_id and not actual_subject_ids and not assignments and not classes:
            frappe.throw(_("Actual Subject ID or actual_subject_ids or assignments is required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Normalize unified assignment list
        normalized_assignments = []

        # Case 1: explicit assignments list
        if isinstance(assignments, list) and assignments:
            for a in assignments:
                cid = a.get("class_id")
                sids = a.get("actual_subject_ids") or ([] if a.get("actual_subject_id") is None else [a.get("actual_subject_id")])
                if cid and sids:
                    normalized_assignments.append({"class_id": cid, "actual_subject_ids": sids})

        # Case 2: top-level classes + actual_subject_ids (apply same subjects to many classes)
        if not normalized_assignments and isinstance(classes, list) and classes and isinstance(actual_subject_ids, list) and actual_subject_ids:
            for cid in classes:
                normalized_assignments.append({"class_id": cid, "actual_subject_ids": actual_subject_ids})

        # Case 3: legacy single/bulk for one class
        if not normalized_assignments:
            effective_actual_subject_ids = actual_subject_ids if isinstance(actual_subject_ids, list) and actual_subject_ids else ([actual_subject_id] if actual_subject_id else [])
            normalized_assignments.append({"class_id": class_id, "actual_subject_ids": effective_actual_subject_ids})

        # Validate classes (if provided) belong to campus
        class_id_set = {na.get("class_id") for na in normalized_assignments if na.get("class_id")}
        for cid in list(class_id_set):
            if cid:
                class_exists = frappe.db.exists("SIS Class", {"name": cid, "campus_id": campus_id})
                if not class_exists:
                    return not_found_response(f"Selected class does not exist or access denied: {cid}")
        
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
        for item in normalized_assignments:
            cid = item.get("class_id")
            sids = item.get("actual_subject_ids") or []
            # Validate and create for each actual subject
            for sid in sids:
                subject_exists = frappe.db.exists(
                    "SIS Actual Subject",
                    {"name": sid, "campus_id": campus_id}
                )
                if not subject_exists:
                    return not_found_response(f"Selected actual subject does not exist or access denied: {sid}")

                filters = {
                    "teacher_id": teacher_id,
                    "actual_subject_id": sid,
                    "campus_id": campus_id,
                }
                if cid:
                    filters["class_id"] = cid
                existing = frappe.db.exists("SIS Subject Assignment", filters)
                if existing:
                    continue

                assignment_doc = frappe.get_doc({
                    "doctype": "SIS Subject Assignment",
                    "teacher_id": teacher_id,
                    "actual_subject_id": sid,
                    "class_id": cid,
                    "campus_id": campus_id
                })
                assignment_doc.insert()
                created_names.append(assignment_doc.name)
                
                # Auto-sync timetable sau khi tạo Subject Assignment
                try:
                    sync_data = {
                        "assignment_id": assignment_doc.name,
                        "old_teacher_id": None,  # Tạo mới nên không có teacher cũ
                        "new_teacher_id": teacher_id,
                        "class_id": cid,
                        "actual_subject_id": sid
                    }
                    _sync_timetable_from_date(sync_data, assignment_doc.creation)
                except Exception as sync_error:
                    frappe.log_error(f"Auto-sync timetable failed for new assignment {assignment_doc.name}: {str(sync_error)}")
                    # Không fail chính, chỉ log error

        frappe.db.commit()

        # Get created data with display names
        created_data = []
        if created_names:
            created_data = frappe.db.sql("""
                SELECT
                    sa.name,
                    sa.teacher_id,
                    sa.actual_subject_id,
                    sa.class_id,
                    sa.campus_id,
                    COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                    s.title_vn as subject_title,
                    c.title as class_title,
                    c.education_grade as education_grade_id,
                    eg.title_vn as education_grade_name
                FROM `tabSIS Subject Assignment` sa
                LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
                LEFT JOIN `tabUser` u ON t.user_id = u.name
                LEFT JOIN `tabSIS Actual Subject` s ON sa.actual_subject_id = s.name
                LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
                LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
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
                "actual_subject_id": result.actual_subject_id,
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
def update_subject_assignment(assignment_id=None, teacher_id=None, actual_subject_id=None):
    """Update an existing subject assignment"""
    try:
        frappe.logger().info(f"UPDATE DEBUG - API called with assignment_id={assignment_id}, teacher_id={teacher_id}, actual_subject_id={actual_subject_id}")

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
                    actual_subject_id = json_data.get('actual_subject_id') or actual_subject_id

                    # Try different possible field names for class_id
                    class_id = (json_data.get('class_id') or
                               json_data.get('class') or
                               json_data.get('classId') or
                               (json_data.get('data', {}).get('class_id') if json_data.get('data') else None))

                    frappe.logger().info(f"UPDATE DEBUG - Final values: assignment_id={assignment_id}, teacher_id={teacher_id}, actual_subject_id={actual_subject_id}, class_id={class_id}")
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
        if not actual_subject_id:
            actual_subject_id = frappe.form_dict.get('actual_subject_id')
        # Preserve class_id parsed from JSON; only fallback to form_dict if not already set
        if 'class_id' in frappe.form_dict and ('class_id' not in locals() or class_id is None):
            class_id = frappe.form_dict.get('class_id')

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
        frappe.logger().info(f"UPDATE DEBUG - Received data: teacher_id={teacher_id}, actual_subject_id={actual_subject_id}, class_id={class_id}")
        frappe.logger().info(f"UPDATE DEBUG - Current assignment: teacher={assignment_doc.teacher_id}, actual_subject={assignment_doc.actual_subject_id}, class={assignment_doc.class_id}")

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

        if actual_subject_id and actual_subject_id != assignment_doc.actual_subject_id:
            # Verify actual subject exists and belongs to same campus
            subject_exists = frappe.db.exists(
                "SIS Actual Subject",
                {
                    "name": actual_subject_id,
                    "campus_id": campus_id
                }
            )

            if not subject_exists:
                return not_found_response("Selected actual subject does not exist or access denied")

            assignment_doc.actual_subject_id = actual_subject_id
            frappe.logger().info(f"UPDATE DEBUG - Updated actual_subject_id to: {actual_subject_id}")
        
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
        if teacher_id or actual_subject_id or class_id is not None:
            final_teacher_id = teacher_id or assignment_doc.teacher_id
            final_actual_subject_id = actual_subject_id or assignment_doc.actual_subject_id
            final_class_id = class_id if class_id is not None else getattr(assignment_doc, 'class_id', None)

            frappe.logger().info(f"UPDATE DEBUG - Checking duplicates: teacher={final_teacher_id}, actual_subject={final_actual_subject_id}, class={final_class_id}")

            filters = {
                "teacher_id": final_teacher_id,
                "actual_subject_id": final_actual_subject_id,
                "campus_id": campus_id,
                "name": ["!=", assignment_id]
            }
            if final_class_id:
                filters["class_id"] = final_class_id
            existing = frappe.db.exists("SIS Subject Assignment", filters)
            if existing:
                frappe.logger().info(f"UPDATE DEBUG - Duplicate found: {existing}")
                return validation_error_response(
                    message="Teacher already assigned to this actual subject",
                    errors={"assignment": [f"This teacher is already assigned to this actual subject" ]}
                )

        frappe.logger().info(f"UPDATE DEBUG - Saving assignment with final values: teacher={assignment_doc.teacher_id}, actual_subject={assignment_doc.actual_subject_id}, class={getattr(assignment_doc, 'class_id', None)}")

        try:
            # Store old teacher for bulk timetable update
            old_teacher_id = frappe.db.get_value("SIS Subject Assignment", assignment_id, "teacher_id")
            
            assignment_doc.save()
            frappe.db.commit()
            frappe.logger().info(f"UPDATE DEBUG - Successfully saved assignment: {assignment_doc.name}")

            # Check if class_id was actually saved
            saved_doc = frappe.get_doc("SIS Subject Assignment", assignment_doc.name)
            saved_class_id = getattr(saved_doc, 'class_id', None)
            frappe.logger().info(f"UPDATE DEBUG - After reload, saved class_id: {saved_class_id}")

            debug_info['saved_class_id'] = saved_class_id
            debug_info['save_successful'] = True
            
            # Auto-sync timetable sau khi update Subject Assignment (luôn chạy, không chỉ khi teacher thay đổi)
            try:
                sync_data = {
                    "assignment_id": assignment_doc.name,
                    "old_teacher_id": old_teacher_id,
                    "new_teacher_id": teacher_id or assignment_doc.teacher_id,
                    "class_id": assignment_doc.class_id,
                    "actual_subject_id": assignment_doc.actual_subject_id
                }
                
                # Sync từ ngày modified của assignment
                sync_result = _sync_timetable_from_date(sync_data, assignment_doc.modified)
                debug_info['sync_result'] = sync_result.get('summary', {}) if sync_result else {}
                
            except Exception as sync_error:
                frappe.log_error(f"Auto-sync timetable failed for updated assignment {assignment_id}: {str(sync_error)}")
                debug_info['sync_error'] = str(sync_error)
                # Don't fail the main update if sync fails

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
                sa.actual_subject_id,
                sa.class_id,
                sa.campus_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                s.title_vn as subject_title,
                c.title as class_title
            FROM `tabSIS Subject Assignment` sa
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            LEFT JOIN `tabSIS Actual Subject` s ON sa.actual_subject_id = s.name
            LEFT JOIN `tabSIS Class` c ON sa.class_id = c.name
            WHERE sa.name = %s
        """, (assignment_doc.name,), as_dict=True)

        if updated_data:
            result = updated_data[0]
            assignment_data = {
                "name": result.name,
                "teacher_id": result.teacher_id,
                "actual_subject_id": result.actual_subject_id,
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
                "actual_subject_id": assignment_doc.actual_subject_id,
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
        
        # Enrich with user full_name for display
        for teacher in teachers:
            if teacher.get("user_id"):
                try:
                    user_doc = frappe.get_cached_doc("User", teacher["user_id"])
                    teacher["full_name"] = user_doc.get("full_name") or user_doc.get("first_name") or teacher["user_id"]
                    teacher["email"] = user_doc.get("email")
                except Exception:
                    teacher["full_name"] = teacher["user_id"]
                    teacher["email"] = teacher["user_id"]
            else:
                teacher["full_name"] = teacher["user_id"]
        
        return list_response(teachers, "Teachers fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching teachers for assignment: {str(e)}")
        return error_response(f"Error fetching teachers: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subjects_for_assignment():
    """Get actual subjects for dropdown selection.
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
                filters["education_stage_id"] = teacher_stage

        subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=[
                "name",
                "title_vn as title"
            ],
            filters=filters,
            order_by="title_vn asc"
        )

        return list_response(subjects, "Actual subjects fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching actual subjects for assignment: {str(e)}")
        return error_response(f"Error fetching actual subjects: {str(e)}")


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


@frappe.whitelist(allow_guest=False, methods=["GET"]) 
def get_my_subjects_for_class(class_id: str | None = None):
    """Return subject_ids that the current logged-in teacher is assigned to for a given class.
    If class_id is None, returns all subject_ids for the teacher across campus (deduped).
    """
    try:
        campus_id = get_current_campus_from_context() or "campus-1"

        # Resolve class_id from query if not passed
        if not class_id:
            class_id = frappe.request.args.get('class_id') or frappe.form_dict.get('class_id')

        # Find teacher by current user and campus
        teacher_rows = frappe.get_all(
            "SIS Teacher", fields=["name"], filters={"user_id": frappe.session.user, "campus_id": campus_id}, limit=1
        )
        if not teacher_rows:
            return list_response([], "No teacher profile for current user")
        teacher_id = teacher_rows[0].name

        filters = {"teacher_id": teacher_id, "campus_id": campus_id}
        if class_id:
            filters["class_id"] = class_id

        rows = frappe.get_all(
            "SIS Subject Assignment",
            fields=["actual_subject_id"],
            filters=filters,
            distinct=True,
        )
        actual_subject_ids = [r["actual_subject_id"] for r in rows if r.get("actual_subject_id")]
        return list_response(actual_subject_ids, "Assigned actual subjects fetched")
    except Exception as e:
        frappe.log_error(f"Error get_my_subjects_for_class: {str(e)}")
        return error_response("Error fetching assigned subjects")


def _bulk_update_timetable_internal(data):
    """Internal function for bulk updating timetable instances.
    Returns dict with results, not API response.
    """
    campus_id = get_current_campus_from_context() or "campus-1"
    
    assignment_id = data.get("assignment_id")
    old_teacher_id = data.get("old_teacher_id") 
    new_teacher_id = data.get("new_teacher_id")
    class_id = data.get("class_id")
    actual_subject_id = data.get("actual_subject_id")
    
    # Find all future timetable instances that need updating
    today = frappe.utils.today()
    
    # Build filters for instances
    instance_filters = {
        "campus_id": campus_id,
        "start_date": [">=", today]  # Only future instances
    }
    
    if class_id:
        instance_filters["class_id"] = class_id
        
    # Get instances to update
    instances = frappe.get_all(
        "SIS Timetable Instance", 
        fields=["name", "class_id", "start_date", "end_date"],
        filters=instance_filters
    )
    
    if not instances:
        return {
            "updated_rows": [],
            "skipped_rows": [],
            "summary": {
                "instances_checked": 0,
                "rows_updated": 0,
                "rows_skipped": 0
            }
        }
        
    updated_rows = []
    skipped_rows = []
    
    # For each instance, find rows with the old actual subject and update teachers
    for instance in instances:
        try:
            # Get rows that match the actual subject (via SIS Subject)
            # First find SIS Subjects that link to this actual_subject_id
            subject_ids = frappe.get_all(
                "SIS Subject",
                fields=["name"],
                filters={
                    "actual_subject_id": actual_subject_id,
                    "campus_id": campus_id
                }
            )
            
            if not subject_ids:
                continue
                
            subject_id_list = [s.name for s in subject_ids]
            
            # Find instance rows with these subjects
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "subject_id", "teacher_1_id", "teacher_2_id", "day_of_week", "timetable_column_id"],
                filters={
                    "parent": instance.name,
                    "subject_id": ["in", subject_id_list]
                }
            )
            
            for row in rows:
                try:
                    # Check if this row has the old teacher
                    has_old_teacher = (
                        (old_teacher_id and (row.get("teacher_1_id") == old_teacher_id or row.get("teacher_2_id") == old_teacher_id)) or
                        not old_teacher_id  # If no old teacher specified, update all rows with this subject
                    )
                    
                    if not has_old_teacher:
                        skipped_rows.append({
                            "row_id": row.name,
                            "reason": "Teacher not matching",
                            "instance_id": instance.name
                        })
                        continue
                        
                    # Update the row
                    row_doc = frappe.get_doc("SIS Timetable Instance Row", row.name)
                    
                    # Replace old teacher with new teacher
                    updated_fields = []
                    if old_teacher_id:
                        # Replace specific old teacher
                        if row_doc.teacher_1_id == old_teacher_id:
                            row_doc.teacher_1_id = new_teacher_id
                            updated_fields.append("teacher_1_id")
                        if row_doc.teacher_2_id == old_teacher_id:
                            row_doc.teacher_2_id = new_teacher_id  
                            updated_fields.append("teacher_2_id")
                    else:
                        # No old teacher specified, assign new teacher to teacher_1_id
                        row_doc.teacher_1_id = new_teacher_id
                        updated_fields.append("teacher_1_id")
                        
                    if updated_fields:
                        row_doc.save()
                        updated_rows.append({
                            "row_id": row.name,
                            "instance_id": instance.name,
                            "class_id": instance.class_id,
                            "updated_fields": updated_fields,
                            "day_of_week": row_doc.day_of_week,
                            "timetable_column_id": row_doc.timetable_column_id
                        })
                    
                except Exception as row_error:
                    frappe.log_error(f"Error updating row {row.name}: {str(row_error)}")
                    skipped_rows.append({
                        "row_id": row.name,
                        "reason": f"Error: {str(row_error)}",
                        "instance_id": instance.name
                    })
                    continue
                    
        except Exception as instance_error:
            frappe.log_error(f"Error processing instance {instance.name}: {str(instance_error)}")
            continue
    
    return {
        "updated_rows": updated_rows,
        "skipped_rows": skipped_rows,
        "summary": {
            "instances_checked": len(instances),
            "rows_updated": len(updated_rows),
            "rows_skipped": len(skipped_rows)
        }
    }


@frappe.whitelist(allow_guest=False, methods=["POST"])
def bulk_update_timetable_from_assignment():
    """Bulk update timetable instances when Subject Assignment changes.
    Updates all future timetable instances from current date forward.
    """
    try:
        # Get current user's campus
        campus_id = get_current_campus_from_context() or "campus-1"
        
        # Get data from request
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
            
        assignment_id = data.get("assignment_id")
        old_teacher_id = data.get("old_teacher_id") 
        new_teacher_id = data.get("new_teacher_id")
        class_id = data.get("class_id")
        actual_subject_id = data.get("actual_subject_id")
        
        if not assignment_id:
            return validation_error_response("Validation failed", {"assignment_id": ["Assignment ID is required"]})
            
        if not new_teacher_id:
            return validation_error_response("Validation failed", {"new_teacher_id": ["New teacher ID is required"]})
        
        # Get assignment details
        try:
            assignment = frappe.get_doc("SIS Subject Assignment", assignment_id)
            if assignment.campus_id != campus_id:
                return forbidden_response("Access denied")
        except frappe.DoesNotExistError:
            return not_found_response("Subject assignment not found")
            
        # Use actual_subject_id from assignment if not provided
        if not actual_subject_id:
            actual_subject_id = assignment.actual_subject_id
            
        if not class_id:
            class_id = assignment.class_id
            
        # Update data with assignment details
        data.update({
            "actual_subject_id": actual_subject_id,
            "class_id": class_id
        })
        
        # Call internal function
        result = _bulk_update_timetable_internal(data)
        
        frappe.db.commit()
        
        return success_response(
            data=result,
            message=f"Bulk update completed: {result['summary']['rows_updated']} rows updated in {result['summary']['instances_checked']} future instances"
        )
        
    except Exception as e:
        frappe.log_error(f"Error in bulk_update_timetable_from_assignment: {str(e)}")
        return error_response(f"Error updating timetables: {str(e)}")


def _sync_timetable_from_date(data: dict, from_date):
    """
    Sync timetable instances từ một ngày cụ thể.
    Dùng cho auto-sync khi Subject Assignment được tạo/cập nhật.
    """
    campus_id = get_current_campus_from_context() or "campus-1"
    
    assignment_id = data.get("assignment_id")
    old_teacher_id = data.get("old_teacher_id")  # Có thể None khi tạo mới
    new_teacher_id = data.get("new_teacher_id")
    class_id = data.get("class_id")
    actual_subject_id = data.get("actual_subject_id")
    
    # Convert from_date to string if it's datetime
    if hasattr(from_date, 'date'):
        sync_from_date = from_date.date()
    elif hasattr(from_date, 'strftime'):
        sync_from_date = from_date.strftime('%Y-%m-%d')
    else:
        sync_from_date = str(from_date).split(' ')[0]  # Take date part if datetime string
    
    # Find timetable instances từ ngày sync trở đi
    instance_filters = {
        "campus_id": campus_id,
        "start_date": [">=", sync_from_date]
    }
    
    if class_id:
        instance_filters["class_id"] = class_id
        
    instances = frappe.get_all(
        "SIS Timetable Instance", 
        fields=["name", "class_id", "start_date", "end_date"],
        filters=instance_filters
    )
    
    if not instances:
        return {
            "updated_rows": [],
            "skipped_rows": [],
            "summary": {
                "instances_checked": 0,
                "rows_updated": 0,
                "rows_skipped": 0,
                "sync_from_date": sync_from_date
            }
        }
        
    updated_rows = []
    skipped_rows = []
    
    for instance in instances:
        try:
            # Find SIS Subjects that link to this actual_subject_id
            subject_ids = frappe.get_all(
                "SIS Subject",
                fields=["name"],
                filters={
                    "actual_subject_id": actual_subject_id,
                    "campus_id": campus_id
                }
            )
            
            # Also try to find by title matching if direct mapping fails
            if not subject_ids and actual_subject_id:
                try:
                    actual_subject = frappe.get_doc("SIS Actual Subject", actual_subject_id)
                    subject_ids = frappe.get_all(
                        "SIS Subject",
                        fields=["name"],
                        filters={
                            "title": actual_subject.title_vn,
                            "campus_id": campus_id
                        }
                    )
                    # Update found subjects to have proper actual_subject_id link
                    for subj in subject_ids:
                        frappe.db.set_value("SIS Subject", subj.name, "actual_subject_id", actual_subject_id)
                except Exception:
                    pass
            
            if not subject_ids:
                continue
                
            subject_id_list = [s.name for s in subject_ids]
            
            # Find instance rows với các subjects này
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "subject_id", "teacher_1_id", "teacher_2_id", "day_of_week", "timetable_column_id"],
                filters={
                    "parent": instance.name,
                    "subject_id": ["in", subject_id_list]
                }
            )
            
            for row in rows:
                try:
                    # Determine if this row should be updated
                    should_update = False
                    
                    if old_teacher_id:
                        # UPDATE case: check if row has old teacher
                        should_update = (row.get("teacher_1_id") == old_teacher_id or row.get("teacher_2_id") == old_teacher_id)
                    else:
                        # CREATE case: update rows that don't have teacher assigned yet
                        should_update = not row.get("teacher_1_id") and not row.get("teacher_2_id")
                    
                    if not should_update:
                        skipped_rows.append({
                            "row_id": row.name,
                            "reason": "Teacher not matching or already assigned",
                            "instance_id": instance.name
                        })
                        continue
                        
                    # Update the row
                    row_doc = frappe.get_doc("SIS Timetable Instance Row", row.name)
                    updated_fields = []
                    
                    if old_teacher_id:
                        # Replace old teacher with new teacher
                        if row_doc.teacher_1_id == old_teacher_id:
                            row_doc.teacher_1_id = new_teacher_id
                            updated_fields.append("teacher_1_id")
                        if row_doc.teacher_2_id == old_teacher_id:
                            row_doc.teacher_2_id = new_teacher_id
                            updated_fields.append("teacher_2_id")
                    else:
                        # No old teacher (CREATE case), assign new teacher to teacher_1_id
                        row_doc.teacher_1_id = new_teacher_id
                        updated_fields.append("teacher_1_id")
                    
                    if updated_fields:
                        row_doc.save(ignore_permissions=True)
                        updated_rows.append({
                            "row_id": row.name,
                            "updated_fields": updated_fields,
                            "instance_id": instance.name,
                            "day_of_week": row.get("day_of_week"),
                            "period": row.get("timetable_column_id")
                        })
                        
                except Exception as row_error:
                    skipped_rows.append({
                        "row_id": row.name,
                        "reason": f"Update error: {str(row_error)}",
                        "instance_id": instance.name
                    })
                    continue
                    
        except Exception as instance_error:
            continue
    
    frappe.db.commit()
    
    return {
        "updated_rows": updated_rows,
        "skipped_rows": skipped_rows,
        "summary": {
            "instances_checked": len(instances),
            "rows_updated": len(updated_rows),
            "rows_skipped": len(skipped_rows),
            "sync_from_date": sync_from_date
        }
    }
