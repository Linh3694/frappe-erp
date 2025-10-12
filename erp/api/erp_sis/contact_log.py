"""
Contact Log API for Teacher -> Parent Communication
Handles badges, comments, and push notifications
"""

import json
import frappe
import requests
from frappe import _
from erp.utils.api_response import success_response, error_response


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
    
    # Get teacher record(s) for current user
    teacher_records = frappe.get_all(
        "SIS Teacher",
        filters={"user_id": user},
        fields=["name"]
    )
    
    if not teacher_records:
        frappe.throw(_("Only homeroom or vice-homeroom teachers can manage contact logs"), frappe.PermissionError)
    
    teacher_ids = [t.name for t in teacher_records]
    
    # Get class document
    class_doc = frappe.get_doc("SIS Class", class_id)
    
    # Check if any teacher ID matches homeroom or vice-homeroom
    is_homeroom = (class_doc.homeroom_teacher in teacher_ids) or (class_doc.vice_homeroom_teacher in teacher_ids)
    
    if not is_homeroom:
        frappe.throw(_("Only homeroom or vice-homeroom teachers can manage contact logs"), frappe.PermissionError)
    
    return True


def _get_student_parent_emails(student_id):
    """Get all parent emails for a student"""
    # Query relationships to find parents
    try:
        relationships = frappe.get_all(
            "CRM Family Relationship",
            filters={"student": student_id},
            fields=["guardian"]
        )
    except Exception:
        return []
    
    parent_emails = []
    for rel in relationships:
        if rel.guardian:
            try:
                # Get guardian document - use get_value instead of get_doc to avoid DocType not found exceptions
                guardian_id = frappe.db.get_value("CRM Guardian", rel.guardian, "guardian_id")
                if guardian_id:
                    # Parent email format: guardian_id@parent.wellspring.edu.vn
                    email = f"{guardian_id}@parent.wellspring.edu.vn"
                    parent_emails.append(email)
            except Exception:
                # Silently skip guardians that don't exist or have issues
                continue
    
    return parent_emails


def _get_badge_name(badge_id):
    """Get badge display name"""
    badge = frappe.get_value("SIS Contact Log Badge", badge_id, ["badge_name", "badge_name_en"], as_dict=True)
    if badge:
        return badge.badge_name or badge.badge_name_en or badge_id
    return badge_id


