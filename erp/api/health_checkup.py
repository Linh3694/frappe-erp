# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Health Checkup API - Proxy module
Exposes health checkup API at /api/method/erp.api.health_checkup.xxx
"""

# Import và re-export tất cả functions từ erp_sis.health_checkup
from erp.api.erp_sis.health_checkup import (
    get_students_health_checkup,
    get_student_health_checkup,
    save_student_health_checkup,
    export_health_checkup,
    import_health_checkup
)

__all__ = [
    'get_students_health_checkup',
    'get_student_health_checkup',
    'save_student_health_checkup',
    'export_health_checkup',
    'import_health_checkup'
]
