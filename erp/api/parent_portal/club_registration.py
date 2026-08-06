# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt
"""
API Parent Portal cho đăng ký Câu lạc bộ.

QUYỀN
-----
Dùng `erp.utils.family_access` (RIGHT_OPERATIONAL) chứ KHÔNG lặp lại idiom cũ
`frappe.get_all("CRM Family Relationship", ...)` như menu_registration.py:43.
Idiom cũ đọc bản mirror `CRM Guardian.student_relationships` có thể đã cũ và không
lọc `docstatus`, nên cổng quyền trở nên không tất định. Docstring của
family_access nêu đích danh "đăng ký suất ăn" là ví dụ của mức operational —
đăng ký CLB cùng nhóm nghiệp vụ.

ĐỒNG HỒ ĐẾM NGƯỢC
-----------------
Backend KHÔNG gửi datetime cho client tự parse. Frappe lưu datetime dạng naive
theo giờ máy chủ (Asia/Ho_Chi_Minh); client parse chuỗi đó sẽ hiểu thành giờ máy
mình -> lệch múi giờ. Thay vào đó API trả `phase` + `seconds_until_open` +
`seconds_until_close` là SỐ NGUYÊN, client chỉ việc đếm lùi. Khi đếm về 0, client
phải gọi lại API để SERVER quyết định phase, không tự đổi trạng thái.
"""

import json

import frappe
from frappe.utils import get_datetime, now_datetime

from erp.sis.utils.club_registration import (
    DAY_LABELS_EN,
    DAY_LABELS_VN,
    DAY_ORDER,
    ClubRegError,
    get_active_registrations,
    get_student_context,
    update_student_registrations,
)
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from erp.utils.family_access import RIGHT_OPERATIONAL, can_guardian_access_student, students_for_guardian
from erp.api.parent_portal.club_beta_access import is_guardian_allowed
from erp.utils.portal_error_handler import get_current_guardian

DT_PERIOD = "SIS Club Registration Period"
DT_OFFERING = "SIS Club Offering"
DT_REGISTRATION = "SIS Club Registration"

#: TTL cache số chỗ (giây). Đặt thấp hơn chu kỳ poll của client để mỗi lần poll
#: vẫn thấy số mới, nhưng đủ để mọi phụ huynh cùng khối dùng chung một query.
OFFERING_COUNTS_CACHE_TTL = 2


# ----------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------


def _data():
    if frappe.request and getattr(frappe.request, "is_json", False):
        return frappe.request.json or {}
    return dict(frappe.form_dict or {})


def _param(key, default=None):
    value = _data().get(key)
    if value in (None, ""):
        return default
    return value


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [v for v in value if v]
    return [value]


def _guardian():
    g = get_current_guardian()
    return g.get("name") if g else None


def _beta_blocked(guardian):
    """
    Cổng chạy thử — GỠ TRƯỚC KHI RELEASE (xem `club_beta_access`).

    Trả về response "chưa có đợt nào" thay vì 403: phụ huynh ngoài nhóm chạy thử
    không nên biết là module đang tồn tại mà mình bị chặn. Đặt ở TỪNG endpoint
    chứ không chỉ trong `_visible_period` vì `get_registration_data` và
    `save_registration` nhận thẳng `period_id` từ client, không đi qua hàm đó.
    """
    if is_guardian_allowed(guardian):
        return None
    return success_response(data=None, message="Chưa có đợt đăng ký câu lạc bộ nào")


def _phase_and_countdown(period, now=None):
    """
    Tính pha hiển thị + số giây còn lại — TẤT CẢ ở phía máy chủ.

    upcoming : đang trong khoảng hiển thị nhưng chưa tới giờ đăng ký
    open     : đang nhận đăng ký
    closed   : đã hết giờ đăng ký (hoặc đợt đã đóng)
    """
    now = now or now_datetime()
    reg_start = get_datetime(period.registration_start_datetime)
    reg_end = get_datetime(period.registration_end_datetime)

    if period.status != "Open":
        phase = "closed"
    elif now < reg_start:
        phase = "upcoming"
    elif now <= reg_end:
        phase = "open"
    else:
        phase = "closed"

    return {
        "phase": phase,
        "seconds_until_open": max(0, int((reg_start - now).total_seconds())),
        "seconds_until_close": max(0, int((reg_end - now).total_seconds())),
        "server_now": str(now),
    }


