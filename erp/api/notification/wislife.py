# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Wislife Notification API
Handles push notifications for Wislife social network
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from datetime import datetime
import json
from collections import defaultdict

from erp.api.erp_sis.mobile_push_notification import send_mobile_notification, send_mobile_notifications_bulk
from erp.common.doctype.erp_notification.erp_notification import create_notification
from erp.api.utils import format_vietnamese_name


# Emoji names mapping (Vietnamese)
EMOJI_NAMES = {
    'like': 'Thích',
    'love': 'Yêu thích',
    'haha': 'Haha',
    'wow': 'Wow',
    'sad': 'Buồn',
    'angry': 'Phẫn nộ'
}


def _wislife_extra_fields(event_data):
    """
    Wave 3: Truyền classId / studentId từ social-service → payload push + ERP Notification (deep link mobile).
    """
    if not event_data:
        return {}
    out = {}
    cid = event_data.get("classId") or event_data.get("class_id")
    if cid:
        s = str(cid).strip()
        if s:
            out["classId"] = s
            out["class_id"] = s
    sid = event_data.get("studentId") or event_data.get("student_id")
    if sid:
        s = str(sid).strip()
        if s:
            out["studentId"] = s
            out["student_id"] = s
    # Danh sách học sinh (lớp) từ social-service — app có thể dùng để chọn con khi deep link
    pids = event_data.get("participantStudentIds") or event_data.get("participant_student_ids")
    if isinstance(pids, (list, tuple)) and pids:
        cleaned = [str(x).strip() for x in pids if x and str(x).strip()]
        if cleaned:
            out["participantStudentIds"] = cleaned
    return out


@frappe.whitelist(allow_guest=True, methods=['POST'])
def handle_wislife_event():
    """
    Wave 3: Webhook từ social-service — chỉ validate + enqueue RQ short, tránh block HTTP worker.
    Endpoint: /api/method/erp.api.notification.wislife.handle_wislife_event
    """
    try:
        # Validate service-to-service call via custom header
        service_name = frappe.get_request_header("X-Service-Name", "")
        request_source = frappe.get_request_header("X-Request-Source", "")

        if service_name == "social-service" and request_source == "service-to-service":
            frappe.logger().info("📱 [Wislife Event] Valid service-to-service call from social-service")
        else:
            frappe.logger().warning(f"📱 [Wislife Event] Request from unknown source: service={service_name}, source={request_source}")

        # Get request data
        if frappe.request.method != 'POST':
            frappe.throw(_("Method not allowed"), frappe.PermissionError)

        data = frappe.form_dict
        if not data:
            data = json.loads(frappe.local.request.get_data() or '{}')

        event_type = data.get('event_type')
        event_data = data.get('event_data', {})

        frappe.logger().info(f"📱 [Wislife Event] Received API event: {event_type}")

        if not event_type:
            frappe.throw(_("Missing event_type"), frappe.ValidationError)

        try:
            frappe.enqueue(
                "erp.api.notification.wislife._handle_wislife_event_async",
                queue="short",
                timeout=180,
                event_type=event_type,
                event_data=event_data,
            )
            frappe.logger().info(f"📱 [Wislife Event] Enqueued {event_type}")
            return {"success": True, "message": f"Queued {event_type} for async processing", "queued": True}
        except Exception as enqueue_err:
            frappe.logger().error(f"❌ [Wislife Event] Enqueue failed, sync fallback: {str(enqueue_err)}")
            _handle_wislife_event_async(event_type, event_data)
            return {"success": True, "message": f"Processed {event_type} sync (fallback)", "queued": False}

    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Event] Error processing API event: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Event Processing Error")
        return {"success": False, "message": str(e)}


def _handle_wislife_event_async(event_type, event_data):
    """Wave 3: Dispatch Wislife trong RQ worker."""
    try:
        if event_type == 'new_post_broadcast':
            handle_new_post_broadcast(event_data)
        elif event_type == 'post_tagged':
            handle_post_tagged(event_data)
        elif event_type == 'post_reacted':
            handle_post_reacted(event_data)
        elif event_type == 'post_commented':
            handle_post_commented(event_data)
        elif event_type == 'comment_replied':
            handle_comment_replied(event_data)
        elif event_type == 'comment_reacted':
            handle_comment_reacted(event_data)
        elif event_type == 'post_mention':
            handle_post_mention(event_data)
        elif event_type == 'new_class_post':
            handle_new_class_post(event_data)
        else:
            frappe.logger().warning(f"⚠️ [Wislife Event Async] Unknown event type: {event_type}")
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Event Async] {event_type}: {str(e)}")
        frappe.log_error(message=str(e), title=f"Wislife Event Async Error - {event_type}")


