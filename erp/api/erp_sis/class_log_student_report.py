"""
Class Log Student Report API — phục vụ trang "Nhật ký học tập" (mục Báo cáo)
Tổng hợp dữ liệu học sinh theo khoảng thời gian, từ những gì GVBM đã nhập trong sổ đầu bài.

Nguồn dữ liệu:
- SIS Class Log Subject  : mỗi tiết học (ngày, tiết, lớp, điểm tiết, nhận xét chung)
- SIS Class Log Student  : dữ liệu từng HS trong tiết (BTVN, thái độ, học tập, lưu ý, khen, nhận xét)
- SIS Class Log Score    : danh mục lựa chọn (title + value) theo cấp học
- SIS Class Attendance   : điểm danh theo tiết

Endpoint:
- get_report_classes            : danh sách lớp cho bộ lọc
- get_class_log_student_report  : số liệu tổng hợp 1 lớp trong 1 khoảng
                                  (year+month = preset 1 tháng, hoặc date_from+date_to tuỳ ý)

Không giới hạn GVCN: mọi user đăng nhập đều xem được, dữ liệu bó theo campus.
"""

import re
import frappe
from datetime import timedelta
from erp.utils.api_response import success_response, error_response

# Tiểu học không dùng sổ đầu bài theo tiết như THCS/THPT
PRIMARY_STAGE_ID = "EDU-STAGE-00001"

# Map weekday() của Python sang giá trị day_of_week trong SIS Timetable Instance Row
DAY_OF_WEEK_MAP = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}

# Các loại lựa chọn có tính điểm (cộng vào tổng điểm học tập của HS)
SCORED_TYPES = ("homework", "behavior", "participation")

# Trạng thái điểm danh theo tiết
ATTENDANCE_STATUSES = ("present", "late", "absent", "excused")

# Trần độ dài khoảng ngày — đủ phủ trọn một năm học, chỉ là chốt chặn chống truy vấn
# vô hạn do tham số hỏng. Phạm vi thật đã bị năm học bó ở tầng UI.
# Khi kèm nhật ký chi tiết, FE gọi theo từng đoạn ngắn rồi gộp (xem classLogStudentReportExport)
# nên không cần trần riêng cho include_details.
MAX_RANGE_DAYS = 400


def _arg(value, key):
    """Lấy tham số từ kwargs, fallback query string"""
    if value:
        return value
    if getattr(frappe, "request", None):
        return frappe.request.args.get(key)
    return None


def _extract_period_number(period_name):
    """'Tiết 1 + 2' -> 1, 'Tiết 11' -> 11. Không có số -> 999"""
    match = re.search(r"\d+", period_name or "")
    return int(match.group()) if match else 999


def _month_range(year, month):
    """Trả về (ngày đầu tháng, ngày cuối tháng) dạng date"""
    first = frappe.utils.getdate(f"{year:04d}-{month:02d}-01")
    if month == 12:
        next_first = frappe.utils.getdate(f"{year + 1:04d}-01-01")
    else:
        next_first = frappe.utils.getdate(f"{year:04d}-{month + 1:02d}-01")
    return first, next_first - timedelta(days=1)


class _RangeError(Exception):
    """Tham số khoảng thời gian không hợp lệ — bắt ở endpoint để trả error_response"""

    def __init__(self, message, code="INVALID_RANGE"):
        super().__init__(message)
        self.message = message
        self.code = code


def _resolve_range(year, month, date_from, date_to):
    """
    Chốt khoảng thời gian của báo cáo. Ưu tiên date_from/date_to nếu có đủ đôi,
    ngược lại dùng preset year+month. Trả về (date_from, date_to, mode).
    """
    if date_from or date_to:
        if not (date_from and date_to):
            raise _RangeError("Cần đủ cả date_from và date_to", "MISSING_PARAMS")
        start = frappe.utils.getdate(date_from)
        end = frappe.utils.getdate(date_to)
        if start > end:
            raise _RangeError("date_from phải trước hoặc trùng date_to")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise _RangeError(f"Khoảng thời gian tối đa {MAX_RANGE_DAYS} ngày", "RANGE_TOO_LONG")
        return start, end, "range"

    if not year or not month:
        raise _RangeError("Thiếu tham số: year+month hoặc date_from+date_to", "MISSING_PARAMS")
    try:
        year_int = int(year)
        month_int = int(month)
    except (TypeError, ValueError):
        raise _RangeError("year/month không hợp lệ", "INVALID_PARAMS")
    if month_int < 1 or month_int > 12:
        raise _RangeError("month phải từ 1 đến 12", "INVALID_PARAMS")

    start, end = _month_range(year_int, month_int)
    return start, end, "month"


