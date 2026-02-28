"""
Push Notification cho Daily Health Visit
Gửi notification đến Mobile Medical, Homeroom Teacher, Vice-Homeroom Teacher
khi có sự kiện y tế (tạo visit, tiếp nhận, checkout, escalation).
"""

import frappe
from frappe.utils import now, today, get_datetime, now_datetime, time_diff_in_seconds
from typing import List, Dict, Set


# =====================================================================
# Resolve danh sách người nhận notification
# =====================================================================

def _get_mobile_medical_users() -> List[str]:
    """Lấy tất cả user có role Mobile Medical và có active device token."""
    users = frappe.db.sql("""
        SELECT DISTINCT hr.parent
        FROM `tabHas Role` hr
        INNER JOIN `tabUser` u ON u.name = hr.parent
        WHERE hr.role = 'Mobile Medical'
          AND u.enabled = 1
          AND hr.parent != 'Administrator'
    """, pluck=True)

    if not users:
        return []

    # Chỉ lấy user có active device token (đã đăng ký mobile)
    users_with_token = frappe.get_all(
        "Mobile Device Token",
        filters={"user": ["in", users], "is_active": 1},
        fields=["user"],
        pluck="user",
        distinct=True
    )
    return users_with_token


def _get_homeroom_teachers(class_id: str) -> List[str]:
    """Lấy email của homeroom + vice-homeroom teacher từ class_id."""
    class_doc = frappe.db.get_value(
        "SIS Class", class_id,
        ["homeroom_teacher", "vice_homeroom_teacher"],
        as_dict=True
    )
    if not class_doc:
        return []

    teacher_ids = []
    if class_doc.get("homeroom_teacher"):
        teacher_ids.append(class_doc["homeroom_teacher"])
    if class_doc.get("vice_homeroom_teacher"):
        teacher_ids.append(class_doc["vice_homeroom_teacher"])

    if not teacher_ids:
        return []

    # SIS Teacher -> user_id (email)
    emails = []
    for tid in teacher_ids:
        user_id = frappe.db.get_value("SIS Teacher", tid, "user_id")
        if user_id:
            emails.append(user_id)
    return emails


def get_health_notification_recipients(
    class_id: str,
    include_medical: bool = True,
    include_homeroom: bool = True,
    extra_users: List[str] = None
) -> List[str]:
    """
    Trả về danh sách unique user emails cần nhận notification.
    - include_medical: bao gồm tất cả user có role Mobile Medical
    - include_homeroom: bao gồm homeroom + vice-homeroom teacher của lớp
    - extra_users: danh sách user_email bổ sung (VD: reporter)
    """
    recipients: Set[str] = set()

    if include_medical:
        recipients.update(_get_mobile_medical_users())

    if include_homeroom:
        recipients.update(_get_homeroom_teachers(class_id))

    if extra_users:
        for u in extra_users:
            if u and u != "Administrator" and u != "Guest":
                recipients.add(u)

    return list(recipients)


# =====================================================================
# Gửi notification cho từng sự kiện
# =====================================================================

def _send_to_recipients(recipients: List[str], title: str, body: str, data: Dict):
    """Gửi mobile push notification đến danh sách recipients."""
    from erp.api.erp_sis.mobile_push_notification import send_mobile_notification

    for user_email in recipients:
        try:
            send_mobile_notification(
                user_email=user_email,
                title=title,
                body=body,
                data=data
            )
        except Exception as e:
            frappe.logger().warning(
                f"[health_notification] Không gửi được notification cho {user_email}: {str(e)}"
            )