# Note: Social-service giờ gửi email trực tiếp, không cần map từ MongoDB ObjectId nữa


def handle_new_post_broadcast(event_data):
    """
    Xử lý khi BOD/Admin đăng bài viết mới - gửi đến TẤT CẢ users
    Enqueue job để chạy background, không block response
    
    Args:
        event_data: Dictionary containing postId, authorEmail, authorName, content, type
    """
    try:
        frappe.logger().info(f"📱 [Wislife New Post] Enqueueing broadcast job...")
        
        # Enqueue background job để không block response
        # Dùng queue 'long' vì broadcast đến nhiều users có thể mất vài phút
        frappe.enqueue(
            'erp.api.notification.wislife._do_broadcast_new_post',
            queue='long',
            timeout=600,  # 10 phút timeout cho job
            event_data=event_data
        )
        
        frappe.logger().info(f"📱 [Wislife New Post] Broadcast job enqueued successfully")
        
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife New Post] Error enqueueing broadcast: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife New Post Broadcast Error")


def handle_new_class_post(event_data):
    """
    Bài Nhật ký theo lớp (GV đăng từ workspace-mobile): gửi push + ERP Notification
    tới phụ huynh có con thuộc đúng lớp + năm học (SIS Class Student).
    """
    try:
        frappe.logger().info("📱 [Wislife Class Post] Enqueueing class notify job...")
        frappe.enqueue(
            "erp.api.notification.wislife._do_notify_class_new_post",
            queue="long",
            timeout=600,
            event_data=event_data,
        )
        frappe.logger().info("📱 [Wislife Class Post] Job enqueued")
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Class Post] Enqueue failed: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Class Post Enqueue Error")


def _portal_email_from_guardian_id(guardian_id):
    gid = (guardian_id or "").strip().lower()
    if not gid:
        return None
    return f"{gid}@parent.wellspring.edu.vn"


def _guardian_student_pairs_for_class(class_id, school_year_id=None):
    """
    (guardian_id, student_id) — student_id là tên bản ghi CRM Student.
    Lọc theo school_year_id nếu có (khớp bài đăng social-service).
    """
    class_id = (class_id or "").strip()
    if not class_id:
        return []

    params = [class_id]
    sy_clause = ""
    sy = (school_year_id or "").strip() if school_year_id is not None else ""
    if sy:
        sy_clause = " AND cs.school_year_id = %s"
        params.append(sy)

    return frappe.db.sql(
        f"""
        SELECT DISTINCT g.guardian_id AS guardian_id, cs.student_id AS student_id
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabCRM Family Relationship` fr ON fr.student = cs.student_id
        INNER JOIN `tabCRM Guardian` g ON g.name = fr.guardian
        WHERE cs.class_id = %s
        {sy_clause}
          AND IFNULL(g.guardian_id, '') != ''
          AND IFNULL(cs.student_id, '') != ''
        """,
        tuple(params),
        as_dict=True,
    )