def _resolve_campus(campus_id):
    if campus_id:
        return campus_id
    try:
        from erp.sis.utils.campus_permissions import get_current_user_campus

        return get_current_user_campus()
    except Exception:
        return None


def _current_school_year(campus_id):
    """
    Năm học đang kích hoạt. Ưu tiên theo campus; nếu campus đó chưa gắn năm học nào
    thì lấy năm đang enable bất kỳ — nếu không sẽ ra danh sách lớp rỗng mà không rõ lý do.
    """
    if campus_id:
        by_campus = frappe.db.get_value(
            "SIS School Year", {"is_enable": 1, "campus_id": campus_id}, "name"
        )
        if by_campus:
            return by_campus
    return frappe.db.get_value("SIS School Year", {"is_enable": 1}, "name")


@frappe.whitelist(allow_guest=False)
def get_report_classes(campus_id=None, school_year_id=None):
    """
    Danh sách lớp Regular (bỏ tiểu học) dùng cho bộ lọc của báo cáo.
    Trả về: class_id, class_title, homeroom_teacher_name, education_stage_id, total_students
    """
    try:
        campus_id = _resolve_campus(_arg(campus_id, "campus_id"))
        school_year_id = _arg(school_year_id, "school_year_id") or _current_school_year(campus_id)

        if not school_year_id:
            return success_response(data={"classes": []}, message="Chưa có năm học đang kích hoạt")

        classes = frappe.db.sql(
            """
            SELECT c.name AS class_id, c.title AS class_title,
                   c.homeroom_teacher, eg.education_stage_id
            FROM `tabSIS Class` c
            LEFT JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
            WHERE c.school_year_id = %(sy)s
                AND LOWER(c.class_type) = 'regular'
                AND (eg.education_stage_id IS NULL OR eg.education_stage_id != %(primary)s)
                {campus_filter}
            ORDER BY c.title ASC
            """.format(
                campus_filter="AND c.campus_id = %(campus_id)s" if campus_id else ""
            ),
            {"sy": school_year_id, "campus_id": campus_id, "primary": PRIMARY_STAGE_ID},
            as_dict=True,
        )

        if not classes:
            return success_response(data={"classes": []}, message="Không có lớp")

        class_ids = [c["class_id"] for c in classes]

        # Tên GVCN (batch)
        teacher_ids = [c["homeroom_teacher"] for c in classes if c.get("homeroom_teacher")]
        teacher_names = {}
        if teacher_ids:
            for row in frappe.db.sql(
                """
                SELECT t.name, u.full_name
                FROM `tabSIS Teacher` t
                INNER JOIN `tabUser` u ON t.user_id = u.name
                WHERE t.name IN %(ids)s
                """,
                {"ids": list(set(teacher_ids))},
                as_dict=True,
            ):
                teacher_names[row["name"]] = row["full_name"]

        # Sĩ số (batch)
        student_counts = {}
        for row in frappe.db.sql(
            """
            SELECT class_id, COUNT(*) AS cnt
            FROM `tabSIS Class Student`
            WHERE class_id IN %(cids)s
            GROUP BY class_id
            """,
            {"cids": class_ids},
            as_dict=True,
        ):
            student_counts[row["class_id"]] = row["cnt"]

        # Tên cấp học (batch)
        stage_ids = list({c["education_stage_id"] for c in classes if c.get("education_stage_id")})
        stage_titles = {}
        if stage_ids:
            for row in frappe.db.sql(
                """
                SELECT name, title_vn FROM `tabSIS Education Stage` WHERE name IN %(ids)s
                """,
                {"ids": stage_ids},
                as_dict=True,
            ):
                stage_titles[row["name"]] = row["title_vn"]

        result = [
            {
                "class_id": c["class_id"],
                "class_title": c["class_title"],
                "homeroom_teacher_name": teacher_names.get(c.get("homeroom_teacher")) or "",
                "education_stage_id": c.get("education_stage_id"),
                "education_stage_title": stage_titles.get(c.get("education_stage_id")) or "",
                "total_students": student_counts.get(c["class_id"], 0),
            }
            for c in classes
        ]

        return success_response(
            data={"classes": result, "school_year_id": school_year_id}, message="OK"
        )

    except Exception as e:
        frappe.log_error(f"get_report_classes error: {str(e)}")
        return error_response(message=str(e), code="GET_REPORT_CLASSES_ERROR")


