# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

"""
Nhắc phụ huynh trước giờ mở cổng đăng ký Câu lạc bộ.

Chạy theo cron mỗi 5 phút, quét đợt sắp mở trong `minutes_before` phút tới. Mỗi
đợt chỉ gửi một lần nhờ cờ `open_reminder_sent` trên chính đợt đó.

Người nhận = phụ huynh của học sinh THỰC SỰ đăng ký được: khối của em phải nằm
trong ít nhất một buổi đang mở của đợt. Gửi cho toàn trường thì phần lớn phụ
huynh nhận thông báo về một thứ họ không dùng được.
"""

import frappe
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from erp.api.parent_portal.club_beta_access import filter_students_for_beta

DT_PERIOD = "SIS Club Registration Period"
DT_OFFERING = "SIS Club Offering"

#: Nhắc trước bao nhiêu phút (mặc định theo yêu cầu nghiệp vụ).
DEFAULT_MINUTES_BEFORE = 15


def _eligible_student_ids(period):
    """
    Học sinh đăng ký được: đang học ở một lớp thuộc khối mà đợt có mở buổi.

    Đi thẳng từ khối -> lớp -> học sinh bằng một query thay vì gọi
    `_get_students_by_grade` cho từng khối: một đợt có thể phủ cả chục khối.

    BẮT BUỘC lọc theo năm học của đợt: khối "Khối 1" tồn tại ở mọi năm, không lọc
    thì lớp của các năm cũ cũng khớp và ta nhắc cả học sinh đã lên lớp hoặc đã ra
    trường. Lọc thêm campus khi đợt có ràng buộc campus.
    """
    conditions = [
        "o.period_id = %(period_id)s",
        "o.status = 'active'",
        "cs.student_id IS NOT NULL",
        "c.school_year_id = %(school_year_id)s",
    ]
    values = {
        "period_id": period.name,
        "offering_dt": DT_OFFERING,
        "school_year_id": period.school_year_id,
    }
    if period.campus_id:
        conditions.append("c.campus_id = %(campus_id)s")
        values["campus_id"] = period.campus_id

    rows = frappe.db.sql(
        f"""
        SELECT DISTINCT cs.student_id
        FROM `tab{DT_OFFERING}` o
        INNER JOIN `tabSIS Club Offering Grade` g
                ON g.parent = o.name AND g.parenttype = %(offering_dt)s
        INNER JOIN `tabSIS Class` c ON c.education_grade = g.education_grade_id
        INNER JOIN `tabSIS Class Student` cs ON cs.class_id = c.name
        WHERE {' AND '.join(conditions)}
        """,
        values,
        as_dict=True,
    )
    return [r["student_id"] for r in rows if r.get("student_id")]


def _reminder_text(period, minutes_before):
    title = {
        "vi": "Sắp mở đăng ký câu lạc bộ",
        "en": "Club registration opens soon",
    }
    body = {
        "vi": (
            f"«{period.title_vn}» mở đăng ký sau {minutes_before} phút. "
            "Vào Parent Portal để xem danh sách câu lạc bộ và giữ chỗ cho con."
        ),
        "en": (
            f"«{period.title_en or period.title_vn}» opens in {minutes_before} minutes. "
            "Open Parent Portal to view the clubs and hold a seat for your child."
        ),
    }
    return title, body


def send_club_open_reminders(minutes_before=DEFAULT_MINUTES_BEFORE):
    """
    Scheduler: nhắc phụ huynh ~15 phút trước giờ mở đăng ký CLB.

    Chỉ xét đợt `status = Open` và đã tới khoảng hiển thị — đợt còn Nháp thì phụ
    huynh chưa nhìn thấy gì, nhắc là gây hoang mang.
    """
    try:
        minutes_before = cint(minutes_before) or DEFAULT_MINUTES_BEFORE
        now = now_datetime()
        threshold = add_to_date(now, minutes=minutes_before)

        periods = frappe.get_all(
            DT_PERIOD,
            filters={
                "status": "Open",
                "open_reminder_sent": 0,
                "registration_start_datetime": ["between", [now, threshold]],
            },
            fields=["name"],
            ignore_permissions=True,
        )

        for row in periods:
            try:
                _send_for_period(row.name, minutes_before, now)
            except Exception:
                frappe.log_error(
                    frappe.get_traceback(), "club_reminders.send_club_open_reminders.item"
                )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "club_reminders.send_club_open_reminders")


def _send_for_period(period_name, minutes_before, now):
    from erp.utils.notification_handler import send_bulk_parent_notifications

    period = frappe.get_doc(DT_PERIOD, period_name)

    # Đợt chưa tới khoảng hiển thị: phụ huynh mở app cũng không thấy gì. Chưa đốt
    # cờ để lần quét sau thử lại — nhưng nếu tới lúc mở cổng vẫn chưa hiển thị
    # thì đợt rớt khỏi cửa sổ và không nhắc nữa, đúng ý.
    if period.display_start_datetime and get_datetime(period.display_start_datetime) > now:
        return

    student_ids = _eligible_student_ids(period)
    if not student_ids:
        # Chưa khai buổi nào / chưa xếp lớp -> không có ai để nhắc. Đốt cờ luôn,
        # nếu không mỗi 5 phút lại quét lại một đợt vĩnh viễn rỗng.
        frappe.db.set_value(DT_PERIOD, period_name, "open_reminder_sent", 1)
        frappe.db.commit()
        return

    # Cổng chạy thử — GỠ TRƯỚC KHI RELEASE (xem `club_beta_access`).
    student_ids = filter_students_for_beta(student_ids)
    if not student_ids:
        # KHÔNG đốt cờ: danh sách chạy thử có thể được bổ sung trước giờ mở, lần
        # quét sau vẫn kịp gửi.
        return

    title, body = _reminder_text(period, minutes_before)

    result = send_bulk_parent_notifications(
        recipient_type="club_registration",
        recipients_data={"student_ids": student_ids, "period_id": period_name},
        title=title,
        body=body,
        data={
            "type": "club_registration_opening",
            "period_id": period_name,
            "minutes_before": minutes_before,
            # Điều hướng: web dùng path, app map sang route riêng.
            "url": "/club",
        },
    )

    frappe.db.set_value(DT_PERIOD, period_name, "open_reminder_sent", 1)
    frappe.db.commit()

    frappe.logger().info(
        f"club_reminders: đợt {period_name} -> {len(student_ids)} HS, "
        f"{result.get('total_parents', 0)} phụ huynh"
    )


@frappe.whitelist()
def send_club_open_reminder_now(period_id=None, minutes_before=DEFAULT_MINUTES_BEFORE):
    """
    Gửi nhắc ngay, không chờ cron — dùng để kiểm thử trên staging.

    Bỏ qua cửa sổ thời gian và cờ `open_reminder_sent` nhưng VẪN qua cổng chạy
    thử, nên không thể lỡ tay bắn cho toàn trường.
    """
    if not frappe.has_permission(DT_PERIOD, "write"):
        frappe.throw("Không có quyền")

    if not period_id:
        frappe.throw("Thiếu period_id")
    if not frappe.db.exists(DT_PERIOD, period_id):
        frappe.throw("Không tìm thấy đợt đăng ký")

    frappe.db.set_value(DT_PERIOD, period_id, "open_reminder_sent", 0)
    frappe.db.commit()
    _send_for_period(period_id, cint(minutes_before) or DEFAULT_MINUTES_BEFORE, now_datetime())
    return {"ok": True, "period_id": period_id}
