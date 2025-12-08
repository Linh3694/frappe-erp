# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Core CRUD API endpoints for Subject Assignment.

Các API chính để quản lý phân công giáo viên dạy môn học.
"""

import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)
# V2 imports - optimized sync engine
from .batch_operations import (
    sync_teacher_timetable_bulk
)
from .timetable_sync_v2 import (
    sync_assignment_to_timetable,
    batch_sync_assignments
)
from .date_override_handler import delete_teacher_override_rows
from .utils import fix_subject_linkages
from erp.api.erp_sis.utils.cache_utils import clear_teacher_dashboard_cache


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_all_subject_assignments():
    """
    Get all subject assignments with basic information.
    
    LEGACY VERSION for backward compatibility.
    
    Returns:
        dict: List of all subject assignments
    """
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
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
        
        # ⚡ BULK: Enrich with teacher's education stages (single query instead of N+1)
        teacher_ids = list(set(a['teacher_id'] for a in subject_assignments_data if a.get('teacher_id')))
        teacher_stages_map = {}
        
        if teacher_ids:
            # Single query to get all education stages for all teachers
            stages_data = frappe.db.sql("""
                SELECT 
                    tes.teacher_id,
                    GROUP_CONCAT(DISTINCT es.title_vn SEPARATOR ', ') as stages_display
                FROM `tabSIS Teacher Education Stage` tes
                INNER JOIN `tabSIS Education Stage` es ON tes.education_stage_id = es.name
                WHERE tes.teacher_id IN %(teacher_ids)s
                  AND tes.is_active = 1
                GROUP BY tes.teacher_id
            """, {"teacher_ids": teacher_ids}, as_dict=True)
            
            for row in stages_data:
                teacher_stages_map[row.teacher_id] = row.stages_display or ""
        
        # Apply to assignments
        for assignment in subject_assignments_data:
            teacher_id = assignment.get('teacher_id')
            assignment["teacher_education_stages_display"] = teacher_stages_map.get(teacher_id, "") if teacher_id else ""
        
        return list_response(subject_assignments_data, "Subject assignments fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject assignments: {str(e)}")
        return error_response(f"Error fetching subject assignments: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_teacher_assignment_details(teacher_id=None):
    """
    🎯 OPTIMIZED: Get full assignment details for a specific teacher.
    
    Grouped by class for easier display and editing.
    
    Args:
        teacher_id: Teacher ID
        
    Returns:
        dict: Teacher info with assignments grouped by class
    """
    try:
        # Get teacher_id from multiple sources
        if not teacher_id:
            teacher_id = frappe.request.args.get('teacher_id') or frappe.form_dict.get('teacher_id')
        
        if not teacher_id:
            return validation_error_response(
                message="Teacher ID is required",
                errors={"teacher_id": ["Teacher ID is required"]}
            )
        
        campus_id = get_current_campus_from_context() or "campus-1"
        
        # Verify teacher belongs to campus
        if not frappe.db.exists("SIS Teacher", {"name": teacher_id, "campus_id": campus_id}):
            return not_found_response("Teacher not found or access denied")
        
        # Query with GROUP_CONCAT to group subjects by class
        query = """
            SELECT 
                sa.class_id,
                c.title as class_title,
                c.education_grade as education_grade_id,
                eg.title_vn as education_grade_name,
                
                -- Subjects aggregated
                GROUP_CONCAT(DISTINCT sa.name ORDER BY s.title_vn SEPARATOR '||') as assignment_ids,
                GROUP_CONCAT(DISTINCT sa.actual_subject_id ORDER BY s.title_vn SEPARATOR '||') as subject_ids,
                GROUP_CONCAT(DISTINCT s.title_vn ORDER BY s.title_vn SEPARATOR '||') as subject_titles,
                
                -- Date fields aggregated
                GROUP_CONCAT(DISTINCT IFNULL(sa.application_type, 'full_year') ORDER BY s.title_vn SEPARATOR '||') as application_types,
                GROUP_CONCAT(DISTINCT sa.start_date ORDER BY s.title_vn SEPARATOR '||') as start_dates,
                GROUP_CONCAT(DISTINCT sa.end_date ORDER BY s.title_vn SEPARATOR '||') as end_dates,
                
                COUNT(DISTINCT sa.actual_subject_id) as subject_count
                
            FROM `tabSIS Subject Assignment` sa
            INNER JOIN `tabSIS Class` c ON sa.class_id = c.name
            INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            INNER JOIN `tabSIS Actual Subject` s ON sa.actual_subject_id = s.name
            WHERE sa.teacher_id = %s 
              AND sa.campus_id = %s
            GROUP BY sa.class_id, c.title, c.education_grade, eg.title_vn
            ORDER BY c.title
        """
        
        results = frappe.db.sql(query, (teacher_id, campus_id), as_dict=True)
        
        # Parse GROUP_CONCAT results
        for row in results:
            row['assignment_ids'] = row['assignment_ids'].split('||') if row['assignment_ids'] else []
            row['subject_ids'] = row['subject_ids'].split('||') if row['subject_ids'] else []
            row['subject_titles'] = row['subject_titles'].split('||') if row['subject_titles'] else []
            # Parse date fields
            row['application_types'] = row['application_types'].split('||') if row['application_types'] else []
            row['start_dates'] = [d if d != 'None' else None for d in (row['start_dates'].split('||') if row['start_dates'] else [])]
            row['end_dates'] = [d if d != 'None' else None for d in (row['end_dates'].split('||') if row['end_dates'] else [])]
        
        # Get teacher info
        teacher_info_result = frappe.db.sql("""
            SELECT 
                t.name as teacher_id,
                COALESCE(NULLIF(u.full_name, ''), t.user_id) as teacher_name,
                t.user_id,
                (
                    SELECT GROUP_CONCAT(DISTINCT es.title_vn SEPARATOR ', ')
                    FROM `tabSIS Teacher Education Stage` tes
                    INNER JOIN `tabSIS Education Stage` es ON tes.education_stage_id = es.name
                    WHERE tes.teacher_id = t.name AND tes.is_active = 1
                ) as education_stages_display
            FROM `tabSIS Teacher` t
            INNER JOIN `tabUser` u ON t.user_id = u.name
            WHERE t.name = %s
        """, (teacher_id,), as_dict=True)
        
        teacher_info = teacher_info_result[0] if teacher_info_result else {}
        
        return {
            "success": True,
            "data": {
                "teacher": teacher_info,
                "assignments_by_class": results,
                "total_classes": len(results),
                "total_subjects": sum(row['subject_count'] for row in results),
                "total_assignments": sum(len(row['assignment_ids']) for row in results)
            },
            "message": "Teacher assignment details fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_teacher_assignment_details: {str(e)}")
        return error_response(f"Error fetching teacher details: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_subject_assignment_by_id(assignment_id=None):
    """
    Get a specific subject assignment by ID.
    
    Args:
        assignment_id: Assignment ID (can be from URL path, query param, form_dict, or JSON)
        
    Returns:
        dict: Assignment data
    """
    try:
        # Get assignment_id from multiple sources
        if not assignment_id:
            # Try to get from URL path first
            try:
                request_path = frappe.local.request.path if hasattr(frappe.local, 'request') else frappe.request.path
                if request_path:
                    path_parts = request_path.strip('/').split('/')
                    if len(path_parts) > 0:
                        last_part = path_parts[-1]
                        if 'SUBJECT_ASSIGNMENT' in last_part or last_part.startswith('SIS-'):
                            assignment_id = last_part
            except Exception:
                pass

        # Try to get from URL query parameters
        if not assignment_id:
            assignment_id = frappe.request.args.get('assignment_id')

        # Try to get from form_dict
        if not assignment_id:
            assignment_id = frappe.form_dict.get('assignment_id')

        # Try to get from JSON payload
        if not assignment_id and frappe.request.data:
            try:
                if isinstance(frappe.request.data, bytes):
                    json_str = frappe.request.data.decode('utf-8')
                else:
                    json_str = str(frappe.request.data)

                if json_str.strip():
                    json_data = json.loads(json_str)
                    assignment_id = json_data.get('assignment_id')
            except Exception:
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
    """
    Create new subject assignments.

    Supported payloads (backward compatible):
    - Single: { teacher_id, subject_id, class_id? }
    - Bulk by subjects for one class: { teacher_id, class_id, subject_ids: [subject_id, ...] }
    - Bulk by classes and subjects: { teacher_id, assignments: [ { class_id, subject_ids: [...] }, ... ] }
      Also supports: { teacher_id, classes: [class_id, ...], subject_ids: [...] } (applies same subjects to many classes)
      
    Returns:
        dict: Created assignment(s) data with sync summary
    """
    try:
        # Get data from request
        data = {}
        
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                else:
                    data = frappe.local.form_dict
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
        
        # Debug logging removed for production
        
        # Extract values from data - Priority: JSON payload > form_dict > URL params
        teacher_id = data.get("teacher_id")
        actual_subject_id = data.get("actual_subject_id")
        class_id = data.get("class_id")
        actual_subject_ids = data.get("actual_subject_ids")
        assignments = data.get("assignments") or []
        classes = data.get("classes") or []
        
        # IMPORTANT: Extract application_type, start_date, end_date from JSON FIRST
        # These are top-level parameters that apply to all assignments if not specified per-assignment
        global_application_type = data.get("application_type", "full_year")
        global_start_date = data.get("start_date")
        global_end_date = data.get("end_date")
        
        # Extract replace_teacher_map for conflict resolution
        # Format: {row_id: "teacher_1" or "teacher_2"}
        replace_teacher_map = data.get("replace_teacher_map") or {}
        
        
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
            for i, a in enumerate(assignments):
                cid = a.get("class_id")
                # Support both "subject_ids" and "actual_subject_ids" field names
                sids = a.get("actual_subject_ids") or a.get("subject_ids") or []
                if isinstance(sids, str):
                    sids = [sids]  # Convert single string to list
                
                application_type = a.get("application_type", "full_year")
                start_date = a.get("start_date")
                end_date = a.get("end_date")
                
                if cid and sids:
                    normalized_assignments.append({
                        "class_id": cid, 
                        "actual_subject_ids": sids,
                        "application_type": application_type,
                        "start_date": start_date,
                        "end_date": end_date
                    })

        # Case 2: top-level classes + actual_subject_ids
        if not normalized_assignments and isinstance(classes, list) and classes and isinstance(actual_subject_ids, list) and actual_subject_ids:
            for cid in classes:
                normalized_assignments.append({
                    "class_id": cid, 
                    "actual_subject_ids": actual_subject_ids,
                    "application_type": global_application_type,
                    "start_date": global_start_date,
                    "end_date": global_end_date
                })

        # Case 3: legacy single/bulk for one class
        if not normalized_assignments:
            effective_actual_subject_ids = actual_subject_ids if isinstance(actual_subject_ids, list) and actual_subject_ids else ([actual_subject_id] if actual_subject_id else [])
            normalized_assignments.append({
                "class_id": class_id, 
                "actual_subject_ids": effective_actual_subject_ids,
                "application_type": global_application_type,
                "start_date": global_start_date,
                "end_date": global_end_date
            })

        # Validate classes belong to campus
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
        affected_classes = set()
        affected_subjects = set()
        skipped_duplicates = []
        
        
        # FAST: Create all assignments without syncing
        for item in normalized_assignments:
            cid = item.get("class_id")
            sids = item.get("actual_subject_ids") or []
            application_type = item.get("application_type", "full_year")
            start_date = item.get("start_date")
            end_date = item.get("end_date")
            
            # Validate and create for each actual subject
            for sid in sids:
                subject_exists = frappe.db.exists(
                    "SIS Actual Subject",
                    {"name": sid, "campus_id": campus_id}
                )
                if not subject_exists:
                    # Check if it's a SIS Subject ID by mistake
                    sis_subject_exists = frappe.db.exists("SIS Subject", {"name": sid, "campus_id": campus_id})
                    if sis_subject_exists:
                        actual_subject_id_from_sis = frappe.db.get_value("SIS Subject", sid, "actual_subject_id")
                        if actual_subject_id_from_sis:
                            sid = actual_subject_id_from_sis
                        else:
                            return validation_error_response(f"SIS Subject {sid} does not have a linked Actual Subject", {"actual_subject_id": [f"Subject {sid} is not properly linked"]})
                    else:
                        return not_found_response(f"Selected actual subject does not exist or access denied: {sid}")

                filters = {
                    "teacher_id": teacher_id,
                    "actual_subject_id": sid,
                    "campus_id": campus_id,
                }
                if cid:
                    filters["class_id"] = cid
                
                # Check for duplicate
                if application_type == "full_year":
                    existing = frappe.db.exists("SIS Subject Assignment", filters)
                    if existing:
                        skipped_duplicates.append({"teacher_id": teacher_id, "class_id": cid, "subject_id": sid, "existing_id": existing})
                        continue
                elif application_type == "from_date" and start_date:
                    # Check if there's a conflicting full_year assignment
                    filters_full_year = {**filters, "application_type": "full_year"}
                    existing_full_year = frappe.db.exists("SIS Subject Assignment", filters_full_year)
                    if existing_full_year:
                        skipped_duplicates.append({"teacher_id": teacher_id, "class_id": cid, "subject_id": sid, "existing_id": existing_full_year, "reason": "conflicts with full_year"})
                        continue
                else:
                    existing = frappe.db.exists("SIS Subject Assignment", filters)
                    if existing:
                        skipped_duplicates.append({"teacher_id": teacher_id, "class_id": cid, "subject_id": sid, "existing_id": existing})
                        continue

                # Create assignment with date fields
                assignment_doc = frappe.get_doc({
                    "doctype": "SIS Subject Assignment",
                    "teacher_id": teacher_id,
                    "actual_subject_id": sid,
                    "class_id": cid,
                    "campus_id": campus_id,
                    "application_type": application_type,
                    "start_date": start_date,
                    "end_date": end_date
                })
                
                assignment_doc.insert()
                
                created_names.append(assignment_doc.name)
                
                # Track for batch sync
                if cid:
                    affected_classes.add(cid)
                affected_subjects.add(sid)

        # NOTE: DON'T commit assignments here! Commit after sync succeeds
        # frappe.db.commit()

        # VALIDATION: If ALL assignments were skipped (all duplicates), return error
        if len(created_names) == 0 and len(skipped_duplicates) > 0:
            return validation_error_response(
                message="Tất cả phân công đã tồn tại",
                errors={
                    "duplicate": [f"Tất cả {len(skipped_duplicates)} phân công đã tồn tại trong hệ thống"],
                    "skipped_duplicates": skipped_duplicates
                }
            )
        
        # SYNC: Handle timetable sync for created assignments
        sync_summary = {"rows_updated": 0, "rows_skipped": 0}
        teacher_timetable_sync_summary = {"created": 0, "updated": 0, "errors": 0}
        all_conflicts = []  # Collect conflicts from all assignments
        sync_warnings = []  # Track assignments that couldn't sync (e.g., no timetable yet)
        
        if created_names and affected_classes:
            # ✅ V2: Use new sync logic that supports conflict detection
            from .timetable_sync_v2 import sync_assignment_to_timetable
            
            for assignment_id in created_names:
                try:
                    sync_result = sync_assignment_to_timetable(
                        assignment_id=assignment_id,
                        replace_teacher_map=replace_teacher_map
                    )
                    
                    # Check for conflicts or other failures
                    if not sync_result.get("success"):
                        if sync_result.get("error_type") == "teacher_conflict":
                            # Conflict detected!
                            conflicts = sync_result.get("conflicts", [])
                            
                            # Add assignment_id to each conflict for frontend tracking
                            for conflict in conflicts:
                                conflict["assignment_id"] = assignment_id
                            
                            all_conflicts.extend(conflicts)
                        else:
                            # ⚡ FIX: Handle other sync failures (e.g., no pattern rows)
                            # Track warning for user notification
                            sync_warnings.append({
                                "assignment_id": assignment_id,
                                "message": sync_result.get("message", "Chưa có thời khóa biểu")
                            })
                            frappe.logger().warning(
                                f"Timetable sync warning for {assignment_id}: {sync_result.get('message', 'Unknown error')}. "
                                f"Debug: {sync_result.get('debug_info', [])}"
                            )
                    else:
                        # Success - update counters
                        sync_summary["rows_updated"] += sync_result.get("rows_updated", 0)
                        sync_summary["rows_created"] = sync_summary.get("rows_created", 0) + sync_result.get("rows_created", 0)
                        
                except Exception as sync_error:
                    error_msg = f"Timetable sync failed for assignment {assignment_id}: {str(sync_error)}"
                    frappe.log_error(error_msg, "Timetable Sync Error")
                    
                    # ⚡ CRITICAL: Throw exception to rollback transaction
                    # This ensures we don't create "orphan" assignments without timetable sync
                    frappe.throw(f"Failed to sync assignment to timetable: {str(sync_error)}")
            
            # If there are conflicts, rollback and return conflict error
            if all_conflicts:
                frappe.db.rollback()
                
                # Return conflict response using standard format but with additional fields
                conflict_response = {
                    "success": False,
                    "message": f"Phát hiện {len(all_conflicts)} xung đột giáo viên. Vui lòng chọn giáo viên để thay thế.",
                    "error_type": "teacher_conflict",
                    "conflicts": all_conflicts,
                    "created_assignments": created_names  # Frontend can use this to retry
                }
                return conflict_response
            
            
            # ⚡ NOTE: Teacher Timetable sync is ALREADY handled by sync_assignment_to_timetable()
            # above (line 598). It calls sync_for_rows() which updates Teacher Timetable.
            # NO NEED for additional sync_teacher_timetable_bulk() call!
            # 
            # Previous implementation used sync_teacher_timetable_bulk() which:
            # - Deleted existing entries
            # - Tried to recreate but failed (returned 0 entries)
            # - Caused data loss
            #
            # Current implementation (sync_assignment_to_timetable):
            # - Updates pattern rows with teachers
            # - Calls sync_for_rows() to update Teacher Timetable incrementally
            # - No deletion, only upsert
            # - More reliable and atomic

        # Auto-fix any existing SIS Subjects that don't have actual_subject_id linkage
        try:
            fix_subject_linkages(campus_id)
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

        # Return the created data
        frappe.msgprint(_("Subject assignment created successfully"))

        # Build response message
        created_count = len(created_names)
        skipped_count = len(skipped_duplicates)
        sync_warning_count = len(sync_warnings)
        
        response_message_parts = []
        if created_count > 0:
            response_message_parts.append(f"{created_count} phân công đã tạo thành công")
        if skipped_count > 0:
            response_message_parts.append(f"{skipped_count} phân công đã tồn tại (bỏ qua)")
        if sync_summary.get('rows_updated', 0) > 0:
            response_message_parts.append(f"TKB: {sync_summary.get('rows_updated', 0)} ô cập nhật")
        elif sync_warning_count > 0:
            # ⚡ FIX: Notify user that sync = 0 because no timetable yet
            response_message_parts.append(f"TKB: 0 ô cập nhật (chưa có thời khóa biểu, sẽ tự đồng bộ khi upload TKB)")
        if teacher_timetable_sync_summary.get('created', 0) > 0 or teacher_timetable_sync_summary.get('updated', 0) > 0:
            total_synced = teacher_timetable_sync_summary.get('created', 0) + teacher_timetable_sync_summary.get('updated', 0)
            response_message_parts.append(f"Teacher View: {total_synced} entries synced")
        
        response_message = ". ".join(response_message_parts) if response_message_parts else "Không có thay đổi"

        # ✅ COMMIT: Only commit after successful sync
        frappe.db.commit()
        
        # ⚡ CLEAR CACHE: Invalidate teacher classes cache after assignment change
        clear_teacher_dashboard_cache()

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
                "class_title": result.class_title,
                "sync_summary": sync_summary,
                "skipped_duplicates": skipped_duplicates,
                "sync_warnings": sync_warnings,  # ⚡ Include sync warnings for frontend
                "sync_warning_count": sync_warning_count
            }, response_message)
        else:
            return list_response({
                "assignments": created_data,
                "sync_summary": sync_summary,
                "skipped_duplicates": skipped_duplicates,
                "created_count": created_count,
                "skipped_count": skipped_count,
                "sync_warnings": sync_warnings,  # ⚡ Include sync warnings for frontend
                "sync_warning_count": sync_warning_count
            }, response_message)
        
    except Exception as e:
        # Check if any assignments were actually created before the error
        if 'created_names' in locals() and created_names:
            frappe.log_error(f"Subject assignments created successfully but post-processing failed: {str(e)}")
            
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
            
            frappe.msgprint(_("Subject assignment created successfully"))
            
            skipped_count = len(skipped_duplicates) if 'skipped_duplicates' in locals() else 0
            created_count = len(created_names)
            
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
                }, f"{created_count} phân công đã tạo. Cảnh báo: {str(e)}")
            else:
                return list_response({
                    "assignments": created_data,
                    "created_count": created_count,
                    "skipped_count": skipped_count,
                    "post_processing_warning": str(e)
                }, f"{created_count} phân công đã tạo, {skipped_count} bỏ qua. Cảnh báo: {str(e)}")
        else:
            frappe.log_error(f"Error creating subject assignment: {str(e)}")
            frappe.throw(_(f"Error creating subject assignment: {str(e)}"))



@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def update_subject_assignment(assignment_id=None, teacher_id=None, actual_subject_id=None):
    """
    Update an existing subject assignment.
    
    Args:
        assignment_id: Required assignment ID
        teacher_id: Optional new teacher ID
        actual_subject_id: Optional new actual subject ID
        class_id: Optional new class ID
        application_type: Optional application type (full_year or from_date)
        start_date: Optional start date
        end_date: Optional end date
        
    Returns:
        dict: Updated assignment data with sync summary
    """
    try:

        # Get data from POST body first (JSON payload)
        if frappe.request.data:
            try:
                if isinstance(frappe.request.data, bytes):
                    json_str = frappe.request.data.decode('utf-8')
                else:
                    json_str = str(frappe.request.data)

                if json_str.strip():
                    json_data = json.loads(json_str)

                    assignment_id = json_data.get('assignment_id') or assignment_id
                    teacher_id = json_data.get('teacher_id') or teacher_id
                    actual_subject_id = json_data.get('actual_subject_id') or actual_subject_id

                    # Try different possible field names for class_id
                    class_id = (json_data.get('class_id') or
                               json_data.get('class') or
                               json_data.get('classId') or
                               (json_data.get('data', {}).get('class_id') if json_data.get('data') else None))
            except Exception:
                pass

        # Get assignment_id from multiple sources if not found in JSON
        if not assignment_id:
            try:
                request_path = frappe.local.request.path if hasattr(frappe.local, 'request') else frappe.request.path
                if request_path:
                    path_parts = request_path.strip('/').split('/')
                    if len(path_parts) > 0:
                        last_part = path_parts[-1]
                        if 'SUBJECT_ASSIGNMENT' in last_part or last_part.startswith('SIS-'):
                            assignment_id = last_part
            except Exception:
                pass

        if not assignment_id:
            assignment_id = frappe.request.args.get('assignment_id')
        if not assignment_id:
            assignment_id = frappe.form_dict.get('assignment_id')
        if not teacher_id:
            teacher_id = frappe.form_dict.get('teacher_id')
        if not actual_subject_id:
            actual_subject_id = frappe.form_dict.get('actual_subject_id')
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
        

        # Update fields if provided
        if teacher_id and teacher_id != assignment_doc.teacher_id:
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

        if actual_subject_id and actual_subject_id != assignment_doc.actual_subject_id:
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
        
        # Update class_id if provided
        current_class_id = getattr(assignment_doc, 'class_id', 'NOT_SET')
        debug_info = {
            'current_class_id': current_class_id,
            'new_class_id': class_id if 'class_id' in locals() else 'NOT_PROVIDED',
            'will_update': 'class_id' in locals() and class_id is not None and class_id != current_class_id
        }

        if 'class_id' in locals() and class_id is not None and class_id != current_class_id:
            assignment_doc.class_id = class_id
        
        # Update time application fields if provided
        application_type = frappe.request.args.get('application_type') or frappe.form_dict.get('application_type')
        start_date = frappe.request.args.get('start_date') or frappe.form_dict.get('start_date')
        end_date = frappe.request.args.get('end_date') or frappe.form_dict.get('end_date')
        
        # Also try to get from JSON payload
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                application_type = json_data.get('application_type') or application_type
                start_date = json_data.get('start_date') or start_date
                end_date = json_data.get('end_date') or end_date
            except (json.JSONDecodeError, TypeError):
                pass
        
        if application_type and application_type != getattr(assignment_doc, 'application_type', 'full_year'):
            assignment_doc.application_type = application_type
            debug_info['updated_application_type'] = application_type
        
        if start_date and start_date != getattr(assignment_doc, 'start_date', None):
            assignment_doc.start_date = start_date
            debug_info['updated_start_date'] = start_date
        
        if end_date and end_date != getattr(assignment_doc, 'end_date', None):
            assignment_doc.end_date = end_date
            debug_info['updated_end_date'] = end_date

        # Check for duplicate assignment after updates
        if teacher_id or actual_subject_id or ('class_id' in locals() and class_id is not None):
            final_teacher_id = teacher_id or assignment_doc.teacher_id
            final_actual_subject_id = actual_subject_id or assignment_doc.actual_subject_id
            final_class_id = class_id if 'class_id' in locals() and class_id is not None else getattr(assignment_doc, 'class_id', None)

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
                return validation_error_response(
                    message="Teacher already assigned to this actual subject",
                    errors={"assignment": ["This teacher is already assigned to this actual subject"]}
                )

        try:
            # Store old teacher and application_type for timetable update
            old_teacher_id = frappe.db.get_value("SIS Subject Assignment", assignment_id, "teacher_id")
            old_application_type = frappe.db.get_value("SIS Subject Assignment", assignment_id, "application_type") or "full_year"
            old_start_date = frappe.db.get_value("SIS Subject Assignment", assignment_id, "start_date")
            old_end_date = frappe.db.get_value("SIS Subject Assignment", assignment_id, "end_date")
            
            new_teacher_id = teacher_id or assignment_doc.teacher_id
            new_application_type = assignment_doc.application_type or "full_year"
            new_start_date = assignment_doc.start_date
            new_end_date = assignment_doc.end_date
            
            # Delete old override rows if needed
            # Case 1: Teacher changed
            # Case 2: Type changed from from_date to full_year
            # Case 3: from_date assignment with changed dates
            should_delete_overrides = (
                old_teacher_id != new_teacher_id or 
                (old_application_type == "from_date" and new_application_type == "full_year") or
                (old_application_type == "from_date" and (old_start_date != new_start_date or old_end_date != new_end_date))
            )
            
            
            if should_delete_overrides:
                try:
                    # Use assignment_doc.campus_id for accurate campus matching
                    subject_mapping = frappe.db.sql("""
                        SELECT name FROM `tabSIS Subject`
                        WHERE actual_subject_id = %s AND campus_id = %s
                    """, (assignment_doc.actual_subject_id, assignment_doc.campus_id), as_dict=True)
                    
                    if subject_mapping:
                        subject_ids = [s.name for s in subject_mapping]
                        override_deleted = delete_teacher_override_rows(
                            old_teacher_id,
                            subject_ids,
                            [assignment_doc.class_id],
                            assignment_doc.campus_id
                        )
                        debug_info['override_rows_deleted'] = override_deleted
                except Exception:
                    pass  # Continue even if override deletion fails
            
            assignment_doc.save()
            frappe.db.commit()
            
            # ⚡ CLEAR CACHE: Invalidate teacher classes cache after assignment change
            clear_teacher_dashboard_cache()

            debug_info['save_successful'] = True
            
            # Auto-sync timetable after update (V2)
            try:
                sync_result = sync_assignment_to_timetable(assignment_doc.name)
                debug_info['sync_result'] = sync_result
                
            except Exception as sync_error:
                frappe.log_error(f"Auto-sync timetable failed for updated assignment {assignment_id}: {str(sync_error)}")
                debug_info['sync_error'] = str(sync_error)

        except Exception as save_error:
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
                "debug_info": debug_info
            }
            return single_item_response(assignment_data, f"Subject assignment updated successfully.{sync_summary}")
        else:
            return single_item_response({
                "name": assignment_doc.name,
                "teacher_id": assignment_doc.teacher_id,
                "actual_subject_id": assignment_doc.actual_subject_id,
                "campus_id": assignment_doc.campus_id,
                "timetable_sync": debug_info.get('sync_result', {}),
                "debug_info": debug_info
            }, "Subject assignment updated successfully.")
        
    except Exception as e:
        frappe.log_error(f"Error updating subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error updating subject assignment: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def delete_subject_assignment(assignment_id=None):
    """
    Delete a subject assignment.
    
    Automatically syncs timetable to remove teacher from affected periods.
    
    Args:
        assignment_id: Assignment ID to delete
        
    Returns:
        dict: Success response with sync summary
    """
    try:
        # Get assignment_id from multiple sources
        if not assignment_id:
            try:
                request_path = frappe.local.request.path if hasattr(frappe.local, 'request') else frappe.request.path
                if request_path:
                    path_parts = request_path.strip('/').split('/')
                    if len(path_parts) > 0:
                        last_part = path_parts[-1]
                        if 'SUBJECT_ASSIGNMENT' in last_part or last_part.startswith('SIS-'):
                            assignment_id = last_part
            except Exception:
                pass

        if not assignment_id:
            assignment_id = frappe.request.args.get('assignment_id')
        if not assignment_id:
            assignment_id = frappe.form_dict.get('assignment_id')

        if not assignment_id and frappe.request.data:
            try:
                if isinstance(frappe.request.data, bytes):
                    json_str = frappe.request.data.decode('utf-8')
                else:
                    json_str = str(frappe.request.data)

                if json_str.strip():
                    json_data = json.loads(json_str)
                    assignment_id = json_data.get('assignment_id')
            except Exception:
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
        
        # BEFORE DELETE: Sync TKB to remove teacher from timetable rows
        sync_summary = {}
        try:
            teacher_id_to_delete = assignment_doc.teacher_id
            class_id_to_delete = assignment_doc.class_id
            actual_subject_id_to_delete = assignment_doc.actual_subject_id
            # ⚡ FIX: Use campus_id from assignment_doc, NOT from context
            # Context may return wrong value (e.g., "campus-1" instead of "CAMPUS-00001")
            doc_campus_id = assignment_doc.campus_id
            
            frappe.logger().info(
                f"🗑️ DELETE SYNC START: teacher={teacher_id_to_delete}, "
                f"class={class_id_to_delete}, actual_subject={actual_subject_id_to_delete}, "
                f"campus={doc_campus_id}"
            )
            
            # Get all timetable instances for this class (include past ones for thorough cleanup)
            instances = frappe.db.sql("""
                SELECT name, class_id, start_date, end_date
                FROM `tabSIS Timetable Instance`
                WHERE campus_id = %s
                  AND class_id = %s
            """, (doc_campus_id, class_id_to_delete), as_dict=True)
            
            frappe.logger().info(f"🔍 Found {len(instances)} timetable instances for class {class_id_to_delete}")
            
            # ⚡ STRATEGY 1: Direct delete by teacher_id + class (most reliable)
            # This doesn't rely on subject mapping which can be inconsistent
            direct_deleted = 0
            try:
                # Find ALL rows belonging to this class's timetable instances
                if instances:
                    instance_ids = [i.name for i in instances]
                    
                    # Get ALL timetable rows for these instances
                    all_rows = frappe.db.sql("""
                        SELECT name 
                        FROM `tabSIS Timetable Instance Row`
                        WHERE parent IN ({}) OR parent_timetable_instance IN ({})
                    """.format(
                        ','.join(['%s'] * len(instance_ids)),
                        ','.join(['%s'] * len(instance_ids))
                    ), tuple(instance_ids + instance_ids), as_dict=True)
                    
                    if all_rows:
                        row_names = [r.name for r in all_rows]
                        
                        # Count before
                        count_before = frappe.db.sql("""
                            SELECT COUNT(*) as cnt FROM `tabSIS Timetable Instance Row Teacher`
                            WHERE parent IN ({}) AND teacher_id = %s
                        """.format(','.join(['%s'] * len(row_names))),
                        tuple(row_names + [teacher_id_to_delete]))[0][0]
                        
                        frappe.logger().info(
                            f"🔍 DIRECT DELETE: Found {count_before} teacher entries for "
                            f"teacher={teacher_id_to_delete} in {len(row_names)} rows"
                        )
                        
                        if count_before > 0:
                            # ⚡ IMPORTANT: Only delete for rows matching the actual_subject_id
                            # First, get subject mapping
                            subject_mapping = frappe.db.sql("""
                                SELECT name FROM `tabSIS Subject`
                                WHERE actual_subject_id = %s AND campus_id = %s
                            """, (actual_subject_id_to_delete, doc_campus_id), as_dict=True)
                            
                            if subject_mapping:
                                subject_ids = [s.name for s in subject_mapping]
                                
                                # Get only rows matching the subject
                                matching_rows = frappe.db.sql("""
                                    SELECT name FROM `tabSIS Timetable Instance Row`
                                    WHERE (parent IN ({0}) OR parent_timetable_instance IN ({0}))
                                      AND subject_id IN ({1})
                                """.format(
                                    ','.join(['%s'] * len(instance_ids)),
                                    ','.join(['%s'] * len(subject_ids))
                                ), tuple(instance_ids + instance_ids + subject_ids), as_dict=True)
                                
                                if matching_rows:
                                    matching_row_names = [r.name for r in matching_rows]
                                    
                                    # Delete teacher from matching rows only
                                    frappe.db.sql("""
                                        DELETE FROM `tabSIS Timetable Instance Row Teacher`
                                        WHERE parent IN ({}) AND teacher_id = %s
                                    """.format(','.join(['%s'] * len(matching_row_names))),
                                    tuple(matching_row_names + [teacher_id_to_delete]))
                                    
                                    # Count after
                                    count_after = frappe.db.sql("""
                                        SELECT COUNT(*) as cnt FROM `tabSIS Timetable Instance Row Teacher`
                                        WHERE parent IN ({}) AND teacher_id = %s
                                    """.format(','.join(['%s'] * len(matching_row_names))),
                                    tuple(matching_row_names + [teacher_id_to_delete]))[0][0]
                                    
                                    direct_deleted = count_before - count_after if count_after < count_before else 0
                                    
                                    frappe.logger().info(
                                        f"✅ DIRECT DELETE: Removed {direct_deleted} teacher entries. "
                                        f"Subject mapping: {subject_ids}, Matching rows: {len(matching_row_names)}"
                                    )
                                    
                                    # Clear cache for affected rows
                                    for row_name in matching_row_names:
                                        try:
                                            frappe.clear_document_cache("SIS Timetable Instance Row", row_name)
                                        except:
                                            pass
                                else:
                                    frappe.logger().warning(
                                        f"⚠️ No matching rows found for subjects {subject_ids}"
                                    )
                            else:
                                frappe.logger().warning(
                                    f"⚠️ No SIS Subject mapping for actual_subject={actual_subject_id_to_delete}"
                                )
                                
            except Exception as direct_err:
                frappe.logger().error(f"❌ Direct delete error: {str(direct_err)}")
            
            # ⚡ STRATEGY 2: Delete from Teacher Timetable (materialized view)
            teacher_timetable_deleted = 0
            try:
                # Delete using class_id + teacher_id (more reliable than subject matching)
                if instances:
                    instance_ids = [i.name for i in instances]
                    
                    # Get subject mapping for specific delete (use doc_campus_id)
                    subject_mapping = frappe.db.sql("""
                        SELECT name FROM `tabSIS Subject`
                        WHERE actual_subject_id = %s AND campus_id = %s
                    """, (actual_subject_id_to_delete, doc_campus_id), as_dict=True)
                    
                    if subject_mapping:
                        subject_ids = [s.name for s in subject_mapping]
                        
                        # Delete with subject filter
                        frappe.db.sql("""
                            DELETE FROM `tabSIS Teacher Timetable`
                            WHERE teacher_id = %s
                              AND class_id = %s
                              AND subject_id IN ({})
                        """.format(','.join(['%s'] * len(subject_ids))),
                        tuple([teacher_id_to_delete, class_id_to_delete] + subject_ids))
                        
                        frappe.logger().info(
                            f"✅ Deleted Teacher Timetable entries for teacher={teacher_id_to_delete}, "
                            f"class={class_id_to_delete}, subjects={subject_ids}"
                        )
                    else:
                        # Fallback: Delete ALL entries for this teacher + class
                        frappe.db.sql("""
                            DELETE FROM `tabSIS Teacher Timetable`
                            WHERE teacher_id = %s AND class_id = %s
                        """, (teacher_id_to_delete, class_id_to_delete))
                        
                        frappe.logger().warning(
                            f"⚠️ Fallback: Deleted ALL Teacher Timetable entries for "
                            f"teacher={teacher_id_to_delete}, class={class_id_to_delete}"
                        )
                        
            except Exception as tt_error:
                frappe.logger().error(f"❌ Teacher Timetable delete error: {str(tt_error)}")
            
            # ⚡ STRATEGY 3: Delete override rows
            override_deleted = 0
            try:
                subject_mapping = frappe.db.sql("""
                    SELECT name FROM `tabSIS Subject`
                    WHERE actual_subject_id = %s AND campus_id = %s
                """, (actual_subject_id_to_delete, doc_campus_id), as_dict=True)
                
                if subject_mapping:
                    subject_ids = [s.name for s in subject_mapping]
                    override_deleted = delete_teacher_override_rows(
                        teacher_id_to_delete,
                        subject_ids,
                        [class_id_to_delete],
                        campus_id
                    )
                    frappe.logger().info(f"✅ Deleted {override_deleted} override rows")
            except Exception as override_error:
                frappe.logger().error(f"❌ Override delete error: {str(override_error)}")
            
            # ⚡ COMMIT before cache clear
            frappe.db.commit()
            
            # ⚡ CLEAR ALL CACHES (most important!)
            try:
                from erp.api.erp_sis.utils.cache_utils import clear_class_cache, clear_teacher_dashboard_cache
                
                # Clear class-specific cache
                class_cache_deleted = clear_class_cache(class_id_to_delete)
                frappe.logger().info(f"✅ Cleared {class_cache_deleted} class_week cache keys for class {class_id_to_delete}")
                
                # Clear ALL teacher dashboard cache (broad clear)
                dashboard_result = clear_teacher_dashboard_cache()
                frappe.logger().info(f"✅ Dashboard cache: {dashboard_result.get('total_deleted', 0)} keys")
                
            except Exception as cache_err:
                frappe.logger().error(f"❌ Cache clear error: {str(cache_err)}")
            
            sync_summary = {
                "rows_deleted": direct_deleted,
                "teacher_timetable_deleted": teacher_timetable_deleted,
                "override_rows_deleted": override_deleted,
                "instances_checked": len(instances) if instances else 0,
                "message": f"Removed {direct_deleted} timetable entries, {override_deleted} overrides"
            }
            
            frappe.logger().info(f"✅ DELETE SYNC COMPLETE: {sync_summary}")
                
        except Exception as sync_error:
            frappe.log_error(f"DELETE SYNC Error: {str(sync_error)}")
            frappe.logger().error(f"❌ DELETE SYNC Error: {str(sync_error)}")
        
        # Delete the document
        frappe.delete_doc("SIS Subject Assignment", assignment_id)
        frappe.db.commit()
        
        # ⚡ FINAL CACHE CLEAR: Ensure all caches are invalidated
        try:
            clear_teacher_dashboard_cache()
        except:
            pass
        
        message = "Subject assignment deleted successfully"
        if sync_summary:
            message += f". Timetable updated: {sync_summary.get('rows_deleted', 0)} rows"
        
        return success_response({"sync_summary": sync_summary}, message=message)
        
    except Exception as e:
        frappe.log_error(f"Error deleting subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error deleting subject assignment: {str(e)}")
