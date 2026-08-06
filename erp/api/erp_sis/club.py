# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt
"""
API nhà trường cho module Câu lạc bộ.

Mọi thao tác ghi đăng ký (tạo hộ / huỷ / chuyển môn) đều đi qua
`erp.sis.utils.club_registration` — KHÔNG tự insert hay tự sửa `registered_count`
ở file này. Xem docstring của module đó để hiểu vì sao.
"""

import json

import frappe

from erp.sis.utils.club_days import days_to_csv, normalize_days
from erp.sis.utils.club_registration import (
    DAY_LABELS_EN,
    DAY_LABELS_VN,
    DAY_ORDER,
    ClubRegError,
    cancel_registration,
    get_active_registrations,
    move_registration,
    recalculate_registered_counts,
    register_student_to_clubs,
)
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    list_response,
    not_found_response,
    paginated_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.search import build_search_condition

DT_PERIOD = "SIS Club Registration Period"
DT_OFFERING = "SIS Club Offering"
DT_REGISTRATION = "SIS Club Registration"

PERIOD_WRITE_FIELDS = [
    "title_vn",
    "title_en",
    "school_year_id",
    "status",
    "activity_days",
    "display_start_datetime",
    "display_end_datetime",
    "registration_start_datetime",
    "registration_end_datetime",
    "cover_image",
    "intro_vn",
    "intro_en",
    "guideline_vn",
    "guideline_en",
]

OFFERING_WRITE_FIELDS = [
    "subject_id",
    "day_of_week",
    "capacity",
    "status",
]

# Ảnh + mô tả giới thiệu thuộc về MÔN (SIS Subject), không thuộc buổi: một môn mở
# cả thứ 3 lẫn thứ 5 vẫn chỉ có một bản giới thiệu, không thể lệch nhau.
SUBJECT_INTRO_FIELDS = [
    "club_cover_image",
    "club_short_description_vn",
    "club_short_description_en",
]


# ----------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------


def _data():
    """Lấy body request dù client gửi JSON hay form-encoded."""
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


def _campus():
    return get_current_campus_from_context() or "campus-1"


def _can_write(doctype):
    """
    Chốt quyền ghi cho các endpoint KHÔNG đi qua kiểm quyền của Frappe.

    Đường ghi đăng ký (`club_registration.py`) và phần giới thiệu môn đều đặt
    `ignore_permissions` / `frappe.db.set_value` — bắt buộc, vì cùng đường đó
    phục vụ cả Parent Portal (role Parent chỉ có `read`). Hệ quả: nếu không
    kiểm ở đây thì role chỉ-đọc (SIS BOD) vẫn huỷ/chuyển/đăng ký hộ được qua
    API dù màn hình đã giấu nút.

    Kiểm theo permission của doctype, không hard-code tên role: đổi phân quyền
    trong .json là endpoint đổi theo.
    """
    return bool(frappe.has_permission(doctype, ptype="write"))


def _named_search(fields, query, prefix):
    """
    Bọc `build_search_condition` để dùng được với tham số theo TÊN.

    `build_search_condition` sinh placeholder POSITIONAL `%s` + list param, trong
    khi mọi query ở file này dùng `%(key)s` + dict. pymysql chỉ nhận một trong hai
    kiểu cho mỗi câu lệnh — trộn lẫn sẽ lỗi lúc chạy. Hàm này đổi tên từng `%s`
    thành khoá duy nhất và trả về dict tương ứng.
    """
    fragment, params = build_search_condition(fields, query)
    if not fragment:
        return "", {}

    parts = fragment.split("%s")
    values = {}
    out = parts[0]
    for i, tail in enumerate(parts[1:]):
        key = f"{prefix}{i}"
        values[key] = params[i]
        out += f"%({key})s{tail}"
    return out, values