def _fetch_students(class_id):
    """Danh sách HS của lớp chủ nhiệm, sắp theo tên"""
    return frappe.db.sql(
        """
        SELECT cs.student_id, s.student_name, s.student_code
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
        WHERE cs.class_id = %(class_id)s
        ORDER BY s.student_name ASC
        """,
        {"class_id": class_id},
        as_dict=True,
    )


def _fetch_mixed_class_ids(student_ids, class_id):
    """Các lớp ghép (mixed) mà HS của lớp này đang học — GVBM cũng nhập sổ ở đó"""
    if not student_ids:
        return []
    rows = frappe.db.sql(
        """
        SELECT DISTINCT cs.class_id
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id IN %(student_ids)s
            AND cs.class_id != %(class_id)s
            AND LOWER(c.class_type) = 'mixed'
        """,
        {"student_ids": student_ids, "class_id": class_id},
        as_dict=True,
    )
    return [r["class_id"] for r in rows]


def _build_timetable_map(class_ids, date_from, date_to):
    """
    Map (class_id, day_of_week, period_number) -> list bản ghi TKB
    Mỗi bản ghi gồm subject_name, teacher_name, valid_from, valid_to để lọc theo từng ngày.
    """
    if not class_ids:
        return {}

    rows = frappe.db.sql(
        """
        SELECT
            ti.class_id,
            tr.day_of_week,
            tc.period_name,
            tr.valid_from,
            tr.valid_to,
            COALESCE(trt.teacher_id, tr.teacher_1_id) AS teacher_id,
            MAX(COALESCE(ts.title_vn, sub.title)) AS subject_name
        FROM `tabSIS Timetable Instance Row` tr
        INNER JOIN `tabSIS Timetable Instance` ti ON tr.parent = ti.name
        INNER JOIN `tabSIS Timetable Column` tc ON tr.timetable_column_id = tc.name
        LEFT JOIN `tabSIS Subject` sub ON tr.subject_id = sub.name
        LEFT JOIN `tabSIS Timetable Subject` ts ON sub.timetable_subject_id = ts.name
        LEFT JOIN `tabSIS Timetable Instance Row Teacher` trt ON trt.parent = tr.name
            AND trt.idx = (SELECT MIN(idx) FROM `tabSIS Timetable Instance Row Teacher` WHERE parent = tr.name)
        WHERE ti.class_id IN %(cids)s
            AND ti.start_date <= %(date_to)s
            AND (ti.end_date >= %(date_from)s OR ti.end_date IS NULL)
            AND LOWER(tc.period_name) LIKE '%%tiết%%'
        GROUP BY ti.class_id, tr.day_of_week, tc.period_name, tr.valid_from, tr.valid_to,
                 COALESCE(trt.teacher_id, tr.teacher_1_id)
        """,
        {"cids": class_ids, "date_from": date_from, "date_to": date_to},
        as_dict=True,
    )

    teacher_ids = list({r["teacher_id"] for r in rows if r.get("teacher_id")})
    teacher_names = {}
    if teacher_ids:
        for row in frappe.db.sql(
            """
            SELECT t.name, u.full_name
            FROM `tabSIS Teacher` t
            INNER JOIN `tabUser` u ON t.user_id = u.name
            WHERE t.name IN %(ids)s
            """,
            {"ids": teacher_ids},
            as_dict=True,
        ):
            teacher_names[row["name"]] = row["full_name"]

    timetable_map = {}
    for r in rows:
        key = (r["class_id"], r["day_of_week"], _extract_period_number(r["period_name"]))
        timetable_map.setdefault(key, []).append(
            {
                "subject_name": r.get("subject_name") or "",
                "teacher_name": teacher_names.get(r.get("teacher_id")) or "",
                "valid_from": r.get("valid_from"),
                "valid_to": r.get("valid_to"),
            }
        )
    return timetable_map


def _lookup_timetable(timetable_map, class_id, log_date, period_number):
    """Tìm môn/GV của 1 tiết cụ thể, tôn trọng valid_from/valid_to"""
    entries = timetable_map.get((class_id, DAY_OF_WEEK_MAP.get(log_date.weekday()), period_number))
    if not entries:
        return {"subject_name": "", "teacher_name": ""}
    for entry in entries:
        vf = entry.get("valid_from")
        vt = entry.get("valid_to")
        if vf and frappe.utils.getdate(vf) > log_date:
            continue
        if vt and frappe.utils.getdate(vt) < log_date:
            continue
        return entry
    return entries[0]