def _do_notify_class_new_post(event_data):
    """Background: thông báo bài mới trong Nhật ký lớp tới PH (có studentId gợi ý trong payload)."""
    try:
        raw_author_name = event_data.get("authorName", "Ai đó")
        author_name = format_vietnamese_name(raw_author_name)
        post_id = event_data.get("postId")
        content_preview = (event_data.get("content", "") or "")[:50]
        author_email = (event_data.get("authorEmail") or "").strip().lower()

        class_id = event_data.get("classId") or event_data.get("class_id")
        school_year_id = event_data.get("schoolYearId") or event_data.get("school_year_id")

        if not post_id or not class_id:
            frappe.logger().warning("⚠️ [Wislife Class Post Job] Thiếu postId hoặc classId")
            return

        pairs = _guardian_student_pairs_for_class(class_id, school_year_id)
        frappe.logger().info(
            f"📱 [Wislife Class Post Job] class={class_id} sy={school_year_id or '_'} → pairs={len(pairs)}"
        )
        if not pairs:
            # Thử lại không lọc school_year_id để tránh mismatch (data cũ / format khác).
            if school_year_id:
                pairs = _guardian_student_pairs_for_class(class_id, None)
                frappe.logger().info(
                    f"📱 [Wislife Class Post Job] retry không lọc school_year_id → pairs={len(pairs)}"
                )
            if not pairs:
                frappe.logger().warning(
                    f"⚠️ [Wislife Class Post Job] Không có PH nào cho lớp {class_id}"
                )
                return

        # Mỗi guardian (portal email) → tập con trong lớp; chọn 1 studentId để deep link mobile
        email_to_students = defaultdict(set)
        for row in pairs:
            gid = row.get("guardian_id")
            sid = row.get("student_id")
            portal = _portal_email_from_guardian_id(gid)
            if portal and sid:
                email_to_students[portal].add(sid)

        notification_message = f'{author_name} vừa đăng: "{content_preview}..."'
        push_title = "Wislife - Bài viết mới"

        targets = []
        for portal_email, student_set in email_to_students.items():
            if author_email and portal_email.strip().lower() == author_email:
                continue
            pick_student = sorted(student_set)[0]
            base = {
                "type": "wislife_new_post",
                "postId": post_id,
                "action": "open_post",
                "studentId": pick_student,
                "student_id": pick_student,
            }
            base.update(_wislife_extra_fields(event_data))
            targets.append({"email": portal_email, "data": base})

        if not targets:
            frappe.logger().info("📱 [Wislife Class Post Job] Không có người nhận sau khi lọc tác giả")
            return

        frappe.logger().info(
            f"📱 [Wislife Class Post Job] Gửi tới {len(targets)} PH cho lớp {class_id}"
        )

        try:
            bulk_result = send_mobile_notifications_bulk(
                targets,
                push_title,
                notification_message,
            )
            frappe.logger().info(
                f"✅ [Wislife Class Post Job] Bulk Expo: {bulk_result.get('success_count', 0)}/"
                f"{bulk_result.get('total_messages', 0)}"
            )
        except Exception as bulk_err:
            frappe.logger().error(f"❌ [Wislife Class Post Job] Bulk Expo failed: {str(bulk_err)}")

        saved = 0
        for t in targets:
            em = t["email"]
            data = t["data"]
            try:
                create_notification(
                    title=push_title,
                    message=notification_message,
                    recipient_user=em,
                    notification_type="system",
                    priority="normal",
                    data={**data, "actorName": author_name},
                    channel="push",
                    event_timestamp=frappe.utils.now(),
                )
                saved += 1
            except Exception as db_err:
                frappe.logger().error(f"❌ [Wislife Class Post Job] DB {em}: {str(db_err)}")

        frappe.logger().info(f"✅ [Wislife Class Post Job] Đã lưu notification center: {saved}/{len(targets)}")

    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Class Post Job] {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Class Post Job Error")


def _do_broadcast_new_post(event_data):
    """
    Background job: Thực hiện gửi notification đến tất cả users
    """
    try:
        raw_author_name = event_data.get('authorName', 'Ai đó')
        author_name = format_vietnamese_name(raw_author_name)
        post_id = event_data.get('postId')
        content_preview = event_data.get('content', '')[:50]
        author_email = (event_data.get('authorEmail') or '').strip().lower()

        frappe.logger().info(f"📱 [Wislife Broadcast Job] Starting for post by {author_name}")

        # Lấy tất cả users có device token đã đăng ký + user còn enabled (loại tài khoản bị khoá).
        token_rows = frappe.db.sql(
            """
            SELECT DISTINCT t.user AS user
            FROM `tabMobile Device Token` t
            INNER JOIN `tabUser` u ON u.name = t.user
            WHERE t.is_active = 1
              AND u.enabled = 1
              AND IFNULL(t.user, '') != ''
            """,
            as_dict=True,
        )

        if not token_rows:
            frappe.logger().warning("📱 [Wislife Broadcast Job] No active device tokens found")
            return

        # Dedupe + loại bỏ author (case-insensitive); chuẩn hoá lowercase email Frappe.
        seen = set()
        recipient_emails = []
        for row in token_rows:
            email = (row.get("user") or "").strip().lower()
            if not email or email in seen:
                continue
            if author_email and email == author_email:
                continue
            seen.add(email)
            recipient_emails.append(email)

        frappe.logger().info(
            f"📱 [Wislife Broadcast Job] tokens={len(token_rows)} → recipients={len(recipient_emails)} (author={author_email or '_'})"
        )

        if not recipient_emails:
            frappe.logger().warning("📱 [Wislife Broadcast Job] No recipients sau khi loại author")
            return
        
        notification_message = f'{author_name} vừa đăng: "{content_preview}..."'
        notification_data = {
            'type': 'wislife_new_post',
            'postId': post_id,
            'action': 'open_post',
        }
        notification_data.update(_wislife_extra_fields(event_data))

        # Wave 2 - F.4: Gửi Expo BATCH 1 lần (max 100 messages/POST) cho toàn bộ users
        # Trước: N POST × 5s với N=2000 = 10000s. Sau: 20 POST × 5s = 100s tối đa.
        try:
            targets = [{"email": email, "data": notification_data} for email in recipient_emails]
            bulk_result = send_mobile_notifications_bulk(
                targets,
                'Wislife - Bài viết mới',
                notification_message,
            )
            success_count = bulk_result.get('success_count', 0)
            total_messages = bulk_result.get('total_messages', 0)
            frappe.logger().info(
                f"✅ [Wislife Broadcast Job] Bulk Expo: {success_count}/{total_messages} messages OK"
            )
        except Exception as bulk_err:
            frappe.logger().error(f"❌ [Wislife Broadcast Job] Bulk Expo failed: {str(bulk_err)}")

        # Lưu Notification Center per-user (DB write nhanh, không nghẽn)
        saved_count = 0
        for user_email in recipient_emails:
            try:
                create_notification(
                    title="Wislife - Bài viết mới",
                    message=notification_message,
                    recipient_user=user_email,
                    notification_type="system",
                    priority="normal",
                    data={
                        'type': 'wislife_new_post',
                        'postId': post_id,
                        'action': 'open_post',
                        'actorName': author_name,
                        **_wislife_extra_fields(event_data),
                    },
                    channel="push",
                    event_timestamp=frappe.utils.now(),
                )
                saved_count += 1
            except Exception as db_error:
                frappe.logger().error(f"❌ [Wislife Broadcast Job] DB save failed for {user_email}: {str(db_error)}")

        frappe.logger().info(f"✅ [Wislife Broadcast Job] Saved to DB: {saved_count}/{len(recipient_emails)}")
        
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Broadcast Job] Error: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Broadcast Job Error")


