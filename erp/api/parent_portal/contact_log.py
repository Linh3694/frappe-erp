"""
Parent Portal Contact Log API
Allows parents to view contact logs from teachers
"""

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response


def _get_current_parent():
    """Get current logged in parent/guardian"""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None

    # Extract guardian_id from email (format: guardian_id@parent.wellspring.edu.vn)
    if "@parent.wellspring.edu.vn" not in user_email:
        return None

    guardian_id = user_email.split("@")[0]

    # Get the actual guardian name from guardian_id field
    guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
    return guardian


def _get_parent_students(parent_id):
    """Get all students for this parent"""
    if not parent_id:
        return []
    
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"parent": parent_id},
        fields=["student"]
    )
    
    return [rel.student for rel in relationships if rel.student]


def _get_badge_info(badge_id):
    """Get badge display info"""
    badge = frappe.get_value(
        "SIS Contact Log Badge",
        badge_id,
        ["badge_name", "badge_name_en", "badge_color"],
        as_dict=True
    )
    if badge:
        return {
            "id": badge_id,
            "name": badge.badge_name,
            "name_en": badge.badge_name_en,
            "color": badge.badge_color
        }
    return {"id": badge_id, "name": badge_id}


@frappe.whitelist(allow_guest=False)
def get_student_contact_logs(student_id=None, from_date=None, to_date=None, limit=50):
    """
    Get contact logs for a student (parent view)
    Only shows logs that are "Sent" status (not Draft or Recalled)
    """
    try:
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response(message="Not authenticated as parent", code="AUTH_ERROR")
        
        # Get parent's students
        parent_students = _get_parent_students(parent_id)
        if not parent_students:
            return success_response(data=[], message="No students found")
        
        # If specific student requested, validate access
        if student_id:
            if student_id not in parent_students:
                return error_response(message="Access denied to this student", code="PERMISSION_ERROR")
            student_filter = [student_id]
        else:
            student_filter = parent_students
        
        # Build filters for class log subject
        subject_filters = {}
        if from_date:
            subject_filters["log_date"] = [">=", from_date]
        if to_date:
            if "log_date" in subject_filters:
                subject_filters["log_date"] = [[">=", from_date], ["<=", to_date]]
            else:
                subject_filters["log_date"] = ["<=", to_date]
        
        # Get class log subjects
        subjects = frappe.get_all(
            "SIS Class Log Subject",
            filters=subject_filters,
            fields=["name", "class_id", "log_date", "period", "recorded_by"],
            order_by="log_date desc",
            limit_page_length=limit
        )
        
        if not subjects:
            return success_response(data=[], message="No contact logs found")
        
        subject_ids = [s['name'] for s in subjects]
        
        # Get student logs - only "Sent" status (not Draft or Recalled)
        student_logs = frappe.get_all(
            "SIS Class Log Student",
            filters={
                "subject_id": ["in", subject_ids],
                "student_id": ["in", student_filter],
                "contact_log_status": "Sent"  # Only show sent logs
            },
            fields=[
                "name",
                "subject_id",
                "student_id",
                "badges",
                "contact_log_comment",
                "contact_log_status",
                "contact_log_sent_by",
                "contact_log_sent_at",
                "contact_log_viewed_count"
            ],
            order_by="contact_log_sent_at desc"
        )
        
        # Build result with subject info
        subject_map = {s['name']: s for s in subjects}
        
        results = []
        for log in student_logs:
            subject = subject_map.get(log['subject_id'])
            if not subject:
                continue
            
            # Parse badges
            badges = []
            if log.get('badges'):
                try:
                    badge_ids = json.loads(log['badges'])
                    badges = [_get_badge_info(bid) for bid in badge_ids]
                except:
                    pass
            
            # Get teacher name
            teacher_name = frappe.get_value("SIS Teacher", {"user": log['contact_log_sent_by']}, "teacher_name")
            if not teacher_name:
                teacher_name = frappe.get_value("User", log['contact_log_sent_by'], "full_name")
            
            # Get student name
            student_name = frappe.get_value("CRM Student", log['student_id'], "student_name")
            
            # Get class name
            class_name = frappe.get_value("SIS Class", subject['class_id'], "class_name")
            
            results.append({
                "id": log['name'],
                "student_id": log['student_id'],
                "student_name": student_name,
                "class_id": subject['class_id'],
                "class_name": class_name,
                "log_date": subject['log_date'],
                "period": subject['period'],
                "comment": log.get('contact_log_comment'),
                "badges": badges,
                "teacher_name": teacher_name,
                "sent_by": log['contact_log_sent_by'],
                "sent_at": log['contact_log_sent_at'],
                "viewed_count": log.get('contact_log_viewed_count') or 0
            })
        
        return success_response(
            data=results,
            message=f"Found {len(results)} contact logs"
        )
    
    except Exception as e:
        frappe.log_error(f"get_student_contact_logs error: {str(e)}")
        return error_response(message="Failed to fetch contact logs", code="GET_CONTACT_LOGS_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def mark_contact_log_viewed(log_id):
    """
    Mark a contact log as viewed by parent
    Creates a view record and increments viewed count
    """
    try:
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response(message="Not authenticated as parent", code="AUTH_ERROR")
        
        # Get the student log
        student_log = frappe.get_doc("SIS Class Log Student", log_id)
        
        # Validate parent has access to this student
        parent_students = _get_parent_students(parent_id)
        if student_log.student_id not in parent_students:
            return error_response(message="Access denied", code="PERMISSION_ERROR")
        
        # Check if already viewed by this parent
        existing = frappe.db.exists(
            "SIS Contact Log View",
            {
                "class_log_student": log_id,
                "parent_user": frappe.session.user
            }
        )
        
        if existing:
            return success_response(message="Already marked as viewed")
        
        # Create view record (this will auto-increment viewed_count via before_insert hook)
        view_doc = frappe.get_doc({
            "doctype": "SIS Contact Log View",
            "class_log_student": log_id,
            "parent_user": frappe.session.user,
            "student_id": student_log.student_id,
            "viewed_at": frappe.utils.now_datetime()
        })
        view_doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
        return success_response(
            message="Contact log marked as viewed",
            data={"viewed": True}
        )
    
    except Exception as e:
        frappe.log_error(f"mark_contact_log_viewed error: {str(e)}")
        return error_response(message="Failed to mark as viewed", code="MARK_VIEWED_ERROR")


@frappe.whitelist(allow_guest=False)
def get_unread_contact_logs_count(student_id=None):
    """
    Get count of unread contact logs for parent
    """
    try:
        parent_id = _get_current_parent()
        if not parent_id:
            return error_response(message="Not authenticated as parent", code="AUTH_ERROR")
        
        # Get parent's students
        parent_students = _get_parent_students(parent_id)
        if not parent_students:
            return success_response(data={"count": 0})
        
        # If specific student requested, validate access
        if student_id:
            if student_id not in parent_students:
                return error_response(message="Access denied", code="PERMISSION_ERROR")
            student_filter = [student_id]
        else:
            student_filter = parent_students
        
        # Get all sent logs for these students
        sent_logs = frappe.get_all(
            "SIS Class Log Student",
            filters={
                "student_id": ["in", student_filter],
                "contact_log_status": "Sent"
            },
            fields=["name"]
        )
        
        if not sent_logs:
            return success_response(data={"count": 0})
        
        sent_log_ids = [log['name'] for log in sent_logs]
        
        # Get logs already viewed by this parent
        viewed_logs = frappe.get_all(
            "SIS Contact Log View",
            filters={
                "class_log_student": ["in", sent_log_ids],
                "parent_user": frappe.session.user
            },
            fields=["class_log_student"]
        )
        
        viewed_log_ids = [v['class_log_student'] for v in viewed_logs]
        
        # Unread = sent - viewed
        unread_count = len(sent_log_ids) - len(viewed_log_ids)
        
        return success_response(
            data={"count": unread_count},
            message=f"{unread_count} unread contact logs"
        )
    
    except Exception as e:
        frappe.log_error(f"get_unread_contact_logs_count error: {str(e)}")
        return error_response(message="Failed to get unread count", code="GET_UNREAD_COUNT_ERROR")