def _fetch_score_catalog(education_stage_id):
    """Danh mục lựa chọn theo cấp học -> map name -> thông tin, và nhóm theo type"""
    filters = {"is_active": 1}
    if education_stage_id:
        filters["education_stage"] = education_stage_id

    rows = frappe.get_all(
        "SIS Class Log Score",
        filters=filters,
        fields=["name", "type", "title_vn", "title_en", "value", "color", "is_default"],
        order_by="type asc, value desc, title_vn asc",
    )
    return {r["name"]: r for r in rows}, rows


def _ensure_scores_loaded(score_map, needed_names):
    """Bổ sung option nằm ngoài cấp học (dữ liệu cũ / lớp ghép khác cấp)"""
    missing = [n for n in needed_names if n and n not in score_map]
    if not missing:
        return []
    extra = frappe.get_all(
        "SIS Class Log Score",
        filters={"name": ["in", list(set(missing))]},
        fields=["name", "type", "title_vn", "title_en", "value", "color", "is_default"],
    )
    for row in extra:
        score_map[row["name"]] = row
    return extra


def _blank_student_stat(student):
    return {
        "student_id": student["student_id"],
        "student_name": student.get("student_name") or student["student_id"],
        "student_code": student.get("student_code") or "",
        "logged_periods": 0,
        "total_value": 0.0,
        "avg_value": 0.0,
        "top_performance_count": 0,
        "issue_count": 0,
        "comment_count": 0,
        "counts": {},
        "attendance": {s: 0 for s in ATTENDANCE_STATUSES},
        "subjects": {},
    }


def _subject_bucket(stat, subject_name):
    label = subject_name or "—"
    bucket = stat["subjects"].get(label)
    if not bucket:
        bucket = {"subject": label, "logged_periods": 0, "total_value": 0.0, "top": 0, "issues": 0}
        stat["subjects"][label] = bucket
    return bucket


