# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Subject Assignment Module

Quản lý phân công giáo viên dạy môn học.

Module structure:
- assignment_api.py: Core CRUD operations
- assignment_queries.py: Query & dropdown helpers
- timetable_sync.py: Timetable synchronization logic
- batch_operations.py: Batch update operations
- date_override_handler.py: Date-specific override handling
- utils.py: Utility functions
"""

import frappe

# Core CRUD APIs
from .assignment_api import (
    get_all_subject_assignments,
    get_teacher_assignment_details,
    get_subject_assignment_by_id,
    create_subject_assignment,
    update_subject_assignment,
    delete_subject_assignment
)

# Query & Dropdown helpers
from .assignment_queries import (
    get_teachers_with_assignment_summary,
    get_teachers_for_assignment,
    get_subjects_for_assignment,
    get_education_grades_for_teacher,
    get_classes_for_teacher,
    get_classes_for_education_grade,
    get_subjects_for_class,
    get_my_subjects_for_class
)

# Batch operations - V2 (Refactored & Optimized)
from .batch_operations import (
    batch_update_assignments,
    validate_all_assignments,
    apply_all_assignments,
    sync_all_assignments,
    sync_teacher_timetable_bulk
)

# Timetable sync - V2 (Migrated)
from .timetable_sync_v2 import (
    sync_assignment_to_timetable,
    sync_full_year_assignment,
    sync_date_range_assignment,
    validate_assignment_for_sync,
    find_pattern_rows,
    get_subject_id_from_actual,
    enqueue_materialized_view_sync,
    batch_sync_assignments
)

# Legacy V1 imports for backward compatibility (deprecated - will be removed)
from .timetable_sync import (
    batch_sync_timetable_optimized,
    sync_teacher_timetable_after_assignment,
    sync_timetable_from_date,
    sync_materialized_views_background
)

# Backward compatibility wrapper
@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_update_teacher_assignments():
    """
    Backward compatibility wrapper for V2 batch_update_assignments.
    
    Transforms V2 response format to match V1 format expected by frontend.
    
    DEPRECATED: This function will be removed in future versions.
    Please use batch_update_assignments() directly.
    """
    import json
    
    try:
        # Parse request data from V1 format
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
        
        # Extract V1 format
        teacher_id = data.get('teacher_id')
        assignments_v1 = data.get('assignments', [])
        deleted_assignment_ids = data.get('deleted_assignment_ids', [])
        
        # Parse if string
        if isinstance(assignments_v1, str):
            assignments_v1 = json.loads(assignments_v1)
        if isinstance(deleted_assignment_ids, str):
            deleted_assignment_ids = json.loads(deleted_assignment_ids)
        
        # Validate teacher_id
        if not teacher_id:
            return {
                "success": False,
                "message": "teacher_id is required"
            }
        
        # Transform V1 format to V2 format
        assignments_v2 = []
        
        # Add delete actions
        for assignment_id in deleted_assignment_ids:
            assignments_v2.append({
                "assignment_id": assignment_id,
                "action": "delete"
            })
        
        # Get teacher campus once
        teacher_campus = frappe.db.get_value("SIS Teacher", teacher_id, "campus_id")
        
        # Add create/update actions from V1 assignments
        # In V1, all items in assignments array are treated as "create or update if exists"
        for item in assignments_v1:
            class_id = item.get('class_id')
            subject_ids = item.get('subject_ids', [])
            application_type = item.get('application_type', 'full_year')
            start_date = item.get('start_date')
            end_date = item.get('end_date')
            
            if not class_id or not subject_ids:
                continue
            
            for subject_id in subject_ids:
                # Check if assignment exists
                existing = frappe.db.exists("SIS Subject Assignment", {
                    "teacher_id": teacher_id,
                    "class_id": class_id,
                    "actual_subject_id": subject_id,
                    "campus_id": teacher_campus
                })
                
                assignment_data = {
                    "class_id": class_id,
                    "actual_subject_id": subject_id,
                    "application_type": application_type,
                    "start_date": start_date,
                    "end_date": end_date
                }
                
                if existing:
                    assignment_data["assignment_id"] = existing
                    assignment_data["action"] = "update"
                else:
                    assignment_data["action"] = "create"
                
                assignments_v2.append(assignment_data)
        
        # Call V2 function directly with parameters (no request parsing)
        result = batch_update_assignments(teacher_id=teacher_id, assignments=assignments_v2)
        
        if not result.get("success"):
            return result
        
        # Transform V2 response to V1 format
        stats = result.get("stats", {})
        return {
            "success": True,
            "message": result.get("message", ""),
            "created_count": stats.get("created", 0),
            "deleted_count": stats.get("deleted", 0),
            "sync_summary": {
                "rows_updated": stats.get("synced", 0),
                "rows_skipped": 0,
                "instances_checked": 0,
                "message": result.get("message", "")
            }
        }
    
    except Exception as e:
        frappe.log_error(f"Error in batch_update_teacher_assignments wrapper: {str(e)}")
        return {
            "success": False,
            "message": f"Error: {str(e)}"
        }

# Date override handlers (internal)
from .date_override_handler import (
    create_date_override_row,
    calculate_dates_in_range,
    delete_teacher_override_rows
)

# Utilities (internal)
from .utils import fix_subject_linkages


__all__ = [
    # Core CRUD APIs
    'get_all_subject_assignments',
    'get_teacher_assignment_details',
    'get_subject_assignment_by_id',
    'create_subject_assignment',
    'update_subject_assignment',
    'delete_subject_assignment',
    
    # Query & Dropdown helpers
    'get_teachers_with_assignment_summary',
    'get_teachers_for_assignment',
    'get_subjects_for_assignment',
    'get_education_grades_for_teacher',
    'get_classes_for_teacher',
    'get_classes_for_education_grade',
    'get_subjects_for_class',
    'get_my_subjects_for_class',
    
    # Batch operations - V2
    'batch_update_assignments',
    'validate_all_assignments',
    'apply_all_assignments',
    'sync_all_assignments',
    
    # Batch operations - V1 (backward compat - deprecated)
    'batch_update_teacher_assignments',
    
    # Timetable sync - V2
    'sync_assignment_to_timetable',
    'sync_full_year_assignment',
    'sync_date_range_assignment',
    'validate_assignment_for_sync',
    'find_pattern_rows',
    'get_subject_id_from_actual',
    'enqueue_materialized_view_sync',
    'batch_sync_assignments',
    
    # Timetable sync - V1 (backward compat - deprecated)
    'batch_sync_timetable_optimized',
    'sync_teacher_timetable_after_assignment',
    'sync_timetable_from_date',
    'sync_materialized_views_background',
    
    # Internal functions
    'create_date_override_row',
    'calculate_dates_in_range',
    'delete_teacher_override_rows',
    'fix_subject_linkages',
]