def _visible_period(campus_id=None):
    """
    Đợt đang được phép hiển thị cho phụ huynh.

    Điều kiện: status = Open VÀ thời điểm hiện tại nằm trong khoảng hiển thị.
    Controller đã chặn không cho hai đợt Open cùng (campus, năm học) nên ở đây
    tối đa chỉ còn một ứng viên; vẫn ORDER BY để tất định nếu dữ liệu cũ lỡ có
    nhiều dòng.
    """
    now = now_datetime()
    filters = {
        "status": "Open",
        "display_start_datetime": ["<=", now],
        "display_end_datetime": [">=", now],
    }
    if campus_id:
        filters["campus_id"] = campus_id

    rows = frappe.get_all(
        DT_PERIOD,
        filters=filters,
        fields=["name"],
        order_by="registration_start_datetime desc",
        limit=1,
        ignore_permissions=True,
    )
    if not rows:
        return None
    return frappe.get_doc(DT_PERIOD, rows[0].name)


def _period_payload(period):
    return {
        "name": period.name,
        "title_vn": period.title_vn,
        "title_en": period.title_en,
        "school_year_id": period.school_year_id,
        "status": period.status,
        "cover_image": period.cover_image,
        "intro_vn": period.intro_vn,
        "intro_en": period.intro_en,
        "guideline_vn": period.guideline_vn,
        "guideline_en": period.guideline_en,
        "display_start_datetime": str(period.display_start_datetime),
        "display_end_datetime": str(period.display_end_datetime),
        "registration_start_datetime": str(period.registration_start_datetime),
        "registration_end_datetime": str(period.registration_end_datetime),
    }


def _attachments_payload(period):
    return [
        {
            "file_url": a.file_url,
            "file_type": a.file_type,
            "title_vn": a.title_vn,
            "title_en": a.title_en,
            "sort_order": _int(a.sort_order),
        }
        for a in sorted(period.attachments or [], key=lambda x: _int(x.sort_order))
    ]


def _guardian_students(guardian):
    """Các con mà phụ huynh này được thao tác (mức operational)."""
    student_ids = students_for_guardian(guardian, RIGHT_OPERATIONAL)
    if not student_ids:
        return []
    rows = frappe.get_all(
        "CRM Student",
        filters={"name": ["in", student_ids]},
        fields=["name", "student_name", "student_code", "campus_id"],
        ignore_permissions=True,
    )
    return rows


def _eligible_offerings(period, education_grade_id):
    """Các môn trong đợt áp dụng cho đúng khối của học sinh."""
    if not education_grade_id:
        return []
    return frappe.db.sql(
        f"""
        SELECT DISTINCT
            o.name AS offering_id, o.subject_id, o.title_vn, o.title_en,
            o.day_of_week, o.capacity, o.registered_count,
            s.club_cover_image AS cover_image,
            s.club_short_description_vn AS short_description_vn,
            s.club_short_description_en AS short_description_en
        FROM `tab{DT_OFFERING}` o
        INNER JOIN `tabSIS Club Offering Grade` g ON g.parent = o.name
        LEFT JOIN `tabSIS Subject` s ON s.name = o.subject_id
        WHERE o.period_id = %(period_id)s
          AND o.status = 'active'
          AND g.education_grade_id = %(grade)s
        ORDER BY FIELD(o.day_of_week,'mon','tue','wed','thu','fri','sat'), o.title_vn
        """,
        {"period_id": period.name, "grade": education_grade_id},
        as_dict=True,
    )