def handle_post_tagged(event_data):
    """
    Wave 3: Có người tag user trong bài — social-service gửi recipientEmails.
    """
    try:
        recipient_emails = event_data.get('recipientEmails') or []
        if not isinstance(recipient_emails, list):
            recipient_emails = []
        recipient_emails = [e for e in recipient_emails if e]
        if not recipient_emails:
            frappe.logger().warning("⚠️ [Wislife Post Tagged] No recipientEmails")
            return

        post_id = event_data.get('postId')
        author_name = format_vietnamese_name(event_data.get('authorName', 'Ai đó'))
        notification_message = f'{author_name} đã tag bạn trong một bài viết'
        extra = _wislife_extra_fields(event_data)
        push_data = {
            'type': 'wislife_post_tagged',
            'postId': post_id,
            'action': 'open_post',
            **extra,
        }
        targets = [{"email": e, "data": push_data} for e in recipient_emails]
        try:
            bulk_result = send_mobile_notifications_bulk(targets, 'Wislife', notification_message)
            frappe.logger().info(
                f"✅ [Wislife Post Tagged] Bulk Expo: {bulk_result.get('success_count', 0)}/"
                f"{bulk_result.get('total_messages', 0)}"
            )
        except Exception as bulk_err:
            frappe.logger().error(f"❌ [Wislife Post Tagged] Bulk failed: {bulk_err}")

        for recipient_email in recipient_emails:
            try:
                create_notification(
                    title="Wislife",
                    message=notification_message,
                    recipient_user=recipient_email,
                    notification_type="system",
                    priority="normal",
                    data={**push_data, 'actorName': author_name},
                    channel="push",
                    event_timestamp=frappe.utils.now(),
                )
            except Exception as db_error:
                frappe.logger().error(f"❌ [Wislife Post Tagged] DB {recipient_email}: {str(db_error)}")
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Post Tagged] Error: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Post Tagged Error")