def _get_teacher_name(user_email):
    """Get teacher display name"""
    # Get full name from User
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
        log_ids = {}  # student_id -> log_id
        
        # First, find timetable instance for this class and date
        timetable_instance = None
        if date:
            timetable_instances = frappe.get_all(
                "SIS Timetable Instance",
                filters={
                    "class_id": class_id,
                    "start_date": ["<=", date],
                    "end_date": [">=", date]
                },
                fields=["name"],
                limit=1
            )
            if timetable_instances:
                timetable_instance = timetable_instances[0]['name']
        
        if not timetable_instance:
            return error_response(
                message="No active timetable instance found for this class and date",
                code="NO_TIMETABLE_INSTANCE"
            )
        
        # Get or create subject
        filters_subject = {
            "timetable_instance_id": timetable_instance,
            "class_id": class_id
        }
        if date:
            filters_subject["log_date"] = date
        
        subject_rows = frappe.get_all(
            "SIS Class Log Subject",
            filters=filters_subject,
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
                "timetable_instance_id": timetable_instance,
                "class_id": class_id,
                "log_date": date,
                "recorded_by": frappe.session.user,
                "campus_id": campus_id
            })
            subject_doc.insert()
            subject_id = subject_doc.name
        else:
            subject_id = subject_rows[0]['name']
        
        # Now process each student
        for student_data in students:
            student_id = student_data.get('student_id')
            badges = student_data.get('badges') or []
            comment = student_data.get('comment') or ""
            
            if not student_id:
                continue
            
            # Get class_student_id from SIS Class Student
            class_student = frappe.get_value(
                "SIS Class Student",
                filters={"class_id": class_id, "student_id": student_id},
                fieldname="name"
            )
            
            if not class_student:
                frappe.log_error(f"No class student found for student_id={student_id}, class_id={class_id}")
                continue
            
            # Find or create student log
            student_log_rows = frappe.get_all(
                "SIS Class Log Student",
                filters={"subject_id": subject_id, "student_id": student_id},
                fields=["name"],
                limit=1
            )
            
            if student_log_rows:
                # Update existing
                log_id = student_log_rows[0]['name']
                student_log = frappe.get_doc("SIS Class Log Student", log_id)
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
                    "class_student_id": class_student,
                    "badges": json.dumps(badges),
                    "contact_log_comment": comment,
                    "contact_log_status": "Draft"
                })
                student_log.insert()
                log_id = student_log.name
            
            log_ids[student_id] = log_id
            saved_count += 1
        
        frappe.db.commit()
        
        return success_response(
            message=f"Saved contact logs for {saved_count} students",
            data={
                "saved_count": saved_count,
                "log_ids": log_ids  # Return log IDs so frontend can track them
            }
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
                
                # Update status to "Sent" first (before trying notifications)
                student_log.contact_log_status = "Sent"
                student_log.contact_log_sent_by = frappe.session.user
                student_log.contact_log_sent_at = frappe.utils.now_datetime()
                student_log.save()
                
                # Try to send push notifications (best effort)
                # Get parent emails
                parent_emails = _get_student_parent_emails(student_log.student_id)
                
                if not parent_emails:
                    # No parents, but still mark as sent
                    sent_count += 1
                    results.append({
                        "student_id": student_log.student_id,
                        "success": True,
                        "message": "Sent (no parent contacts found)"
                    })
                    continue
                
                # Send push notification via notification-service (best effort)
                notification_sent = False
                if parent_emails:
                    # Deduplicate parent emails to avoid MongoDB unique constraint error
                    parent_emails = list(set(parent_emails))
                    
                    try:
                        print(f"📨 Preparing to send notification to {len(parent_emails)} parent(s): {parent_emails}")
                        
                        title = f"📝 Nhận xét từ giáo viên - {student_name}"
                        body_text = f"Giáo viên {teacher_name} đã gửi nhận xét cho {student_name}.{badges_text}"
                        
                        if student_log.contact_log_comment:
                            comment = student_log.contact_log_comment
                            body_text += f"\n💬 Nhận xét: {comment[:100]}{'...' if len(comment) > 100 else ''}"
                        
                        # Call notification-service API directly (internal network)
                        notification_service_url = frappe.conf.get("notification_service_url", "http://172.16.20.115:5001")
                        
                        payload = {
                            "title": title,
                            "body": body_text,
                            "recipients": parent_emails,
                            "type": "system", 
                            "priority": "high",
                            "channel": "push",
                            "data": {
                                "type": "contact_log",  # Custom type in data field
                                "student_id": student_log.student_id,
                                "student_name": student_name,
                                "teacher_name": teacher_name,
                                "log_id": log_id
                            }
                        }
                        
                        print(f"📨 Calling notification service: {notification_service_url}/api/notifications/send")
                        print(f"📨 Payload: {payload}")
                        
                        response = requests.post(
                            f"{notification_service_url}/api/notifications/send",
                            json=payload,
                            timeout=5
                        )
                        
                        print(f"📨 Notification service response status: {response.status_code}")
                        print(f"📨 Notification service response body: {response.text[:200]}")
                        
                        if response.status_code == 200:
                            notification_sent = True
                            print(f"✅ Sent notification to {len(parent_emails)} parent(s)")
                        else:
                            print(f"⚠️ Notification service returned: {response.status_code} - {response.text[:100]}")
                            
                    except Exception as e:
                        # Silently log but don't crash
                        print(f"⚠️ Failed to send notifications: {str(e)[:200]}")
                        import traceback
                        print(traceback.format_exc()[:500])
                
                # Always count as sent (notification is best-effort)
                sent_count += 1
                results.append({
                    "student_id": student_log.student_id,
                    "success": True,
                    "message": "Sent successfully" if notification_sent else "Sent (notifications may have failed)"
                })
                
            except Exception as e:
                failed_count += 1
                results.append({
                    "student_id": log_id,
                    "success": False,
                    "message": str(e)[:200]  # Truncate to avoid logging issues
                })
                print(f"⚠️ Error sending contact log {log_id}: {str(e)[:200]}")
        
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
        error_msg = str(e)[:500]  # Truncate to avoid Error Log title length issues
        print(f"⚠️ send_contact_log error: {error_msg}")
        return error_response(
            message=f"Failed to send contact log: {error_msg}", 
            code="SEND_CONTACT_LOG_ERROR"
        )


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


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_contact_log_status():
    """
    Get contact log status for all students in a class
    Returns: { student_id: { status, sent_at, viewed_count, ... } }
    """
    try:
        # Get params from POST body or GET query params
        body = _get_body() or {}
        class_id = body.get('class_id') or frappe.form_dict.get('class_id') or frappe.request.args.get('class_id')
        date = body.get('date') or frappe.form_dict.get('date') or frappe.request.args.get('date')
        
        if not class_id:
            return error_response(message="Missing class_id", code="MISSING_PARAMS")
        
        # Validate teacher access
        _validate_homeroom_teacher_access(class_id)
        
        # Find timetable instance for this class and date
        timetable_instance = None
        if date:
            timetable_instances = frappe.get_all(
                "SIS Timetable Instance",
                filters={
                    "class_id": class_id,
                    "start_date": ["<=", date],
                    "end_date": [">=", date]
                },
                fields=["name"],
                limit=1
            )
            if timetable_instances:
                timetable_instance = timetable_instances[0]['name']
        
        if not timetable_instance:
            return success_response(data={}, message="No timetable instance found")
        
        # Find class log subject
        filters = {
            "timetable_instance_id": timetable_instance,
            "class_id": class_id
        }
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
                "name",
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
                "log_id": log['name'],  # Important: Include log ID for send/recall
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

