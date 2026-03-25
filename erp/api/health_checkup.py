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
    import_health_checkup,
    get_health_checkup_session_meta,
    save_health_checkup_session_meta,
    submit_student_health_checkup,
    submit_student_health_checkup_bulk,
    approve_health_checkup_l2,
    reject_health_checkup_l2,
    approve_health_checkup_l3,
    reject_health_checkup_l3,
    revoke_health_checkup_l3,
    get_health_checkup_approval_queue_l2,
    get_class_periodic_health_checkups,
    upload_health_checkup_images,
    delete_health_checkup_images,
    get_health_checkup_images,
)

__all__ = [
    'get_students_health_checkup',
    'get_student_health_checkup',
    'save_student_health_checkup',
    'export_health_checkup',
    'import_health_checkup',
    'get_health_checkup_session_meta',
    'save_health_checkup_session_meta',
    'submit_student_health_checkup',
    'submit_student_health_checkup_bulk',
    'approve_health_checkup_l2',
    'reject_health_checkup_l2',
    'approve_health_checkup_l3',
    'reject_health_checkup_l3',
    'revoke_health_checkup_l3',
    'get_health_checkup_approval_queue_l2',
    'get_class_periodic_health_checkups',
    'upload_health_checkup_images',
    'delete_health_checkup_images',
    'get_health_checkup_images',
]
