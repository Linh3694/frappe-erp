# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Batch operations for Subject Assignment.

Xử lý các thao tác hàng loạt như batch update, bulk sync timetable.
"""

import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)
from .timetable_sync import batch_sync_timetable_optimized, sync_materialized_views_with_progress
from .date_override_handler import delete_teacher_override_rows


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_update_teacher_assignments():
    """
    🎯 OPTIMIZED: Bulk update all assignments for a teacher.
    
    Input:
    {
        "teacher_id": "teacher-001",
        "assignments": [
            {
                "class_id": "class-1a",
                "subject_ids": ["math", "english"],  // actual_subject_ids
                "application_type": "full_year" or "from_date",
                "start_date": "2025-01-15",  // required if from_date
                "end_date": "2025-06-30"  // optional
            }
        ],
        "deleted_assignment_ids": ["SIS-SUBJECT-ASSIGNMENT-00123"]
    }
    
    Strategy:
    1. Execute all DB changes FAST (no sync during loop)
    2. Collect affected classes + subjects
    3. ONE batch sync at end with date filtering
    4. Return sync summary
    
    Returns:
        dict: {success, data: {created_count, deleted_count, sync_summary}, message}
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
        
        frappe.logger().info(f"BATCH UPDATE DEBUG - Received data keys: {list(data.keys())}")
        
        # Extract values from data
        teacher_id = data.get('teacher_id')
        assignments = data.get('assignments', [])
        deleted_assignment_ids = data.get('deleted_assignment_ids', [])
        
        frappe.logger().info(f"BATCH UPDATE DEBUG - teacher_id={teacher_id}, assignments count={len(assignments)}, deleted count={len(deleted_assignment_ids)}")
            
        # Validate required parameters
        if not teacher_id:
            return validation_error_response(
                message="Teacher ID is required",
                errors={"teacher_id": ["Teacher ID is required"]}
            )
        if assignments is None:
            return validation_error_response(
                message="Assignments are required",
                errors={"assignments": ["Assignments are required"]}
            )
        
        campus_id = get_current_campus_from_context() or "campus-1"
        
        # Parse input if string
        if isinstance(assignments, str):
            assignments = json.loads(assignments)
        if isinstance(deleted_assignment_ids, str):
            deleted_assignment_ids = json.loads(deleted_assignment_ids)
        
        # Verify teacher
        if not frappe.db.exists("SIS Teacher", {"name": teacher_id, "campus_id": campus_id}):
            return forbidden_response("Access denied")
        
        # Track changes for sync
        affected_classes = set()
        affected_subjects = set()
        created_count = 0
        deleted_count = 0
        
        frappe.db.begin()
        
        try:
            # STEP 1: Delete removed assignments (FAST)
            for assignment_id in deleted_assignment_ids:
                try:
                    doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
                    if doc.teacher_id == teacher_id and doc.campus_id == campus_id:
                        affected_classes.add(doc.class_id)
                        affected_subjects.add(doc.actual_subject_id)
                        frappe.delete_doc("SIS Subject Assignment", assignment_id, force=1)
                        deleted_count += 1
                except:
                    continue
            
            # STEP 2: Process new/updated assignments (FAST - no sync)
            for item in assignments:
                class_id = item.get('class_id')
                subject_ids = item.get('subject_ids', [])
                application_type = item.get('application_type', 'full_year')
                start_date = item.get('start_date')
                end_date = item.get('end_date')
                
                if not class_id or not subject_ids:
                    continue
                
                affected_classes.add(class_id)
                
                # Validate date if from_date type
                if application_type == 'from_date' and not start_date:
                    frappe.logger().warning(f"Missing start_date for from_date assignment: {class_id}")
                    continue
                
                for subject_id in subject_ids:
                    affected_subjects.add(subject_id)
                    
                    # Check if exists
                    existing = frappe.db.exists("SIS Subject Assignment", {
                        "teacher_id": teacher_id,
                        "class_id": class_id,
                        "actual_subject_id": subject_id,
                        "campus_id": campus_id
                    })
                    
                    if not existing:
                        # Create new assignment with date fields
                        doc = frappe.get_doc({
                            "doctype": "SIS Subject Assignment",
                            "teacher_id": teacher_id,
                            "class_id": class_id,
                            "actual_subject_id": subject_id,
                            "campus_id": campus_id,
                            "application_type": application_type,
                            "start_date": start_date,
                            "end_date": end_date
                        })
                        doc.insert(ignore_permissions=True)
                        created_count += 1
                    else:
                        # Check if application_type or dates are different - if so, UPDATE
                        existing_doc = frappe.get_doc("SIS Subject Assignment", existing)
                        old_application_type = getattr(existing_doc, 'application_type', 'full_year')
                        old_start_date = getattr(existing_doc, 'start_date', None)
                        old_end_date = getattr(existing_doc, 'end_date', None)
                        
                        # Convert dates for comparison
                        def normalize_date(d):
                            if d is None or d == '':
                                return None
                            if isinstance(d, str):
                                from datetime import datetime
                                try:
                                    return datetime.strptime(d, '%Y-%m-%d').date()
                                except:
                                    return None
                            if hasattr(d, 'date'):
                                return d.date()
                            return d
                        
                        old_start_normalized = normalize_date(old_start_date)
                        old_end_normalized = normalize_date(old_end_date)
                        new_start_normalized = normalize_date(start_date)
                        new_end_normalized = normalize_date(end_date)
                        
                        is_modified = False
                        if old_application_type != application_type:
                            existing_doc.application_type = application_type
                            is_modified = True
                        
                        if old_start_normalized != new_start_normalized:
                            existing_doc.start_date = start_date
                            is_modified = True
                        
                        if old_end_normalized != new_end_normalized:
                            existing_doc.end_date = end_date
                            is_modified = True
                        
                        if is_modified:
                            # Delete override rows before saving if changing to full_year
                            if old_application_type == "from_date" and application_type == "full_year":
                                try:
                                    subject_mapping = frappe.db.sql("""
                                        SELECT name FROM `tabSIS Subject`
                                        WHERE actual_subject_id = %s AND campus_id = %s
                                    """, (subject_id, campus_id), as_dict=True)
                                    
                                    if subject_mapping:
                                        subj_ids = [s.name for s in subject_mapping]
                                        delete_teacher_override_rows(
                                            teacher_id,
                                            subj_ids,
                                            [class_id],
                                            campus_id
                                        )
                                except Exception as del_err:
                                    frappe.logger().error(f"Failed to delete override rows: {str(del_err)}")
                            
                            existing_doc.save(ignore_permissions=True)
                            frappe.logger().info(f"BATCH UPDATE - Updated assignment {existing}")
                            created_count += 1
            
            frappe.db.commit()
            
        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(f"Error in batch update: {str(e)}")
            return error_response(f"Failed to update assignments: {str(e)}")
        
        # STEP 3: SMART BATCH SYNC (once, after all changes)
        sync_summary = batch_sync_timetable_optimized(
            teacher_id=teacher_id,
            affected_classes=list(affected_classes),
            affected_subjects=list(affected_subjects),
            campus_id=campus_id
        )
        
        frappe.logger().info(f"BATCH UPDATE - Teacher {teacher_id}: Created {created_count}, Deleted {deleted_count}, Sync: {sync_summary}")
        
        return success_response({
            "created_count": created_count,
            "deleted_count": deleted_count,
            "sync_summary": sync_summary
        }, message=f"Đã cập nhật {created_count + deleted_count} phân công thành công. Đồng bộ thời khóa biểu: {sync_summary.get('rows_updated', 0)} ô được cập nhật.")
        
    except Exception as e:
        frappe.log_error(f"Error in batch_update_teacher_assignments: {str(e)}")
        return error_response(str(e))


