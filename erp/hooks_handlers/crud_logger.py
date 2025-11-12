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
        'Student': ['name', 'first_name', 'last_name', 'email', 'student_status', 'active_class'],
        'Guardian': ['name', 'fullname', 'email', 'relationship_to_student', 'is_primary'],
        'SIS Class Student': ['name', 'student', 'class', 'status', 'enrollment_date'],
        'SIS Class Attendance': ['name', 'student', 'class', 'date', 'status', 'attendance_type'],
        'SIS Event': ['name', 'title', 'event_type', 'status', 'start_datetime', 'end_datetime'],
        'SIS Class': ['name', 'class_name', 'academic_year', 'level', 'education_grade', 'primary_teacher'],
        'SIS Teacher': ['name', 'user', 'fullname', 'email', 'departments'],
        'SIS Subject': ['name', 'subject_name', 'code', 'subject_type'],
        'SIS Curriculum': ['name', 'curriculum_name', 'academic_year', 'education_stage'],
        'SIS Actual Subject': ['name', 'subject', 'class', 'teacher', 'credit_hours'],
        'SIS Timetable': ['name', 'timetable_name', 'academic_year', 'class'],
        'SIS Timetable Subject': ['name', 'subject', 'timetable', 'day_of_week', 'start_time'],
        'SIS Photo': ['name', 'student', 'photo_type', 'academic_year'],
        'SIS School Year': ['name', 'year', 'start_date', 'end_date', 'status'],
        'SIS Education Stage': ['name', 'stage_name', 'sequence'],
        'SIS Education Grade': ['name', 'grade_name', 'education_stage'],
        'SIS Academic Program': ['name', 'program_name', 'education_stage'],
        'SIS Sub Curriculum': ['name', 'title', 'curriculum', 'sequence'],
        'SIS Calendar': ['name', 'calendar_name', 'academic_year'],
        'SIS Subject Assignment': ['name', 'teacher', 'subject', 'class', 'semester'],
        'Feedback': ['name', 'student', 'giver_type', 'rating', 'category'],
        'SIS Student Leave Request': ['name', 'student', 'from_date', 'to_date', 'status', 'reason'],
        'SIS Announcement': ['name', 'title', 'content', 'start_date', 'target_audience'],
        'SIS News Article': ['name', 'title', 'content', 'publish_date'],
        'Daily Menu': ['name', 'date', 'campus'],
        'SIS Bus Route': ['name', 'route_name', 'campus', 'driver_name'],
        'SIS Bus Student': ['name', 'student', 'bus_route', 'status'],
        'SIS Bus Daily Trip': ['name', 'bus_route', 'trip_date', 'status'],
        'SIS Badge': ['name', 'badge_name', 'badge_type', 'icon'],
    }
    
    return key_fields_map.get(doctype, ['name'])

