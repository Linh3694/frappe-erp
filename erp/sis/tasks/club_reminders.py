# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

"""
Thông báo vòng đời đợt đăng ký Câu lạc bộ.

Ba mốc, cùng một lõi gửi, khác nhau ở cửa sổ thời gian và cờ chống trùng:

  open    — ~15 phút TRƯỚC giờ mở đăng ký
  closing — ~1 tiếng TRƯỚC giờ đóng đăng ký
  closed  — ngay SAU khi đóng đăng ký

Chạy theo cron mỗi 5 phút. Mỗi đợt × mỗi mốc chỉ gửi một lần nhờ cờ riêng trên
chính đợt đó.

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

#: Nhắc trước bao nhiêu phút (giữ tên cũ cho tương thích lời gọi sẵn có).
DEFAULT_MINUTES_BEFORE = 15

#: Cấu hình từng mốc.
#:   field   — cột mốc thời gian trên đợt
#:   flag    — cờ chống gửi trùng
#:   window  — số phút TRƯỚC mốc mà cron được phép bắn
#:   after   — True: mốc đã QUA (bắn sau), False: mốc SẮP tới (bắn trước)
KINDS = {
    "open": {
        "field": "registration_start_datetime",
        "flag": "open_reminder_sent",
        "window": 15,
        "after": False,
    },
    "closing": {
        "field": "registration_end_datetime",
        "flag": "close_reminder_sent",
        "window": 60,
        "after": False,
    },
    "closed": {
        # Bắn sau khi mốc đã qua. Cửa sổ 120 phút là CHẶN AN TOÀN: thiếu nó thì
        # lần deploy đầu tiên mọi đợt cũ đã đóng từ lâu đều có cờ = 0 và sẽ bị
        # bắn hàng loạt cho phụ huynh về những đợt của năm ngoái.
        "field": "registration_end_datetime",
        "flag": "closed_notice_sent",
        "window": 120,
        "after": True,
    },
}


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
    tên 200 ký tự vẫn vượt ngưỡng sau khi đã bỏ câu cuối. Thà mình cắt còn hơn
    để thiết bị cắt ở chỗ ngẫu nhiên.
    """
    full = f"{lead} {tail}".strip() if tail else lead
    if len(full) <= max_length:
        return full
    if len(lead) <= max_length:
        return lead
    return lead[: max_length - 1].rstrip() + "…"


def _humanize(minutes, lang):
    """
    "khoảng 1 tiếng" thay vì "58 phút".

    Cron 5 phút một nhịp nên mốc 1 tiếng thực tế bắn ở 55–60 phút. Nói "58 phút"
    đúng nhưng đọc như máy; nói "1 tiếng" mà thực tế còn 58 phút thì vẫn đúng
    trong cách người ta nói. Dưới 45 phút mới quay lại đếm phút cho chính xác.
    """
    if minutes >= 45:
        return "khoảng 1 tiếng" if lang == "vi" else "about 1 hour"
    return f"{minutes} phút" if lang == "vi" else f"{minutes} minutes"


def _reminder_text(period, kind, now):
    """
    Nội dung theo từng mốc.

    Số phút là THỜI GIAN CÒN LẠI THẬT, không phải hằng số cấu hình: cron chạy
    5 phút một lần nên thời điểm bắn rơi bất kỳ đâu trong cửa sổ.
    """
    title_vn = period.title_vn
    title_en = period.title_en or period.title_vn

    if kind == "closed":
        return (
            {"vi": "Đã đóng đăng ký CLB", "en": "Club Registration Closed"},
            {
                # Cổng đã đóng thì không còn việc gì để giục — chỉ một câu thông báo.
                "vi": _fit_body(f"{title_vn} đã đóng đăng ký.", ""),
                "en": _fit_body(f"{title_en} registration has closed.", ""),
            },
        )

    field = KINDS[kind]["field"]
    remaining = max(1, int(round((get_datetime(period.get(field)) - now).total_seconds() / 60.0)))

    if kind == "closing":
        return (
            {"vi": "Sắp đóng đăng ký CLB", "en": "Club Registration Closing Soon!"},
            {
                "vi": _fit_body(
                    f"{title_vn} sẽ đóng đăng ký sau {_humanize(remaining, 'vi')} nữa.",
                    "Phụ huynh vui lòng hoàn thiện đăng ký cho con.",
                ),
                "en": _fit_body(
                    f"{title_en} registration closes in {_humanize(remaining, 'en')}.",
                    "Please complete your child's registration.",
                ),
            },
        )

    return (
        {"vi": "Mở đăng ký CLB", "en": "Club Registration Opening Soon!"},
        {
            "vi": _fit_body(
                f"{title_vn} sẽ mở đăng ký sau {_humanize(remaining, 'vi')} nữa.",
                "Phụ huynh nhanh tay bấm để không bỏ lỡ!",
            ),
            "en": _fit_body(
                f"{title_en} registration opens in {_humanize(remaining, 'en')}.",
                "Tap now so you don't miss out!",
            ),
        },
    )


