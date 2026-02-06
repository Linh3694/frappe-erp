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
    Lưu contact log (badges + comment) cho học sinh - chưa gửi notification.
    ⚡ Tối ưu: Batch update existing logs bằng SQL, batch query class_students.
    """
    try:
        body = _get_body() or {}
        class_id = body.get('class_id')
        date = body.get('date')
        students = body.get('students') or []
        
        if not class_id:
            return error_response(message="Missing class_id", code="MISSING_PARAMS")
        
        # Validate quyền giáo viên chủ nhiệm
        _validate_homeroom_teacher_access(class_id)
        
        saved_count = 0
        log_ids = {}  # student_id -> log_id
        
        # ⚡ Batch query: Tìm tất cả existing logs của class + date (1 query)
        existing_logs_map = {}  # student_id -> log record
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
            
            for log in existing_logs:
                if log['student_id'] not in existing_logs_map:
                    existing_logs_map[log['student_id']] = log
        
        # Phân loại: students cần update vs students cần tạo mới
        students_to_update = []  # [(log_id, badges_json, comment, student_id)]
        students_to_create = []  # [(student_id, badges, comment)]
        
        for student_data in students:
            student_id = student_data.get('student_id')
            badges = student_data.get('badges') or []
            comment = student_data.get('comment') or ""
            
            if not student_id:
                continue
            
            existing_log = existing_logs_map.get(student_id)
            if existing_log:
                students_to_update.append((
                    existing_log['log_id'],
                    json.dumps(badges),
                    comment,
                    student_id,
                    existing_log.get('contact_log_status')
                ))
            else:
                students_to_create.append((student_id, badges, comment))
        
        # ⚡ Batch UPDATE: Cập nhật tất cả existing logs cùng lúc
        now = frappe.utils.now_datetime()
        user = frappe.session.user
        
        for (log_id, badges_json, comment, student_id, current_status) in students_to_update:
            # Dùng SQL trực tiếp thay vì frappe.get_doc + save (tiết kiệm ~50ms/record)
            new_status = current_status if current_status == 'Sent' else 'Draft'
            frappe.db.sql("""
                UPDATE `tabSIS Class Log Student`
                SET badges = %(badges)s,
                    contact_log_comment = %(comment)s,
                    contact_log_status = %(status)s,
                    modified = %(now)s,
                    modified_by = %(user)s
                WHERE name = %(log_id)s
            """, {
                "badges": badges_json,
                "comment": comment,
                "status": new_status,
                "now": now,
                "user": user,
                "log_id": log_id
            })
            log_ids[student_id] = log_id
            saved_count += 1
        
        # Xử lý students cần tạo mới (nếu có)
        if students_to_create:
            # Tìm hoặc tạo subject mặc định (chỉ 1 lần)
            default_subject_id = None
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
            
            # ⚡ Batch query class_student_ids (1 query thay vì N queries)
            new_student_ids = [s[0] for s in students_to_create]
            class_student_rows = frappe.db.sql("""
                SELECT name, student_id FROM `tabSIS Class Student`
                WHERE class_id = %(class_id)s AND student_id IN %(student_ids)s
            """, {"class_id": class_id, "student_ids": new_student_ids}, as_dict=True)
            
            class_student_map = {r['student_id']: r['name'] for r in class_student_rows}
            
            # Tạo student logs cho các student mới
            for (student_id, badges, comment) in students_to_create:
                class_student = class_student_map.get(student_id)
                if not class_student:
                    frappe.log_error(f"No class student found for student_id={student_id}, class_id={class_id}")
                    continue
                
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
                log_ids[student_id] = student_log.name
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
    Gửi contact log cho phụ huynh qua push notification.
    ⚡ Tối ưu:
    - Batch update status bằng 1 SQL query
    - Batch lấy student names (1 query)
    - Batch lấy guardians (1 query)
    - Gửi notification synchronous để đảm bảo phụ huynh nhận được ngay
    """
    try:
        body = _get_body() or {}
        class_id = body.get('class_id')
        student_log_ids = body.get('student_log_ids') or []
        
        if not class_id or not student_log_ids:
            return error_response(message="Missing class_id or student_log_ids", code="MISSING_PARAMS")
        
        # Validate quyền giáo viên chủ nhiệm
        _validate_homeroom_teacher_access(class_id)
        
        now = frappe.utils.now_datetime()
        user = frappe.session.user
        
        # ⚡ Batch lấy student_ids (1 query)
        log_data = frappe.db.sql("""
            SELECT name, student_id 
            FROM `tabSIS Class Log Student`
            WHERE name IN %(log_ids)s
        """, {"log_ids": student_log_ids}, as_dict=True)
        
        if not log_data:
            return error_response(message="No valid student logs found", code="NO_LOGS")
        
        student_ids = [d['student_id'] for d in log_data]
        valid_log_ids = [d['name'] for d in log_data]
        
        # ⚡ Batch update tất cả status cùng lúc (1 query thay vì N get_doc+save)
        frappe.db.sql("""
            UPDATE `tabSIS Class Log Student`
            SET contact_log_status = 'Sent',
                contact_log_sent_by = %(user)s,
                contact_log_sent_at = %(now)s,
                modified = %(now)s,
                modified_by = %(user)s
            WHERE name IN %(log_ids)s
        """, {"user": user, "now": now, "log_ids": valid_log_ids})
        
        frappe.db.commit()
        
        sent_count = len(valid_log_ids)
        
        # ⚡ Gửi notification synchronous (đảm bảo phụ huynh nhận được)
        notification_result = _send_contact_log_notifications(class_id, student_ids)
        
        return success_response(
            message="Contact logs sent successfully",
            data={
                "total_logs_updated": sent_count,
                "notification_summary": notification_result
            }
        )
        
    except frappe.PermissionError as e:
        return error_response(message=str(e), code="PERMISSION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"Send Contact Log Error: {str(e)}")
        return error_response(
            message=f"Failed to send contact logs: {str(e)}",
            code="SEND_CONTACT_LOG_ERROR"
        )


def _send_contact_log_notifications(class_id, student_ids):
    """
    Gửi notification cho phụ huynh (synchronous).
    ⚡ Tối ưu so với code cũ:
    - Code cũ: N lần gọi send_bulk_parent_notifications (N = số học sinh)
      → mỗi lần query guardians, tạo notification, gửi push riêng biệt
    - Code mới: 1 batch query guardians + 1 batch query student names
      → chỉ loop 1 lần qua parents để tạo notification + push
    """
    from erp.utils.notification_handler import (
        get_guardians_for_students,
        get_parent_emails
    )
    
    result = {"success_count": 0, "failed_count": 0, "total_parents": 0}
    
    try:
        if not student_ids:
            return result
        
        # ⚡ Batch lấy tên tất cả học sinh cùng lúc (1 query thay vì N queries)
        name_rows = frappe.db.sql("""
            SELECT name, student_name FROM `tabCRM Student`
            WHERE name IN %(ids)s
        """, {"ids": student_ids}, as_dict=True)
        student_names = {r['name']: r['student_name'] for r in name_rows}
        
        # ⚡ Batch lấy tất cả guardians cho TẤT CẢ students (1 batch thay vì N lần)
        guardians = get_guardians_for_students(student_ids)
        
        if not guardians:
            return result
        
        parent_emails = get_parent_emails(guardians)
        result["total_parents"] = len(parent_emails)
        
        # Tạo mapping: email → [student_ids] (1 phụ huynh có thể có nhiều con trong danh sách gửi)
        # VD: PH có 2 con A, B đều trong lớp → email_to_students_map["ph@..."] = ["A", "B"]
        student_ids_set = set(student_ids)
        email_to_students_map = {}
        for guardian in guardians:
            email = guardian.get("email")
            guardian_student_ids = guardian.get("student_ids", [])
            if email and guardian_student_ids:
                # Chỉ lấy những student nằm trong danh sách gửi lần này
                matched_students = [s for s in guardian_student_ids if s in student_ids_set]
                if matched_students:
                    email_to_students_map[email] = matched_students
        
        # Import helpers
        from erp.common.doctype.erp_notification.erp_notification import get_unread_count
        from erp.api.parent_portal.realtime_notification import emit_notification_to_user, emit_unread_count_update, get_notification_text
        from erp.api.parent_portal.push_notification import send_push_notification
        
        # Gửi notification cho từng phụ huynh × từng học sinh
        # VD: PH có 2 con A, B → gửi 2 notification riêng biệt:
        #   "Học sinh A có nhận xét mới..."
        #   "Học sinh B có nhận xét mới..."
        for parent_email in parent_emails:
            matched_students = email_to_students_map.get(parent_email, [])
            if not matched_students:
                continue
            
            for student_id in matched_students:
                try:
                    student_name = student_names.get(student_id, student_id)
                    
                    notification_title = {"vi": "Sổ liên lạc", "en": "Contact Log"}
                    notification_body = {
                        "vi": f"Học sinh {student_name} có nhận xét mới về ngày học hôm nay.",
                        "en": f"Student {student_name} has a new comment about today's school day."
                    }
                    
                    merged_data = {
                        "type": "contact_log",
                        "notificationType": "contact_log",
                        "student_id": student_id,
                        "student_name": student_name,
                        "timestamp": frappe.utils.now()
                    }
                    
                    # Tạo notification record trong DB
                    notification_doc = frappe.get_doc({
                        "doctype": "ERP Notification",
                        "title": json.dumps(notification_title),
                        "message": json.dumps(notification_body),
                        "recipient_user": parent_email,
                        "recipients": json.dumps([parent_email]),
                        "notification_type": "contact_log",
                        "priority": "medium",
                        "data": json.dumps(merged_data),
                        "channel": "push",
                        "status": "sent",
                        "delivery_status": "pending",
                        "sent_at": frappe.utils.now(),
                        "event_timestamp": frappe.utils.now(),
                        "student_id": student_id
                    })
                    notification_doc.insert(ignore_permissions=True)
                    
                    # Emit realtime notification (SocketIO) → hiển thị popup trên parent portal
                    emit_notification_to_user(parent_email, {
                        "id": notification_doc.name,
                        "type": "contact_log",
                        "title": notification_title,
                        "message": notification_body,
                        "status": "unread",
                        "priority": "medium",
                        "created_at": frappe.utils.now(),
                        "data": merged_data,
                        "student_id": student_id
                    })
                    
                    # Gửi push notification → hiện notification trên điện thoại/browser
                    # Dùng tag riêng cho mỗi student để KHÔNG bị ghi đè nhau
                    try:
                        final_title = get_notification_text(notification_title)
                        final_body = get_notification_text(notification_body)
                        send_push_notification(
                            user_email=parent_email,
                            title=final_title,
                            body=final_body,
                            icon="/icon.png",
                            data=merged_data,
                            tag=f"contact_log_{student_id}"
                        )
                    except Exception as push_err:
                        frappe.logger().warning(f"❌ [CONTACT_LOG] Push failed for {parent_email}/{student_id}: {str(push_err)}")
                    
                    result["success_count"] += 1
                    
                except Exception as parent_err:
                    result["failed_count"] += 1
                    frappe.logger().error(f"❌ [CONTACT_LOG] Notification failed for {parent_email}/{student_id}: {str(parent_err)}")
            
            # Cập nhật unread count 1 lần cho mỗi phụ huynh (sau khi gửi hết notifications của PH đó)
            try:
                unread_count = get_unread_count(parent_email)
                emit_unread_count_update(parent_email, unread_count)
            except Exception:
                pass
        
        # Commit tất cả notification records 1 lần duy nhất
        frappe.db.commit()
        
        frappe.logger().info(
            f"✅ [CONTACT_LOG] Notifications: {result['success_count']} success, "
            f"{result['failed_count']} failed out of {len(parent_emails)} parents"
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ [CONTACT_LOG] Notification error: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
    
    return result


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