def bulk_update_timetable_internal(data):
    """
    Internal function for bulk updating timetable instances.
    
    Returns dict with results, not API response.
    
    Args:
        data: dict with assignment info
        
    Returns:
        dict: {updated_rows, skipped_rows, summary}
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
                        not old_teacher_id
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
                        if row_doc.teacher_1_id == old_teacher_id:
                            row_doc.teacher_1_id = new_teacher_id
                            updated_fields.append("teacher_1_id")
                        if row_doc.teacher_2_id == old_teacher_id:
                            row_doc.teacher_2_id = new_teacher_id  
                            updated_fields.append("teacher_2_id")
                    else:
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
    """
    Bulk update timetable instances when Subject Assignment changes.
    
    Updates all future timetable instances from current date forward.
    
    Input:
    {
        "assignment_id": "SIS-SUBJECT-ASSIGNMENT-001",
        "old_teacher_id": "teacher-001",  // optional
        "new_teacher_id": "teacher-002",
        "class_id": "class-1a",  // optional
        "actual_subject_id": "math"  // optional
    }
    
    Returns:
        dict: {success, data: result, message}
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
        result = bulk_update_timetable_internal(data)
        
        frappe.db.commit()
        
        return success_response(
            data=result,
            message=f"Bulk update completed: {result['summary']['rows_updated']} rows updated in {result['summary']['instances_checked']} future instances"
        )
        
    except Exception as e:
        frappe.log_error(f"Error in bulk_update_timetable_from_assignment: {str(e)}")
        return error_response(f"Error updating timetables: {str(e)}")