def handle_post_reacted(event_data):
    """
    Xử lý khi có người react bài viết
    
    Args:
        event_data: Dictionary containing postId, recipientEmail, userEmail, userName, reactionType
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Post React] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        extra = _wislife_extra_fields(event_data)
        
        # Message đơn giản, không cần chi tiết emoji
        notification_message = f'{user_name} đã bày tỏ cảm xúc về bài viết của bạn'
        push_data = {
            'type': 'wislife_post_reaction',
            'postId': post_id,
            'action': 'open_post',
            **extra,
        }

        # Wave 3: gửi Expo qua bulk (đồng bộ pattern Wave 2)
        try:
            result = send_mobile_notifications_bulk(
                [{"email": recipient_email, "data": push_data}],
                'Wislife',
                notification_message,
            )
            if result.get("success"):
                frappe.logger().info(f"✅ [Wislife Post React] Push sent to {recipient_email}")
            else:
                frappe.logger().warning(f"⚠️ [Wislife Post React] Push may have failed: {result.get('message')}")
        except Exception as push_err:
            frappe.logger().error(f"❌ [Wislife Post React] Bulk push error: {str(push_err)}")
        
        # Lưu vào Notification Center để frontend có thể query và hiển thị
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_post_reaction',
                    'postId': post_id,
                    'action': 'open_post',
                    'actorName': user_name,
                    'reactionType': event_data.get('reactionType'),
                    **extra,
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Post React] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Post React] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Post React] Error in handle_post_reacted: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Post React Error")


def handle_post_commented(event_data):
    """
    Xử lý khi có người comment bài viết
    
    Args:
        event_data: Dictionary containing postId, recipientEmail, userEmail, userName, content
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Post Comment] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        extra = _wislife_extra_fields(event_data)
        
        notification_message = f'{user_name} đã bình luận bài viết của bạn'
        push_data = {
            'type': 'wislife_post_comment',
            'postId': post_id,
            'action': 'open_post',
            **extra,
        }

        try:
            result = send_mobile_notifications_bulk(
                [{"email": recipient_email, "data": push_data}],
                'Wislife',
                notification_message,
            )
            if result.get("success"):
                frappe.logger().info(f"✅ [Wislife Post Comment] Push sent to {recipient_email}")
            else:
                frappe.logger().warning(f"⚠️ [Wislife Post Comment] Push may have failed: {result.get('message')}")
        except Exception as push_err:
            frappe.logger().error(f"❌ [Wislife Post Comment] Bulk push error: {str(push_err)}")
        
        # Lưu vào Notification Center
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_post_comment',
                    'postId': post_id,
                    'action': 'open_post',
                    'actorName': user_name,
                    **extra,
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Post Comment] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Post Comment] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Post Comment] Error in handle_post_commented: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Post Comment Error")