def _period_stats(period_id):
    row = frappe.db.sql(
        f"""
        SELECT
            COUNT(*)                          AS offering_count,
            COALESCE(SUM(capacity), 0)        AS total_capacity,
            COALESCE(SUM(registered_count), 0) AS total_registered
        FROM `tab{DT_OFFERING}`
        WHERE period_id = %s AND status = 'active'
        """,
        (period_id,),
        as_dict=True,
    )[0]

    student_count = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT student_id) FROM `tab{DT_REGISTRATION}`
        WHERE period_id = %s AND status = 'active'
        """,
        (period_id,),
    )[0][0]

    total_capacity = _int(row.get("total_capacity"))
    total_registered = _int(row.get("total_registered"))
    return {
        "offering_count": _int(row.get("offering_count")),
        "total_capacity": total_capacity,
        "total_registered": total_registered,
        "remaining": max(0, total_capacity - total_registered),
        "student_count": _int(student_count),
        "fill_rate": round(total_registered * 100.0 / total_capacity, 1) if total_capacity else 0.0,
    }


def _index_health():
    """
    Hai UNIQUE index là lưới an toàn cuối cùng chống trùng đăng ký.

    Nếu patch chưa chạy (hoặc chạy hụt) thì dữ liệu vẫn có thể trùng qua các đường
    ghi không đi qua lõi. Trả cờ này để màn hình nhà trường cảnh báo ngay, thay vì
    im lặng cho tới lúc phát hiện dữ liệu hỏng.
    """
    required = {"uq_club_reg_student_subject", "uq_club_reg_student_day"}
    try:
        rows = frappe.db.sql(f"SHOW INDEX FROM `tab{DT_REGISTRATION}`", as_dict=True)
        present = {r.get("Key_name") for r in rows}
    except Exception:
        return {"ok": False, "missing": sorted(required)}
    missing = sorted(required - present)
    return {"ok": not missing, "missing": missing}


def _offering_payload(row):
    row = dict(row)
    row["remaining"] = max(0, _int(row.get("capacity")) - _int(row.get("registered_count")))
    row["is_full"] = row["remaining"] <= 0
    row["day_label_vn"] = DAY_LABELS_VN.get(row.get("day_of_week"), row.get("day_of_week"))
    row["day_label_en"] = DAY_LABELS_EN.get(row.get("day_of_week"), row.get("day_of_week"))
    return row


def _load_offering_grades(offering_ids):
    """Nạp khối áp dụng cho nhiều môn bằng MỘT query, tránh N+1."""
    if not offering_ids:
        return {}
    rows = frappe.get_all(
        "SIS Club Offering Grade",
        filters={"parent": ["in", list(offering_ids)], "parenttype": DT_OFFERING},
        fields=["parent", "education_grade_id", "education_grade_name", "education_stage_id"],
    )
    grouped = {}
    for r in rows:
        grouped.setdefault(r.parent, []).append(
            {
                "education_grade_id": r.education_grade_id,
                "education_grade_name": r.education_grade_name,
                "education_stage_id": r.education_stage_id,
            }
        )
    return grouped


def _apply_grades(doc, grade_ids):
    doc.set("education_grades", [])
    for gid in grade_ids:
        doc.append("education_grades", {"education_grade_id": gid})


def _club_error(e: ClubRegError):
    return error_response(message=e.message, code=e.code)


# ----------------------------------------------------------------------
# Đợt đăng ký
# ----------------------------------------------------------------------


@frappe.whitelist()
def get_club_periods():
    """Danh sách đợt đăng ký CLB (phân trang)."""
    try:
        school_year_id = _param("school_year_id")
        status = _param("status")
        search = _param("search")
        page = max(1, _int(_param("page", 1), 1))
        page_size = min(100, max(1, _int(_param("page_size", 25), 25)))

        conditions = ["p.campus_id = %(campus_id)s"]
        values = {"campus_id": _campus()}

        if school_year_id:
            conditions.append("p.school_year_id = %(school_year_id)s")
            values["school_year_id"] = school_year_id
        if status:
            conditions.append("p.status = %(status)s")
            values["status"] = status
        if search:
            cond, search_values = _named_search(["p.title_vn", "p.title_en"], search, "pq")
            if cond:
                conditions.append(cond)
                values.update(search_values)

        where = " AND ".join(conditions)

        total = frappe.db.sql(
            f"SELECT COUNT(*) FROM `tab{DT_PERIOD}` p WHERE {where}", values
        )[0][0]

        values["limit"] = page_size
        values["offset"] = (page - 1) * page_size

        rows = frappe.db.sql(
            f"""
            SELECT
                p.name, p.title_vn, p.title_en, p.school_year_id, p.status,
                p.display_start_datetime, p.display_end_datetime,
                p.registration_start_datetime, p.registration_end_datetime,
                p.cover_image, p.modified,
                COALESCE(sy.title_vn, '') AS school_year_name,
                (SELECT COUNT(*) FROM `tab{DT_OFFERING}` o
                    WHERE o.period_id = p.name AND o.status = 'active') AS offering_count,
                (SELECT COUNT(*) FROM `tab{DT_REGISTRATION}` r
                    WHERE r.period_id = p.name AND r.status = 'active') AS registration_count
            FROM `tab{DT_PERIOD}` p
            LEFT JOIN `tabSIS School Year` sy ON sy.name = p.school_year_id
            WHERE {where}
            ORDER BY p.registration_start_datetime DESC, p.modified DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            values,
            as_dict=True,
        )

        return paginated_response(
            data=rows,
            current_page=page,
            total_count=_int(total),
            per_page=page_size,
            message="Lấy danh sách đợt đăng ký CLB thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_club_periods")
        return error_response(f"Lỗi khi lấy danh sách đợt: {e}", code="GET_CLUB_PERIODS_ERROR")


@frappe.whitelist()
def get_club_period():
    """Chi tiết một đợt + đính kèm + thống kê + tình trạng unique index."""
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")

        doc = frappe.get_doc(DT_PERIOD, period_id)
        data = doc.as_dict()
        data["school_year_name"] = frappe.db.get_value(
            "SIS School Year", doc.school_year_id, "title_vn"
        )
        # Trả về DANH SÁCH, không phải CSV thô: FE dựng cột và checkbox từ đây.
        # `activity_days_configured` phân biệt "chưa cấu hình" (hiện đủ 6 thứ)
        # với "đã chọn đủ 6 thứ" — hai trạng thái này trông giống nhau ở
        # `activity_days` nhưng khác nhau khi hiển thị trạng thái form.
        data["activity_days"] = doc.get_activity_days()
        data["activity_days_configured"] = bool(normalize_days(doc.get("activity_days")))
        data["attachments"] = [
            {
                "name": a.name,
                "file_url": a.file_url,
                "file_type": a.file_type,
                "title_vn": a.title_vn,
                "title_en": a.title_en,
                "sort_order": a.sort_order,
            }
            for a in sorted(doc.attachments or [], key=lambda x: _int(x.sort_order))
        ]
        data["stats"] = _period_stats(period_id)
        data["index_health"] = _index_health()

        return single_item_response(data, "Lấy chi tiết đợt đăng ký thành công")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_club_period")
        return error_response(f"Lỗi khi lấy chi tiết đợt: {e}", code="GET_CLUB_PERIOD_ERROR")


