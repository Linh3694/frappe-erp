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

# Batch operations - V2 (Migrated)
from .batch_operations_v2 import (
    batch_update_assignments,
    validate_all_assignments,
    apply_all_assignments,
    sync_all_assignments
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
from .batch_operations import (
    bulk_update_timetable_from_assignment
)

# Backward compatibility wrapper
def batch_update_teacher_assignments():
    """
    Backward compatibility wrapper for V2 batch_update_assignments.
    
    Transforms V2 response format to match V1 format expected by frontend.
    
    DEPRECATED: This function will be removed in future versions.
    Please use batch_update_assignments() directly.
    """
    result = batch_update_assignments()
    
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
    'bulk_update_timetable_from_assignment',
    
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