@frappe.whitelist(allow_guest=False)
def get_class_log_student_report(
    class_id=None, year=None, month=None, date_from=None, date_to=None, include_details=None
):
    """
    Tổng hợp dữ liệu sổ đầu bài của 1 lớp trong 1 khoảng thời gian, theo từng học sinh.

    GET params:
    - class_id            : bắt buộc — lớp chủ nhiệm (SIS Class)
    - year + month        : preset 1 tháng (VD 2026, 8)
    - date_from + date_to : khoảng tuỳ ý (YYYY-MM-DD) — ưu tiên hơn year/month nếu có
    - include_details     : '1' để kèm nhật ký chi tiết từng tiết (dùng khi xuất Excel)

    Ghi chú: gộp cả tiết ở lớp ghép (mixed) mà HS của lớp đang học, vì GVBM nhập sổ tại lớp đó.
    """
    try:
        class_id = _arg(class_id, "class_id")
        include_details = str(_arg(include_details, "include_details") or "") in ("1", "true", "yes")

        if not class_id:
            return error_response(message="Thiếu tham số: class_id", code="MISSING_PARAMS")

        try:
            date_from, date_to, range_mode = _resolve_range(
                _arg(year, "year"),
                _arg(month, "month"),
                _arg(date_from, "date_from"),
                _arg(date_to, "date_to"),
            )
        except _RangeError as re_err:
            return error_response(message=re_err.message, code=re_err.code)

        class_doc = frappe.db.get_value(
            "SIS Class",
            class_id,
            ["name", "title", "campus_id", "education_grade", "homeroom_teacher"],
            as_dict=True,
        )
        if not class_doc:
            return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

        # Bó dữ liệu theo campus của user (không chặn theo vai trò GVCN)
        if class_doc.get("campus_id"):
            try:
                from erp.utils.campus_utils import validate_user_campus_access

                if not validate_user_campus_access(frappe.session.user, class_doc["campus_id"]):
                    return error_response(
                        message="Không có quyền xem dữ liệu của campus này", code="CAMPUS_FORBIDDEN"
                    )
            except ImportError:
                pass

        education_stage_id = None
        if class_doc.get("education_grade"):
            education_stage_id = frappe.db.get_value(
                "SIS Education Grade", class_doc["education_grade"], "education_stage_id"
            )

        homeroom_teacher_name = ""
        if class_doc.get("homeroom_teacher"):
            homeroom_teacher_name = (
                frappe.db.sql(
                    """
                SELECT u.full_name FROM `tabSIS Teacher` t
                INNER JOIN `tabUser` u ON t.user_id = u.name
                WHERE t.name = %(tid)s
                """,
                    {"tid": class_doc["homeroom_teacher"]},
                )
                or [[""]]
            )[0][0] or ""

        students = _fetch_students(class_id)
        student_ids = [s["student_id"] for s in students]

        base_payload = {
            "class_info": {
                "class_id": class_doc["name"],
                "class_title": class_doc["title"],
                "homeroom_teacher_name": homeroom_teacher_name,
                "education_stage_id": education_stage_id,
            },
            "range": {
                "mode": range_mode,
                "year": date_from.year,
                "month": date_from.month,
                "date_from": str(date_from),
                "date_to": str(date_to),
            },
            "options": [],
            "summary": {
                "total_students": len(students),
                "logged_periods": 0,
                "total_periods_with_log": 0,
                "student_entries": 0,
                "top_performance_count": 0,
                "issue_count": 0,
                "comment_count": 0,
                "avg_lesson_score": None,
            },
            "students": [],
            "details": [],
        }

        if not student_ids:
            return success_response(data=base_payload, message="Lớp chưa có học sinh")

        all_class_ids = [class_id] + _fetch_mixed_class_ids(student_ids, class_id)

        # 1) Các tiết có sổ trong tháng (bỏ tiết đánh dấu kiểm tra/nghỉ)
        subject_logs = frappe.db.sql(
            """
            SELECT name AS subject_id, class_id, log_date, period, lesson_score, general_comment
            FROM `tabSIS Class Log Subject`
            WHERE class_id IN %(cids)s
                AND log_date BETWEEN %(date_from)s AND %(date_to)s
                AND LOWER(period) LIKE '%%tiết%%'
                AND IFNULL(is_practise_test, 0) = 0
            ORDER BY log_date ASC, period ASC
            """,
            {"cids": all_class_ids, "date_from": date_from, "date_to": date_to},
            as_dict=True,
        )

        stats = {s["student_id"]: _blank_student_stat(s) for s in students}

        # 2) Điểm danh theo tiết trong tháng (GVBM điểm danh từng tiết)
        for row in frappe.db.sql(
            """
            SELECT student_id, status, COUNT(*) AS cnt
            FROM `tabSIS Class Attendance`
            WHERE student_id IN %(sids)s
                AND class_id IN %(cids)s
                AND date BETWEEN %(date_from)s AND %(date_to)s
                AND LOWER(period) LIKE '%%tiết%%'
            GROUP BY student_id, status
            """,
            {
                "sids": student_ids,
                "cids": all_class_ids,
                "date_from": date_from,
                "date_to": date_to,
            },
            as_dict=True,
        ):
            stat = stats.get(row["student_id"])
            if stat and row.get("status") in stat["attendance"]:
                stat["attendance"][row["status"]] = row["cnt"]

        if not subject_logs:
            base_payload["students"] = [_finalize_stat(s) for s in stats.values()]
            base_payload["options"] = _fetch_score_catalog(education_stage_id)[1]
            return success_response(data=base_payload, message="Tháng này chưa có dữ liệu sổ đầu bài")

        subject_by_id = {sl["subject_id"]: sl for sl in subject_logs}

        # 3) Dữ liệu từng HS trong các tiết đó
        student_logs = frappe.db.sql(
            """
            SELECT subject_id, student_id, homework, behavior, participation,
                   issues, is_top_performance, specific_comment
            FROM `tabSIS Class Log Student`
            WHERE subject_id IN %(sub_ids)s
                AND student_id IN %(sids)s
            """,
            {"sub_ids": list(subject_by_id.keys()), "sids": student_ids},
            as_dict=True,
        )

        # 4) Danh mục lựa chọn + bổ sung option ngoài cấp học
        score_map, catalog = _fetch_score_catalog(education_stage_id)
        needed = set()
        for sl in student_logs:
            for field in SCORED_TYPES:
                if sl.get(field):
                    needed.add(sl[field])
            for issue_name in (sl.get("issues") or "").split(","):
                issue_name = issue_name.strip()
                if issue_name:
                    needed.add(issue_name)
        catalog = catalog + _ensure_scores_loaded(score_map, needed)

        # 5) Môn học / GV theo TKB
        timetable_map = _build_timetable_map(all_class_ids, date_from, date_to)

        details = []
        logged_subject_ids = set()
        lesson_scores = []

        for sl in student_logs:
            stat = stats.get(sl["student_id"])
            subject_log = subject_by_id.get(sl["subject_id"])
            if not stat or not subject_log:
                continue

            issue_names = [n.strip() for n in (sl.get("issues") or "").split(",") if n.strip()]
            is_top = 1 if sl.get("is_top_performance") else 0
            comment = (sl.get("specific_comment") or "").strip()
            has_content = bool(
                sl.get("homework")
                or sl.get("behavior")
                or sl.get("participation")
                or issue_names
                or is_top
                or comment
            )
            if not has_content:
                continue

            log_date = frappe.utils.getdate(subject_log["log_date"])
            tt = _lookup_timetable(
                timetable_map,
                subject_log["class_id"],
                log_date,
                _extract_period_number(subject_log["period"]),
            )
            bucket = _subject_bucket(stat, tt["subject_name"])

            stat["logged_periods"] += 1
            bucket["logged_periods"] += 1
            logged_subject_ids.add(sl["subject_id"])

            row_value = 0.0
            for field in SCORED_TYPES:
                score_name = sl.get(field)
                if not score_name:
                    continue
                stat["counts"][score_name] = stat["counts"].get(score_name, 0) + 1
                row_value += float((score_map.get(score_name) or {}).get("value") or 0)

            stat["total_value"] += row_value
            bucket["total_value"] += row_value

            for issue_name in issue_names:
                stat["counts"][issue_name] = stat["counts"].get(issue_name, 0) + 1
            stat["issue_count"] += len(issue_names)
            bucket["issues"] += len(issue_names)

            stat["top_performance_count"] += is_top
            bucket["top"] += is_top

            if comment:
                stat["comment_count"] += 1

            if include_details:
                details.append(
                    {
                        "date": str(subject_log["log_date"]),
                        "period": subject_log["period"],
                        "subject": tt["subject_name"],
                        "teacher_name": tt["teacher_name"],
                        "student_id": stat["student_id"],
                        "student_code": stat["student_code"],
                        "student_name": stat["student_name"],
                        "homework": _score_title(score_map, sl.get("homework")),
                        "behavior": _score_title(score_map, sl.get("behavior")),
                        "participation": _score_title(score_map, sl.get("participation")),
                        "issues": ", ".join(_score_title(score_map, n) for n in issue_names),
                        "is_top_performance": is_top,
                        "comment": comment,
                        "lesson_score": subject_log.get("lesson_score") or "",
                        "value": row_value,
                    }
                )

        for sl in subject_logs:
            raw = sl.get("lesson_score")
            if raw:
                try:
                    lesson_scores.append(float(raw))
                except (TypeError, ValueError):
                    pass

        student_rows = [_finalize_stat(s) for s in stats.values()]
        details.sort(key=lambda d: (d["student_name"], d["date"], d["period"]))

        base_payload["options"] = catalog
        base_payload["students"] = student_rows
        base_payload["details"] = details
        base_payload["summary"].update(
            {
                "logged_periods": len(logged_subject_ids),
                "total_periods_with_log": len(subject_logs),
                "student_entries": sum(s["logged_periods"] for s in student_rows),
                "top_performance_count": sum(s["top_performance_count"] for s in student_rows),
                "issue_count": sum(s["issue_count"] for s in student_rows),
                "comment_count": sum(s["comment_count"] for s in student_rows),
                "avg_lesson_score": (
                    round(sum(lesson_scores) / len(lesson_scores), 2) if lesson_scores else None
                ),
            }
        )

        return success_response(data=base_payload, message="OK")

    except Exception as e:
        frappe.log_error(f"get_class_log_student_report error: {str(e)}")
        return error_response(message=str(e), code="CLASS_LOG_MONTHLY_REPORT_ERROR")


def _score_title(score_map, score_name):
    if not score_name:
        return ""
    row = score_map.get(score_name)
    return (row or {}).get("title_vn") or score_name


def _finalize_stat(stat):
    """Chốt số liệu dẫn xuất + đổi subjects từ dict sang list"""
    logged = stat["logged_periods"]
    stat["total_value"] = round(stat["total_value"], 2)
    stat["avg_value"] = round(stat["total_value"] / logged, 2) if logged else 0.0
    stat["subjects"] = sorted(
        (
            {**bucket, "total_value": round(bucket["total_value"], 2)}
            for bucket in stat["subjects"].values()
        ),
        key=lambda b: b["subject"],
    )
    return stat
