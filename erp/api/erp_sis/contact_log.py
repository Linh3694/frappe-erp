"""
Contact Log API for Teacher -> Parent Communication
Handles badges, comments, and push notifications
"""

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.api.parent_portal.push_notification import send_push_notification


def _get_body():
    """Get request body"""
    try:
        if hasattr(frappe, 'request') and getattr(frappe.request, 'data', None):
            return json.loads(frappe.request.data.decode('utf-8'))
    except Exception:
        return {}
    return {}


def _validate_homeroom_teacher_access(class_id):
    """Validate that current user is homeroom or vice-homeroom teacher for this class"""
    user = frappe.session.user
    
    # Get class document
    class_doc = frappe.get_doc("SIS Class", class_id)
    
    # Check if user is homeroom or vice-homeroom teacher
    is_homeroom = (class_doc.homeroom_teacher == user) or (class_doc.vice_homeroom_teacher == user)
    
    if not is_homeroom:
        frappe.throw(_("Only homeroom or vice-homeroom teachers can manage contact logs"), frappe.PermissionError)
    
    return True


def _get_student_parent_emails(student_id):
    """Get all parent emails for a student"""
    # Query relationships to find parents
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"student": student_id},
        fields=["parent"]
    )
    
    parent_emails = []
    for rel in relationships:
        if rel.parent:
            # Get guardian document
            guardian = frappe.get_doc("CRM Guardian", rel.parent)
            if guardian.guardian_id:
                # Parent email format: guardian_id@parent.wellspring.edu.vn
                email = f"{guardian.guardian_id}@parent.wellspring.edu.vn"
                parent_emails.append(email)
    
    return parent_emails


def _get_badge_name(badge_id):
    """Get badge display name"""
    badge = frappe.get_value("SIS Contact Log Badge", badge_id, ["badge_name", "badge_name_en"], as_dict=True)
    if badge:
        return badge.badge_name or badge.badge_name_en or badge_id
    return badge_id


def _get_teacher_name(user_email):
    """Get teacher display name"""
    teacher = frappe.get_value("SIS Teacher", {"user": user_email}, "teacher_name")
    if teacher:
        return teacher
    
    # Fallback to user full name
    user = frappe.get_value("User", user_email, "full_name")
    return user or user_email


def _get_student_name(student_id):
    """Get student display name"""
    student = frappe.get_value("CRM Student", student_id, "student_name")
    return student or student_id