def _write_period(doc, data):
    for field in PERIOD_WRITE_FIELDS:
        if field in data:
            # API nói chuyện bằng danh sách, DB lưu CSV — quy đổi ở đúng một chỗ.
            value = (
                days_to_csv(data.get(field)) if field == "activity_days" else data.get(field)
            )
            doc.set(field, value)

    if "attachments" in data:
        doc.set("attachments", [])
        for idx, item in enumerate(_as_list(data.get("attachments"))):
            if not isinstance(item, dict) or not item.get("file_url"):
                continue
            doc.append(
                "attachments",
                {
                    "file_url": item.get("file_url"),
                    "file_type": item.get("file_type") or "image",
                    "title_vn": item.get("title_vn"),
                    "title_en": item.get("title_en"),
                    "sort_order": _int(item.get("sort_order"), idx),
                },
            )


@frappe.whitelist()
def create_club_period():
    try:
        data = _data()
        if not data.get("title_vn"):
            return validation_error_response("Thiếu tên đợt", {"title_vn": ["Bắt buộc"]})
        if not data.get("school_year_id"):
            return validation_error_response("Thiếu năm học", {"school_year_id": ["Bắt buộc"]})

        doc = frappe.new_doc(DT_PERIOD)
        doc.campus_id = data.get("campus_id") or _campus()
        _write_period(doc, data)
        doc.insert()
        frappe.db.commit()

        return single_item_response(doc.as_dict(), "Tạo đợt đăng ký CLB thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club create_club_period")
        return error_response(f"Lỗi khi tạo đợt: {e}", code="CREATE_CLUB_PERIOD_ERROR")


@frappe.whitelist()
def update_club_period():
    try:
        data = _data()
        period_id = data.get("period_id") or data.get("name")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")

        doc = frappe.get_doc(DT_PERIOD, period_id)
        _write_period(doc, data)
        doc.save()
        frappe.db.commit()

        return single_item_response(doc.as_dict(), "Cập nhật đợt đăng ký thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club update_club_period")
        return error_response(f"Lỗi khi cập nhật đợt: {e}", code="UPDATE_CLUB_PERIOD_ERROR")


@frappe.whitelist()
def update_club_period_status():
    try:
        period_id = _param("period_id")
        status = _param("status")
        if not period_id or status not in ("Draft", "Open", "Closed"):
            return validation_error_response(
                "Tham số không hợp lệ", {"status": ["Draft | Open | Closed"]}
            )
        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")

        doc = frappe.get_doc(DT_PERIOD, period_id)
        doc.status = status
        doc.save()
        frappe.db.commit()
        return single_item_response({"name": doc.name, "status": doc.status}, "Đã cập nhật trạng thái")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club update_club_period_status")
        return error_response(f"Lỗi khi đổi trạng thái: {e}", code="UPDATE_STATUS_ERROR")


@frappe.whitelist()
def delete_club_period():
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")

        frappe.delete_doc(DT_PERIOD, period_id)
        frappe.db.commit()
        return success_response(message="Đã xoá đợt đăng ký")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club delete_club_period")
        return error_response(f"Lỗi khi xoá đợt: {e}", code="DELETE_CLUB_PERIOD_ERROR")


# ----------------------------------------------------------------------
# Môn CLB (offering)
# ----------------------------------------------------------------------


@frappe.whitelist()
def get_offerings():
    """Danh sách môn CLB trong một đợt, kèm khối áp dụng."""
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})

        day_of_week = _param("day_of_week")
        education_grade_id = _param("education_grade_id")
        education_stage_id = _param("education_stage_id")
        search = _param("search")

        conditions = ["o.period_id = %(period_id)s"]
        values = {"period_id": period_id}

        if day_of_week:
            conditions.append("o.day_of_week = %(day_of_week)s")
            values["day_of_week"] = day_of_week
        if search:
            cond, search_values = _named_search(["o.title_vn", "o.title_en"], search, "oq")
            if cond:
                conditions.append(cond)
                values.update(search_values)
        if education_grade_id:
            conditions.append(
                "EXISTS (SELECT 1 FROM `tabSIS Club Offering Grade` g "
                "WHERE g.parent = o.name AND g.education_grade_id = %(education_grade_id)s)"
            )
            values["education_grade_id"] = education_grade_id
        if education_stage_id:
            conditions.append(
                "EXISTS (SELECT 1 FROM `tabSIS Club Offering Grade` g "
                "WHERE g.parent = o.name AND g.education_stage_id = %(education_stage_id)s)"
            )
            values["education_stage_id"] = education_stage_id

        rows = frappe.db.sql(
            f"""
            SELECT
                o.name, o.period_id, o.subject_id, o.timetable_subject_id,
                o.title_vn, o.title_en, o.day_of_week, o.capacity, o.registered_count,
                o.status,
                s.club_cover_image AS cover_image,
                s.club_short_description_vn AS short_description_vn,
                s.club_short_description_en AS short_description_en
            FROM `tab{DT_OFFERING}` o
            LEFT JOIN `tabSIS Subject` s ON s.name = o.subject_id
            WHERE {' AND '.join(conditions)}
            ORDER BY FIELD(o.day_of_week, 'mon','tue','wed','thu','fri','sat'), o.title_vn
            """,
            values,
            as_dict=True,
        )

        grades = _load_offering_grades([r.name for r in rows])
        data = []
        for r in rows:
            payload = _offering_payload(r)
            payload["education_grades"] = grades.get(r.name, [])
            data.append(payload)

        return list_response(data, "Lấy danh sách môn CLB thành công")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_offerings")
        return error_response(f"Lỗi khi lấy danh sách môn: {e}", code="GET_OFFERINGS_ERROR")