def notify_health_visit_created(visit_name: str):
    """
    Gửi notification khi tạo mới Daily Health Visit.
    Người nhận: Mobile Medical + Homeroom + Vice-homeroom
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        class_name = visit.class_name or visit.class_id
        reason = visit.reason or ""

        recipients = get_health_notification_recipients(
            class_id=visit.class_id,
            include_medical=True,
            include_homeroom=True
        )

        if not recipients:
            return

        title = "Báo Y tế"
        body = f"{student_name} ({class_name}) đã được báo xuống Y tế. Lý do: {reason}"

        data = {
            "type": "health_visit_created",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": visit.class_id,
            "class_name": class_name,
            "status": visit.status,
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_created cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_created: {str(e)}")


def notify_health_visit_received(visit_name: str):
    """
    Gửi notification khi Y tế tiếp nhận học sinh (left_class -> at_clinic).
    Người nhận: Homeroom + Vice-homeroom + Reporter (người báo ban đầu)
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id

        extra_users = []
        if visit.reported_by:
            extra_users.append(visit.reported_by)

        recipients = get_health_notification_recipients(
            class_id=visit.class_id,
            include_medical=False,
            include_homeroom=True,
            extra_users=extra_users
        )

        if not recipients:
            return

        title = "Y tế đã tiếp nhận"
        body = f"{student_name} đã được tiếp nhận tại phòng Y tế"

        data = {
            "type": "health_visit_received",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": visit.class_id,
            "status": "at_clinic",
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_received cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_received: {str(e)}")


def notify_health_visit_completed(visit_name: str):
    """
    Gửi notification khi Y tế checkout học sinh.
    Người nhận: Homeroom + Vice-homeroom + Mobile Medical
    Nội dung thay đổi tùy outcome (returned / picked_up / transferred).
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        outcome = visit.status

        outcome_messages = {
            "returned": ("HS đã về lớp", f"{student_name} đã được Y tế cho về lớp"),
            "picked_up": ("PH đã đón HS", f"{student_name} đã được phụ huynh đón về"),
            "transferred": ("Chuyển viện", f"{student_name} đã được chuyển viện"),
        }

        title, body = outcome_messages.get(
            outcome,
            ("Hoàn thành Y tế", f"{student_name} đã hoàn thành lượt xuống Y tế")
        )

        recipients = get_health_notification_recipients(
            class_id=visit.class_id,
            include_medical=True,
            include_homeroom=True
        )

        if not recipients:
            return

        data = {
            "type": "health_visit_completed",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": visit.class_id,
            "status": outcome,
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_completed ({outcome}) cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_completed: {str(e)}")


# =====================================================================
# Scheduled job: kiểm tra visit quá 15 phút chưa chuyển trạng thái
# =====================================================================

def check_stale_health_visits():
    """
    Scheduled job (chạy mỗi 5 phút).
    Tìm các visit có status = 'left_class' và đã tạo hơn 15 phút trước.
    Gửi escalation notification cho Mobile Medical.
    Dùng Redis debounce để tránh gửi lặp cho cùng một visit.
    """
    try:
        from datetime import timedelta

        threshold = now_datetime() - timedelta(minutes=15)

        stale_visits = frappe.db.sql("""
            SELECT name, student_id, student_name, class_id, class_name,
                   reason, creation, reported_by
            FROM `tabSIS Daily Health Visit`
            WHERE status = 'left_class'
              AND visit_date = %(today)s
              AND creation <= %(threshold)s
        """, {"today": today(), "threshold": threshold}, as_dict=True)

        if not stale_visits:
            return

        redis = frappe.cache()

        for visit in stale_visits:
            debounce_key = f"health_escalation:{visit.name}"
            if redis.get_value(debounce_key):
                continue

            student_name = visit.student_name or visit.student_id
            class_name = visit.class_name or visit.class_id

            recipients = _get_mobile_medical_users()
            if not recipients:
                continue

            title = "Nhắc nhở Y tế"
            body = f"{student_name} ({class_name}) đã rời lớp hơn 15 phút nhưng chưa đến phòng Y tế"

            data = {
                "type": "health_visit_escalation",
                "visit_id": visit.name,
                "student_id": visit.student_id,
                "student_name": student_name,
                "class_id": visit.class_id,
                "status": "left_class",
            }

            _send_to_recipients(recipients, title, body, data)

            # Đánh dấu đã gửi escalation, TTL 4 giờ (tránh gửi lặp trong ngày)
            redis.set_value(debounce_key, "1", expires_in_sec=14400)

            frappe.logger().info(
                f"[health_notification] Đã gửi escalation cho visit {visit.name} - "
                f"{student_name} (left_class > 15 phút)"
            )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi check_stale_health_visits: {str(e)}")
