"""
CRUD Operation Logging Handler
Logs critical CRUD operations for audit trail and data loss investigation
"""

import frappe
from erp.utils.centralized_logger import log_crud_operation, log_error


def get_field_changes(doc, old_doc):
    """Get changed fields between old and new document"""
    changes = {}
    if not old_doc:
        return changes
    
    for field in doc.meta.get_valid_columns():
        old_value = old_doc.get(field)
        new_value = doc.get(field)
        
        if old_value != new_value:
            changes[field] = {
                'old': old_value,
                'new': new_value
            }
    
    return changes


def log_create(doc, method=None, **kwargs):
    """Log document creation"""
    try:
        user = frappe.session.user
        doctype = doc.doctype
        docname = doc.name
        
        # Get key fields based on doctype
        key_fields = _get_key_fields(doctype)
        details = {field: doc.get(field) for field in key_fields if field in doc}
        details['timestamp'] = frappe.utils.now()
        
        log_crud_operation(
            doctype=doctype,
            operation='create',
            docname=docname,
            user=user,
            changes=None,
            details=details
        )
    except Exception as e:
        frappe.errprint(f"Error logging CRUD create: {str(e)}")


def log_update(doc, method=None, **kwargs):
    """Log document update"""
    try:
        user = frappe.session.user
        doctype = doc.doctype
        docname = doc.name
        
        # Get old document to track changes
        old_doc = doc.get_doc_before_save() if hasattr(doc, 'get_doc_before_save') else None
        changes = get_field_changes(doc, old_doc) if old_doc else {}
        
        details = {
            'timestamp': frappe.utils.now(),
            'modified_at': doc.modified if hasattr(doc, 'modified') else None
        }
        
        log_crud_operation(
            doctype=doctype,
            operation='update',
            docname=docname,
            user=user,
            changes=changes,
            details=details
        )
    except Exception as e:
        frappe.errprint(f"Error logging CRUD update: {str(e)}")


def log_delete(doc, method=None, **kwargs):
    """Log document deletion"""
    try:
        user = frappe.session.user
        doctype = doc.doctype
        docname = doc.name
        
        # Store key information before deletion
        key_fields = _get_key_fields(doctype)
        details = {field: doc.get(field) for field in key_fields if field in doc}
        details['timestamp'] = frappe.utils.now()
        details['deleted_at'] = frappe.utils.now()
        
        log_crud_operation(
            doctype=doctype,
            operation='delete',
            docname=docname,
            user=user,
            changes=None,
            details=details
        )
    except Exception as e:
        frappe.errprint(f"Error logging CRUD delete: {str(e)}")


def log_cancel(doc, method=None, **kwargs):
    """Log document cancellation"""
    try:
        user = frappe.session.user
        doctype = doc.doctype
        docname = doc.name
        
        details = {
            'timestamp': frappe.utils.now(),
            'cancelled_at': frappe.utils.now()
        }
        
        log_crud_operation(
            doctype=doctype,
            operation='cancel',
            docname=docname,
            user=user,
            changes=None,
            details=details
        )
    except Exception as e:
        frappe.errprint(f"Error logging CRUD cancel: {str(e)}")


def _get_key_fields(doctype: str) -> list:
    """Get key fields to track for a doctype"""
    key_fields_map = {
        'Student': ['name', 'student_name', 'student_code', 'dob', 'gender', 'campus_id'],
        'Guardian': ['name', 'guardian_id', 'guardian_name', 'phone_number', 'email', 'family_code'],
        'SIS Class Student': ['name', 'campus_id', 'class_id', 'student_id', 'school_year_id'],
        'SIS Class Attendance': ['name', 'student_id', 'class_id', 'date', 'status', 'remarks'],
        'SIS Event': ['name', 'title', 'start_time', 'end_time', 'status', 'campus_id'],
        'SIS Class': ['name', 'title', 'school_year_id', 'education_grade', 'homeroom_teacher'],
        'SIS Teacher': ['name', 'user_id', 'campus_id', 'education_stage_id', 'subject_department_id'],
        'SIS Subject': ['name', 'title', 'education_stage', 'campus_id'],
        'SIS Curriculum': ['name', 'title_vn', 'title_en', 'campus_id'],
        'SIS Actual Subject': ['name', 'title_vn', 'title_en', 'education_stage_id', 'curriculum_id'],
        'SIS Timetable': ['name', 'title_vn', 'title_en', 'school_year_id', 'education_stage_id'],
        'SIS Timetable Subject': ['name', 'title_vn', 'title_en', 'education_stage_id', 'curriculum_id'],
        'SIS Photo': ['name', 'title', 'type', 'school_year_id', 'student_id'],
        'SIS School Year': ['name', 'title_vn', 'title_en', 'start_date', 'end_date', 'is_enable'],
        'SIS Education Stage': ['name', 'title_vn', 'title_en', 'campus_id'],
        'SIS Education Grade': ['name', 'title_vn', 'title_en', 'education_stage_id', 'grade_code'],
        'SIS Academic Program': ['name', 'title_vn', 'title_en', 'campus_id'],
        'SIS Sub Curriculum': ['name', 'title_vn', 'title_en', 'curriculum_id', 'campus_id'],
        'SIS Calendar': ['name', 'title', 'type', 'school_year_id', 'start_date'],
        'SIS Subject Assignment': ['name', 'teacher_id', 'actual_subject_id', 'class_id', 'application_type'],
        'Feedback': ['name', 'guardian', 'feedback_type', 'status', 'title'],
        'SIS Student Leave Request': ['name', 'student_id', 'start_date', 'end_date', 'reason', 'campus_id'],
        'SIS Announcement': ['name', 'title_vn', 'title_en', 'status', 'campus_id'],
        'SIS News Article': ['name', 'title_vn', 'title_en', 'status', 'published_at'],
        'Daily Menu': ['name', 'date', 'campus'],
        'SIS Bus Route': ['name', 'route_name', 'driver_id', 'status', 'campus_id'],
        'SIS Bus Student': ['name', 'student_code', 'route_id', 'status', 'campus_id'],
        'SIS Bus Daily Trip': ['name', 'route_id', 'trip_date', 'trip_status', 'trip_type'],
        'SIS Badge': ['name', 'title_vn', 'title_en', 'is_active'],
    }
    
    return key_fields_map.get(doctype, ['name'])

