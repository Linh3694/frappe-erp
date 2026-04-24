"""
Push Notification cho Daily Health Visit
Gửi notification đến Mobile Medical, Mobile Supervisory (giám thị hành lang),
Homeroom Teacher, Vice-Homeroom Teacher khi có sự kiện y tế (tạo visit, tiếp nhận, checkout, escalation).
"""

import frappe
from frappe.utils import now, today, get_datetime, now_datetime, time_diff_in_seconds
from typing import List, Dict, Set, Optional, Tuple

from erp.api.erp_sis.student import _get_homeroom_class_map_for_students

# Tiêu đề thống nhất mọi push y tế (workspace-mobile)
STANDARD_HEALTH_NOTIFICATION_TITLE = "Thông báo Y tế"


# =====================================================================
# Resolve danh sách người nhận notification
# =====================================================================

def _get_users_by_role_with_mobile_token(role: str) -> List[str]:
    """Lấy user có role Frappe `role` và có Mobile Device Token đang active."""
    users = frappe.db.sql("""
        SELECT DISTINCT hr.parent
        FROM `tabHas Role` hr
        INNER JOIN `tabUser` u ON u.name = hr.parent
        WHERE hr.role = %(role)s
          AND u.enabled = 1
          AND hr.parent != 'Administrator'
    """, {"role": role}, pluck=True)

    if not users:
        return []

    return frappe.get_all(
        "Mobile Device Token",
        filters={"user": ["in", users], "is_active": 1},
        fields=["user"],
        pluck="user",
        distinct=True,
    )


def _get_mobile_medical_users() -> List[str]:
    """Lấy tất cả user có role Mobile Medical và có active device token."""
    return _get_users_by_role_with_mobile_token("Mobile Medical")


def _get_mobile_supervisory_users() -> List[str]:
    """Lấy user có role Mobile Supervisory (giám thị hành lang) và có active device token."""
    return _get_users_by_role_with_mobile_token("Mobile Supervisory")


def _get_homeroom_teachers(class_id: str) -> List[str]:
    """Lấy email của homeroom + vice-homeroom teacher từ class_id."""
    if not class_id:
        return []
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


def _label_hoc_sinh(ten_hien_thi: str) -> str:
    """Nội dung push: gắn 'Học sinh' trước tên khi hiển thị học sinh."""
    t = (ten_hien_thi or "").strip()
    if not t:
        return ""
    return f"Học sinh {t}"