@frappe.whitelist(allow_guest=False)
def get_badges(education_stage=None):
    """Get available badges"""
    try:
        filters = {"is_active": 1}
        if education_stage:
            filters["education_stage"] = education_stage
        
        badges = frappe.get_all(
            "SIS Contact Log Badge",
            filters=filters,
            fields=["badge_id", "badge_name", "badge_name_en", "badge_color", "education_stage"],
            order_by="badge_name asc"
        )
        
        return success_response(data=badges, message="Badges fetched")
    except Exception as e:
        frappe.log_error(f"get_badges error: {str(e)}")
        return error_response(message="Failed to fetch badges", code="GET_BADGES_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_contact_log():
    """
    Save contact log (badges + comment) for students
    Does NOT send notification yet - just saves draft
    """
    try:
        body = _get_body() or {}
        class_id = body.get('class_id')
        date = body.get('date')
        students = body.get('students') or []
        
        if not class_id:
            return error_response(message="Missing class_id", code="MISSING_PARAMS")
        
        # Validate teacher access
        _validate_homeroom_teacher_access(class_id)
        
        saved_count = 0
        
        for student_data in students:
            student_id = student_data.get('student_id')
            badges = student_data.get('badges') or []
            comment = student_data.get('comment') or ""
            
            if not student_id:
                continue
            
            # Find or create class log student record
            # First, find the class log subject for this class/date
            filters = {"class_id": class_id}
            if date:
                filters["log_date"] = date
            
            subject_rows = frappe.get_all(
                "SIS Class Log Subject",
                filters=filters,
                fields=["name"],
                limit=1
            )
            
            if not subject_rows:
                # Need to create subject first
                from erp.sis.utils.campus_permissions import get_current_user_campus, get_user_campuses
                campus_id = None
                try:
                    campus_id = get_current_user_campus()
                    if not campus_id:
                        campuses = get_user_campuses(frappe.session.user)
                        campus_id = campuses[0] if campuses else None
                except Exception:
                    pass
                
                subject_doc = frappe.get_doc({
                    "doctype": "SIS Class Log Subject",
                    "class_id": class_id,
                    "log_date": date,
                    "recorded_by": frappe.session.user,
                    "campus_id": campus_id
                })
                subject_doc.insert()
                subject_id = subject_doc.name
            else:
                subject_id = subject_rows[0]['name']
            
            # Find or create student log
            student_log_rows = frappe.get_all(
                "SIS Class Log Student",
                filters={"subject_id": subject_id, "student_id": student_id},
                fields=["name"],
                limit=1
            )
            
            if student_log_rows:
                # Update existing
                student_log = frappe.get_doc("SIS Class Log Student", student_log_rows[0]['name'])
                student_log.badges = json.dumps(badges)
                student_log.contact_log_comment = comment
                student_log.contact_log_status = "Draft"
                student_log.save()
            else:
                # Create new
                student_log = frappe.get_doc({
                    "doctype": "SIS Class Log Student",
                    "subject_id": subject_id,
                    "student_id": student_id,
                    "badges": json.dumps(badges),
                    "contact_log_comment": comment,
                    "contact_log_status": "Draft"
                })
                student_log.insert()
            
            saved_count += 1
        
        frappe.db.commit()
        
        return success_response(
            message=f"Saved contact logs for {saved_count} students",
            data={"saved_count": saved_count}
        )
    
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"save_contact_log error: {str(e)}")
        return error_response(message="Failed to save contact log", code="SAVE_CONTACT_LOG_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def send_contact_log():
    """
    Send contact log to parents via push notification
    Updates status to "Sent" and sends push notifications
    """
    try:
        body = _get_body() or {}
        class_id = body.get('class_id')
        student_log_ids = body.get('student_log_ids') or []
        
        if not class_id or not student_log_ids:
            return error_response(message="Missing class_id or student_log_ids", code="MISSING_PARAMS")
        
        # Validate teacher access
        _validate_homeroom_teacher_access(class_id)
        
        teacher_name = _get_teacher_name(frappe.session.user)
        sent_count = 0
        failed_count = 0
        results = []
        
        for log_id in student_log_ids:
            try:
                # Get student log
                student_log = frappe.get_doc("SIS Class Log Student", log_id)
                
                # Update status
                student_log.contact_log_status = "Sent"
                student_log.contact_log_sent_by = frappe.session.user
                student_log.contact_log_sent_at = frappe.utils.now_datetime()
                student_log.save()
                
                # Get student name
                student_name = _get_student_name(student_log.student_id)
                
                # Parse badges
                badges_text = ""
                if student_log.badges:
                    try:
                        badge_list = json.loads(student_log.badges)
                        if badge_list:
                            badge_names = [_get_badge_name(badge_id) for badge_id in badge_list]
                            badges_text = "\n🏆 Huy hiệu: " + ", ".join(badge_names)
                    except:
                        pass
                
                # Get parent emails
                parent_emails = _get_student_parent_emails(student_log.student_id)
                
                if not parent_emails:
                    failed_count += 1
                    results.append({
                        "student_id": student_log.student_id,
                        "success": False,
                        "message": "No parent emails found"
                    })
                    continue
                
                # Send push notification to all parents
                notification_sent = False
                for email in parent_emails:
                    try:
                        title = f"📝 Nhận xét từ giáo viên - {student_name}"
                        body_text = f"Giáo viên {teacher_name} đã gửi nhận xét cho {student_name}.{badges_text}"
                        
                        if student_log.contact_log_comment:
                            comment = student_log.contact_log_comment
                            body_text += f"\n💬 Nhận xét: {comment[:100]}{'...' if len(comment) > 100 else ''}"
                        
                        result = send_push_notification(
                            user_email=email,
                            title=title,
                            body=body_text,
                            icon="/icon.png",
                            data={
                                "type": "contact_log",
                                "student_id": student_log.student_id,
                                "student_name": student_name,
                                "teacher_name": teacher_name,
                                "log_id": log_id
                            },
                            tag=f"contact-log-{log_id}"
                        )
                        
                        if result.get("success"):
                            notification_sent = True
                    except Exception as e:
                        frappe.log_error(f"Failed to send to {email}: {str(e)}")
                
                if notification_sent:
                    sent_count += 1
                    results.append({
                        "student_id": student_log.student_id,
                        "success": True,
                        "message": "Sent successfully"
                    })
                else:
                    failed_count += 1
                    results.append({
                        "student_id": student_log.student_id,
                        "success": False,
                        "message": "Failed to send notifications"
                    })
                
            except Exception as e:
                failed_count += 1
                results.append({
                    "student_id": log_id,
                    "success": False,
                    "message": str(e)
                })
                frappe.log_error(f"Error sending contact log {log_id}: {str(e)}")
        
        frappe.db.commit()
        
        return success_response(
            message=f"Sent to {sent_count} students, failed: {failed_count}",
            data={
                "sent_count": sent_count,
                "failed_count": failed_count,
                "total": len(student_log_ids),
                "results": results
            }
        )
    
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"send_contact_log error: {str(e)}")
        return error_response(message="Failed to send contact log", code="SEND_CONTACT_LOG_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def recall_contact_log():
    """
    Recall contact log - mark as recalled
    Note: Cannot actually remove push notifications once sent, but marks as recalled
    """
    try:
        body = _get_body() or {}
        class_id = body.get('class_id')
        student_log_ids = body.get('student_log_ids') or []
        
        if not class_id or not student_log_ids:
            return error_response(message="Missing class_id or student_log_ids", code="MISSING_PARAMS")
        
        # Validate teacher access
        _validate_homeroom_teacher_access(class_id)
        
        recalled_count = 0
        
        for log_id in student_log_ids:
            try:
                student_log = frappe.get_doc("SIS Class Log Student", log_id)
                
                # Update recall status
                student_log.contact_log_status = "Recalled"
                student_log.contact_log_recalled_by = frappe.session.user
                student_log.contact_log_recalled_at = frappe.utils.now_datetime()
                student_log.save()
                
                recalled_count += 1
                
            except Exception as e:
                frappe.log_error(f"Error recalling contact log {log_id}: {str(e)}")
        
        frappe.db.commit()
        
        return success_response(
            message=f"Recalled {recalled_count} contact logs",
            data={"recalled_count": recalled_count}
        )
    
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"recall_contact_log error: {str(e)}")
        return error_response(message="Failed to recall contact log", code="RECALL_CONTACT_LOG_ERROR")


