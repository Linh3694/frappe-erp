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
def debug_club_reminder(period_id=None):
    """
    Phễu chẩn đoán: chỉ ra chính xác bước nào rơi về 0.

    KHÔNG gửi gì cả. Dựng ra vì khi "không thấy thông báo" thì có tới sáu chỗ có
    thể đứt (đợt ngoài cửa sổ, cờ đã đốt, chưa khai buổi, chưa xếp lớp, cổng
    beta, chưa có token push) mà log không phân biệt được.
    """
    if not frappe.has_permission(DT_PERIOD, "read"):
        frappe.throw("Không có quyền")

    from erp.api.parent_portal.club_beta_access import (
        beta_gate_enabled,
        guardian_phones,
        is_guardian_allowed,
    )
    from erp.utils.notification_handler import get_guardians_for_students

    now = now_datetime()
    if not period_id:
        rows = frappe.get_all(
            DT_PERIOD,
            filters={"status": "Open"},
            fields=["name"],
            order_by="registration_start_datetime desc",
            limit=1,
        )
        if not rows:
            return {"error": "Không có đợt nào ở trạng thái Open"}
        period_id = rows[0].name

    period = frappe.get_doc(DT_PERIOD, period_id)
    reg_start = get_datetime(period.registration_start_datetime)
    minutes_to_open = (reg_start - now).total_seconds() / 60.0

    students = _eligible_student_ids(period)
    after_beta = filter_students_for_beta(students)
    guardians = get_guardians_for_students(after_beta) if after_beta else []
    emails = [g.get("email") for g in guardians if g.get("email")]

    mobile_tokens = (
        frappe.db.count("Mobile Device Token", {"user": ["in", emails], "is_active": 1})
        if emails
        else 0
    )
    web_subs = frappe.db.count("Push Subscription", {"user": ["in", emails]}) if emails else 0

    return {
        "period": period_id,
        "status": period.status,
        "server_now": str(now),
        "registration_start": str(reg_start),
        "minutes_to_open": round(minutes_to_open, 1),
        # Cron chỉ bắn khi 0 <= minutes_to_open <= minutes_before
        "in_reminder_window": 0 <= minutes_to_open <= DEFAULT_MINUTES_BEFORE,
        "already_sent_flag": cint(period.get("open_reminder_sent")),
        "eligible_students": len(students),
        "after_beta_filter": len(after_beta),
        "beta_gate_enabled": beta_gate_enabled(),
        "guardians": len(guardians),
        "guardian_phones_sample": [
            {"guardian": g["guardian_name"], "phones": guardian_phones(g["guardian_name"]),
             "allowed": is_guardian_allowed(g["guardian_name"])}
            for g in guardians[:5]
        ],
        "mobile_push_tokens": mobile_tokens,
        "web_push_subscriptions": web_subs,
    }


