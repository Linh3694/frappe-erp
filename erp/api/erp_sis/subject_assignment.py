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
        
        # Enrich with teacher's education stages
        for assignment in subject_assignments_data:
            if assignment.get('teacher_id'):
                try:
                    # Get education stages for this teacher
                    teacher_stages = frappe.get_all(
                        "SIS Teacher Education Stage",
                        filters={
                            "teacher_id": assignment['teacher_id'],
                            "is_active": 1
                        },
                        fields=["education_stage_id"],
                        order_by="creation asc"
                    )
                    
                    # Create a display string for education stages
                    if teacher_stages:
                        stage_names = []
                        for stage in teacher_stages:
                            stage_name = frappe.db.get_value("SIS Education Stage", stage.education_stage_id, "title_vn")
                            if stage_name:
                                stage_names.append(stage_name)
                        assignment["teacher_education_stages_display"] = ", ".join(stage_names) if stage_names else ""
                    else:
                        assignment["teacher_education_stages_display"] = ""
                        
                except Exception as e:
                    frappe.logger().warning(f"Error fetching education stages for teacher {assignment['teacher_id']}: {str(e)}")
                    assignment["teacher_education_stages_display"] = ""
            else:
                assignment["teacher_education_stages_display"] = ""
        
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
        
        # Log received data for debugging [[memory:7723612]]
        frappe.logger().info(f"CREATE DEBUG - Received data: {data}")
        
        # Extract values from data
        teacher_id = data.get("teacher_id")
        actual_subject_id = data.get("actual_subject_id")
        class_id = data.get("class_id")
        actual_subject_ids = data.get("actual_subject_ids")
        assignments = data.get("assignments") or []
        classes = data.get("classes") or []
        
        frappe.logger().info(f"CREATE DEBUG - Parsed values: teacher_id={teacher_id}, assignments={len(assignments)}")
        
        # Input validation
        if not teacher_id:
            frappe.logger().error("CREATE DEBUG - Missing teacher_id")
            frappe.throw(_("Teacher ID is required"))
        if not actual_subject_id and not actual_subject_ids and not assignments and not classes:
            frappe.logger().error(f"CREATE DEBUG - Missing required fields: actual_subject_id={actual_subject_id}, actual_subject_ids={actual_subject_ids}, assignments={assignments}, classes={classes}")
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
            for i, a in enumerate(assignments):
                cid = a.get("class_id")
                sids = a.get("actual_subject_ids") or ([] if a.get("actual_subject_id") is None else [a.get("actual_subject_id")])
                frappe.logger().info(f"CREATE DEBUG - Assignment {i}: class_id={cid}, actual_subject_ids={sids}")
                if cid and sids:
                    normalized_assignments.append({"class_id": cid, "actual_subject_ids": sids})
                else:
                    frappe.logger().warning(f"CREATE DEBUG - Skipping invalid assignment {i}: class_id={cid}, actual_subject_ids={sids}")

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
        assignments_with_sync = []
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
                    frappe.logger().error(f"CREATE DEBUG - Actual subject not found: {sid} for campus: {campus_id}")
                    # Instead of hard fail, let's check if it's a SIS Subject ID by mistake
                    sis_subject_exists = frappe.db.exists("SIS Subject", {"name": sid, "campus_id": campus_id})
                    if sis_subject_exists:
                        frappe.logger().warning(f"CREATE DEBUG - Found SIS Subject with ID {sid}, but expected Actual Subject ID")
                        # Try to get actual_subject_id from SIS Subject
                        actual_subject_id = frappe.db.get_value("SIS Subject", sid, "actual_subject_id")
                        if actual_subject_id:
                            frappe.logger().info(f"CREATE DEBUG - Using actual_subject_id {actual_subject_id} from SIS Subject {sid}")
                            sid = actual_subject_id  # Replace with correct actual_subject_id
                        else:
                            return validation_error_response(f"SIS Subject {sid} does not have a linked Actual Subject", {"actual_subject_id": [f"Subject {sid} is not properly linked to an Actual Subject"]})
                    else:
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
                    sync_result = _sync_timetable_from_date(sync_data, assignment_doc.creation)
                    # Store sync result for later inclusion in response
                    assignments_with_sync.append({
                        "assignment_id": assignment_doc.name,
                        "sync_result": sync_result
                    })
                    
                    # Log sync result [[memory:7723612]]
                    frappe.logger().info(f"CREATE DEBUG - Auto-sync completed for new assignment {assignment_doc.name}: {sync_result.get('summary', {})}")
                except Exception as sync_error:
                    frappe.log_error(f"Auto-sync timetable failed for new assignment {assignment_doc.name}: {str(sync_error)}")
                    assignments_with_sync.append({
                        "assignment_id": assignment_doc.name,
                        "sync_error": str(sync_error)
                    })
                    # Không fail chính, chỉ log error

        frappe.db.commit()

        # Auto-fix any existing SIS Subjects that don't have actual_subject_id linkage
        try:
            _fix_subject_linkages(campus_id)
        except Exception as fix_error:
            frappe.logger().warning(f"Subject linkage fix failed: {str(fix_error)}")

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
            # Find sync result for this assignment
            sync_info = next((item for item in assignments_with_sync if item["assignment_id"] == result.name), {})
            return single_item_response({
                "name": result.name,
                "teacher_id": result.teacher_id,
                "actual_subject_id": result.actual_subject_id,
                "class_id": result.class_id,
                "campus_id": result.campus_id,
                "teacher_name": result.teacher_name,
                "subject_title": result.subject_title,
                "class_title": result.class_title,
                "timetable_sync": sync_info
            }, f"Subject assignment created successfully. Timetable sync: {sync_info.get('sync_result', {}).get('summary', {}).get('rows_updated', 0)} rows updated")
        else:
            return list_response({
                "assignments": created_data,
                "timetable_sync_results": assignments_with_sync
            }, f"Subject assignments created successfully. {len(assignments_with_sync)} assignments processed for timetable sync")
        
    except Exception as e:
        # Check if any assignments were actually created before the error
        if created_names:
            # Assignments were created successfully, but something else failed (likely timetable sync)
            # Don't throw error, just log warning and return success with the created assignments
            frappe.log_error(f"Subject assignments created successfully but post-processing failed: {str(e)}")
            
            # Get created data with display names (same logic as success case)
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
            
            # Return success response with warning about post-processing
            frappe.msgprint(_("Subject assignment created successfully"))
            if created_data and len(created_data) == 1:
                return single_item_response({
                    "name": created_data[0].name,
                    "teacher_id": created_data[0].teacher_id,
                    "actual_subject_id": created_data[0].actual_subject_id,
                    "class_id": created_data[0].class_id,
                    "campus_id": created_data[0].campus_id,
                    "teacher_name": created_data[0].teacher_name,
                    "subject_title": created_data[0].subject_title,
                    "class_title": created_data[0].class_title,
                    "post_processing_warning": str(e)
                }, f"Subject assignment created successfully. Warning: {str(e)}")
            else:
                return list_response({
                    "assignments": created_data,
                    "timetable_sync_results": assignments_with_sync,
                    "post_processing_warning": str(e)
                }, f"Subject assignments created successfully. Warning: {str(e)}")
        else:
            # No assignments were created, this is a real error
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
                debug_info['sync_result'] = sync_result  # Store full sync result
                
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
            sync_summary = ""
            if 'sync_result' in debug_info:
                sync_info = debug_info['sync_result']
                if isinstance(sync_info, dict) and 'summary' in sync_info:
                    rows_updated = sync_info['summary'].get('rows_updated', 0)
                    sync_summary = f" Timetable sync: {rows_updated} rows updated"
                
            assignment_data = {
                "name": result.name,
                "teacher_id": result.teacher_id,
                "actual_subject_id": result.actual_subject_id,
                "class_id": result.class_id,
                "campus_id": result.campus_id,
                "teacher_name": result.teacher_name,
                "subject_title": result.subject_title,
                "class_title": result.class_title,
                "timetable_sync": debug_info.get('sync_result', {}),
                "debug_info": debug_info if 'debug_info' in locals() else None
            }
            return single_item_response(assignment_data, f"Subject assignment updated successfully.{sync_summary}")
        else:
            sync_summary = ""
            if 'sync_result' in debug_info:
                sync_info = debug_info['sync_result']
                if isinstance(sync_info, dict) and 'summary' in sync_info:
                    rows_updated = sync_info['summary'].get('rows_updated', 0)
                    sync_summary = f" Timetable sync: {rows_updated} rows updated"
            
            assignment_data = {
                "name": assignment_doc.name,
                "teacher_id": assignment_doc.teacher_id,
                "actual_subject_id": assignment_doc.actual_subject_id,
                "campus_id": assignment_doc.campus_id,
                "timetable_sync": debug_info.get('sync_result', {}),
                "debug_info": debug_info if 'debug_info' in locals() else None
            }
            return single_item_response(assignment_data, f"Subject assignment updated successfully.{sync_summary}")
        
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
        
        # Enrich with user full_name and education stages for display
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
            
            # Fetch multiple education stages from mapping table
            try:
                education_stages = frappe.get_all(
                    "SIS Teacher Education Stage",
                    filters={
                        "teacher_id": teacher["name"],
                        "is_active": 1
                    },
                    fields=["education_stage_id"],
                    order_by="creation asc"
                )
                teacher["education_stages"] = education_stages
                
                # Create a display string for education stages
                if education_stages:
                    stage_names = []
                    for stage in education_stages:
                        stage_name = frappe.db.get_value("SIS Education Stage", stage.education_stage_id, "title_vn")
                        if stage_name:
                            stage_names.append(stage_name)
                    teacher["education_stages_display"] = ", ".join(stage_names) if stage_names else ""
                else:
                    teacher["education_stages_display"] = ""
                    
            except Exception as e:
                frappe.logger().warning(f"Error fetching education stages for teacher {teacher['name']}: {str(e)}")
                teacher["education_stages"] = []
                teacher["education_stages_display"] = ""
        
        return list_response(teachers, "Teachers fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching teachers for assignment: {str(e)}")
        return error_response(f"Error fetching teachers: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subjects_for_assignment():
    """Get actual subjects for dropdown selection.
    Optional: pass teacher_id to filter by teacher's education stages (supports multiple stages).
    Falls back to single education_stage_id for backward compatibility.
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        filters = {"campus_id": campus_id}
        # If teacher_id provided, restrict subjects by teacher's education stages
        teacher_id = frappe.request.args.get('teacher_id') or frappe.form_dict.get('teacher_id')
        if teacher_id:
            # Get all education stages for this teacher from mapping table
            teacher_stages = frappe.get_all(
                "SIS Teacher Education Stage",
                filters={
                    "teacher_id": teacher_id,
                    "is_active": 1
                },
                fields=["education_stage_id"]
            )
            
            # If teacher has assigned stages, filter subjects by those stages
            if teacher_stages:
                stage_ids = [stage.education_stage_id for stage in teacher_stages]
                filters["education_stage_id"] = ["in", stage_ids]
            else:
                # Fallback to single education_stage_id for backward compatibility
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
    Pass teacher_id to filter by teacher's education stages (supports multiple stages).
    Falls back to single education_stage_id for backward compatibility.
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

        # Get teacher's education stages from mapping table
        teacher_stages = frappe.get_all(
            "SIS Teacher Education Stage",
            filters={
                "teacher_id": teacher_id,
                "is_active": 1
            },
            fields=["education_stage_id"]
        )
        
        filters = {"campus_id": campus_id}
        
        if teacher_stages:
            # Use multiple education stages
            stage_ids = [stage.education_stage_id for stage in teacher_stages]
            filters["education_stage_id"] = ["in", stage_ids]
        else:
            # Fallback to single education_stage_id for backward compatibility
            teacher_stage = frappe.db.get_value("SIS Teacher", teacher_id, "education_stage_id")
            if not teacher_stage:
                return list_response([], "No education grades found for this teacher")
            filters["education_stage_id"] = teacher_stage

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
def get_classes_for_teacher():
    """Get classes for teacher selection based on teacher's education stages.
    Pass teacher_id and school_year_id to filter classes by teacher's education stages.
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get parameters
        teacher_id = frappe.request.args.get('teacher_id') or frappe.form_dict.get('teacher_id')
        school_year_id = frappe.request.args.get('school_year_id') or frappe.form_dict.get('school_year_id')
        
        if not teacher_id:
            return validation_error_response(
                message="Teacher ID is required",
                errors={"teacher_id": ["Teacher ID is required"]}
            )
            
        if not school_year_id:
            return validation_error_response(
                message="School Year ID is required", 
                errors={"school_year_id": ["School Year ID is required"]}
            )

        # Get teacher's education stages from mapping table
        teacher_stages = frappe.get_all(
            "SIS Teacher Education Stage",
            filters={
                "teacher_id": teacher_id,
                "is_active": 1
            },
            fields=["education_stage_id"]
        )
        
        # Get education grades that belong to teacher's education stages
        grade_filters = {"campus_id": campus_id}
        
        if teacher_stages:
            # Use multiple education stages
            stage_ids = [stage.education_stage_id for stage in teacher_stages]
            grade_filters["education_stage_id"] = ["in", stage_ids]
        else:
            # Fallback to single education_stage_id for backward compatibility
            teacher_stage = frappe.db.get_value("SIS Teacher", teacher_id, "education_stage_id")
            if not teacher_stage:
                return list_response([], "No classes found for this teacher")
            grade_filters["education_stage_id"] = teacher_stage

        # Get education grades for teacher's stages
        education_grades = frappe.get_all(
            "SIS Education Grade",
            fields=["name"],
            filters=grade_filters
        )
        
        if not education_grades:
            return list_response([], "No education grades found for teacher's stages")
        
        # Get grade IDs
        grade_ids = [grade.name for grade in education_grades]
        
        # Get classes filtered by education grades and school year
        class_filters = {
            "campus_id": campus_id,
            "school_year_id": school_year_id,
            "education_grade": ["in", grade_ids]
        }
        
        classes = frappe.get_all(
            "SIS Class",
            fields=[
                "name",
                "title",
                "education_grade",
                "school_year_id"
            ],
            filters=class_filters,
            order_by="title asc"
        )

        return list_response(classes, "Classes fetched successfully for teacher")
        
    except Exception as e:
        frappe.log_error(f"Error fetching classes for teacher: {str(e)}")
        return error_response(f"Error fetching classes for teacher: {str(e)}")


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


def _fix_subject_linkages(campus_id: str):
    """Fix SIS Subjects that don't have actual_subject_id linkages"""
    try:
        # Find SIS Subjects without actual_subject_id
        unlinked_subjects = frappe.get_all(
            "SIS Subject",
            fields=["name", "title"],
            filters={
                "campus_id": campus_id,
                "actual_subject_id": ["is", "not set"]
            }
        )
        
        fixed_count = 0
        for subj in unlinked_subjects:
            # Try to find matching Actual Subject
            title_to_match = subj.get("title")
            if not title_to_match:
                continue
                
            actual_subjects = frappe.get_all(
                "SIS Actual Subject",
                fields=["name"],
                filters={
                    "title_vn": title_to_match,
                    "campus_id": campus_id
                }
            )
            
            if actual_subjects:
                try:
                    frappe.db.set_value("SIS Subject", subj.name, "actual_subject_id", actual_subjects[0].name)
                    fixed_count += 1
                except Exception:
                    continue
        
        if fixed_count > 0:
            frappe.db.commit()
            frappe.logger().info(f"SUBJECT LINKAGE FIX - Fixed {fixed_count} SIS Subjects with actual_subject_id linkages")
            
    except Exception as e:
        frappe.logger().error(f"Error fixing subject linkages: {str(e)}")


def _sync_timetable_from_date(data: dict, from_date):
    """
    PRIORITY 2: Sync timetable instances when Subject Assignment created/updated.
    
    Rules:
    - Only sync Timetable Instance Rows (not overrides)
    - Sync from assignment date until end of active instances
    - Update teacher assignments based on new Subject Assignment
    """
    campus_id = get_current_campus_from_context() or "campus-1"
    
    assignment_id = data.get("assignment_id")
    old_teacher_id = data.get("old_teacher_id")  # Có thể None khi tạo mới
    new_teacher_id = data.get("new_teacher_id")
    class_id = data.get("class_id")
    actual_subject_id = data.get("actual_subject_id")
    
    sync_debug = {
        "assignment_id": assignment_id,
        "actual_subject_id": actual_subject_id,
        "new_teacher_id": new_teacher_id,
        "old_teacher_id": old_teacher_id,
        "campus_id": campus_id,
        "sync_from_date": None,
        "found_subjects": [],
        "processed_instances": []
    }
    
    # Convert from_date to string if it's datetime
    if hasattr(from_date, 'date'):
        sync_from_date = from_date.date()
    elif hasattr(from_date, 'strftime'):
        sync_from_date = from_date.strftime('%Y-%m-%d')
    else:
        sync_from_date = str(from_date).split(' ')[0]  # Take date part if datetime string
    
    sync_debug["sync_from_date"] = str(sync_from_date)
    
    # Find active or future timetable instances (not just future start dates)
    instance_filters = {
        "campus_id": campus_id,
    }
    
    if class_id:
        instance_filters["class_id"] = class_id
    
    # Get all instances and filter by date logic in Python (more flexible)
    all_instances = frappe.get_all(
        "SIS Timetable Instance", 
        fields=["name", "class_id", "start_date", "end_date", "creation", "modified"],
        filters=instance_filters
    )
    
    # PRIORITY 2: Filter instances that need sync from assignment date
    today = frappe.utils.getdate()
    sync_date = frappe.utils.getdate(sync_from_date) if isinstance(sync_from_date, str) else sync_from_date
    instances = []
    
    for instance in all_instances:
        instance_start = instance.get("start_date") 
        instance_end = instance.get("end_date")
        
        # PRIORITY 2: Include instance if it's active during/after sync period
        include_instance = False
        
        if not instance_start or not instance_end:
            # Legacy instances without proper dates - include them
            include_instance = True
            sync_debug.setdefault("legacy_instances", []).append(instance.name)
            frappe.logger().info(f"SYNC PRIORITY 2 - Including legacy instance {instance.name} (no dates)")
        elif instance_end >= sync_date:
            # Instance is still active on/after sync date
            include_instance = True  
            sync_debug.setdefault("active_instances", []).append(instance.name)
            frappe.logger().info(f"SYNC PRIORITY 2 - Including active instance {instance.name} (end: {instance_end}, sync: {sync_date})")
        else:
            # Instance ended before sync date - skip
            frappe.logger().info(f"SYNC PRIORITY 2 - Skipping expired instance {instance.name} (ended: {instance_end}, sync: {sync_date})")
            
        if include_instance:
            instances.append(instance)
    
    frappe.logger().info(f"SYNC DEBUG - Found {len(instances)} relevant instances out of {len(all_instances)} total for campus {campus_id}, class {class_id}")
    
    sync_debug["found_instances"] = len(instances)
    
    if not instances:
        sync_debug["message"] = f"No timetable instances found from date {sync_from_date} onwards"
        frappe.logger().info(f"SYNC DEBUG - No instances found to sync: {sync_debug}")
        return {
            "updated_rows": [],
            "skipped_rows": [],
            "sync_debug": sync_debug,
            "summary": {
                "instances_checked": 0,
                "rows_updated": 0,
                "rows_skipped": 0,
                "sync_from_date": sync_from_date
            },
            "logs": [f"Không tìm thấy thời khóa biểu nào để đồng bộ từ ngày {sync_from_date} trở đi"]
        }
        
    updated_rows = []
    skipped_rows = []
    
    for instance in instances:
        instance_debug = {
            "instance_id": instance.name,
            "class_id": instance.get("class_id"),
            "found_subjects": 0,
            "found_rows": 0,
            "updated_rows": 0,
            "skipped_rows": 0,
            "method": "direct"
        }
        
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
            
            instance_debug["found_subjects"] = len(subject_ids)
            
            # Also try to find by title matching if direct mapping fails
            if not subject_ids and actual_subject_id:
                try:
                    actual_subject = frappe.get_doc("SIS Actual Subject", actual_subject_id)
                    instance_debug["method"] = "title_match"
                    instance_debug["title_vn"] = actual_subject.title_vn
                    
                    # Try to find matching subjects by title
                    subject_ids = frappe.get_all(
                        "SIS Subject",
                        fields=["name"],
                        filters={
                            "title": actual_subject.title_vn,
                            "campus_id": campus_id
                        }
                    )
                    
                    instance_debug["found_subjects"] = len(subject_ids)
                    instance_debug["title_matched"] = actual_subject.title_vn
                    
                    # Update found subjects to have proper actual_subject_id link
                    updated_count = 0
                    for subj in subject_ids:
                        try:
                            frappe.db.set_value("SIS Subject", subj.name, "actual_subject_id", actual_subject_id)
                            updated_count += 1
                        except Exception as update_error:
                            instance_debug[f"update_error_{subj.name}"] = str(update_error)
                    
                    instance_debug["subjects_updated"] = updated_count
                    if updated_count > 0:
                        frappe.db.commit()
                        frappe.logger().info(f"SYNC DEBUG - Updated {updated_count} SIS Subjects with actual_subject_id: {actual_subject_id}")
                        
                except Exception as e:
                    instance_debug["title_match_error"] = str(e)
                    frappe.logger().error(f"SYNC DEBUG - Title matching failed for actual_subject_id {actual_subject_id}: {str(e)}")
                    pass
            
            if not subject_ids:
                instance_debug["skip_reason"] = "No SIS Subjects found"
                sync_debug["processed_instances"].append(instance_debug)
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
            
            frappe.logger().info(f"SYNC DEBUG - Instance {instance.name}: Looking for rows with subject_ids {subject_id_list}, found {len(rows)} rows")
            
            instance_debug["found_rows"] = len(rows)
            instance_debug["subject_ids"] = subject_id_list
            
            for row in rows:
                try:
                    # Determine if this row should be updated
                    should_update = False
                    update_case = ""
                    
                    if old_teacher_id:
                        # UPDATE case: check if row has old teacher
                        should_update = (row.get("teacher_1_id") == old_teacher_id or row.get("teacher_2_id") == old_teacher_id)
                        update_case = f"UPDATE - looking for old_teacher_id={old_teacher_id}"
                    else:
                        # CREATE case: update rows that don't have teacher assigned yet
                        should_update = not row.get("teacher_1_id") and not row.get("teacher_2_id")
                        update_case = "CREATE - empty teacher fields"
                    
                    if not should_update:
                        instance_debug["skipped_rows"] += 1
                        skipped_rows.append({
                            "row_id": row.name,
                            "reason": f"{update_case} - not matching",
                            "instance_id": instance.name,
                            "teacher_1_id": row.get("teacher_1_id"),
                            "teacher_2_id": row.get("teacher_2_id")
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
                        # PRIORITY 2: New assignment (CREATE case) 
                        # Strategy: Always assign new teacher, prefer empty slots but can overwrite if needed
                        
                        if not row_doc.teacher_1_id:
                            # teacher_1_id is empty - use it
                            row_doc.teacher_1_id = new_teacher_id
                            updated_fields.append("teacher_1_id")
                        elif not row_doc.teacher_2_id:
                            # teacher_1_id occupied but teacher_2_id empty - use teacher_2_id
                            row_doc.teacher_2_id = new_teacher_id
                            updated_fields.append("teacher_2_id")
                        else:
                            # Both slots occupied - check if new teacher is already assigned
                            if row_doc.teacher_1_id == new_teacher_id or row_doc.teacher_2_id == new_teacher_id:
                                # Teacher already assigned to this subject - skip
                                skipped_rows.append({
                                    "row_id": row.name,
                                    "reason": "CREATE - teacher already assigned",
                                    "instance_id": instance.name,
                                    "teacher_1_id": row_doc.teacher_1_id,
                                    "teacher_2_id": row_doc.teacher_2_id
                                })
                                continue
                            else:
                                # Both slots occupied by different teachers - replace teacher_2_id with new assignment
                                row_doc.teacher_2_id = new_teacher_id
                                updated_fields.append("teacher_2_id")
                                frappe.logger().info(f"SYNC PRIORITY 2 - Replaced teacher_2_id in row {row.name}: old={row_doc.teacher_2_id} -> new={new_teacher_id}")
                    
                    if updated_fields:
                        row_doc.save(ignore_permissions=True)
                        instance_debug["updated_rows"] += 1
                        updated_rows.append({
                            "row_id": row.name,
                            "updated_fields": updated_fields,
                            "instance_id": instance.name,
                            "day_of_week": row.get("day_of_week"),
                            "period": row.get("timetable_column_id"),
                            "subject_id": row.get("subject_id"),
                            "new_teacher_id": new_teacher_id,
                            "old_teacher_id": old_teacher_id
                        })
                        
                except Exception as row_error:
                    instance_debug["skipped_rows"] += 1
                    skipped_rows.append({
                        "row_id": row.name,
                        "reason": f"Update error: {str(row_error)}",
                        "instance_id": instance.name
                    })
                    continue
            
            sync_debug["processed_instances"].append(instance_debug)
                    
        except Exception as instance_error:
            instance_debug["error"] = str(instance_error)
            sync_debug["processed_instances"].append(instance_debug)
            continue
    
    frappe.db.commit()
    
    return {
        "updated_rows": updated_rows,
        "skipped_rows": skipped_rows,
        "sync_debug": sync_debug,
        "summary": {
            "instances_checked": len(instances),
            "rows_updated": len(updated_rows),
            "rows_skipped": len(skipped_rows),
            "sync_from_date": sync_from_date
        }
    }