def handle_comment_replied(event_data):
    """
    Xử lý khi có người reply comment
    
    Args:
        event_data: Dictionary containing postId, commentId, recipientEmail, userEmail, userName, content
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Comment Reply] No recipient email provided")
            return

        # Debug: đếm device token đang active cho recipient để chẩn đoán "không nhận noti"
        try:
            token_count = frappe.db.count(
                "Mobile Device Token",
                {"user": recipient_email, "is_active": 1},
            )
            frappe.logger().info(
                f"🔍 [Wislife Comment Reply] recipient={recipient_email} active_tokens={token_count}"
            )
        except Exception:
            pass

        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        comment_id = event_data.get('commentId')
        extra = _wislife_extra_fields(event_data)
        
        notification_message = f'{user_name} đã trả lời bình luận của bạn'
        push_data = {
            'type': 'wislife_comment_reply',
            'postId': post_id,
            'commentId': comment_id,
            'action': 'open_post',
            **extra,
        }

        try:
            result = send_mobile_notifications_bulk(
                [{"email": recipient_email, "data": push_data}],
                'Wislife',
                notification_message,
            )
            if result.get("success"):
                frappe.logger().info(f"✅ [Wislife Comment Reply] Push sent to {recipient_email}")
            else:
                frappe.logger().warning(f"⚠️ [Wislife Comment Reply] Push may have failed: {result.get('message')}")
        except Exception as push_err:
            frappe.logger().error(f"❌ [Wislife Comment Reply] Bulk push error: {str(push_err)}")
        
        # Lưu vào Notification Center
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_comment_reply',
                    'postId': post_id,
                    'commentId': comment_id,
                    'action': 'open_post',
                    'actorName': user_name,
                    **extra,
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Comment Reply] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Comment Reply] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Comment Reply] Error in handle_comment_replied: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Comment Reply Error")


def handle_comment_reacted(event_data):
    """
    Xử lý khi có người react comment
    
    Args:
        event_data: Dictionary containing postId, commentId, recipientEmail, userEmail, userName, reactionType
    """
    try:
        recipient_email = event_data.get('recipientEmail')
        if not recipient_email:
            frappe.logger().warning(f"⚠️ [Wislife Comment React] No recipient email provided")
            return
            
        # Format tên theo chuẩn Việt Nam
        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        comment_id = event_data.get('commentId')
        extra = _wislife_extra_fields(event_data)
        
        # Message đơn giản
        notification_message = f'{user_name} đã bày tỏ cảm xúc về bình luận của bạn'
        push_data = {
            'type': 'wislife_comment_reaction',
            'postId': post_id,
            'commentId': comment_id,
            'action': 'open_post',
            **extra,
        }

        try:
            result = send_mobile_notifications_bulk(
                [{"email": recipient_email, "data": push_data}],
                'Wislife',
                notification_message,
            )
            if result.get("success"):
                frappe.logger().info(f"✅ [Wislife Comment React] Push sent to {recipient_email}")
            else:
                frappe.logger().warning(f"⚠️ [Wislife Comment React] Push may have failed: {result.get('message')}")
        except Exception as push_err:
            frappe.logger().error(f"❌ [Wislife Comment React] Bulk push error: {str(push_err)}")
        
        # Lưu vào Notification Center
        try:
            create_notification(
                title="Wislife",
                message=notification_message,
                recipient_user=recipient_email,
                notification_type="system",
                priority="low",
                data={
                    'type': 'wislife_comment_reaction',
                    'postId': post_id,
                    'commentId': comment_id,
                    'action': 'open_post',
                    'actorName': user_name,
                    'reactionType': event_data.get('reactionType'),
                    **extra,
                },
                channel="push",
                event_timestamp=frappe.utils.now()
            )
            frappe.logger().info(f"✅ [Wislife Comment React] Saved to notification center for {recipient_email}")
        except Exception as db_error:
            frappe.logger().error(f"❌ [Wislife Comment React] Failed to save to notification center: {str(db_error)}")
            
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Comment React] Error in handle_comment_reacted: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Comment React Error")


def handle_post_mention(event_data):
    """
    Wave 2 - F.4: chỉ enqueue, xử lý nặng chuyển sang _do_handle_post_mention
    để webhook social-service không phải chờ.
    """
    try:
        frappe.enqueue(
            'erp.api.notification.wislife._do_handle_post_mention',
            queue='short',
            timeout=180,
            event_data=event_data,
        )
        frappe.logger().info("📱 [Wislife Mention] Enqueued for async processing")
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Mention] Enqueue failed, fallback sync: {str(e)}")
        _do_handle_post_mention(event_data)


def _do_handle_post_mention(event_data):
    """
    Background job: xử lý mention - dùng send_mobile_notifications_bulk thay vì loop.
    """
    try:
        mentioned_emails = event_data.get('mentionedEmails', [])
        mentioned_names = event_data.get('mentionedNames', [])

        raw_name = event_data.get('userName', 'Ai đó')
        user_name = format_vietnamese_name(raw_name)
        post_id = event_data.get('postId')
        comment_id = event_data.get('commentId')

        notification_message = f'{user_name} đã nhắc đến bạn trong một bình luận'
        # Wave 3: classId / studentId cho deep link mobile
        extra = _wislife_extra_fields(event_data)
        notification_data = {
            'type': 'wislife_mention',
            'postId': post_id,
            'commentId': comment_id,
            'action': 'open_post',
            **extra,
        }
        center_data = {
            **notification_data,
            'actorName': user_name,
        }

        # Resolve danh sách email: ưu tiên mentionedEmails, fallback lookup theo name (legacy)
        recipient_emails = []
        if mentioned_emails:
            recipient_emails = [e for e in mentioned_emails if e]
            frappe.logger().info(f"📱 [Wislife Mention] Processing {len(recipient_emails)} mentions by email")
        elif mentioned_names:
            frappe.logger().info(f"📱 [Wislife Mention] Processing mentions by name (legacy): {mentioned_names}")
            for name in mentioned_names:
                try:
                    users = frappe.db.sql(
                        """
                        SELECT email FROM `tabUser`
                        WHERE full_name LIKE %s AND enabled = 1 AND email IS NOT NULL
                        LIMIT 1
                        """,
                        (f"%{name}%",),
                        as_dict=True,
                    )
                    if not users:
                        users = frappe.db.sql(
                            """
                            SELECT email FROM `tabCRM Teacher`
                            WHERE teacher_name LIKE %s AND email IS NOT NULL
                            LIMIT 1
                            """,
                            (f"%{name}%",),
                            as_dict=True,
                        )
                    if users:
                        email = users[0].get('email')
                        if email:
                            recipient_emails.append(email)
                    else:
                        frappe.logger().warning(f"⚠️ [Wislife Mention] No user found for name: {name}")
                except Exception as lookup_err:
                    frappe.logger().error(f"❌ [Wislife Mention] Lookup error for {name}: {str(lookup_err)}")
        else:
            frappe.logger().warning("⚠️ [Wislife Mention] No mentions provided")
            return

        if not recipient_emails:
            frappe.logger().warning("⚠️ [Wislife Mention] No recipients resolved")
            return

        # Wave 2 - F.4: Gửi Expo BATCH 1 lần thay vì loop
        try:
            targets = [{"email": email, "data": notification_data} for email in recipient_emails]
            bulk_result = send_mobile_notifications_bulk(targets, 'Wislife', notification_message)
            frappe.logger().info(
                f"✅ [Wislife Mention] Bulk Expo: {bulk_result.get('success_count', 0)}/"
                f"{bulk_result.get('total_messages', 0)} OK"
            )
        except Exception as bulk_err:
            frappe.logger().error(f"❌ [Wislife Mention] Bulk Expo failed: {str(bulk_err)}")

        saved_count = 0
        for recipient_email in recipient_emails:
            try:
                create_notification(
                    title="Wislife",
                    message=notification_message,
                    recipient_user=recipient_email,
                    notification_type="system",
                    priority="normal",
                    data=center_data,
                    channel="push",
                    event_timestamp=frappe.utils.now(),
                )
                saved_count += 1
            except Exception as db_error:
                frappe.logger().error(f"❌ [Wislife Mention] DB error for {recipient_email}: {str(db_error)}")

        frappe.logger().info(f"✅ [Wislife Mention] Saved {saved_count}/{len(recipient_emails)} to notification center")

    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Mention Async] Error: {str(e)}")
        frappe.log_error(message=str(e), title="Wislife Mention Async Error")


# Whitelist for testing
@frappe.whitelist(allow_guest=True, methods=['GET', 'POST'])
def test_wislife_notification():
    """
    Test endpoint để verify Wislife notification flow
    GET: Kiểm tra endpoint có hoạt động không
    POST: Gửi test notification đến user cụ thể
    
    POST body:
    {
        "user_email": "user@example.com",
        "event_type": "post_reacted",
        "post_id": "test123"
    }
    """
    try:
        if frappe.request.method == 'GET':
            # Health check
            return {
                "success": True,
                "message": "Wislife notification endpoint is working",
                "timestamp": datetime.now().isoformat()
            }
        
        # POST - Send test notification
        data = frappe.form_dict
        if not data:
            data = json.loads(frappe.local.request.get_data() or '{}')
        
        user_email = data.get('user_email')
        if not user_email:
            return {"success": False, "message": "user_email is required"}
        
        event_type = data.get('event_type', 'post_reacted')
        post_id = data.get('post_id', 'test-post-123')
        
        # Check if user has device tokens
        tokens = frappe.get_all("Mobile Device Token",
            filters={"user": user_email, "is_active": 1},
            fields=["device_token", "platform", "device_name"]
        )
        
        frappe.logger().info(f"🧪 [Wislife Test] Found {len(tokens)} device tokens for {user_email}")
        
        if not tokens:
            return {
                "success": False,
                "message": f"No active device tokens found for user: {user_email}",
                "hint": "Make sure the user has registered their mobile device"
            }
        
        # Send test notification
        result = send_mobile_notification(
            user_email=user_email,
            title='Wislife Test Notification',
            body='This is a test notification from Wislife system',
            data={
                'type': f'wislife_{event_type}',
                'postId': post_id,
                'action': 'open_post'
            }
        )
        
        return {
            "success": True,
            "message": f"Test notification sent to {user_email}",
            "device_count": len(tokens),
            "devices": [{"platform": t.platform, "device_name": t.device_name} for t in tokens],
            "result": result
        }
        
    except Exception as e:
        frappe.logger().error(f"❌ [Wislife Test] Error: {str(e)}")
        return {"success": False, "message": str(e)}