@frappe.whitelist()
def debug_club_beta_phones(period_id=None):
    """
    Soi NGƯỢC từ số trong danh sách chạy thử: số -> phụ huynh -> con -> có đủ
    điều kiện của đợt không.

    `debug_club_reminder` chỉ nói "rơi về 0", không nói vì sao. Có bốn nguyên
    nhân khác hẳn nhau: số không có trong CRM, số có nhưng lưu ở dạng lạ, phụ
    huynh không gắn với học sinh nào, hoặc con học khối/năm học/campus mà đợt
    không mở. Hàm này phân biệt được cả bốn.
    """
    if not frappe.has_permission(DT_PERIOD, "read"):
        frappe.throw("Không có quyền")

    from erp.api.parent_portal.club_beta_access import _allowed_set, normalize_phone

    allowed = sorted(_allowed_set())
    if not allowed:
        return {"error": "Danh sách chạy thử đang rỗng"}

    eligible = set()
    if period_id:
        eligible = set(_eligible_student_ids(frappe.get_doc(DT_PERIOD, period_id)))

    # Bỏ dấu phân cách ngay trong SQL rồi so HẬU TỐ 9 chữ số: đủ bắt '0376…',
    # '+84376…', '84376…', '037 641 2589', '037.641.2589', '+84 (376) 412-589'.
    #
    # Phải bỏ CẢ CẶP ngoặc: bỏ mỗi '(' thì '(376) 412589' còn '376)412589' và
    # hậu tố không khớp — tệ hơn là không xử lý gì, vì trông như đã xử lý.
    def _strip_separators(col):
        expr = col
        for ch in (" ", ".", "-", "(", ")", "+"):
            expr = f"REPLACE({expr},'{ch}','')"
        return expr

    report = []
    for suffix in allowed:
        rows = frappe.db.sql(
            f"""
            SELECT g.name, g.guardian_id, g.guardian_name, g.phone_number
            FROM `tabCRM Guardian` g
            WHERE {_strip_separators('g.phone_number')} LIKE %(like)s
            UNION
            SELECT g.name, g.guardian_id, g.guardian_name, g.phone_number
            FROM `tabCRM Guardian` g
            INNER JOIN `tabCRM Guardian Phone` p
                    ON p.parent = g.name AND p.parenttype = 'CRM Guardian'
            WHERE {_strip_separators('p.phone_number')} LIKE %(like)s
            """,
            {"like": f"%{suffix}"},
            as_dict=True,
        )

        entry = {"phone_suffix": suffix, "guardians": []}
        for g in rows:
            students = frappe.db.sql(
                """
                SELECT DISTINCT fr.student, s.student_name, s.student_code
                FROM `tabCRM Family Relationship` fr
                INNER JOIN `tabCRM Family` f ON f.name = fr.parent
                LEFT JOIN `tabCRM Student` s ON s.name = fr.student
                WHERE fr.guardian = %(g)s
                  AND fr.parentfield = 'relationships'
                  AND f.docstatus < 2
                """,
                {"g": g["name"]},
                as_dict=True,
            )
            entry["guardians"].append(
                {
                    "guardian": g["name"],
                    "guardian_name": g["guardian_name"],
                    "phone_stored": g["phone_number"],
                    "phone_normalized": normalize_phone(g["phone_number"]),
                    "students": [
                        {
                            "student": s["student"],
                            "name": s["student_name"],
                            "code": s["student_code"],
                            "eligible_for_period": s["student"] in eligible,
                        }
                        for s in students
                    ],
                }
            )
        report.append(entry)

    return {
        "period": period_id,
        "eligible_students_in_period": len(eligible),
        "allowlist": allowed,
        "found": report,
    }


@frappe.whitelist()
def send_club_open_reminder_now(
    period_id=None, minutes_before=DEFAULT_MINUTES_BEFORE, force=0
):
    """
    Gửi nhắc NGAY, không chờ cron — dùng để kiểm thử.

    Bỏ qua cửa sổ thời gian và cờ `open_reminder_sent`, nhưng VẪN đi qua cổng
    chạy thử trong `_send_for_period`.

    CHỐT AN TOÀN: từ chối chạy khi cổng chạy thử đang TẮT (danh sách số rỗng),
    vì lúc đó `filter_students_for_beta` trả nguyên danh sách và một lệnh gõ tay
    sẽ đẩy push tới TOÀN BỘ phụ huynh của mọi khối có mở buổi — việc không thu
    hồi được. Cổng tắt là trạng thái đúng sau khi release, nhưng khi đó thông
    báo phải do cron gửi theo lịch, không phải do người gõ lệnh.
    Muốn gửi thật cho tất cả thì truyền `force=1` một cách có chủ đích.
    """
    from erp.api.parent_portal.club_beta_access import beta_gate_enabled

    if not frappe.has_permission(DT_PERIOD, "write"):
        frappe.throw("Không có quyền")

    if not cint(force) and not beta_gate_enabled():
        frappe.throw(
            "Cổng chạy thử đang TẮT (danh sách số điện thoại rỗng) — lệnh này sẽ gửi "
            "cho TẤT CẢ phụ huynh. Kiểm `club_beta_phones` trong site_config.json và "
            "`CLUB_BETA_PHONES` trong club_beta_access.py. Nếu thật sự muốn gửi cho "
            "tất cả, chạy lại với force=1."
        )

    if not period_id:
        frappe.throw("Thiếu period_id")
    if not frappe.db.exists(DT_PERIOD, period_id):
        frappe.throw("Không tìm thấy đợt đăng ký")

    frappe.db.set_value(DT_PERIOD, period_id, "open_reminder_sent", 0)
    frappe.db.commit()
    _send_for_period(period_id, cint(minutes_before) or DEFAULT_MINUTES_BEFORE, now_datetime())
    return {"ok": True, "period_id": period_id}
