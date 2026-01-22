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
    # Try SIS Badge first (new system)
    badge = frappe.get_value("SIS Badge", badge_id, ["title_vn", "title_en"], as_dict=True)
    if badge:
        return badge.title_vn or badge.title_en or badge_id
    
    # Fallback to old system for backward compatibility
    old_badge = frappe.get_value("SIS Contact Log Badge", badge_id, ["badge_name", "badge_name_en"], as_dict=True)
    if old_badge:
        return old_badge.badge_name or old_badge.badge_name_en or badge_id
    
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
    """Get available badges - now using SIS Badge (new system)"""
    try:
        filters = {"is_active": 1}
        
        # Get all active badges from SIS Badge (no education_stage filter as badges are global)
        badges = frappe.get_all(
            "SIS Badge",
            filters=filters,
            fields=["name as badge_id", "title_vn as badge_name", "title_en as badge_name_en", "image"],
            order_by="title_vn asc"
        )
        
        # Transform to match expected format (add default color if needed)
        result = []
        for badge in badges:
            result.append({
                "badge_id": badge.badge_id,
                "badge_name": badge.badge_name,
                "badge_name_en": badge.badge_name_en,
                "badge_color": "#3F4246",  # Default color
                "badge_image": badge.image  # Include image URL
            })
        
        return success_response(data=result, message="Badges fetched")
    except Exception as e:
        frappe.log_error(f"get_badges error: {str(e)}")
        return error_response(message="Failed to fetch badges", code="GET_BADGES_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_contact_log():
    """
    Save contact log (badges + comment) for students
    Does NOT send notification yet - just saves draft
    
    FIX: Tìm student log đã có contact_log trước (từ bất kỳ subject nào trong ngày),
    nếu có thì update, nếu không mới tạo mới
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
        
        # Tìm tất cả subjects của class + date để tìm existing contact logs
        existing_logs_map = {}  # student_id -> log record có contact_log
        if date:
            existing_logs = frappe.db.sql("""
                SELECT 
                    cls.name as log_id,
                    cls.student_id,
                    cls.subject_id,
                    cls.contact_log_comment,
                    cls.contact_log_status
                FROM `tabSIS Class Log Student` cls
                JOIN `tabSIS Class Log Subject` sub ON cls.subject_id = sub.name
                WHERE sub.class_id = %(class_id)s AND sub.log_date = %(date)s
                ORDER BY 
                    CASE 
                        WHEN cls.contact_log_status = 'Sent' THEN 1
                        WHEN cls.contact_log_comment IS NOT NULL AND cls.contact_log_comment != '' THEN 2
                        ELSE 3
                    END
            """, {"class_id": class_id, "date": date}, as_dict=True)
            
            # Lấy record tốt nhất cho mỗi student (ưu tiên record có contact_log)
            for log in existing_logs:
                if log['student_id'] not in existing_logs_map:
                    existing_logs_map[log['student_id']] = log
        
        # Tìm hoặc tạo subject mặc định cho trường hợp cần tạo mới
        default_subject_id = None
        
        # Now process each student
        for student_data in students:
            student_id = student_data.get('student_id')
            badges = student_data.get('badges') or []
            comment = student_data.get('comment') or ""
            
            if not student_id:
                continue
            
            # Kiểm tra xem student đã có log với contact_log chưa
            existing_log = existing_logs_map.get(student_id)
            
            if existing_log:
                # Update existing log (đã có contact_log hoặc ít nhất có record)
                log_id = existing_log['log_id']
                student_log = frappe.get_doc("SIS Class Log Student", log_id)
                student_log.badges = json.dumps(badges)
                student_log.contact_log_comment = comment
                # Chỉ set Draft nếu chưa Sent
                if student_log.contact_log_status != 'Sent':
                    student_log.contact_log_status = "Draft"
                student_log.save()
            else:
                # Cần tạo mới - lấy hoặc tạo subject mặc định
                if not default_subject_id:
                    # Tìm timetable instance
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
                    
                    # Tìm subject đã có
                    subject_rows = frappe.get_all(
                        "SIS Class Log Subject",
                        filters={
                            "timetable_instance_id": timetable_instance,
                            "class_id": class_id,
                            "log_date": date
                        },
                        fields=["name"],
                        limit=1
                    )
                    
                    if subject_rows:
                        default_subject_id = subject_rows[0]['name']
                    else:
                        # Tạo subject mới
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
                        default_subject_id = subject_doc.name
                
                # Get class_student_id
                class_student = frappe.get_value(
                    "SIS Class Student",
                    filters={"class_id": class_id, "student_id": student_id},
                    fieldname="name"
                )
                
                if not class_student:
                    frappe.log_error(f"No class student found for student_id={student_id}, class_id={class_id}")
                    continue
                
                # Tạo student log mới
                student_log = frappe.get_doc({
                    "doctype": "SIS Class Log Student",
                    "subject_id": default_subject_id,
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
                "log_ids": log_ids
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
    Updates status to "Sent" and sends push notifications using unified handler
    """
    try:
        print("=" * 80)
        print("📨 [CONTACT_LOG] ========== START send_contact_log ==========")
        print("=" * 80)
        
        body = _get_body() or {}
        print(f"📨 [CONTACT_LOG] Request body: {body}")
        
        class_id = body.get('class_id')
        student_log_ids = body.get('student_log_ids') or []
        
        print(f"📨 [CONTACT_LOG] class_id: {class_id}")
        print(f"📨 [CONTACT_LOG] student_log_ids: {student_log_ids}")
        
        if not class_id or not student_log_ids:
            print(f"❌ [CONTACT_LOG] Missing params")
            return error_response(message="Missing class_id or student_log_ids", code="MISSING_PARAMS")
        
        # Validate teacher access
        print(f"📨 [CONTACT_LOG] Validating teacher access...")
        _validate_homeroom_teacher_access(class_id)
        print(f"✅ [CONTACT_LOG] Teacher access validated")
        
        # Collect all student IDs and update status
        student_ids = []
        sent_count = 0
        failed_count = 0
        results = []
        
        for log_id in student_log_ids:
            try:
                # Get student log
                student_log = frappe.get_doc("SIS Class Log Student", log_id)
                student_ids.append(student_log.student_id)
                
                # Update status to "Sent"
                student_log.contact_log_status = "Sent"
                student_log.contact_log_sent_by = frappe.session.user
                student_log.contact_log_sent_at = frappe.utils.now_datetime()
                student_log.save()
                
                print(f"📨 [CONTACT_LOG] Updated student_log: {log_id}")
                sent_count += 1
                
            except Exception as e:
                print(f"❌ [CONTACT_LOG] Error updating log {log_id}: {str(e)}")
                failed_count += 1
                results.append({
                    "student_log_id": log_id,
                    "success": False,
                    "message": str(e)
                })
        
        print(f"📨 [CONTACT_LOG] Updated {sent_count} logs, {failed_count} failed")
        
        if not student_ids:
            print(f"⚠️ [CONTACT_LOG] No students to notify")
            return error_response(
                message="Failed to update contact logs",
                code="UPDATE_FAILED"
            )
        
        # Send notifications using unified handler - individually for each student
        from erp.utils.notification_handler import send_bulk_parent_notifications
        
        try:
            print(f"📨 [CONTACT_LOG] Sending individual notifications to parents of {len(student_ids)} students")
            
            # Send notification for each student individually (so we can include student_name)
            total_success = 0
            total_failed = 0
            total_parents = 0
            
            for student_id in student_ids:
                try:
                    # Get student name
                    student_name = frappe.db.get_value("CRM Student", student_id, "student_name")
                    
                    if not student_name:
                        print(f"⚠️ [CONTACT_LOG] Student name not found for {student_id}, skipping")
                        continue
                    
                    # Send notification for this student with their name
                    result = send_bulk_parent_notifications(
                        recipient_type="contact_log",
                        recipients_data={
                            "student_ids": [student_id]
                        },
                        title="Sổ liên lạc",
                        body=f"Học sinh {student_name} có nhận xét mới về ngày học hôm nay.",
                        icon="/icon.png",
                        data={
                            "type": "contact_log",
                            "student_id": student_id,
                            "student_name": student_name,
                            "timestamp": frappe.utils.now()
                        }
                    )
                    
                    total_success += result.get('success_count', 0)
                    total_failed += result.get('failed_count', 0)
                    total_parents += result.get('total_parents', 0)
                    
                except Exception as student_error:
                    print(f"❌ [CONTACT_LOG] Error sending notification for {student_id}: {str(student_error)}")
                    continue
            
            # Create summary result
            notification_result = {
                'success_count': total_success,
                'failed_count': total_failed,
                'total_parents': total_parents
            }
            
            print(f"✅ [CONTACT_LOG] Notifications sent - Success: {notification_result.get('success_count')}, Failed: {notification_result.get('failed_count')}")
            
            return success_response(
                message="Contact logs sent successfully",
                data={
                    "total_logs_updated": sent_count,
                    "notification_summary": {
                        "total_parents": notification_result.get('total_parents', 0),
                        "success_count": notification_result.get('success_count', 0),
                        "failed_count": notification_result.get('failed_count', 0)
                    }
                }
            )
        
        except Exception as e:
            print(f"❌ [CONTACT_LOG] Error sending notifications: {str(e)}")
            frappe.logger().error(f"Contact Log Notification Error: {str(e)}")
            
            # Still return success since logs were updated, just notification failed
            return success_response(
                message="Contact logs updated but notification sending failed",
                data={
                    "total_logs_updated": sent_count,
                    "notification_error": str(e)
                }
            )
        
    except Exception as e:
        print(f"❌ [CONTACT_LOG] Error: {str(e)}")
        frappe.logger().error(f"Send Contact Log Error: {str(e)}")
        return error_response(
            message=f"Failed to send contact logs: {str(e)}",
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
    
    FIX: Query từ TẤT CẢ subjects của ngày đó, không chỉ 1 subject
    Vì contact_log có thể được lưu ở bất kỳ tiết nào trong ngày
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
        
        # Query trực tiếp student logs từ TẤT CẢ subjects của class + date
        # Không cần qua timetable_instance vì có thể có nhiều subjects trong ngày
        # Ưu tiên log có contact_log_comment hoặc status = 'Sent'
        student_logs = frappe.db.sql("""
            SELECT 
                cls.name,
                cls.student_id,
                cls.badges,
                cls.contact_log_comment,
                cls.contact_log_status,
                cls.contact_log_sent_by,
                cls.contact_log_sent_at,
                cls.contact_log_recalled_by,
                cls.contact_log_recalled_at,
                cls.contact_log_viewed_count
            FROM `tabSIS Class Log Student` cls
            JOIN `tabSIS Class Log Subject` sub ON cls.subject_id = sub.name
            WHERE sub.class_id = %(class_id)s AND sub.log_date = %(date)s
            ORDER BY 
                CASE 
                    WHEN cls.contact_log_status = 'Sent' THEN 1
                    WHEN cls.contact_log_comment IS NOT NULL AND cls.contact_log_comment != '' THEN 2
                    WHEN cls.contact_log_status = 'Draft' AND cls.badges IS NOT NULL THEN 3
                    ELSE 4
                END,
                cls.contact_log_sent_at DESC
        """, {"class_id": class_id, "date": date}, as_dict=True)
        
        if not student_logs:
            return success_response(data={}, message="No logs found")
        
        # Build map: student_id -> status info
        # Vì có thể có nhiều logs cho cùng 1 student (từ nhiều tiết),
        # chỉ lấy log có contact_log đầy đủ nhất (đã sort ở trên)
        status_map = {}
        for log in student_logs:
            student_id = log['student_id']
            # Chỉ lấy record đầu tiên cho mỗi student (đã ưu tiên bởi ORDER BY)
            if student_id not in status_map:
                status_map[student_id] = {
                    "log_id": log['name'],
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

