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

from erp.api.parent_portal.club_beta_access import (
    allowed_parent_emails,
    filter_students_for_beta,
)

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


#: Giới hạn độ dài phần nội dung thông báo.
MAX_BODY_LENGTH = 140


def _fit_body(lead, tail, max_length=MAX_BODY_LENGTH):
    """
    Ghép câu chính + câu kêu gọi, cắt dần cho vừa `max_length`.

    Ba mức, dừng ở mức đầu tiên vừa:
      1. đủ cả hai câu
      2. bỏ câu kêu gọi (đúng yêu cầu nghiệp vụ)
      3. tên đợt vẫn quá dài -> cắt bớt tên, thêm "…"

    Mức 3 không có trong yêu cầu nhưng cần: câu chính CHỨA tên đợt, nên một cái
    tên 200 ký tự vẫn vượt ngưỡng sau khi đã bỏ câu cuối. Thà cắt tên còn hơn để
    thông báo bị chính thiết bị cắt ở chỗ ngẫu nhiên.
    """
    full = f"{lead} {tail}"
    if len(full) <= max_length:
        return full
    if len(lead) <= max_length:
        return lead
    return lead[: max_length - 1].rstrip() + "…"


def _reminder_text(period, now):
    """
    Nội dung nhắc.

    Nói SỐ PHÚT CÒN LẠI THẬT, không nói giá trị cấu hình `minutes_before`. Cron
    chạy 5 phút một lần nên thời điểm bắn rơi bất kỳ đâu trong khoảng 10–15 phút
    trước giờ mở; in cứng "15 phút" là sai với phần lớn các lần gửi.
    """
    reg_start = get_datetime(period.registration_start_datetime)
    remaining = max(1, int(round((reg_start - now).total_seconds() / 60.0)))

    title = {
        "vi": "Mở đăng ký CLB",
        "en": "Club Registration Opening Soon!",
    }
    body = {
        "vi": _fit_body(
            f"{period.title_vn} sẽ mở đăng ký sau {remaining} phút nữa.",
            "Phụ huynh nhanh tay bấm để không bỏ lỡ!",
        ),
        "en": _fit_body(
            f"{period.title_en or period.title_vn} registration opens in "
            f"{remaining} minutes.",
            "Tap now so you don't miss out!",
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
        return {"sent": 0, "outcome": "chưa tới khoảng hiển thị của đợt"}

    student_ids = _eligible_student_ids(period)
    if not student_ids:
        # Chưa khai buổi nào / chưa xếp lớp -> không có ai để nhắc. Đốt cờ luôn,
        # nếu không mỗi 5 phút lại quét lại một đợt vĩnh viễn rỗng.
        frappe.db.set_value(DT_PERIOD, period_name, "open_reminder_sent", 1)
        frappe.db.commit()
        return {"sent": 0, "outcome": "không có học sinh nào đủ điều kiện"}

    # Cổng chạy thử — GỠ TRƯỚC KHI RELEASE (xem `club_beta_access`).
    eligible_count = len(student_ids)
    student_ids = filter_students_for_beta(student_ids)
    if not student_ids:
        # KHÔNG đốt cờ: danh sách chạy thử có thể được bổ sung trước giờ mở, lần
        # quét sau vẫn kịp gửi.
        return {
            "sent": 0,
            "outcome": "cổng chạy thử loại hết người nhận",
            "eligible_students": eligible_count,
        }

    title, body = _reminder_text(period, now)

    result = send_bulk_parent_notifications(
        recipient_type="club_registration",
        recipients_data={"student_ids": student_ids, "period_id": period_name},
        title=title,
        body=body,
        # Cắt lần hai ở tầng NGƯỜI NHẬN: lọc học sinh mới chỉ đảm bảo "em này có
        # ít nhất một phụ huynh trong nhóm chạy thử", phụ huynh còn lại của chính
        # em đó vẫn lọt. `None` = cổng tắt = giữ nguyên hành vi gửi cho tất cả.
        allowed_parent_emails=allowed_parent_emails(student_ids),
        data={
            "type": "club_registration_opening",
            "period_id": period_name,
            "minutes_before": minutes_before,
            # `timestamp` BẮT BUỘC phải có: `send_bulk_parent_notifications` dựng
            # khoá chống trùng từ `data["timestamp"]`. Thiếu nó thì khoá là hằng
            # số và mọi lần gửi sau cho cùng nhóm học sinh đều bị nuốt im lặng —
            # nhìn từ ngoài y hệt "đã gửi mà không có thông báo nào".
            "timestamp": str(now),
            # Điều hướng: web dùng path, app map sang route riêng.
            "url": "/club",
        },
    )

    # CHỈ đốt cờ khi thật sự tạo được thông báo.
    #
    # Trước đây đốt vô điều kiện: gửi hỏng (sai tham số, debounce nuốt, guardian
    # rỗng…) vẫn bị đánh dấu "đã gửi" và đợt vĩnh viễn không được thử lại — mất
    # luôn cơ hội nhắc, mà log thì im lặng.
    sent = cint(result.get("success_count")) if isinstance(result, dict) else 0
    if sent > 0:
        frappe.db.set_value(DT_PERIOD, period_name, "open_reminder_sent", 1)
        frappe.db.commit()
        frappe.logger().info(
            f"club_reminders: đợt {period_name} -> {len(student_ids)} HS, {sent} thông báo"
        )
        return {
            "sent": sent,
            "outcome": "đã gửi",
            "students": len(student_ids),
            "recipients": result.get("parent_emails"),
        }

    # `frappe.log_error(title, message)` — THAM SỐ ĐẦU LÀ TIÊU ĐỀ, giới hạn 140
    # ký tự và KHÔNG tự cắt: nhét cả phản hồi vào đó thì chính lời ghi log ném
    # CharacterLengthExceededError, nuốt mất nguyên nhân thật.
    # (Frappe chỉ hoán đổi hai tham số khi tiêu đề có chữ "Traceback".)
    frappe.log_error(
        "club_reminders: không tạo được thông báo",
        f"Đợt {period_name}: {len(student_ids)} học sinh đủ điều kiện nhưng "
        f"KHÔNG tạo được thông báo nào.\n\nPhản hồi:\n{result}",
    )
    return {
        "sent": 0,
        "outcome": "gửi thất bại — xem Error Log 'club_reminders: không tạo được thông báo'",
        "students": len(student_ids),
        "errors": [r.get("error") for r in (result or {}).get("results", []) if r.get("error")][:3],
    }


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
        allowed_parent_emails,
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
    # None = cổng tắt = gửi cho tất cả (giữ nguyên ngữ nghĩa của tham số).
    recipient_emails = allowed_parent_emails(after_beta) if after_beta else None

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
        # `guardians` = MỌI phụ huynh của các em đủ điều kiện (chưa lọc).
        # `recipients_after_email_filter` mới là số người THỰC SỰ nhận — lọc học
        # sinh giữ em lại vì mẹ trong nhóm thì bố vẫn nằm trong `guardians`.
        "guardians": len(guardians),
        "recipients_after_email_filter": (
            len(recipient_emails) if recipient_emails is not None else len(guardians)
        ),
        "recipient_emails": recipient_emails,
        "guardian_phones_sample": [
            {"guardian": g["guardian_name"], "phones": guardian_phones(g["guardian_name"]),
             "allowed": is_guardian_allowed(g["guardian_name"])}
            for g in guardians[:5]
        ],
        "mobile_push_tokens": mobile_tokens,
        "web_push_subscriptions": web_subs,
        # Token Expo lưu theo `frappe.session.user` lúc app gọi register, còn
        # push thì tìm theo email tổng hợp `{guardian_id}@parent…`. Hai giá trị
        # này lệch nhau là push mobile im lặng không tới. Liệt kê token mới nhất
        # để đối chiếu xem nó thật sự nằm dưới user nào.
        "recent_mobile_tokens": frappe.get_all(
            "Mobile Device Token",
            fields=["user", "platform", "app_type", "is_active", "last_seen"],
            order_by="modified desc",
            limit=10,
        ),
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
    period = None
    if period_id:
        period = frappe.get_doc(DT_PERIOD, period_id)
        eligible = set(_eligible_student_ids(period))

    def _period_requirements():
        """Đợt yêu cầu gì: năm học, campus, và các khối có mở buổi."""
        if not period:
            return None
        grades = frappe.db.sql(
            f"""
            SELECT DISTINCT g.education_grade_id, g.education_grade_name
            FROM `tab{DT_OFFERING}` o
            INNER JOIN `tabSIS Club Offering Grade` g
                    ON g.parent = o.name AND g.parenttype = %(dt)s
            WHERE o.period_id = %(pid)s AND o.status = 'active'
            """,
            {"pid": period.name, "dt": DT_OFFERING},
            as_dict=True,
        )
        return {
            "school_year_id": period.school_year_id,
            "campus_id": period.campus_id,
            "grades": grades,
        }

    def _placement(student_id):
        """
        Học sinh đang ở lớp nào, khối nào, năm học nào.

        Lấy MỌI năm học chứ không chỉ năm của đợt: cần phân biệt "chưa xếp lớp
        năm nay" với "học khối mà đợt không mở" — hai nguyên nhân này đòi hai
        cách xử lý hoàn toàn khác nhau.
        """
        return frappe.db.sql(
            """
            SELECT cs.class_id, c.education_grade, c.school_year_id, c.campus_id,
                   COALESCE(eg.title_vn, '') AS grade_name
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
            LEFT JOIN `tabSIS Education Grade` eg ON eg.name = c.education_grade
            WHERE cs.student_id = %(sid)s
            ORDER BY c.school_year_id DESC
            LIMIT 10
            """,
            {"sid": student_id},
            as_dict=True,
        )

    def _reason(student_id, placement):
        if student_id in eligible:
            return "ok"
        if not placement:
            return "chưa xếp lớp ở bất kỳ năm học nào"
        if period and not any(p["school_year_id"] == period.school_year_id for p in placement):
            years = sorted({p["school_year_id"] for p in placement if p["school_year_id"]})
            return f"không có lớp trong năm học của đợt ({period.school_year_id}); đang ở: {years}"
        if period and period.campus_id and not any(
            p["campus_id"] == period.campus_id
            for p in placement
            if p["school_year_id"] == period.school_year_id
        ):
            return f"khác campus với đợt ({period.campus_id})"
        grades = sorted(
            {
                p["grade_name"] or p["education_grade"]
                for p in placement
                if p["school_year_id"] == (period.school_year_id if period else None)
            }
        )
        return f"đợt không mở buổi cho khối của em ({grades})"

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

    def _student_entry(s):
        # Gọi `_placement` một lần rồi dùng lại cho cả `reason` lẫn output —
        # trước đó gọi hai lần, tức gấp đôi query cho mỗi học sinh.
        placement = _placement(s["student"])
        return {
            "student": s["student"],
            "name": s["student_name"],
            "code": s["student_code"],
            "eligible_for_period": s["student"] in eligible,
            "reason": _reason(s["student"], placement),
            "placement": placement,
        }

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
                        _student_entry(s)
                        for s in students
                    ],
                }
            )
        report.append(entry)

    return {
        "period": period_id,
        "eligible_students_in_period": len(eligible),
        "period_requirements": _period_requirements(),
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
    # Trả về KẾT QUẢ THẬT, không phải `{"ok": True}`: lần trước lệnh này báo
    # thành công trong khi không một thông báo nào được tạo — `ok` chỉ có nghĩa
    # "không ném exception", vô dụng đúng lúc cần biết nhất.
    outcome = _send_for_period(
        period_id, cint(minutes_before) or DEFAULT_MINUTES_BEFORE, now_datetime()
    )
    return {"period_id": period_id, **(outcome or {})}
