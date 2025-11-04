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

# Batch operations
from .batch_operations import (
    batch_update_teacher_assignments,
    bulk_update_timetable_from_assignment
)

# Timetable sync (internal - not exposed as API)
from .timetable_sync import (
    batch_sync_timetable_optimized,
    sync_teacher_timetable_after_assignment,
    sync_timetable_from_date,
    sync_materialized_views_background
)

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
    
    # Batch operations
    'batch_update_teacher_assignments',
    'bulk_update_timetable_from_assignment',
    
    # Internal functions (for use within module)
    'batch_sync_timetable_optimized',
    'sync_teacher_timetable_after_assignment',
    'sync_timetable_from_date',
    'sync_materialized_views_background',
    'create_date_override_row',
    'calculate_dates_in_range',
    'delete_teacher_override_rows',
    'fix_subject_linkages',
]