def _regular_class_id_and_title(
    student_id: Optional[str],
    fallback_class_id: Optional[str] = None,
    fallback_title: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """
    Lấy lớp regular (chủ nhiệm) từ SIS Class Student + SIS Class; fallback class trên visit nếu không có.
    Dùng cho copy push và cho class_id gửi GVCN (tránh lớp mixed/club).
    """
    if not student_id:
        return fallback_class_id, (fallback_title or fallback_class_id or "")
    try:
        campus_id = frappe.db.get_value("CRM Student", student_id, "campus_id")
    except Exception:
        campus_id = None
    m = _get_homeroom_class_map_for_students([student_id], campus_id)
    if student_id in m:
        r = m[student_id]
        rid = r.get("class_id") or fallback_class_id
        t = (r.get("class_title") or "").strip()
        if not t:
            t = (fallback_title or fallback_class_id or "")
        return rid, t
    return fallback_class_id, (fallback_title or fallback_class_id or "")


def get_health_notification_recipients(
    class_id: str,
    include_medical: bool = True,
    include_homeroom: bool = True,
    include_supervisory: bool = False,
    extra_users: List[str] = None,
) -> List[str]:
    """
    Trả về danh sách unique user emails cần nhận notification.
    - include_medical: bao gồm tất cả user có role Mobile Medical
    - include_homeroom: bao gồm homeroom + vice-homeroom teacher của lớp
    - include_supervisory: bao gồm user role Mobile Supervisory (theo dõi lộ trình hành lang khi HS đi/về Y tế)
    - extra_users: danh sách user_email bổ sung (VD: reporter)
    """
    recipients: Set[str] = set()

    if include_medical:
        recipients.update(_get_mobile_medical_users())

    if include_supervisory:
        recipients.update(_get_mobile_supervisory_users())

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
    """Gửi ERP Notification + mobile push Expo đến danh sách recipients."""
    from erp.api.erp_sis.mobile_push_notification import send_mobile_notification_persisted

    visit_ref = (data or {}).get("visit_id") or (data or {}).get("visitId")
    for user_email in recipients:
        try:
            send_mobile_notification_persisted(
                user_email=user_email,
                title=title,
                body=body,
                data=data,
                erp_notification_type="health_examination",
                reference_doctype="SIS Daily Health Visit" if visit_ref else None,
                reference_name=visit_ref,
            )
        except Exception as e:
            frappe.logger().warning(
                f"[health_notification] Không gửi được notification cho {user_email}: {str(e)}"
            )


def notify_health_visit_created(visit_name: str):
    """
    Gửi notification khi tạo mới Daily Health Visit.
    Người nhận: Mobile Medical + Mobile Supervisory + Homeroom + Vice-homeroom.
    (Giám thị: biết HS được báo xuống Y tế để theo dõi lộ trình hành lang.)
    """
    try:
        frappe.logger().info(f"[health_notification] === BẮT ĐẦU notify_health_visit_created cho visit {visit_name} ===")

        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        r_class_id, class_name = _regular_class_id_and_title(
            visit.student_id, visit.class_id, visit.class_name
        )
        reason = visit.reason or ""
        label_hs = _label_hoc_sinh(student_name)

        frappe.logger().info(
            f"[health_notification] Visit info: student={student_name}, class_visit={visit.class_id}, "
            f"class_regular={r_class_id}, status={visit.status}"
        )

        # Log chi tiết từng bước resolve recipients
        medical_users = _get_mobile_medical_users()
        frappe.logger().info(f"[health_notification] Mobile Medical users: {medical_users}")

        homeroom_teachers = _get_homeroom_teachers(r_class_id)
        frappe.logger().info(f"[health_notification] Homeroom teachers: {homeroom_teachers}")

        supervisory_users = _get_mobile_supervisory_users()
        frappe.logger().info(f"[health_notification] Mobile Supervisory users: {supervisory_users}")

        recipients = get_health_notification_recipients(
            class_id=r_class_id,
            include_medical=True,
            include_homeroom=True,
            include_supervisory=True,
        )

        frappe.logger().info(f"[health_notification] Tổng recipients: {recipients}")

        if not recipients:
            frappe.logger().warning(f"[health_notification] KHÔNG TÌM THẤY người nhận nào cho visit {visit_name}")
            return

        title = STANDARD_HEALTH_NOTIFICATION_TITLE
        body = f"{label_hs} ({class_name}) đã được báo xuống Y tế. Lý do: {reason}"

        data = {
            "type": "health_visit_created",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": r_class_id,
            "class_name": class_name,
            "status": visit.status,
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_created cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_created: {str(e)}")
        import traceback
        frappe.logger().error(f"[health_notification] Traceback: {traceback.format_exc()}")


def notify_health_visit_received(visit_name: str):
    """
    Gửi notification khi Y tế tiếp nhận học sinh (left_class -> at_clinic).
    Người nhận: Mobile Supervisory + Homeroom + Vice-homeroom + Reporter.
    (Giám thị: HS đã vào phòng Y tế — cập nhật hiện diện trên hành lang.)
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        r_class_id, class_name = _regular_class_id_and_title(
            visit.student_id, visit.class_id, visit.class_name
        )
        label_hs = _label_hoc_sinh(student_name)

        extra_users = []
        if visit.reported_by:
            extra_users.append(visit.reported_by)

        recipients = get_health_notification_recipients(
            class_id=r_class_id,
            include_medical=False,
            include_homeroom=True,
            include_supervisory=True,
            extra_users=extra_users,
        )

        if not recipients:
            return

        title = STANDARD_HEALTH_NOTIFICATION_TITLE
        body = f"{label_hs} đã được tiếp nhận tại phòng Y tế"

        data = {
            "type": "health_visit_received",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": r_class_id,
            "class_name": class_name,
            "status": "at_clinic",
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_received cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_received: {str(e)}")


def notify_health_visit_cancelled(visit_name: str):
    """
    Gửi notification khi GV hủy đơn báo Y tế (học sinh quay lại lớp / trốn đi chơi).
    Người nhận: Mobile Medical + Mobile Supervisory.
    (Giám thị: điều chỉnh theo dõi — HS có thể không còn trên tuyến xuống Y tế.)
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        r_class_id, class_name = _regular_class_id_and_title(
            visit.student_id, visit.class_id, visit.class_name
        )
        label_hs = _label_hoc_sinh(student_name)

        recipients = get_health_notification_recipients(
            class_id=r_class_id,
            include_medical=True,
            include_homeroom=False,
            include_supervisory=True,
        )

        if not recipients:
            return

        title = STANDARD_HEALTH_NOTIFICATION_TITLE
        body = f"{label_hs} ({class_name}) - GV đã hủy đơn báo xuống Y tế"

        data = {
            "type": "health_visit_cancelled",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": r_class_id,
            "class_name": class_name,
            "status": "cancelled",
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_cancelled cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_cancelled: {str(e)}")


def notify_health_visit_rejected(visit_name: str):
    """
    Gửi notification khi Y tế từ chối tiếp nhận học sinh.
    Người nhận: Mobile Supervisory + Homeroom + Vice-homeroom + Reporter.
    (Giám thị: HS quay lớp qua hành lang — phối hợp an toàn lộ trình.)
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        r_class_id, class_name = _regular_class_id_and_title(
            visit.student_id, visit.class_id, visit.class_name
        )
        label_hs = _label_hoc_sinh(student_name)

        extra_users = []
        if visit.reported_by:
            extra_users.append(visit.reported_by)

        recipients = get_health_notification_recipients(
            class_id=r_class_id,
            include_medical=False,
            include_homeroom=True,
            include_supervisory=True,
            extra_users=extra_users,
        )

        if not recipients:
            return

        title = STANDARD_HEALTH_NOTIFICATION_TITLE
        body = f"{label_hs} ({class_name}) - Y tế đã từ chối, học sinh đang về lớp"

        data = {
            "type": "health_visit_rejected",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": r_class_id,
            "class_name": class_name,
            "status": "rejected",
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_rejected cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_rejected: {str(e)}")


def notify_health_visit_completed(visit_name: str):
    """
    Gửi notification khi Y tế checkout học sinh.
    Người nhận: Mobile Medical + Mobile Supervisory + Homeroom + Vice-homeroom.
    Nội dung thay đổi tùy outcome (returned / picked_up / transferred).
    (Giám thị: biết HS về lớp / ra cổng / chuyển viện để phối hợp khu vực công cộng.)
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        outcome = visit.status
        r_class_id, class_name = _regular_class_id_and_title(
            visit.student_id, visit.class_id, visit.class_name
        )
        label_hs = _label_hoc_sinh(student_name)

        # Nội dung theo kết quả; tiêu đề thống nhất
        outcome_bodies = {
            "returned": f"{label_hs} đã được Y tế cho về lớp",
            "picked_up": f"{label_hs} đã được phụ huynh đón về",
            "transferred": f"{label_hs} đã được chuyển viện",
        }
        body = outcome_bodies.get(
            outcome,
            f"{label_hs} đã hoàn thành lượt xuống Y tế",
        )
        title = STANDARD_HEALTH_NOTIFICATION_TITLE

        recipients = get_health_notification_recipients(
            class_id=r_class_id,
            include_medical=True,
            include_homeroom=True,
            include_supervisory=True,
        )

        if not recipients:
            return

        data = {
            "type": "health_visit_completed",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": r_class_id,
            "class_name": class_name,
            "status": outcome,
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi health_visit_completed ({outcome}) cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_health_visit_completed: {str(e)}")


def notify_examination_created(visit_name: str, disease_classification: str = ""):
    """
    Gửi notification khi NVYT tạo hồ sơ thăm khám mới.
    Người nhận: Homeroom + Vice-homeroom (GV cần biết kết quả khám).
    """
    try:
        visit = frappe.get_doc("SIS Daily Health Visit", visit_name)
        student_name = visit.student_name or visit.student_id
        r_class_id, class_name = _regular_class_id_and_title(
            visit.student_id, visit.class_id, visit.class_name
        )
        label_hs = _label_hoc_sinh(student_name)

        title = STANDARD_HEALTH_NOTIFICATION_TITLE
        body = f"{label_hs} ({class_name}) đã được Y tế thăm khám"
        if disease_classification:
            body += f" - {disease_classification}"

        recipients = get_health_notification_recipients(
            class_id=r_class_id,
            include_medical=False,
            include_homeroom=True,
        )

        if not recipients:
            return

        data = {
            "type": "examination_created",
            "visit_id": visit.name,
            "student_id": visit.student_id,
            "student_name": student_name,
            "class_id": r_class_id,
            "class_name": class_name,
        }

        _send_to_recipients(recipients, title, body, data)
        frappe.logger().info(
            f"[health_notification] Đã gửi examination_created cho {len(recipients)} người - visit {visit.name}"
        )

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi notify_examination_created: {str(e)}")


# =====================================================================
# Scheduled job: kiểm tra visit quá 15 phút chưa chuyển trạng thái
# =====================================================================

@frappe.whitelist(allow_guest=False)
def check_stale_health_visits():
    """
    Kiểm tra visit quá 15 phút chưa chuyển trạng thái.
    Gửi escalation cho Mobile Medical + Mobile Supervisory + Homeroom + Vice-homeroom + Reporter.
    (Giám thị: HS lâu chưa đến phòng Y tế — hỗ trợ tìm/điều phối trên hành lang.)
    Dùng Redis debounce để tránh gửi lặp cho cùng một visit.

    Được gọi bởi:
    - Scheduled job (hooks.py) mỗi 5 phút (production)
    - Piggyback khi load trang DailyHealth (development & production)
    - Có thể gọi thủ công qua API để test
    """
    try:
        from datetime import timedelta

        frappe.logger().info("[health_notification] === BẮT ĐẦU check_stale_health_visits ===")

        threshold = now_datetime() - timedelta(minutes=15)

        stale_visits = frappe.db.sql("""
            SELECT name, student_id, student_name, class_id, class_name,
                   reason, creation, reported_by
            FROM `tabSIS Daily Health Visit`
            WHERE status = 'left_class'
              AND visit_date = %(today)s
              AND creation <= %(threshold)s
        """, {"today": today(), "threshold": threshold}, as_dict=True)

        frappe.logger().info(f"[health_notification] Tìm thấy {len(stale_visits) if stale_visits else 0} visit quá 15 phút (threshold={threshold})")

        if not stale_visits:
            return

        redis = frappe.cache()
        sent_count = 0

        for visit in stale_visits:
            debounce_key = f"health_escalation:{visit.name}"
            if redis.get_value(debounce_key):
                frappe.logger().info(f"[health_notification] Skip visit {visit.name} - đã gửi escalation trước đó")
                continue

            student_name = visit.student_name or visit.student_id
            r_class_id, class_name = _regular_class_id_and_title(
                visit.student_id, visit.class_id, visit.class_name
            )
            label_hs = _label_hoc_sinh(student_name)

            # Gửi cho Mobile Medical + Mobile Supervisory + Homeroom + Vice-homeroom + Reporter
            extra_users = []
            if visit.reported_by:
                extra_users.append(visit.reported_by)

            recipients = get_health_notification_recipients(
                class_id=r_class_id,
                include_medical=True,
                include_homeroom=True,
                include_supervisory=True,
                extra_users=extra_users,
            )
            frappe.logger().info(f"[health_notification] Escalation recipients cho visit {visit.name}: {recipients}")

            if not recipients:
                frappe.logger().warning(f"[health_notification] Không tìm thấy người nhận nào cho escalation visit {visit.name}")
                continue

            title = STANDARD_HEALTH_NOTIFICATION_TITLE
            body = f"{label_hs} ({class_name}) đã rời lớp hơn 15 phút nhưng chưa đến phòng Y tế"

            data = {
                "type": "health_visit_escalation",
                "visit_id": visit.name,
                "student_id": visit.student_id,
                "student_name": student_name,
                "class_id": r_class_id,
                "class_name": class_name,
                "status": "left_class",
            }

            _send_to_recipients(recipients, title, body, data)

            # Đánh dấu đã gửi escalation, TTL 4 giờ (tránh gửi lặp trong ngày)
            redis.set_value(debounce_key, "1", expires_in_sec=14400)
            sent_count += 1

            frappe.logger().info(
                f"[health_notification] Đã gửi escalation cho visit {visit.name} - "
                f"{student_name} (left_class > 15 phút)"
            )

        frappe.logger().info(f"[health_notification] === KẾT THÚC check_stale_health_visits - gửi {sent_count} escalation ===")

    except Exception as e:
        frappe.logger().error(f"[health_notification] Lỗi check_stale_health_visits: {str(e)}")
        import traceback
        frappe.logger().error(f"[health_notification] Traceback: {traceback.format_exc()}")


def piggyback_check_stale_visits():
    """
    Kiểm tra stale visits khi load trang DailyHealth.
    Rate limit: chỉ chạy tối đa 1 lần mỗi 3 phút để tránh gọi quá nhiều.
    """
    try:
        redis = frappe.cache()
        rate_key = "health_stale_check_last_run"

        if redis.get_value(rate_key):
            return

        # Đánh dấu đã chạy, TTL 3 phút
        redis.set_value(rate_key, "1", expires_in_sec=180)

        check_stale_health_visits()

    except Exception as e:
        frappe.logger().warning(f"[health_notification] Lỗi piggyback_check_stale_visits: {str(e)}")
