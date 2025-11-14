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
from .timetable_sync import (
    batch_sync_timetable_optimized,
    sync_teacher_timetable_after_assignment,
    sync_timetable_from_date
)
from .date_override_handler import delete_teacher_override_rows
from .utils import fix_subject_linkages


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
        
        frappe.logger().info(f"CREATE DEBUG - Received data: {data}")
        
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
        
        frappe.logger().info(f"CREATE DEBUG - Parsed values: teacher_id={teacher_id}, assignments={len(assignments)}")
        frappe.logger().info(f"CREATE DEBUG - Global params: application_type={global_application_type}, start_date={global_start_date}, end_date={global_end_date}")
        frappe.logger().info(f"CREATE DEBUG - Top-level params: application_type={data.get('application_type')}, start_date={data.get('start_date')}, end_date={data.get('end_date')}")
        
        if assignments:
            frappe.logger().info(f"CREATE DEBUG - First assignment: {assignments[0] if len(assignments) > 0 else 'N/A'}")
        
        # Input validation
        if not teacher_id:
            frappe.logger().error("CREATE DEBUG - Missing teacher_id")
            frappe.throw(_("Teacher ID is required"))
        if not actual_subject_id and not actual_subject_ids and not assignments and not classes:
            frappe.logger().error(f"CREATE DEBUG - Missing required fields")
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
                
                frappe.logger().info(f"CREATE DEBUG - Assignment {i}: class_id={cid}, subject_ids={sids}, application_type={application_type}")
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
        
        frappe.logger().info(f"🎯 CREATE - Processing {len(normalized_assignments)} normalized assignments for teacher {teacher_id}")
        
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
                    frappe.logger().error(f"CREATE DEBUG - Actual subject not found: {sid} for campus: {campus_id}")
                    # Check if it's a SIS Subject ID by mistake
                    sis_subject_exists = frappe.db.exists("SIS Subject", {"name": sid, "campus_id": campus_id})
                    if sis_subject_exists:
                        actual_subject_id_from_sis = frappe.db.get_value("SIS Subject", sid, "actual_subject_id")
                        if actual_subject_id_from_sis:
                            frappe.logger().info(f"CREATE DEBUG - Using actual_subject_id {actual_subject_id_from_sis} from SIS Subject {sid}")
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
                        frappe.logger().info(f"🎯 CREATE - SKIPPED duplicate full_year: teacher={teacher_id}, class={cid}, subject={sid}")
                        skipped_duplicates.append({"teacher_id": teacher_id, "class_id": cid, "subject_id": sid, "existing_id": existing})
                        continue
                elif application_type == "from_date" and start_date:
                    # Check if there's a conflicting full_year assignment
                    filters_full_year = {**filters, "application_type": "full_year"}
                    existing_full_year = frappe.db.exists("SIS Subject Assignment", filters_full_year)
                    if existing_full_year:
                        frappe.logger().info(f"🎯 CREATE - SKIPPED: conflict with full_year assignment")
                        skipped_duplicates.append({"teacher_id": teacher_id, "class_id": cid, "subject_id": sid, "existing_id": existing_full_year, "reason": "conflicts with full_year"})
                        continue
                else:
                    existing = frappe.db.exists("SIS Subject Assignment", filters)
                    if existing:
                        frappe.logger().info(f"🎯 CREATE - SKIPPED duplicate: teacher={teacher_id}, class={cid}, subject={sid}")
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
                
                frappe.logger().info(f"🎯 CREATE - Creating assignment: teacher={teacher_id}, subject={sid}, class={cid}")
                frappe.logger().info(f"           application_type={application_type}, start_date={start_date}, end_date={end_date}")
                
                assignment_doc.insert()
                
                # Verify after insert
                created_doc = frappe.get_doc("SIS Subject Assignment", assignment_doc.name)
                frappe.logger().info(f"✅ VERIFY - Created assignment {created_doc.name}")
                frappe.logger().info(f"           application_type={created_doc.application_type}, start_date={created_doc.start_date}, end_date={created_doc.end_date}")
                
                created_names.append(assignment_doc.name)
                
                # Track for batch sync
                if cid:
                    affected_classes.add(cid)
                affected_subjects.add(sid)

        # NOTE: DON'T commit assignments here! Commit after sync succeeds
        # frappe.db.commit()

        # VALIDATION: If ALL assignments were skipped (all duplicates), return error
        if len(created_names) == 0 and len(skipped_duplicates) > 0:
            frappe.logger().info(f"❌ All {len(skipped_duplicates)} assignments already exist - returning validation error")
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
        
        if created_names and affected_classes:
            # ✅ V2: Use new sync logic that supports conflict detection
            from .timetable_sync_v2 import sync_assignment_to_timetable
            
            for assignment_id in created_names:
                try:
                    frappe.logger().info(f"🔄 Syncing assignment {assignment_id}")
                    sync_result = sync_assignment_to_timetable(
                        assignment_id=assignment_id,
                        replace_teacher_map=replace_teacher_map
                    )
                    
                    # Check for conflicts
                    if not sync_result.get("success") and sync_result.get("error_type") == "teacher_conflict":
                        # Conflict detected!
                        frappe.logger().warning(f"⚠️ Conflict detected for assignment {assignment_id}")
                        conflicts = sync_result.get("conflicts", [])
                        
                        # Add assignment_id to each conflict for frontend tracking
                        for conflict in conflicts:
                            conflict["assignment_id"] = assignment_id
                        
                        all_conflicts.extend(conflicts)
                    else:
                        # Success - update counters
                        sync_summary["rows_updated"] += sync_result.get("rows_updated", 0)
                        sync_summary["rows_created"] = sync_summary.get("rows_created", 0) + sync_result.get("rows_created", 0)
                        
                except Exception as sync_error:
                    frappe.log_error(f"Timetable sync failed for assignment {assignment_id}: {str(sync_error)}")
                    frappe.logger().error(f"❌ Sync failed for {assignment_id}: {str(sync_error)}")
            
            # If there are conflicts, rollback and return conflict error
            if all_conflicts:
                frappe.db.rollback()
                frappe.logger().warning(f"⚠️ Rolling back due to {len(all_conflicts)} conflicts")
                
                return {
                    "success": False,
                    "message": f"Phát hiện {len(all_conflicts)} xung đột giáo viên. Vui lòng chọn giáo viên để thay thế.",
                    "error_type": "teacher_conflict",
                    "conflicts": all_conflicts,
                    "created_assignments": created_names  # Frontend can use this to retry
                }
            
            frappe.logger().info(f"✅ Timetable sync completed: {sync_summary}")
            
            # ✅ V2: ALWAYS sync Teacher Timetable when creating assignments
            # Even if rows_updated = 0 (e.g., new subject not in timetable pattern yet)
            # Teacher Timetable is a materialized view that should reflect ALL assignments
            if created_names:
                try:
                    frappe.logger().info(f"🎯 TEACHER TIMETABLE SYNC V2 - Starting for teacher {teacher_id}, {len(created_names)} new assignments")
                    teacher_timetable_result = sync_teacher_timetable_bulk(
                        teacher_id=teacher_id,
                        assignment_ids=created_names
                    )
                    teacher_timetable_sync_summary = {
                        "created": teacher_timetable_result["created"],
                        "updated": 0,
                        "errors": teacher_timetable_result["errors"]
                    }
                    frappe.logger().info(f"🎯 TEACHER TIMETABLE SYNC V2 - Completed: {teacher_timetable_result}")
                except Exception as teacher_sync_error:
                    frappe.logger().error(f"🎯 TEACHER TIMETABLE SYNC V2 - Failed: {str(teacher_sync_error)}")
                    import traceback
                    frappe.logger().error(traceback.format_exc())

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
        
        response_message_parts = []
        if created_count > 0:
            response_message_parts.append(f"{created_count} phân công đã tạo thành công")
        if skipped_count > 0:
            response_message_parts.append(f"{skipped_count} phân công đã tồn tại (bỏ qua)")
        if sync_summary.get('rows_updated', 0) > 0:
            response_message_parts.append(f"TKB: {sync_summary.get('rows_updated', 0)} ô cập nhật")
        if teacher_timetable_sync_summary.get('created', 0) > 0 or teacher_timetable_sync_summary.get('updated', 0) > 0:
            total_synced = teacher_timetable_sync_summary.get('created', 0) + teacher_timetable_sync_summary.get('updated', 0)
            response_message_parts.append(f"Teacher View: {total_synced} entries synced")
        
        response_message = ". ".join(response_message_parts) if response_message_parts else "Không có thay đổi"

        # ✅ COMMIT: Only commit after successful sync
        frappe.db.commit()

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
                "skipped_duplicates": skipped_duplicates
            }, response_message)
        else:
            return list_response({
                "assignments": created_data,
                "sync_summary": sync_summary,
                "skipped_duplicates": skipped_duplicates,
                "created_count": created_count,
                "skipped_count": skipped_count
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
        frappe.logger().info(f"UPDATE DEBUG - API called with assignment_id={assignment_id}, teacher_id={teacher_id}, actual_subject_id={actual_subject_id}")

        # Get data from POST body first (JSON payload)
        if frappe.request.data:
            try:
                if isinstance(frappe.request.data, bytes):
                    json_str = frappe.request.data.decode('utf-8')
                else:
                    json_str = str(frappe.request.data)

                if json_str.strip():
                    json_data = json.loads(json_str)
                    frappe.logger().info(f"UPDATE DEBUG - Parsed JSON data: {json_data}")

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
        
        frappe.logger().info(f"UPDATE DEBUG - Current assignment: teacher={assignment_doc.teacher_id}, actual_subject={assignment_doc.actual_subject_id}, class={assignment_doc.class_id}")

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
            except:
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
            
            frappe.logger().info(f"UPDATE SYNC - Delete decision: old_teacher={old_teacher_id}, new_teacher={new_teacher_id}, old_type={old_application_type}, new_type={new_application_type}")
            frappe.logger().info(f"              Old dates: {old_start_date} to {old_end_date}, New dates: {new_start_date} to {new_end_date}")
            frappe.logger().info(f"              should_delete_overrides={should_delete_overrides}")
            
            if should_delete_overrides:
                try:
                    subject_mapping = frappe.db.sql("""
                        SELECT name FROM `tabSIS Subject`
                        WHERE actual_subject_id = %s AND campus_id = %s
                    """, (assignment_doc.actual_subject_id, campus_id), as_dict=True)
                    
                    if subject_mapping:
                        subject_ids = [s.name for s in subject_mapping]
                        override_deleted = delete_teacher_override_rows(
                            old_teacher_id,
                            subject_ids,
                            [assignment_doc.class_id],
                            campus_id
                        )
                        debug_info['override_rows_deleted'] = override_deleted
                        frappe.logger().info(f"UPDATE SYNC - Deleted {override_deleted} old override rows")
                except Exception as override_del_error:
                    frappe.logger().error(f"UPDATE SYNC - Failed to delete old override rows: {str(override_del_error)}")
            
            assignment_doc.save()
            frappe.db.commit()

            debug_info['save_successful'] = True
            
            # Auto-sync timetable after update
            try:
                sync_data = {
                    "assignment_id": assignment_doc.name,
                    "old_teacher_id": old_teacher_id,
                    "new_teacher_id": new_teacher_id,
                    "class_id": assignment_doc.class_id,
                    "actual_subject_id": assignment_doc.actual_subject_id,
                    "start_date": new_start_date,
                    "end_date": new_end_date
                }
                
                sync_result = sync_timetable_from_date(sync_data, assignment_doc.modified)
                debug_info['sync_result'] = sync_result
                
                # Also sync Teacher Timetable
                if sync_result and sync_result.get('summary', {}).get('rows_updated', 0) > 0:
                    try:
                        affected_classes = [assignment_doc.class_id] if assignment_doc.class_id else []
                        teacher_sync_result = sync_teacher_timetable_after_assignment(
                            teacher_id=new_teacher_id,
                            affected_classes=affected_classes,
                            campus_id=campus_id,
                            assignment_start_date=new_start_date,
                            assignment_end_date=new_end_date
                        )
                        debug_info['teacher_timetable_sync'] = teacher_sync_result
                    except Exception as teacher_sync_error:
                        debug_info['teacher_timetable_sync_error'] = str(teacher_sync_error)
                
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
            frappe.logger().info(f"DELETE SYNC - Starting for assignment: teacher={assignment_doc.teacher_id}, class={assignment_doc.class_id}")
            
            # Get all timetable instances for this class
            instances = frappe.db.sql("""
                SELECT name, class_id, start_date, end_date
                FROM `tabSIS Timetable Instance`
                WHERE campus_id = %s
                  AND class_id = %s
                  AND end_date >= %s
            """, (campus_id, assignment_doc.class_id, frappe.utils.getdate()), as_dict=True)
            
            if instances:
                # Find the SIS Subject that corresponds to this actual_subject_id
                subject_mapping = frappe.db.sql("""
                    SELECT name FROM `tabSIS Subject`
                    WHERE actual_subject_id = %s AND campus_id = %s
                """, (assignment_doc.actual_subject_id, campus_id), as_dict=True)
                
                if not subject_mapping:
                    return success_response({"sync_summary": {"rows_updated": 0, "message": "No matching SIS Subject found"}}, 
                                          message="Subject assignment deleted successfully")
                
                subject_ids = [s.name for s in subject_mapping]
                instance_ids = [i.name for i in instances]
                
                # Get rows with this subject
                rows_to_update = frappe.db.sql("""
                    SELECT name, teacher_1_id, teacher_2_id
                    FROM `tabSIS Timetable Instance Row`
                    WHERE parent IN ({})
                      AND subject_id IN ({})
                """.format(','.join(['%s'] * len(instance_ids)), ','.join(['%s'] * len(subject_ids))), 
                tuple(instance_ids + subject_ids), as_dict=True)
                
                updated_count = 0
                for row in rows_to_update:
                    if row.teacher_1_id == assignment_doc.teacher_id:
                        frappe.db.set_value(
                            "SIS Timetable Instance Row",
                            row.name,
                            "teacher_1_id",
                            None,
                            update_modified=False
                        )
                        updated_count += 1
                    elif row.teacher_2_id == assignment_doc.teacher_id:
                        frappe.db.set_value(
                            "SIS Timetable Instance Row",
                            row.name,
                            "teacher_2_id",
                            None,
                            update_modified=False
                        )
                        updated_count += 1
                
                frappe.db.commit()
                
                # Delete override rows for this assignment
                override_deleted = 0
                try:
                    override_deleted = delete_teacher_override_rows(
                        assignment_doc.teacher_id,
                        subject_ids,
                        [assignment_doc.class_id],
                        campus_id
                    )
                except Exception as override_error:
                    frappe.logger().error(f"DELETE SYNC - Failed to delete override rows: {str(override_error)}")
                
                # ✅ FIX: Delete Teacher Timetable entries (materialized view)
                teacher_timetable_deleted = 0
                try:
                    frappe.logger().info(f"DELETE SYNC - Deleting Teacher Timetable entries for teacher={assignment_doc.teacher_id}")
                    
                    # Delete ALL Teacher Timetable entries for this teacher + class + subject
                    # (Not just future dates - also delete past entries for data consistency)
                    teacher_timetable_deleted = frappe.db.sql("""
                        DELETE FROM `tabSIS Teacher Timetable`
                        WHERE teacher_id = %s
                          AND class_id = %s
                          AND subject_id IN ({})
                          AND timetable_instance_id IN ({})
                    """.format(
                        ','.join(['%s'] * len(subject_ids)),
                        ','.join(['%s'] * len(instance_ids))
                    ), tuple([assignment_doc.teacher_id, assignment_doc.class_id] + subject_ids + instance_ids))
                    
                    frappe.logger().info(f"DELETE SYNC - Deleted {teacher_timetable_deleted or 0} Teacher Timetable entries")
                    frappe.db.commit()
                    
                except Exception as teacher_tt_error:
                    frappe.logger().error(f"DELETE SYNC - Failed to delete Teacher Timetable: {str(teacher_tt_error)}")
                    import traceback
                    frappe.logger().error(traceback.format_exc())
                
                # DISABLED: Student Timetable sync removed (not used, wastes 50% performance)
                student_timetable_updated = 0
                # Student Timetable không được dùng trong hệ thống, bỏ qua việc update
                
                sync_summary = {
                    "rows_updated": updated_count,
                    "override_rows_deleted": override_deleted,
                    "teacher_timetable_deleted": teacher_timetable_deleted or 0,
                    "student_timetable_updated": student_timetable_updated,
                    "instances_checked": len(instances),
                    "message": (
                        f"Removed teacher from {updated_count} timetable rows" + 
                        (f", deleted {override_deleted} override rows" if override_deleted > 0 else "") +
                        (f", deleted {teacher_timetable_deleted or 0} teacher timetable entries" if teacher_timetable_deleted else "") +
                        (f", updated {student_timetable_updated} student timetable entries" if student_timetable_updated else "")
                    )
                }
        except Exception as sync_error:
            frappe.logger().error(f"DELETE SYNC - Failed: {str(sync_error)}")
            frappe.log_error(f"DELETE SYNC Error: {str(sync_error)}")
        
        # Delete the document
        frappe.delete_doc("SIS Subject Assignment", assignment_id)
        frappe.db.commit()
        
        message = "Subject assignment deleted successfully"
        if sync_summary:
            message += f". Timetable updated: {sync_summary.get('rows_updated', 0)} rows"
        
        return success_response({"sync_summary": sync_summary}, message=message)
        
    except Exception as e:
        frappe.log_error(f"Error deleting subject assignment {assignment_id}: {str(e)}")
        return error_response(f"Error deleting subject assignment: {str(e)}")