@frappe.whitelist()
def get_offering():
    try:
        offering_id = _param("offering_id")
        if not offering_id:
            return validation_error_response("Thiếu offering_id", {"offering_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_OFFERING, offering_id):
            return not_found_response("Không tìm thấy môn CLB")

        doc = frappe.get_doc(DT_OFFERING, offering_id)
        data = _offering_payload(doc.as_dict())
        data["education_grades"] = [
            {
                "education_grade_id": g.education_grade_id,
                "education_grade_name": g.education_grade_name,
                "education_stage_id": g.education_stage_id,
            }
            for g in doc.education_grades or []
        ]
        return single_item_response(data, "Lấy chi tiết môn CLB thành công")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_offering")
        return error_response(f"Lỗi khi lấy chi tiết môn: {e}", code="GET_OFFERING_ERROR")


@frappe.whitelist()
def create_offering():
    try:
        data = _data()
        period_id = data.get("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})
        if not data.get("subject_id"):
            return validation_error_response("Thiếu môn học", {"subject_id": ["Bắt buộc"]})

        grade_ids = _as_list(data.get("education_grade_ids"))
        if not grade_ids:
            return validation_error_response(
                "Chưa chọn khối áp dụng", {"education_grade_ids": ["Bắt buộc"]}
            )

        doc = frappe.new_doc(DT_OFFERING)
        doc.period_id = period_id
        doc.campus_id = data.get("campus_id") or _campus()
        for field in OFFERING_WRITE_FIELDS:
            if field in data:
                doc.set(field, data.get(field))
        _apply_grades(doc, grade_ids)
        doc.insert()
        frappe.db.commit()

        return single_item_response(doc.as_dict(), "Tạo môn CLB thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club create_offering")
        return error_response(f"Lỗi khi tạo môn: {e}", code="CREATE_OFFERING_ERROR")


@frappe.whitelist()
def update_offering():
    try:
        data = _data()
        offering_id = data.get("offering_id") or data.get("name")
        if not offering_id:
            return validation_error_response("Thiếu offering_id", {"offering_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_OFFERING, offering_id):
            return not_found_response("Không tìm thấy môn CLB")

        doc = frappe.get_doc(DT_OFFERING, offering_id)
        for field in OFFERING_WRITE_FIELDS:
            if field in data:
                doc.set(field, data.get(field))
        if "education_grade_ids" in data:
            _apply_grades(doc, _as_list(data.get("education_grade_ids")))
        doc.save()
        frappe.db.commit()

        return single_item_response(doc.as_dict(), "Cập nhật môn CLB thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club update_offering")
        return error_response(f"Lỗi khi cập nhật môn: {e}", code="UPDATE_OFFERING_ERROR")


@frappe.whitelist()
def delete_offering():
    try:
        offering_id = _param("offering_id")
        if not offering_id:
            return validation_error_response("Thiếu offering_id", {"offering_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_OFFERING, offering_id):
            return not_found_response("Không tìm thấy môn CLB")

        frappe.delete_doc(DT_OFFERING, offering_id)
        frappe.db.commit()
        return success_response(message="Đã xoá môn CLB")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club delete_offering")
        return error_response(f"Lỗi khi xoá môn: {e}", code="DELETE_OFFERING_ERROR")


@frappe.whitelist()
def update_club_subject_intro():
    """
    Sửa ảnh + mô tả giới thiệu của MỘT MÔN câu lạc bộ.

    Các trường này nằm trên `SIS Subject` chứ không trên từng buổi: một môn mở
    nhiều thứ vẫn chỉ có một bản giới thiệu. Chỉ cho sửa môn `subject_type='club'`
    để không ai vô tình gắn nội dung marketing vào môn học thuật.
    """
    try:
        if not _can_write(DT_OFFERING):
            return forbidden_response("Bạn chỉ có quyền xem câu lạc bộ")

        data = _data()
        subject_id = data.get("subject_id")
        if not subject_id:
            return validation_error_response("Thiếu subject_id", {"subject_id": ["Bắt buộc"]})
        if not frappe.db.exists("SIS Subject", subject_id):
            return not_found_response("Không tìm thấy môn học")

        if frappe.db.has_column("SIS Subject", "subject_type"):
            if frappe.db.get_value("SIS Subject", subject_id, "subject_type") != "club":
                return error_response(
                    "Chỉ môn có Loại môn học = «Câu lạc bộ» mới có phần giới thiệu này",
                    code="NOT_A_CLUB_SUBJECT",
                )

        updates = {f: data.get(f) for f in SUBJECT_INTRO_FIELDS if f in data}
        if not updates:
            return validation_error_response(
                "Không có nội dung nào để lưu",
                {"club_short_description_vn": ["Bắt buộc"]},
            )

        # Ghi thẳng cột thay vì `doc.save()`.
        #
        # `SISSubject.validate()` bắt buộc phải có `timetable_subject_id` VÀ
        # `actual_subject_id` — hai ràng buộc sinh ra cho môn học thuật (map
        # import Excel, phân công GV, học bạ). Môn CLB thường không có
        # `actual_subject_id`, nên `doc.save()` sẽ throw "Actual Subject is
        # required" và không bao giờ lưu được ảnh/mô tả. Ba trường này thuần mô
        # tả, không đụng tới business state, nên vá cột là đúng phạm vi.
        frappe.db.set_value("SIS Subject", subject_id, updates, update_modified=True)
        frappe.db.commit()

        saved = frappe.db.get_value(
            "SIS Subject", subject_id, ["name", *SUBJECT_INTRO_FIELDS], as_dict=True
        )
        return single_item_response(saved, "Đã lưu giới thiệu môn câu lạc bộ")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club update_club_subject_intro")
        return error_response(f"Lỗi khi lưu giới thiệu: {e}", code="UPDATE_SUBJECT_INTRO_ERROR")


@frappe.whitelist()
def bulk_save_offerings():
    """
    Lưu nhiều môn CLB trong một request — phục vụ bảng sửa tại chỗ.

    Body: {period_id,
           rows: [{offering_id?, subject_id, day_of_week, capacity, education_grade_ids[]}],
           delete_offering_ids: [...]}

    Mỗi dòng nằm trong savepoint riêng: một dòng sai (trùng môn+thứ, khối lệch
    cấp, môn không phải loại CLB…) chỉ hỏng dòng đó, phần còn lại vẫn lưu. Trả về
    theo INDEX của dòng để bảng ở FE tô đỏ đúng dòng thay vì báo một lỗi chung
    chung rồi bắt nhà trường tự dò.
    """
    try:
        data = _data()
        period_id = data.get("period_id")
        rows = _as_list(data.get("rows"))
        delete_ids = _as_list(data.get("delete_offering_ids"))

        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})
        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")
        if not rows and not delete_ids:
            return validation_error_response(
                "Không có thay đổi nào để lưu", {"rows": ["Bắt buộc"]}
            )

        campus_id = _campus()
        saved, failed, deleted = [], [], []

        # Xoá TRƯỚC khi ghi: bỏ một ô rồi mở lại chính (môn, thứ) đó trong cùng một
        # lần lưu sẽ vướng ràng buộc "mỗi (đợt, môn, thứ) chỉ một lần" nếu bản ghi
        # cũ vẫn còn nằm đó.
        for offering_id in delete_ids:
            savepoint = "club_del_" + str(offering_id).replace("-", "_")
            frappe.db.savepoint(savepoint)
            try:
                if frappe.db.exists(DT_OFFERING, offering_id):
                    # on_trash của doctype chặn nếu môn còn học sinh đăng ký.
                    frappe.delete_doc(DT_OFFERING, offering_id)
                deleted.append(offering_id)
            except Exception as e:
                frappe.db.rollback(save_point=savepoint)
                failed.append({"offering_id": offering_id, "message": str(e)})

        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                failed.append({"index": index, "message": "Dữ liệu dòng không hợp lệ"})
                continue

            savepoint = f"club_bulk_{index}"
            frappe.db.savepoint(savepoint)
            try:
                offering_id = row.get("offering_id")
                grade_ids = _as_list(row.get("education_grade_ids"))

                if not row.get("subject_id"):
                    raise frappe.ValidationError("Chưa chọn môn học")
                if not row.get("day_of_week"):
                    raise frappe.ValidationError("Chưa chọn thứ sinh hoạt")
                if not grade_ids:
                    raise frappe.ValidationError("Chưa chọn khối áp dụng")

                if offering_id:
                    if not frappe.db.exists(DT_OFFERING, offering_id):
                        raise frappe.ValidationError("Môn CLB không tồn tại")
                    doc = frappe.get_doc(DT_OFFERING, offering_id)
                else:
                    doc = frappe.new_doc(DT_OFFERING)
                    doc.period_id = period_id
                    doc.campus_id = campus_id

                for field in ("subject_id", "day_of_week", "capacity", "status"):
                    if field in row:
                        doc.set(field, row.get(field))
                _apply_grades(doc, grade_ids)
                doc.save()

                saved.append(
                    {
                        "index": index,
                        "offering_id": doc.name,
                        "title_vn": doc.title_vn,
                        "day_of_week": doc.day_of_week,
                    }
                )
            except Exception as e:
                frappe.db.rollback(save_point=savepoint)
                failed.append({"index": index, "message": str(e) or "Không lưu được dòng này"})

        frappe.db.commit()

        parts = []
        if saved:
            parts.append(f"đã lưu {len(saved)} môn")
        if deleted:
            parts.append(f"gỡ {len(deleted)} môn")
        if failed:
            parts.append(f"{len(failed)} lỗi")
        message = ("Đã " + ", ".join(parts)) if parts else "Không có thay đổi"

        return success_response(
            data={"saved": saved, "failed": failed, "deleted": deleted}, message=message
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club bulk_save_offerings")
        return error_response(f"Lỗi khi lưu danh sách môn: {e}", code="BULK_SAVE_OFFERINGS_ERROR")


@frappe.whitelist()
def duplicate_offering():
    """
    Nhân bản một môn sang thứ khác.

    Vì mỗi offering chỉ có MỘT thứ (để capacity rõ nghĩa và để luật ≤1 môn/thứ ép
    được bằng unique index), mở cùng một môn ở hai thứ cần hai bản ghi. Hàm này
    giúp không phải nhập lại toàn bộ mô tả / ảnh / khối.
    """
    try:
        offering_id = _param("offering_id")
        day_of_week = _param("day_of_week")
        if not offering_id or day_of_week not in DAY_ORDER:
            return validation_error_response(
                "Tham số không hợp lệ", {"day_of_week": ["mon..sat"]}
            )
        if not frappe.db.exists(DT_OFFERING, offering_id):
            return not_found_response("Không tìm thấy môn CLB")

        source = frappe.get_doc(DT_OFFERING, offering_id)
        doc = frappe.copy_doc(source)
        doc.day_of_week = day_of_week
        doc.registered_count = 0
        doc.insert()
        frappe.db.commit()

        return single_item_response(doc.as_dict(), "Đã nhân bản môn CLB sang thứ mới")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e), code="VALIDATION_ERROR")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club duplicate_offering")
        return error_response(f"Lỗi khi nhân bản môn: {e}", code="DUPLICATE_OFFERING_ERROR")


@frappe.whitelist()
def resync_offering_titles():
    """Đồng bộ lại tên snapshot khi Timetable Subject / Subject đổi tên."""
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})

        names = frappe.get_all(DT_OFFERING, filters={"period_id": period_id}, pluck="name")
        for name in names:
            doc = frappe.get_doc(DT_OFFERING, name)
            doc.save()
        frappe.db.commit()

        return success_response(
            data={"updated": len(names)}, message=f"Đã đồng bộ tên cho {len(names)} môn"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club resync_offering_titles")
        return error_response(f"Lỗi khi đồng bộ tên: {e}", code="RESYNC_TITLES_ERROR")


@frappe.whitelist()
def get_schedule_matrix():
    """
    Ma trận Khối × Thứ cho tab "Lịch theo khối".

    Trả lời trực tiếp câu hỏi nghiệp vụ "Tiểu học thứ 3 có môn gì": nhờ
    `education_stage_id` được denormalize xuống child table, đây chỉ là một
    JOIN có index thay vì phải đi qua ba bảng.
    """
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})

        rows = frappe.db.sql(
            f"""
            SELECT
                o.name AS offering_id, o.title_vn, o.title_en, o.day_of_week,
                o.capacity, o.registered_count, o.status,
                g.education_grade_id, g.education_grade_name, g.education_stage_id
            FROM `tab{DT_OFFERING}` o
            INNER JOIN `tabSIS Club Offering Grade` g ON g.parent = o.name
            WHERE o.period_id = %(period_id)s AND o.status = 'active'
            ORDER BY g.education_stage_id, g.education_grade_id,
                     FIELD(o.day_of_week, 'mon','tue','wed','thu','fri','sat'), o.title_vn
            """,
            {"period_id": period_id},
            as_dict=True,
        )

        cells = {}
        totals = {}
        stage_map = {}
        grade_meta = {}

        for r in rows:
            key = f"{r.education_grade_id}|{r.day_of_week}"
            cells.setdefault(key, []).append(
                {
                    "offering_id": r.offering_id,
                    "title_vn": r.title_vn,
                    "title_en": r.title_en,
                    "capacity": _int(r.capacity),
                    "registered_count": _int(r.registered_count),
                    "remaining": max(0, _int(r.capacity) - _int(r.registered_count)),
                }
            )
            bucket = totals.setdefault(key, {"offerings": 0, "capacity": 0, "registered": 0})
            bucket["offerings"] += 1
            bucket["capacity"] += _int(r.capacity)
            bucket["registered"] += _int(r.registered_count)

            grade_meta[r.education_grade_id] = {
                "id": r.education_grade_id,
                "title_vn": r.education_grade_name,
                "education_stage_id": r.education_stage_id,
            }
            stage_map.setdefault(r.education_stage_id, set()).add(r.education_grade_id)

        # Bổ sung sort_order + tên cấp học để FE dựng hàng đúng thứ tự.
        grade_ids = list(grade_meta.keys())
        if grade_ids:
            for g in frappe.get_all(
                "SIS Education Grade",
                filters={"name": ["in", grade_ids]},
                fields=["name", "sort_order"],
            ):
                grade_meta[g.name]["sort_order"] = _int(g.sort_order)

        stages = []
        stage_ids = [s for s in stage_map.keys() if s]
        stage_titles = {}
        if stage_ids:
            for s in frappe.get_all(
                "SIS Education Stage",
                filters={"name": ["in", stage_ids]},
                fields=["name", "title_vn", "title_en"],
            ):
                stage_titles[s.name] = s

        for stage_id, gids in stage_map.items():
            info = stage_titles.get(stage_id)
            stages.append(
                {
                    "id": stage_id,
                    "title_vn": info.title_vn if info else stage_id,
                    "title_en": info.title_en if info else stage_id,
                    "grades": sorted(
                        [grade_meta[g] for g in gids],
                        key=lambda x: (x.get("sort_order", 0), x.get("title_vn") or ""),
                    ),
                }
            )
        stages.sort(key=lambda s: s["title_vn"] or "")

        return success_response(
            data={
                # Chỉ các thứ đợt này sinh hoạt. Đợt chưa cấu hình thì
                # `get_activity_days()` trả đủ sáu thứ như trước.
                "days": [
                    {"key": d, "label_vn": DAY_LABELS_VN[d], "label_en": DAY_LABELS_EN[d]}
                    for d in frappe.get_cached_doc(DT_PERIOD, period_id).get_activity_days()
                ],
                "stages": stages,
                "cells": cells,
                "totals": totals,
            },
            message="Lấy lịch theo khối thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_schedule_matrix")
        return error_response(f"Lỗi khi lấy lịch theo khối: {e}", code="GET_SCHEDULE_MATRIX_ERROR")


# ----------------------------------------------------------------------
# Đăng ký
# ----------------------------------------------------------------------


@frappe.whitelist()
def get_club_registrations():
    """Danh sách đăng ký trong một đợt (phân trang, nhiều bộ lọc)."""
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})

        page = max(1, _int(_param("page", 1), 1))
        page_size = min(200, max(1, _int(_param("page_size", 25), 25)))

        conditions = ["r.period_id = %(period_id)s"]
        values = {"period_id": period_id}

        # `subject_id` lọc theo MÔN (gộp mọi thứ mà môn đó mở); `offering_id` lọc
        # đúng một buổi. Cột `subject_id` được denormalize sẵn trên dòng đăng ký
        # nên không phải JOIN sang offering.
        for key, column in (
            ("offering_id", "r.offering_id"),
            ("subject_id", "r.subject_id"),
            ("education_grade_id", "r.education_grade_id"),
            ("day_of_week", "r.day_of_week"),
            ("class_id", "r.class_id"),
        ):
            value = _param(key)
            if value:
                conditions.append(f"{column} = %({key})s")
                values[key] = value

        status = _param("status", "active")
        if status and status != "all":
            conditions.append("r.status = %(status)s")
            values["status"] = status

        search = _param("search")
        if search:
            cond, search_values = _named_search(
                ["r.student_name", "r.student_code"], search, "rq"
            )
            if cond:
                conditions.append(cond)
                values.update(search_values)

        where = " AND ".join(conditions)
        total = frappe.db.sql(
            f"SELECT COUNT(*) FROM `tab{DT_REGISTRATION}` r WHERE {where}", values
        )[0][0]

        values["limit"] = page_size
        values["offset"] = (page - 1) * page_size

        rows = frappe.db.sql(
            f"""
            SELECT
                r.name, r.student_id, r.student_name, r.student_code,
                r.class_id, r.class_name, r.education_grade_id,
                r.offering_id, r.subject_id, r.day_of_week, r.status,
                r.source, r.registration_datetime, r.registered_by,
                r.cancelled_at, r.cancel_reason,
                o.title_vn AS offering_title_vn, o.title_en AS offering_title_en,
                COALESCE(g.title_vn, '') AS education_grade_name
            FROM `tab{DT_REGISTRATION}` r
            LEFT JOIN `tab{DT_OFFERING}` o ON o.name = r.offering_id
            LEFT JOIN `tabSIS Education Grade` g ON g.name = r.education_grade_id
            WHERE {where}
            ORDER BY r.registration_datetime DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            values,
            as_dict=True,
        )

        for r in rows:
            r["day_label_vn"] = DAY_LABELS_VN.get(r.get("day_of_week"), r.get("day_of_week"))
            r["day_label_en"] = DAY_LABELS_EN.get(r.get("day_of_week"), r.get("day_of_week"))

        return paginated_response(
            data=rows,
            current_page=page,
            total_count=_int(total),
            per_page=page_size,
            message="Lấy danh sách đăng ký thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_club_registrations")
        return error_response(f"Lỗi khi lấy danh sách đăng ký: {e}", code="GET_REGISTRATIONS_ERROR")


@frappe.whitelist()
def get_club_registration_stats():
    """Thống kê lấp đầy theo môn / thứ / khối cho trang chi tiết đợt."""
    try:
        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})

        offerings = frappe.db.sql(
            f"""
            SELECT name AS offering_id, title_vn, title_en, day_of_week,
                   capacity, registered_count
            FROM `tab{DT_OFFERING}`
            WHERE period_id = %s AND status = 'active'
            ORDER BY FIELD(day_of_week,'mon','tue','wed','thu','fri','sat'), title_vn
            """,
            (period_id,),
            as_dict=True,
        )

        by_day = {}
        for o in offerings:
            o["remaining"] = max(0, _int(o.capacity) - _int(o.registered_count))
            o["fill_rate"] = (
                round(_int(o.registered_count) * 100.0 / _int(o.capacity), 1)
                if _int(o.capacity)
                else 0.0
            )
            bucket = by_day.setdefault(
                o.day_of_week, {"offerings": 0, "capacity": 0, "registered": 0}
            )
            bucket["offerings"] += 1
            bucket["capacity"] += _int(o.capacity)
            bucket["registered"] += _int(o.registered_count)

        by_grade = {}
        for row in frappe.db.sql(
            f"""
            SELECT education_grade_id, COUNT(*) AS registered,
                   COUNT(DISTINCT student_id) AS students
            FROM `tab{DT_REGISTRATION}`
            WHERE period_id = %s AND status = 'active'
            GROUP BY education_grade_id
            """,
            (period_id,),
            as_dict=True,
        ):
            by_grade[row.education_grade_id or "unknown"] = {
                "registered": _int(row.registered),
                "students": _int(row.students),
            }

        return success_response(
            data={
                "summary": _period_stats(period_id),
                "offerings": offerings,
                "by_day": by_day,
                "by_grade": by_grade,
                "index_health": _index_health(),
            },
            message="Lấy thống kê đăng ký thành công",
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club get_club_registration_stats")
        return error_response(f"Lỗi khi lấy thống kê: {e}", code="GET_STATS_ERROR")


@frappe.whitelist()
def cancel_club_registration():
    """Nhà trường huỷ một đăng ký. Bắt buộc có lý do để giữ vết xử lý."""
    try:
        if not _can_write(DT_REGISTRATION):
            return forbidden_response("Bạn chỉ có quyền xem đăng ký câu lạc bộ")

        registration_id = _param("registration_id")
        reason = _param("reason")
        if not registration_id:
            return validation_error_response(
                "Thiếu registration_id", {"registration_id": ["Bắt buộc"]}
            )
        if not reason:
            return validation_error_response("Vui lòng nhập lý do huỷ", {"reason": ["Bắt buộc"]})

        result = cancel_registration(registration_id, reason=reason)
        return success_response(data=result, message="Đã huỷ đăng ký")
    except ClubRegError as e:
        return _club_error(e)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club cancel_club_registration")
        return error_response(f"Lỗi khi huỷ đăng ký: {e}", code="CANCEL_REGISTRATION_ERROR")


@frappe.whitelist()
def move_club_registration():
    """Nhà trường chuyển một đăng ký sang môn khác (kiểm lại slot + 2 luật)."""
    try:
        if not _can_write(DT_REGISTRATION):
            return forbidden_response("Bạn chỉ có quyền xem đăng ký câu lạc bộ")

        registration_id = _param("registration_id")
        target_offering_id = _param("target_offering_id")
        reason = _param("reason")
        if not registration_id or not target_offering_id:
            return validation_error_response(
                "Thiếu tham số",
                {"target_offering_id": ["Bắt buộc"] if not target_offering_id else []},
            )

        result = move_registration(registration_id, target_offering_id, reason=reason)
        return success_response(data=result, message="Đã chuyển môn cho học sinh")
    except ClubRegError as e:
        return _club_error(e)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club move_club_registration")
        return error_response(f"Lỗi khi chuyển môn: {e}", code="MOVE_REGISTRATION_ERROR")


@frappe.whitelist()
def staff_create_registration():
    """
    Nhà trường đăng ký hộ phụ huynh.

    `enforce_window=False`: được phép làm ngoài khung giờ đăng ký, nhưng luật số
    lượng / một môn mỗi thứ / không trùng môn thì VẪN áp dụng đầy đủ.
    """
    try:
        if not _can_write(DT_REGISTRATION):
            return forbidden_response("Bạn chỉ có quyền xem đăng ký câu lạc bộ")

        data = _data()
        period_id = data.get("period_id")
        student_id = data.get("student_id")
        offering_ids = _as_list(data.get("offering_ids"))

        if not period_id or not student_id or not offering_ids:
            return validation_error_response(
                "Thiếu tham số",
                {
                    "period_id": ["Bắt buộc"] if not period_id else [],
                    "student_id": ["Bắt buộc"] if not student_id else [],
                    "offering_ids": ["Bắt buộc"] if not offering_ids else [],
                },
            )
        if not frappe.db.exists(DT_PERIOD, period_id):
            return not_found_response("Không tìm thấy đợt đăng ký")

        period = frappe.get_doc(DT_PERIOD, period_id)
        result = register_student_to_clubs(
            period,
            student_id,
            offering_ids,
            source="staff",
            enforce_window=False,
        )
        result["my_registrations"] = get_active_registrations(period_id, student_id)

        if not result["saved"] and result["failed"]:
            first = result["failed"][0]
            return error_response(
                first.get("message") or "Không thể đăng ký",
                code=first.get("code"),
                debug_info=result,
            )

        return success_response(data=result, message="Đã đăng ký cho học sinh")
    except ClubRegError as e:
        return _club_error(e)
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club staff_create_registration")
        return error_response(f"Lỗi khi đăng ký hộ: {e}", code="STAFF_REGISTER_ERROR")


@frappe.whitelist()
def recalculate_club_counts():
    """Sửa chữa registered_count nếu có ai đó sửa dữ liệu ngoài luồng."""
    try:
        if not _can_write(DT_OFFERING):
            return forbidden_response("Bạn chỉ có quyền xem câu lạc bộ")

        period_id = _param("period_id")
        if not period_id:
            return validation_error_response("Thiếu period_id", {"period_id": ["Bắt buộc"]})

        recalculate_registered_counts(period_id=period_id)
        return success_response(
            data=_period_stats(period_id), message="Đã tính lại số lượng đăng ký"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Club recalculate_club_counts")
        return error_response(f"Lỗi khi tính lại số lượng: {e}", code="RECALCULATE_ERROR")


@frappe.whitelist()
def search_subjects_for_club():
    """
    Dropdown chọn môn khi khai báo offering.

    CHỈ trả môn có `subject_type = 'club'`. Môn học thuật và môn CLB dùng chung
    bảng `SIS Subject`, nên không lọc thì danh sách này lẫn cả trăm môn Toán/Văn.
    Chiều ngược lại (môn CLB lọt vào dropdown TKB / phân công GV / học bạ) được
    chặn ở `erp/api/erp_sis/subject.py::_subject_type_clause`.

    Tên hiển thị ưu tiên SIS Timetable Subject (song ngữ); môn chưa gắn timetable
    subject vẫn trả về nhưng kèm cờ `has_bilingual_title=0` để form cảnh báo.
    """
    try:
        search = _param("search")
        education_stage_id = _param("education_stage_id")

        conditions = ["s.campus_id = %(campus_id)s"]
        values = {"campus_id": _campus()}

        if frappe.db.has_column("SIS Subject", "subject_type"):
            conditions.append("s.subject_type = 'club'")

        if education_stage_id:
            conditions.append("s.education_stage = %(education_stage_id)s")
            values["education_stage_id"] = education_stage_id
        if search:
            cond, search_values = _named_search(
                ["s.title", "ts.title_vn", "ts.title_en"], search, "sq"
            )
            if cond:
                conditions.append(cond)
                values.update(search_values)

        rows = frappe.db.sql(
            f"""
            SELECT
                s.name AS subject_id,
                s.title AS subject_title,
                s.education_stage,
                s.timetable_subject_id,
                COALESCE(ts.title_vn, s.title) AS title_vn,
                COALESCE(ts.title_en, s.title) AS title_en,
                CASE WHEN ts.name IS NULL THEN 0 ELSE 1 END AS has_bilingual_title,
                s.club_cover_image,
                s.club_short_description_vn,
                s.club_short_description_en,
                COALESCE(es.title_vn, '') AS education_stage_name
            FROM `tabSIS Subject` s
            LEFT JOIN `tabSIS Timetable Subject` ts ON ts.name = s.timetable_subject_id
            LEFT JOIN `tabSIS Education Stage` es ON es.name = s.education_stage
            WHERE {' AND '.join(conditions)}
            ORDER BY COALESCE(ts.title_vn, s.title)
            LIMIT 200
            """,
            values,
            as_dict=True,
        )

        return list_response(rows, "Lấy danh sách môn học thành công")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Club search_subjects_for_club")
        return error_response(f"Lỗi khi tìm môn học: {e}", code="SEARCH_SUBJECTS_ERROR")
