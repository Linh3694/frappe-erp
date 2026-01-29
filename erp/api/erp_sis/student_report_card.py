# -*- coding: utf-8 -*-
"""
Student Report Card APIs
========================

DEPRECATED: File này được giữ lại để backward compatible.
Code thực tế đã được move vào package erp.api.erp_sis.report_card/student_report.py

Tất cả imports và API paths cũ vẫn hoạt động bình thường.
"""

# Re-export tất cả APIs từ package mới
from erp.api.erp_sis.report_card.student_report import (
    create_reports_for_class,
    get_reports_by_class,
    list_reports,
    get_report,
    get_report_by_id,
    update_report_section,
    delete_report,
    sync_new_subjects_to_reports,
    get_previous_semester_score,
    update_report_field,
)

# Export cho backward compatibility
__all__ = [
    "create_reports_for_class",
    "get_reports_by_class",
    "list_reports",
    "get_report",
    "get_report_by_id",
    "update_report_section",
    "delete_report",
    "sync_new_subjects_to_reports",
    "get_previous_semester_score",
    "update_report_field",
]