def _offering_grades(offering_ids):
    """
    Toàn bộ khối mà mỗi offering áp dụng — KHÔNG lọc theo khối của học sinh
    đang xem, vì thẻ CLB cần hiển thị đủ các khối được mở, không chỉ khối của
    người xem. Sắp theo `SIS Education Grade.sort_order` để tránh sort chuỗi
    kiểu "Khối 10" đứng trước "Khối 2".
    """
    if not offering_ids:
        return {}
    rows = frappe.db.sql(
        """
        SELECT g.parent AS offering_id, e.title_vn AS grade_name
        FROM `tabSIS Club Offering Grade` g
        INNER JOIN `tabSIS Education Grade` e ON e.name = g.education_grade_id
        WHERE g.parent IN %(offering_ids)s
        ORDER BY e.sort_order
        """,
        {"offering_ids": offering_ids},
        as_dict=True,
    )
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r.offering_id, []).append(r.grade_name)
    return result


def _build_days(period, education_grade_id, existing, is_open):
    """
    Gom môn theo thứ và tính sẵn trạng thái khoá của từng thẻ.

    Parent Portal render THUẦN theo các cờ này — không đặt logic nghiệp vụ ở
    client, để bản web và bản mobile sau này không thể lệch luật nhau.
    """
    taken_subjects = {r.subject_id: r for r in existing}
    taken_days = {r.day_of_week: r for r in existing}

    offerings = _eligible_offerings(period, education_grade_id)
    grades_by_offering = _offering_grades(list({o.offering_id for o in offerings}))
    by_day = {}

    for o in offerings:
        capacity = _int(o.capacity)
        registered = _int(o.registered_count)
        remaining = max(0, capacity - registered)

        prior_same_subject = taken_subjects.get(o.subject_id)
        clash_day = taken_days.get(o.day_of_week)

        is_registered = bool(
            prior_same_subject and prior_same_subject.offering_id == o.offering_id
        )

        lock_reason = None
        if is_registered:
            lock_reason = "already_registered"
        elif prior_same_subject:
            # Cùng MÔN nhưng ở thứ khác -> luật 2 chặn.
            lock_reason = "already_registered"
        elif clash_day:
            lock_reason = "day_taken"
        elif remaining <= 0:
            lock_reason = "full"
        elif not is_open:
            lock_reason = "not_open"

        card = {
            "offering_id": o.offering_id,
            "subject_id": o.subject_id,
            "title_vn": o.title_vn,
            "title_en": o.title_en,
            "short_description_vn": o.short_description_vn,
            "short_description_en": o.short_description_en,
            "cover_image": o.cover_image,
            "grade_names": grades_by_offering.get(o.offering_id, []),
            "day_of_week": o.day_of_week,
            "capacity": capacity,
            "registered_count": registered,
            "remaining": remaining,
            "is_full": remaining <= 0,
            "is_registered": is_registered,
            "can_select": lock_reason is None,
            "lock_reason": lock_reason,
            # Sửa được chừng nào còn trong giờ đăng ký. `registration_id` là thứ
            # client gửi lại khi phụ huynh bỏ tick — client KHÔNG tự tra id.
            "registration_id": prior_same_subject.name if is_registered else None,
            "can_cancel": bool(is_registered and is_open),
            "registered_on_day": prior_same_subject.day_of_week if prior_same_subject else None,
        }
        by_day.setdefault(o.day_of_week, []).append(card)

    days = []
    for day in DAY_ORDER:
        if day not in by_day:
            continue
        locked = taken_days.get(day)
        days.append(
            {
                "day_of_week": day,
                "label_vn": DAY_LABELS_VN[day],
                "label_en": DAY_LABELS_EN[day],
                "locked_by_registration_id": locked.name if locked else None,
                "clubs": by_day[day],
            }
        )
    return days


def _my_registrations_payload(period_id, student_id):
    return frappe.db.sql(
        f"""
        SELECT
            r.name AS registration_id, r.offering_id, r.subject_id, r.day_of_week,
            r.registration_datetime,
            o.title_vn, o.title_en, s.club_cover_image AS cover_image
        FROM `tab{DT_REGISTRATION}` r
        LEFT JOIN `tab{DT_OFFERING}` o ON o.name = r.offering_id
        LEFT JOIN `tabSIS Subject` s ON s.name = r.subject_id
        WHERE r.period_id = %(period_id)s AND r.student_id = %(student_id)s
          AND r.status = 'active'
        ORDER BY FIELD(r.day_of_week,'mon','tue','wed','thu','fri','sat')
        """,
        {"period_id": period_id, "student_id": student_id},
        as_dict=True,
    )