def _scan(kind, now=None):
    """Quét các đợt tới hạn của MỘT mốc và gửi."""
    cfg = KINDS[kind]
    now = now or now_datetime()

    if cfg["after"]:
        # Mốc đã qua: [now - window, now]
        lo, hi = add_to_date(now, minutes=-cfg["window"]), now
    else:
        # Mốc sắp tới: [now, now + window]
        lo, hi = now, add_to_date(now, minutes=cfg["window"])

    return frappe.get_all(
        DT_PERIOD,
        filters={
            "status": "Open",
            cfg["flag"]: 0,
            cfg["field"]: ["between", [lo, hi]],
        },
        fields=["name"],
        ignore_permissions=True,
    )


def _run(kind, now=None):
    try:
        now = now or now_datetime()
        for row in _scan(kind, now):
            try:
                _send_for_period(row.name, kind, now)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"club_reminders.{kind}.item")
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"club_reminders.{kind}")


def send_club_open_reminders(minutes_before=DEFAULT_MINUTES_BEFORE):
    """Scheduler: nhắc ~15 phút TRƯỚC giờ mở đăng ký."""
    _run("open")


def send_club_close_reminders():
    """Scheduler: nhắc ~1 tiếng TRƯỚC giờ đóng đăng ký."""
    _run("closing")


def send_club_closed_notices():
    """Scheduler: báo đã đóng cổng, ngay SAU giờ đóng đăng ký."""
    _run("closed")


