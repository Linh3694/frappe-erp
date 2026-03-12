# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
API Điểm chủ nhiệm (Homeroom Score Record)
- get_homeroom_score_records: Lấy danh sách ghi nhận điểm
- create_homeroom_score_record: Tạo record mới
- delete_homeroom_score_record: Xoá record
- get_homeroom_score_stats: Thống kê điểm theo tháng (tab Thống kê)
"""

import json
import frappe
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import validate_user_campus_access


def _get_body():
    """Lấy dữ liệu từ request body"""
    try:
        if hasattr(frappe, "request") and getattr(frappe.request, "data", None):
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            if body:
                return json.loads(body)
    except Exception:
        pass
    return {}


def _get_class_campus_id(class_id):
    """Lấy campus_id của lớp từ SIS Class"""
    return frappe.db.get_value("SIS Class", class_id, "campus_id")


def _validate_class_campus_access(class_id):
    """Kiểm tra user có quyền truy cập campus của lớp không"""
    campus_id = _get_class_campus_id(class_id)
    if not campus_id:
        return True  # Lớp không có campus -> cho phép
    return validate_user_campus_access(frappe.session.user, campus_id)


@frappe.whitelist(allow_guest=False)
def get_homeroom_score_records(class_id=None, date_from=None, date_to=None, search=None):
    """
    Lấy danh sách ghi nhận điểm chủ nhiệm.

    Params (GET hoặc POST body):
    - class_id: Bắt buộc. ID lớp (SIS Class)
    - date_from: Tùy chọn. Ngày bắt đầu (YYYY-MM-DD)
    - date_to: Tùy chọn. Ngày kết thúc (YYYY-MM-DD)
    - search: Tùy chọn. Tìm kiếm theo tên học sinh

    Returns: List records với student (name, avatar), reason (title_vn, color), value, note, date
    """
    try:
        # Lấy params từ GET hoặc body
        if not class_id and getattr(frappe, "request", None):
            class_id = frappe.request.args.get("class_id")
            date_from = date_from or frappe.request.args.get("date_from")
            date_to = date_to or frappe.request.args.get("date_to")
            search = search or frappe.request.args.get("search")
        if not class_id:
            data = _get_body()
            class_id = class_id or data.get("class_id")
            date_from = date_from or data.get("date_from")
            date_to = date_to or data.get("date_to")
            search = search or data.get("search")

        if not class_id:
            return error_response(
                message="class_id là bắt buộc",
                code="MISSING_PARAMS",
            )

        # Kiểm tra quyền truy cập campus của lớp
        if not _validate_class_campus_access(class_id):
            return error_response(
                message="Bạn không có quyền truy cập lớp này",
                code="CAMPUS_ACCESS_DENIED",
            )

        filters = [["class_id", "=", class_id]]
        if date_from:
            filters.append(["date", ">=", date_from])
        if date_to:
            filters.append(["date", "<=", date_to])

        records = frappe.get_all(
            "SIS Homeroom Score Record",
            filters=filters,
            fields=[
                "name",
                "class_id",
                "student_id",
                "class_log_score_id",
                "value",
                "note",
                "date",
            ],
            order_by="date desc, creation desc",
        )

        # Filter theo search (tên học sinh) nếu có
        if search and records:
            search_lower = (search or "").strip().lower()
            if search_lower:
                student_ids = list(set(r["student_id"] for r in records if r.get("student_id")))
                student_names = {}
                if student_ids:
                    for s in frappe.get_all(
                        "CRM Student",
                        filters={"name": ["in", student_ids]},
                        fields=["name", "student_name"],
                    ):
                        student_names[s["name"]] = (s.get("student_name") or "").lower()
                records = [
                    r
                    for r in records
                    if search_lower in student_names.get(r.get("student_id", ""), "")
                ]

        # Enrich: student (name, avatar), reason (title_vn, color)
        student_ids = list(set(r["student_id"] for r in records if r.get("student_id")))
        score_ids = list(set(r["class_log_score_id"] for r in records if r.get("class_log_score_id")))

        # Batch lấy thông tin học sinh
        student_info = {}
        if student_ids:
            for s in frappe.get_all(
                "CRM Student",
                filters={"name": ["in", student_ids]},
                fields=["name", "student_name"],
            ):
                student_info[s["name"]] = {"name": s.get("student_name") or s["name"], "avatar": None}

            # Lấy avatar từ SIS Photo (năm học hiện tại)
            current_sy = frappe.db.get_value(
                "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
            )
            if student_ids:
                # Dùng tuple cho IN clause (list gây lỗi với PostgreSQL/MySQL)
                photo_rows = frappe.db.sql(
                    """
                    SELECT student_id, photo FROM `tabSIS Photo`
                    WHERE student_id IN %(student_ids)s AND type = 'student' AND status = 'Active'
                    ORDER BY CASE WHEN school_year_id = %(sy)s THEN 0 ELSE 1 END,
                             upload_date DESC, creation DESC
                    """,
                    {"student_ids": tuple(student_ids), "sy": current_sy or ""},
                    as_dict=True,
                )
                seen = set()
                for row in photo_rows:
                    if row["student_id"] not in seen and row.get("photo"):
                        purl = row["photo"]
                        if purl.startswith("/files/"):
                            purl = frappe.utils.get_url(purl)
                        elif not purl.startswith("http"):
                            purl = frappe.utils.get_url("/files/" + purl)
                        student_info[row["student_id"]]["avatar"] = purl
                        seen.add(row["student_id"])

        # Batch lấy thông tin reason (SIS Class Log Score)
        reason_info = {}
        if score_ids:
            for sc in frappe.get_all(
                "SIS Class Log Score",
                filters={"name": ["in", score_ids]},
                fields=["name", "title_vn", "color"],
            ):
                reason_info[sc["name"]] = {
                    "title_vn": sc.get("title_vn") or sc["name"],
                    "color": sc.get("color") or "",
                }

        # Gắn vào từng record
        for r in records:
            r["student"] = student_info.get(r.get("student_id"), {"name": "", "avatar": None})
            r["reason"] = reason_info.get(
                r.get("class_log_score_id"), {"title_vn": "", "color": ""}
            )

        return success_response(
            data={"data": records, "total": len(records)},
            message="Lấy danh sách ghi nhận điểm thành công",
        )

    except Exception as e:
        frappe.log_error(f"get_homeroom_score_records error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy danh sách ghi nhận điểm: {str(e)}",
            code="GET_HOMEROOM_SCORE_RECORDS_ERROR",
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_homeroom_score_record(
    class_id=None,
    student_id=None,
    class_log_score_id=None,
    note=None,
    date=None,
):
    """
    Tạo ghi nhận điểm chủ nhiệm mới.

    Params (POST body):
    - class_id: Bắt buộc
    - student_id: Bắt buộc
    - class_log_score_id: Bắt buộc (SIS Class Log Score, type=homeroom)
    - note: Tùy chọn
    - date: Bắt buộc (YYYY-MM-DD)

    value sẽ được lấy tự động từ SIS Class Log Score.
    """
    try:
        body = _get_body() or {}
        class_id = class_id or body.get("class_id")
        student_id = student_id or body.get("student_id")
        class_log_score_id = class_log_score_id or body.get("class_log_score_id")
        note = note if note is not None else body.get("note")
        date = date or body.get("date")

        if not class_id:
            return error_response(message="class_id là bắt buộc", code="MISSING_PARAMS")
        if not student_id:
            return error_response(message="student_id là bắt buộc", code="MISSING_PARAMS")
        if not class_log_score_id:
            return error_response(
                message="class_log_score_id là bắt buộc",
                code="MISSING_PARAMS",
            )
        if not date:
            return error_response(message="date là bắt buộc", code="MISSING_PARAMS")

        # Kiểm tra quyền truy cập campus của lớp
        if not _validate_class_campus_access(class_id):
            return error_response(
                message="Bạn không có quyền truy cập lớp này",
                code="CAMPUS_ACCESS_DENIED",
            )

        # Validate class_log_score phải có type=homeroom
        score_type = frappe.db.get_value(
            "SIS Class Log Score", class_log_score_id, "type"
        )
        if (score_type or "").lower() != "homeroom":
            return error_response(
                message="class_log_score_id phải có type=homeroom",
                code="INVALID_CLASS_LOG_SCORE",
            )

        doc = frappe.get_doc(
            {
                "doctype": "SIS Homeroom Score Record",
                "class_id": class_id,
                "student_id": student_id,
                "class_log_score_id": class_log_score_id,
                "note": note or "",
                "date": date,
            }
        )
        doc.insert()
        frappe.db.commit()

        return success_response(
            data={"name": doc.name},
            message="Tạo ghi nhận điểm thành công",
        )

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"create_homeroom_score_record error: {str(e)}")
        return error_response(
            message=f"Lỗi khi tạo ghi nhận điểm: {str(e)}",
            code="CREATE_HOMEROOM_SCORE_RECORD_ERROR",
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_homeroom_score_record(name=None):
    """
    Xóa ghi nhận điểm chủ nhiệm.

    Params (POST body):
    - name: Bắt buộc. ID record (SIS-HSR-xxxxx)
    """
    try:
        body = _get_body() or {}
        name = name or body.get("name")

        if not name:
            return error_response(message="name là bắt buộc", code="MISSING_PARAMS")

        doc = frappe.get_doc("SIS Homeroom Score Record", name)
        class_id = doc.class_id

        # Kiểm tra quyền truy cập campus của lớp
        if not _validate_class_campus_access(class_id):
            return error_response(
                message="Bạn không có quyền xóa ghi nhận này",
                code="CAMPUS_ACCESS_DENIED",
            )

        frappe.delete_doc("SIS Homeroom Score Record", name)
        frappe.db.commit()

        return success_response(
            data={"name": name},
            message="Xóa ghi nhận điểm thành công",
        )

    except frappe.DoesNotExistError:
        return error_response(
            message="Không tìm thấy ghi nhận",
            code="RECORD_NOT_FOUND",
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"delete_homeroom_score_record error: {str(e)}")
        return error_response(
            message=f"Lỗi khi xóa ghi nhận điểm: {str(e)}",
            code="DELETE_HOMEROOM_SCORE_RECORD_ERROR",
        )


@frappe.whitelist(allow_guest=False)
def get_homeroom_score_stats(class_id=None, year=None, month=None):
    """
    Thống kê điểm chủ nhiệm theo tháng (cho tab Thống kê).

    Params (GET hoặc POST body):
    - class_id: Bắt buộc
    - year: Bắt buộc (ví dụ: 2025)
    - month: Bắt buộc (1-12)

    Returns:
    {
        "students": [
            {
                "student_id": "...",
                "student_name": "...",
                "avatar": "...",
                "daily_scores": {
                    "2025-03-01": 5.0,
                    "2025-03-02": 3.0,
                    ...
                }
            }
        ],
        "dates": ["2025-03-01", "2025-03-02", ...]  // Các ngày trong tháng có dữ liệu
    }
    """
    try:
        if not class_id and getattr(frappe, "request", None):
            class_id = frappe.request.args.get("class_id")
            year = year or frappe.request.args.get("year")
            month = month or frappe.request.args.get("month")
        if not class_id:
            data = _get_body()
            class_id = class_id or data.get("class_id")
            year = year or data.get("year")
            month = month or data.get("month")

        if not class_id or year is None or year == "" or month is None or month == "":
            return error_response(
                message="class_id, year, month là bắt buộc",
                code="MISSING_PARAMS",
            )

        try:
            year = int(year)
            month = int(month)
        except (ValueError, TypeError):
            return error_response(
                message="year và month phải là số hợp lệ",
                code="INVALID_PARAMS",
            )
        if month < 1 or month > 12:
            return error_response(
                message="month phải từ 1 đến 12",
                code="INVALID_MONTH",
            )

        # Kiểm tra quyền truy cập campus của lớp
        if not _validate_class_campus_access(class_id):
            return error_response(
                message="Bạn không có quyền truy cập lớp này",
                code="CAMPUS_ACCESS_DENIED",
            )

        import calendar

        # Ngày đầu và cuối tháng
        _, last_day = calendar.monthrange(year, month)
        date_from = f"{year}-{month:02d}-01"
        date_to = f"{year}-{month:02d}-{last_day:02d}"

        # Lấy tất cả records trong tháng
        records = frappe.get_all(
            "SIS Homeroom Score Record",
            filters=[
                ["class_id", "=", class_id],
                ["date", ">=", date_from],
                ["date", "<=", date_to],
            ],
            fields=["student_id", "date", "value"],
        )

        # Tính tổng điểm theo (student_id, date)
        from collections import defaultdict

        student_daily = defaultdict(lambda: defaultdict(float))
        for r in records:
            sid = r.get("student_id")
            d = r.get("date")
            v = float(r.get("value") or 0)
            if sid and d:
                student_daily[sid][d] += v

        # Lấy danh sách học sinh trong lớp
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id},
            fields=["student_id"],
        )
        student_ids = [s["student_id"] for s in class_students if s.get("student_id")]

        # Thêm học sinh có điểm nhưng không trong class_students (edge case)
        for sid in student_daily:
            if sid not in student_ids:
                student_ids.append(sid)

        # Lấy tên và avatar học sinh
        student_info = {}
        if student_ids:
            for s in frappe.get_all(
                "CRM Student",
                filters={"name": ["in", student_ids]},
                fields=["name", "student_name"],
            ):
                student_info[s["name"]] = {
                    "student_name": s.get("student_name") or s["name"],
                    "avatar": None,
                }

            current_sy = frappe.db.get_value(
                "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
            )
            # Dùng tuple cho IN clause (list gây lỗi với PostgreSQL/MySQL)
            photo_rows = frappe.db.sql(
                """
                SELECT student_id, photo FROM `tabSIS Photo`
                WHERE student_id IN %(student_ids)s AND type = 'student' AND status = 'Active'
                ORDER BY CASE WHEN school_year_id = %(sy)s THEN 0 ELSE 1 END,
                         upload_date DESC, creation DESC
                """,
                {"student_ids": tuple(student_ids), "sy": current_sy or ""},
                as_dict=True,
            )
            seen = set()
            for row in photo_rows:
                if row["student_id"] not in seen and row.get("photo"):
                    purl = row["photo"]
                    if purl.startswith("/files/"):
                        purl = frappe.utils.get_url(purl)
                    elif not purl.startswith("http"):
                        purl = frappe.utils.get_url("/files/" + purl)
                    student_info[row["student_id"]]["avatar"] = purl
                    seen.add(row["student_id"])

        # Tập hợp tất cả các ngày có dữ liệu
        all_dates = set()
        for sid, daily in student_daily.items():
            all_dates.update(daily.keys())
        dates_sorted = sorted(all_dates)

        # Build response
        students = []
        for sid in student_ids:
            daily_scores = dict(student_daily.get(sid, {}))
            info = student_info.get(sid, {"student_name": sid, "avatar": None})
            students.append(
                {
                    "student_id": sid,
                    "student_name": info["student_name"],
                    "avatar": info["avatar"],
                    "daily_scores": daily_scores,
                }
            )

        return success_response(
            data={
                "students": students,
                "dates": dates_sorted,
                "date_from": date_from,
                "date_to": date_to,
            },
            message="Lấy thống kê điểm thành công",
        )

    except Exception as e:
        frappe.log_error(f"get_homeroom_score_stats error: {str(e)}")
        return error_response(
            message=f"Lỗi khi lấy thống kê điểm: {str(e)}",
            code="GET_HOMEROOM_SCORE_STATS_ERROR",
        )
