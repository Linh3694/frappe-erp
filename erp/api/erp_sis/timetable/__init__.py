# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable API Module

Organized timetable operations with clear separation of concerns.

Structure:
- columns.py: Timetable column CRUD
- weeks.py: Weekly timetable queries
- import_excel.py: Excel import logic
- crud.py: Timetable CRUD
- instance_rows.py: Instance row operations
- overrides.py: Date-specific overrides
- helpers.py: Shared utility functions
"""

# Timetable Column operations
from .columns import (
    create_timetable_column,
    update_timetable_column,
    delete_timetable_column,
    get_education_stages_for_timetable_column
)

# Timetable CRUD operations
from .crud import (
    get_timetables,
    get_timetable_detail,
    delete_timetable,
    test_class_week_api
)

# Excel import operations
from .import_excel import (
    import_timetable,
    get_import_job_status,
    save_uploaded_file
)

# Excel import execution (NEW - validator + executor pattern)
from .import_executor import (
    process_with_new_executor,
    TimetableImportExecutor
)

from .import_validator import (
    TimetableImportValidator
)

# Weekly queries
from .weeks import (
    get_teacher_week,
    get_class_week
)

# Instance row operations
from .instance_rows import (
    get_instance_row_details,
    update_instance_row
)

# Date-specific overrides
from .overrides import (
    create_or_update_timetable_override,
    delete_timetable_override
)

# Helper functions (not exposed as API but available for internal use)
from .helpers import (
    format_time_for_html,
    _parse_iso_date,
    _add_days,
    _day_of_week_to_index,
    _build_entries,
    _apply_timetable_overrides,
    _get_request_arg
)

__all__ = [
    # Column operations
    "create_timetable_column",
    "update_timetable_column",
    "delete_timetable_column",
    "get_education_stages_for_timetable_column",
    
    # CRUD operations
    "get_timetables",
    "get_timetable_detail",
    "delete_timetable",
    "test_class_week_api",
    
    # Import operations
    "import_timetable",
    "get_import_job_status",
    "save_uploaded_file",
    
    # Import execution (NEW)
    "process_with_new_executor",
    "TimetableImportExecutor",
    "TimetableImportValidator",
    
    # Weekly queries
    "get_teacher_week",
    "get_class_week",
    
    # Instance row operations
    "get_instance_row_details",
    "update_instance_row",
    
    # Date-specific overrides
    "create_or_update_timetable_override",
    "delete_timetable_override",
    
    # Helper functions
    "format_time_for_html",
    "_parse_iso_date",
    "_add_days",
    "_day_of_week_to_index",
    "_build_entries",
    "_apply_timetable_overrides",
    "_get_request_arg",
]