def _decorate_registrations(rows):
    for r in rows:
        r["label_vn"] = DAY_LABELS_VN.get(r.get("day_of_week"), r.get("day_of_week"))
        r["label_en"] = DAY_LABELS_EN.get(r.get("day_of_week"), r.get("day_of_week"))
        r["registration_datetime"] = (
            str(r["registration_datetime"]) if r.get("registration_datetime") else None
        )
    return rows


# ----------------------------------------------------------------------
# Endpoint
# ----------------------------------------------------------------------


@frappe.whitelist()
def get_period_overview():
    """
    Thông tin đợt sắp tới / đang mở để dựng trang giới thiệu + đếm ngược.

    Trả `data = None` khi không có đợt nào đang hiển thị (không phải lỗi).
    """
    try:
        guardian = _guardian()
        if not guardian:
            return forbidden_response("Không tìm thấy thông tin phụ huynh")
        blocked = _beta_blocked(guardian)
        if blocked:
            return blocked

        students = _guardian_students(guardian)
        campus_id = students[0].campus_id if students else None

        period = _visible_period(campus_id)
        if not period:
            return success_response(data=None, message="Hiện chưa có đợt đăng ký CLB nào")

        countdown = _phase_and_countdown(period)
        return success_response(
            data={
                "period": _period_payload(period),
                "attachments": _attachments_payload(period),
                "has_eligible_students": bool(students),
                **countdown,
            },
            message="Lấy thông tin đợt đăng ký thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "PP Club get_period_overview")
        return error_response(f"Lỗi khi lấy thông tin đợt: {e}", code="GET_OVERVIEW_ERROR")


@frappe.whitelist()
def get_registration_data():
    """
    Dữ liệu đầy đủ cho màn đăng ký của MỘT học sinh.

    Mỗi con có khối khác nhau nên danh sách môn khác nhau — vì vậy API trả theo
    từng học sinh, client dùng bộ chọn con toàn cục để đổi.
    """
    try:
        guardian = _guardian()
        if not guardian:
            return forbidden_response("Không tìm thấy thông tin phụ huynh")
        blocked = _beta_blocked(guardian)
        if blocked:
            return blocked

        students = _guardian_students(guardian)
        if not students:
            return success_response(data=None, message="Không có học sinh nào")

        campus_id = students[0].campus_id
        period_id = _param("period_id")
        period = (
            frappe.get_doc(DT_PERIOD, period_id)
            if period_id and frappe.db.exists(DT_PERIOD, period_id)
            else _visible_period(campus_id)
        )
        if not period:
            return success_response(data=None, message="Hiện chưa có đợt đăng ký CLB nào")

        student_id = _param("student_id") or students[0].name
        if not can_guardian_access_student(guardian, student_id, RIGHT_OPERATIONAL):
            return forbidden_response("Phụ huynh không có quyền đăng ký cho học sinh này")

        countdown = _phase_and_countdown(period)
        is_open = countdown["phase"] == "open"

        student_notice = None
        education_grade_id = None
        class_title = None
        class_id = None
        try:
            ctx = get_student_context(student_id, period)
            education_grade_id = ctx["education_grade_id"]
            class_title = ctx["class_title"]
            class_id = ctx["class_id"]
        except ClubRegError as e:
            # Chưa xếp lớp -> không suy được khối. Báo rõ ràng thay vì trả danh
            # sách rỗng khiến phụ huynh tưởng trường chưa mở môn nào.
            student_notice = {"code": e.code, "message": e.message}

        existing = get_active_registrations(period.name, student_id)
        days = (
            _build_days(period, education_grade_id, existing, is_open)
            if education_grade_id
            else []
        )

        grade_name = (
            frappe.db.get_value("SIS Education Grade", education_grade_id, "title_vn")
            if education_grade_id
            else None
        )

        return success_response(
            data={
                "period": _period_payload(period),
                "attachments": _attachments_payload(period),
                **countdown,
                "students": [
                    {
                        "student_id": s.name,
                        "student_name": s.student_name,
                        "student_code": s.student_code,
                    }
                    for s in students
                ],
                "selected_student_id": student_id,
                "student_context": {
                    "class_id": class_id,
                    "class_name": class_title,
                    "education_grade_id": education_grade_id,
                    "education_grade_name": grade_name,
                    "notice": student_notice,
                },
                "days": days,
                "my_registrations": _decorate_registrations(
                    _my_registrations_payload(period.name, student_id)
                ),
            },
            message="Lấy dữ liệu đăng ký CLB thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "PP Club get_registration_data")
        return error_response(f"Lỗi khi lấy dữ liệu đăng ký: {e}", code="GET_REGISTRATION_DATA_ERROR")


@frappe.whitelist()
def get_offering_counts():
    """
    CHỈ số chỗ của các môn trong một đợt, cho đúng một khối.

    Vì sao tách khỏi `get_registration_data`: màn đăng ký cần số chỗ nhúc nhích
    gần thời gian thực, nhưng payload đầy đủ tốn ~15-25 round-trip SQL (quyền,
    danh sách con, doc đợt + child table, context lớp, đăng ký hiện có). Poll
    payload đó vài giây một lần với hàng nghìn phụ huynh lúc mở cổng sẽ giành
    lock với chính các transaction ghi đăng ký — polling làm hỏng đúng việc mà
    nó phục vụ.

    Hàm này đổi lại: một câu SQL, và số chỗ là dữ liệu DÙNG CHUNG theo cặp
    (đợt, khối) nên cache Redis vài giây làm tải DB thành O(1) — 2000 người
    poll hay 2 người poll cũng chỉ một query mỗi chu kỳ.

    Quyền: chỉ cần là phụ huynh hợp lệ (và trong nhóm chạy thử). KHÔNG kiểm
    `can_guardian_access_student` như các endpoint khác vì response không chứa
    bất kỳ dữ liệu học sinh nào — chỉ sức chứa/đã đăng ký của môn, thứ mà mọi
    phụ huynh trong đợt đều thấy trên màn đăng ký. Đổi lại `education_grade_id`
    nhận thẳng từ client (client đã có sẵn từ lần load đầu), tránh phải truy
    context lớp của học sinh — chính là phần đắt nhất muốn cắt bỏ.

    `my_offering_ids` là ngoại lệ có chủ đích: số chỗ thôi thì chưa đủ, vì nhà
    trường có thể HUỶ một đăng ký — lúc đó số chỗ tăng nhưng ô vẫn phải bỏ khoá
    "đã đăng ký". Trả kèm danh sách môn đang đăng ký của học sinh để client biết
    tập đăng ký đã đổi và nạp lại payload đầy đủ MỘT lần; các cờ `lock_reason`
    vẫn do máy chủ tính, client không tự suy. Phần này theo từng học sinh nên
    không cache được, nhưng chỉ là một lookup có index.
    """
    try:
        guardian = _guardian()
        if not guardian:
            return forbidden_response("Không tìm thấy thông tin phụ huynh")
        blocked = _beta_blocked(guardian)
        if blocked:
            return blocked

        period_id = _param("period_id")
        education_grade_id = _param("education_grade_id")
        if not period_id or not education_grade_id:
            return validation_error_response(
                "Thiếu tham số",
                {
                    "period_id": ["Bắt buộc"] if not period_id else [],
                    "education_grade_id": ["Bắt buộc"] if not education_grade_id else [],
                },
            )

        student_id = _param("student_id")
        my_offering_ids = (
            [
                r.offering_id
                for r in get_active_registrations(period_id, student_id)
            ]
            if student_id
            else []
        )

        cache_key = f"club:offering_counts:{period_id}:{education_grade_id}"
        cached = frappe.cache().get_value(cache_key)
        if cached is not None:
            return success_response(
                data={"counts": cached, "my_offering_ids": my_offering_ids},
                message="Lấy số chỗ CLB thành công",
            )

        rows = frappe.db.sql(
            f"""
            SELECT DISTINCT o.name AS offering_id, o.capacity, o.registered_count
            FROM `tab{DT_OFFERING}` o
            INNER JOIN `tabSIS Club Offering Grade` g ON g.parent = o.name
            WHERE o.period_id = %(period_id)s
              AND o.status = 'active'
              AND g.education_grade_id = %(grade)s
            """,
            {"period_id": period_id, "grade": education_grade_id},
            as_dict=True,
        )

        counts = [
            {
                "offering_id": r.offering_id,
                "capacity": _int(r.capacity),
                "registered_count": _int(r.registered_count),
                "remaining": max(0, _int(r.capacity) - _int(r.registered_count)),
            }
            for r in rows
        ]
        frappe.cache().set_value(cache_key, counts, expires_in_sec=OFFERING_COUNTS_CACHE_TTL)
        return success_response(
            data={"counts": counts, "my_offering_ids": my_offering_ids},
            message="Lấy số chỗ CLB thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "PP Club get_offering_counts")
        return error_response(f"Lỗi khi lấy số chỗ: {e}", code="GET_OFFERING_COUNTS_ERROR")


@frappe.whitelist()
def get_club_detail():
    """Chi tiết một môn để phụ huynh đọc trước khi quyết định."""
    try:
        guardian = _guardian()
        if not guardian:
            return forbidden_response("Không tìm thấy thông tin phụ huynh")
        blocked = _beta_blocked(guardian)
        if blocked:
            return blocked

        offering_id = _param("offering_id")
        if not offering_id:
            return validation_error_response("Thiếu offering_id", {"offering_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_OFFERING, offering_id):
            return not_found_response("Không tìm thấy môn CLB")

        doc = frappe.get_doc(DT_OFFERING, offering_id)
        capacity = _int(doc.capacity)
        registered = _int(doc.registered_count)
        # Giới thiệu thuộc về môn, không thuộc buổi.
        intro = frappe.db.get_value(
            "SIS Subject",
            doc.subject_id,
            ["club_cover_image", "club_short_description_vn", "club_short_description_en"],
            as_dict=True,
        ) or frappe._dict()

        return single_item_response(
            {
                "offering_id": doc.name,
                "subject_id": doc.subject_id,
                "title_vn": doc.title_vn,
                "title_en": doc.title_en,
                "cover_image": intro.get("club_cover_image"),
                "short_description_vn": intro.get("club_short_description_vn"),
                "short_description_en": intro.get("club_short_description_en"),
                "day_of_week": doc.day_of_week,
                "label_vn": DAY_LABELS_VN.get(doc.day_of_week, doc.day_of_week),
                "label_en": DAY_LABELS_EN.get(doc.day_of_week, doc.day_of_week),
                "capacity": capacity,
                "registered_count": registered,
                "remaining": max(0, capacity - registered),
            },
            "Lấy chi tiết môn CLB thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "PP Club get_club_detail")
        return error_response(f"Lỗi khi lấy chi tiết môn: {e}", code="GET_CLUB_DETAIL_ERROR")


@frappe.whitelist()
def save_registration():
    """
    Lưu thay đổi đăng ký CLB: thêm môn và/hoặc huỷ môn đã đăng ký.

    Phụ huynh sửa được CHỪNG NÀO CÒN TRONG THỜI GIAN ĐĂNG KÝ (`enforce_window`).
    Hết giờ là chốt, muốn đổi phải nhờ nhà trường. Huỷ được cả môn do nhà trường
    xếp, không riêng môn phụ huynh tự đăng ký.

    Hai ngữ nghĩa khác nhau tuỳ lô, xem `update_student_registrations`:
        - Lô CHỈ thêm  -> thành công một phần (2/3 môn còn chỗ thì nhận 2 môn).
        - Lô CÓ huỷ    -> tất-cả-hoặc-không, để đổi môn hụt không mất môn cũ.

    Kết quả chia nhóm cho client hiển thị:
        cancelled - đã huỷ
        saved     - đã đăng ký thêm
        skipped   - đã đăng ký từ trước (không phải lỗi, bấm 2 lần vô hại)
        failed    - hết chỗ / trùng thứ / không hợp lệ
    """
    try:
        guardian = _guardian()
        if not guardian:
            return forbidden_response("Không tìm thấy thông tin phụ huynh")
        blocked = _beta_blocked(guardian)
        if blocked:
            return blocked

        data = _data()
        period_id = data.get("period_id")
        student_id = data.get("student_id")
        offering_ids = _as_list(data.get("offering_ids"))
        cancel_registration_ids = _as_list(data.get("cancel_registration_ids"))

        if not period_id or not student_id or not (offering_ids or cancel_registration_ids):
            return validation_error_response(
                "Thiếu tham số",
                {
                    "period_id": ["Bắt buộc"] if not period_id else [],
                    "student_id": ["Bắt buộc"] if not student_id else [],
                    "offering_ids": (
                        ["Vui lòng chọn ít nhất một thay đổi"]
                        if not (offering_ids or cancel_registration_ids)
                        else []
                    ),
                },
            )

        if not can_guardian_access_student(guardian, student_id, RIGHT_OPERATIONAL):
            return forbidden_response("Phụ huynh không có quyền đăng ký cho học sinh này")

        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")

        period = frappe.get_doc(DT_PERIOD, period_id)

        result = update_student_registrations(
            period,
            student_id,
            cancel_registration_ids=cancel_registration_ids,
            offering_ids=offering_ids,
            actor_user=frappe.session.user,
            guardian=guardian,
            source="parent_portal",
            enforce_window=True,
            reason="Phụ huynh tự huỷ trên Parent Portal",
        )

        result["period_id"] = period_id
        result["student_id"] = student_id
        result["my_registrations"] = _decorate_registrations(
            _my_registrations_payload(period_id, student_id)
        )

        cancelled_count = len(result.get("cancelled") or [])
        saved_count = len(result["saved"])

        # Chỉ coi là thất bại khi KHÔNG thay đổi được gì cả. Lô chỉ-thêm có thể
        # lưu được một phần và vẫn là thành công; lô có huỷ thì hoặc trọn vẹn,
        # hoặc `failed` khác rỗng và không có gì được áp dụng.
        if not saved_count and not cancelled_count:
            if result["failed"]:
                first = result["failed"][0]
                return error_response(
                    first.get("message") or "Không thể lưu thay đổi",
                    code=first.get("code"),
                    debug_info=result,
                )
            return success_response(
                data=result, message="Các môn Phụ huynh chọn đều đã được đăng ký trước đó"
            )

        parts = []
        if saved_count:
            parts.append(f"đăng ký {saved_count} môn")
        if cancelled_count:
            parts.append(f"huỷ {cancelled_count} môn")
        message = "Đã " + " và ".join(parts)
        if result["failed"]:
            message += f", {len(result['failed'])} môn không thể đăng ký"

        return success_response(data=result, message=message)

    except ClubRegError as e:
        return error_response(e.message, code=e.code)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "PP Club save_registration")
        return error_response(f"Lỗi khi lưu đăng ký: {e}", code="SAVE_REGISTRATION_ERROR")


@frappe.whitelist()
def get_my_registrations():
    """Danh sách môn đã đăng ký của tất cả các con trong một đợt."""
    try:
        guardian = _guardian()
        if not guardian:
            return forbidden_response("Không tìm thấy thông tin phụ huynh")
        blocked = _beta_blocked(guardian)
        if blocked:
            return blocked

        students = _guardian_students(guardian)
        if not students:
            return success_response(data={"students": []}, message="Không có học sinh nào")

        period_id = _param("period_id")
        if not period_id:
            period = _visible_period(students[0].campus_id)
            if not period:
                return success_response(
                    data={"students": []}, message="Hiện chưa có đợt đăng ký CLB nào"
                )
            period_id = period.name

        payload = []
        for s in students:
            payload.append(
                {
                    "student_id": s.name,
                    "student_name": s.student_name,
                    "student_code": s.student_code,
                    "registrations": _decorate_registrations(
                        _my_registrations_payload(period_id, s.name)
                    ),
                }
            )

        return success_response(
            data={"period_id": period_id, "students": payload},
            message="Lấy danh sách đã đăng ký thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "PP Club get_my_registrations")
        return error_response(f"Lỗi khi lấy danh sách đã đăng ký: {e}", code="GET_MY_REGISTRATIONS_ERROR")
