# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Excel Import - Backward Compatibility Wrapper

⚠️ REFACTORED: This file now imports from the modular timetable/ package.

The Excel import logic is now organized in timetable/import_excel.py
Core processing logic remains in timetable/excel_import_legacy.py until full migration.

Date: 2025-01-14
Migration: Partial (API endpoints migrated, core logic pending)
"""

# Re-export Excel import functions from new structure
from .timetable.import_excel import (
    import_timetable,
    get_import_job_status,
    save_uploaded_file
)

# Core processing classes and functions still in legacy file (moved to timetable/)
# These are internal and will be migrated later
# from .timetable.excel_import_legacy import (
#     TimetableExcelImporter,
#     process_excel_import_with_metadata_v2,
#     process_excel_import_background,
#     sync_materialized_views_for_instance
# )

__all__ = [
    "import_timetable",
    "get_import_job_status",
    "save_uploaded_file",
]