def _send_for_period(period_name, kind, now):
    from erp.utils.notification_handler import send_bulk_parent_notifications

    cfg = KINDS[kind]
    period = frappe.get_doc(DT_PERIOD, period_name)

    # Đợt chưa tới khoảng hiển thị: phụ huynh mở app cũng không thấy gì. Chưa đốt
    # cờ để lần quét sau thử lại — nhưng nếu tới lúc rớt khỏi cửa sổ thì thôi.
    if period.display_start_datetime and get_datetime(period.display_start_datetime) > now:
        return {"sent": 0, "outcome": "chưa tới khoảng hiển thị của đợt"}

    student_ids = _eligible_student_ids(period)
    if not student_ids:
        # Chưa khai buổi nào / chưa xếp lớp -> không có ai để nhắc. Đốt cờ luôn,
        # nếu không mỗi 5 phút lại quét lại một đợt vĩnh viễn rỗng.
        frappe.db.set_value(DT_PERIOD, period_name, cfg["flag"], 1)
        frappe.db.commit()
        return {"sent": 0, "outcome": "không có học sinh nào đủ điều kiện"}

    # Cổng chạy thử — GỠ TRƯỚC KHI RELEASE (xem `club_beta_access`).
    eligible_count = len(student_ids)
    student_ids = filter_students_for_beta(student_ids)
    if not student_ids:
        # KHÔNG đốt cờ: danh sách chạy thử có thể được bổ sung, lần quét sau vẫn kịp.
        return {
            "sent": 0,
            "outcome": "cổng chạy thử loại hết người nhận",
            "eligible_students": eligible_count,
        }

    title, body = _reminder_text(period, kind, now)

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
            "type": f"club_registration_{kind}",
            "period_id": period_name,
            # `timestamp` BẮT BUỘC phải có: `send_bulk_parent_notifications` dựng
            # khoá chống trùng từ `data["timestamp"]`. Thiếu nó thì khoá là hằng
            # số và mọi lần gửi sau cho cùng nhóm học sinh đều bị nuốt im lặng.
            #
            # PHẢI là datetime THUẦN — cùng giá trị này còn được ghi thẳng vào
            # cột `event_timestamp` (kiểu Datetime) của ERP Notification, thêm
            # tiền tố gì vào là MySQL từ chối cả bản ghi.
            # Ba mốc không cần phân biệt trong khoá: chúng cách nhau hàng chục
            # phút theo thiết kế, không thể rơi vào cùng một phút.
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
        frappe.db.set_value(DT_PERIOD, period_name, cfg["flag"], 1)
        frappe.db.commit()
        frappe.logger().info(
            f"club_reminders[{kind}]: đợt {period_name} -> {len(student_ids)} HS, {sent} thông báo"
        )
        return {
            "sent": sent,
            "outcome": "đã gửi",
            "kind": kind,
            "students": len(student_ids),
            "recipients": result.get("parent_emails"),
        }

    # `frappe.log_error(title, message)` — THAM SỐ ĐẦU LÀ TIÊU ĐỀ, giới hạn 140
    # ký tự và KHÔNG tự cắt: nhét cả phản hồi vào đó thì chính lời ghi log ném
    # CharacterLengthExceededError, nuốt mất nguyên nhân thật.
    frappe.log_error(
        f"club_reminders[{kind}]: không tạo được thông báo",
        f"Đợt {period_name}: {len(student_ids)} học sinh đủ điều kiện nhưng "
        f"KHÔNG tạo được thông báo nào.\n\nPhản hồi:\n{result}",
    )
    # Phân biệt "bị debounce nuốt" với "insert hỏng": hai cái này cùng cho
    # success_count = 0 nhưng cách xử lý ngược nhau — một cái chờ 60 giây rồi
    # chạy lại là xong, một cái phải sửa code. Nhánh debounce không có `results`
    # nên `errors` rỗng; chỉ nhìn `errors` thì không tài nào đoán ra.
    skipped = cint(result.get("skipped_count")) if isinstance(result, dict) else 0
    message = (result or {}).get("message") or ""
    debounced = skipped > 0 or "debounce" in message.lower()

    return {
        "sent": 0,
        "outcome": (
            "bị chặn trùng (debounce 60 giây) — chờ 1 phút rồi chạy lại"
            if debounced
            else "gửi thất bại — xem Error Log 'club_reminders'"
        ),
        "kind": kind,
        "students": len(student_ids),
        "skipped": skipped,
        "server_message": message,
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
    reg_end = get_datetime(period.registration_end_datetime)
    minutes_to_open = (reg_start - now).total_seconds() / 60.0
    minutes_to_close = (reg_end - now).total_seconds() / 60.0

    def _kind_state(kind):
        """Từng mốc: còn bao lâu, có đang trong cửa sổ, cờ đã đốt chưa."""
        cfg = KINDS[kind]
        delta = (get_datetime(period.get(cfg["field"])) - now).total_seconds() / 60.0
        in_window = (
            -cfg["window"] <= delta <= 0 if cfg["after"] else 0 <= delta <= cfg["window"]
        )
        return {
            "minutes_to_mark": round(delta, 1),
            "in_window": in_window,
            "already_sent": cint(period.get(cfg["flag"])),
        }

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
        "registration_end": str(reg_end),
        "minutes_to_open": round(minutes_to_open, 1),
        "minutes_to_close": round(minutes_to_close, 1),
        # Trạng thái RIÊNG cho từng mốc — trước đây chỉ báo mốc "open", nhìn vào
        # không biết hai mốc kia đã gửi hay chưa.
        "marks": {k: _kind_state(k) for k in KINDS},
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
        # `Mobile Device Token` DÙNG CHUNG với app nhân viên (workspace-mobile
        # gọi cùng endpoint register), mà `app_type` chỉ phân biệt
        # expo-go/standalone chứ không phân biệt hai app. Lấy 10 dòng mới nhất
        # là ra toàn token nhân viên, che mất câu hỏi thật: app PHỤ HUYNH đã
        # đăng ký token nào chưa. Nên lọc theo domain tài khoản phụ huynh.
        "parent_mobile_tokens_total": frappe.db.count(
            "Mobile Device Token",
            {"user": ["like", "%@parent.wellspring.edu.vn"], "is_active": 1},
        ),
        "recent_parent_mobile_tokens": frappe.get_all(
            "Mobile Device Token",
            filters={"user": ["like", "%@parent.wellspring.edu.vn"]},
            fields=["user", "platform", "app_type", "bundle_id", "is_active", "last_seen"],
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
def send_club_open_reminder_now(period_id=None, kind="open", force=0):
    """
    Gửi NGAY một mốc bất kỳ, không chờ cron — dùng để kiểm thử.

    `kind`: open | closing | closed. Bỏ qua cửa sổ thời gian và reset cờ của
    riêng mốc đó, nhưng VẪN đi qua cổng chạy thử trong `_send_for_period`.

    CHỐT AN TOÀN: từ chối chạy khi cổng chạy thử đang TẮT (danh sách số rỗng),
    vì lúc đó `filter_students_for_beta` trả nguyên danh sách và một lệnh gõ tay
    sẽ đẩy push tới TOÀN BỘ phụ huynh — việc không thu hồi được. Muốn gửi thật
    cho tất cả thì truyền `force=1` một cách có chủ đích.
    """
    from erp.api.parent_portal.club_beta_access import beta_gate_enabled

    if not frappe.has_permission(DT_PERIOD, "write"):
        frappe.throw("Không có quyền")
    if kind not in KINDS:
        frappe.throw(f"kind phải là một trong {sorted(KINDS)}")
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

    frappe.db.set_value(DT_PERIOD, period_id, KINDS[kind]["flag"], 0)
    frappe.db.commit()

    # Trả về KẾT QUẢ THẬT, không phải `{"ok": True}`: `ok` chỉ có nghĩa "không
    # ném exception", vô dụng đúng lúc cần biết nhất.
    outcome = _send_for_period(period_id, kind, now_datetime())
    return {"period_id": period_id, "kind": kind, **(outcome or {})}
