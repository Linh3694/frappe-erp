# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Daily Health Visit API - Proxy module
Exposes daily health API at /api/method/erp.api.daily_health.xxx
"""

# Import và re-export tất cả functions từ erp_sis.daily_health
from erp.api.erp_sis.daily_health import (
    report_student_to_clinic,
    get_daily_health_visits,
    receive_student_at_clinic,
    create_health_examination,
    update_health_examination,
    get_student_examination_history,
    get_students_at_clinic,
    complete_health_visit
)

__all__ = [
    'report_student_to_clinic',
    'get_daily_health_visits',
    'receive_student_at_clinic',
    'create_health_examination',
    'update_health_examination',
    'get_student_examination_history',
    'get_students_at_clinic',
    'complete_health_visit'
]