@frappe.whitelist(allow_guest=False)
def get_contact_log_status(class_id, date=None):
    """
    Get contact log status for all students in a class
    Returns: { student_id: { status, sent_at, viewed_count, ... } }
    """
    try:
        if not class_id:
            return error_response(message="Missing class_id", code="MISSING_PARAMS")
        
        # Validate teacher access
        _validate_homeroom_teacher_access(class_id)
        
        # Find class log subject
        filters = {"class_id": class_id}
        if date:
            filters["log_date"] = date
        
        subject_rows = frappe.get_all(
            "SIS Class Log Subject",
            filters=filters,
            fields=["name"],
            limit=1
        )
        
        if not subject_rows:
            return success_response(data={}, message="No logs found")
        
        subject_id = subject_rows[0]['name']
        
        # Get all student logs
        student_logs = frappe.get_all(
            "SIS Class Log Student",
            filters={"subject_id": subject_id},
            fields=[
                "student_id",
                "badges",
                "contact_log_comment",
                "contact_log_status",
                "contact_log_sent_by",
                "contact_log_sent_at",
                "contact_log_recalled_by",
                "contact_log_recalled_at",
                "contact_log_viewed_count"
            ]
        )
        
        # Build map: student_id -> status info
        status_map = {}
        for log in student_logs:
            status_map[log['student_id']] = {
                "status": log.get('contact_log_status'),
                "badges": log.get('badges'),
                "comment": log.get('contact_log_comment'),
                "sent_by": log.get('contact_log_sent_by'),
                "sent_at": log.get('contact_log_sent_at'),
                "recalled_by": log.get('contact_log_recalled_by'),
                "recalled_at": log.get('contact_log_recalled_at'),
                "viewed_count": log.get('contact_log_viewed_count') or 0
            }
        
        return success_response(data=status_map, message="Contact log status fetched")
    
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_ERROR")
    except Exception as e:
        frappe.log_error(f"get_contact_log_status error: {str(e)}")
        return error_response(message="Failed to get contact log status", code="GET_STATUS_ERROR")

