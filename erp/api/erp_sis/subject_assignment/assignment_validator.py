# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Assignment Validator

Luật chống chồng lấn cho Subject Assignment (SIS-161).

Nghiệp vụ:
- Cùng (giáo viên, lớp, môn, năm học) ĐƯỢC PHÉP có nhiều đợt phân công, miễn là các
  khoảng ngày áp dụng không chồng lên nhau. Ví dụ một giáo viên dạy Toán lớp 2A1 từ
  01/09–31/12, nghỉ, rồi dạy tiếp 02/03–30/05.
- Chỉ chặn khi hai khoảng thực sự giao nhau.

⚠️ Bản ghi "cả năm" (application_type=full_year) lưu start_date/end_date = NULL. Phải quy
đổi thành [start_date, end_date] của năm học TRƯỚC KHI so sánh — nếu so trực tiếp trên NULL
thì mọi phép so ngày trong SQL đều trả NULL, "cả năm" sẽ không chặn được đợt nào và ngược
lại đợt cũng không chặn được "cả năm".

Đây là nguồn sự thật duy nhất cho luật này. Ba luồng ghi đều phải gọi vào đây, đừng viết
lại luật chống trùng ở chỗ khác:
- assignment_api.create_subject_assignment  (màn Thêm phân công)
- batch_operations.validate_all_assignments (màn chi tiết giáo viên)
- import Excel (SIS-162)
"""

from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import getdate

# Biên khi không xác định được mốc năm học: coi như phủ toàn bộ trục thời gian, tức là
# "cả năm" vẫn chặn được mọi đợt. Thà chặn nhầm còn hơn cho lọt hai phân công đè nhau.
DATE_MIN = date(1900, 1, 1)
DATE_MAX = date(2999, 12, 31)

# Key định danh một chuỗi phân công: (giáo viên, lớp, môn, năm học)
AssignmentKey = Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]


def _to_date(value) -> Optional[date]:
    """Chuẩn hoá mọi kiểu ngày (str / date / datetime / None) về date."""
    if not value:
        return None
    try:
        return getdate(value)
    except Exception:
        return None


def get_school_year_bounds(school_year_id: Optional[str]) -> Tuple[date, date]:
    """
    Mốc đầu/cuối năm học, dùng để quy đổi phân công "cả năm".

    Cache theo request vì import Excel gọi lại rất nhiều lần cho cùng một năm học.
    """
    if not school_year_id:
        return DATE_MIN, DATE_MAX

    # ⚠️ Dùng getattr/setattr, KHÔNG dùng frappe.local.__dict__: frappe.local là werkzeug
    # Local khai __slots__ nên không có __dict__, truy cập sẽ ném AttributeError.
    cache = getattr(frappe.local, "_sis_school_year_bounds", None)
    if cache is None:
        cache = {}
        frappe.local._sis_school_year_bounds = cache
    if school_year_id in cache:
        return cache[school_year_id]

    row = frappe.db.get_value(
        "SIS School Year",
        school_year_id,
        ["start_date", "end_date"],
        as_dict=True,
    )
    bounds = (
        _to_date(row.get("start_date")) if row else None,
        _to_date(row.get("end_date")) if row else None,
    )
    bounds = (bounds[0] or DATE_MIN, bounds[1] or DATE_MAX)

    cache[school_year_id] = bounds
    return bounds


def resolve_effective_range(
    start_date=None,
    end_date=None,
    application_type: Optional[str] = None,
    school_year_id: Optional[str] = None,
) -> Tuple[date, date]:
    """
    Khoảng áp dụng THỰC TẾ của một phân công.

    - full_year, hoặc không có ngày nào  -> trọn năm học
    - có start, không có end             -> từ start đến hết năm học
    - có cả hai                          -> đúng khoảng đó
    """
    sy_start, sy_end = get_school_year_bounds(school_year_id)

    start = _to_date(start_date)
    end = _to_date(end_date)

    if application_type == "full_year":
        # "Cả năm" thì bỏ qua ngày lẻ còn sót lại trong bản ghi cũ.
        return sy_start, sy_end

    return (start or sy_start), (end or sy_end)


def ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Hai khoảng đóng giao nhau khi mỗi khoảng bắt đầu trước khi khoảng kia kết thúc."""
    return a_start <= b_end and a_end >= b_start


def format_range(start: Optional[date], end: Optional[date], school_year_id=None) -> str:
    """Mô tả khoảng áp dụng cho thông báo lỗi tiếng Việt."""
    sy_start, sy_end = get_school_year_bounds(school_year_id)
    if (start is None or start == sy_start) and (end is None or end == sy_end):
        return "cả năm"
    left = start.strftime("%d/%m/%Y") if start else "đầu năm"
    right = end.strftime("%d/%m/%Y") if end else "cuối năm"
    return f"{left} – {right}"


def make_key(
    teacher_id: Optional[str],
    class_id: Optional[str],
    actual_subject_id: Optional[str],
    school_year_id: Optional[str],
) -> AssignmentKey:
    return (teacher_id, class_id, actual_subject_id, school_year_id)


def fetch_existing_ranges(
    keys: Iterable[AssignmentKey],
    campus_id: Optional[str] = None,
) -> Dict[AssignmentKey, List[Dict]]:
    """
    Nạp các phân công đã có trong DB cho một loạt key, gom về MỘT truy vấn.

    Import Excel có thể mang vài trăm dòng; query từng dòng một sẽ thành vài trăm
    round-trip. Ở đây lọc rộng theo tập teacher/class/subject rồi gom lại theo key
    trong Python.
    """
    keys = [k for k in keys if k[0] and k[2]]  # tối thiểu phải có giáo viên và môn
    if not keys:
        return {}

    teacher_ids = sorted({k[0] for k in keys if k[0]})
    class_ids = sorted({k[1] for k in keys if k[1]})
    subject_ids = sorted({k[2] for k in keys if k[2]})
    school_year_ids = sorted({k[3] for k in keys if k[3]})

    filters = {
        "teacher_id": ["in", teacher_ids],
        "actual_subject_id": ["in", subject_ids],
    }
    if class_ids:
        filters["class_id"] = ["in", class_ids]
    if school_year_ids:
        filters["school_year_id"] = ["in", school_year_ids]
    if campus_id:
        filters["campus_id"] = campus_id

    rows = frappe.get_all(
        "SIS Subject Assignment",
        filters=filters,
        fields=[
            "name",
            "teacher_id",
            "class_id",
            "actual_subject_id",
            "school_year_id",
            "campus_id",
            "application_type",
            "start_date",
            "end_date",
        ],
    )

    wanted = set(keys)
    buckets: Dict[AssignmentKey, List[Dict]] = {}
    for row in rows:
        key = make_key(
            row.get("teacher_id"),
            row.get("class_id"),
            row.get("actual_subject_id"),
            row.get("school_year_id"),
        )
        if key not in wanted:
            # Lọc theo "in" nên kết quả rộng hơn tập key thật (tích chéo) — bỏ phần thừa.
            continue
        start, end = resolve_effective_range(
            row.get("start_date"),
            row.get("end_date"),
            row.get("application_type"),
            row.get("school_year_id"),
        )
        row["_start"] = start
        row["_end"] = end
        buckets.setdefault(key, []).append(row)

    return buckets


def validate_no_overlap(
    teacher_id: str,
    class_id: str,
    actual_subject_id: str,
    start_date=None,
    end_date=None,
    assignment_id: Optional[str] = None,
    school_year_id: Optional[str] = None,
    campus_id: Optional[str] = None,
    application_type: Optional[str] = None,
) -> Dict:
    """
    Kiểm tra một phân công có chồng ngày với phân công đã có trong DB không.

    Args:
        assignment_id: bản ghi đang sửa, loại trừ khỏi phép so (tránh tự chồng chính nó)

    Returns:
        {"valid": bool, "overlaps": List[Dict], "message": str}
    """
    key = make_key(teacher_id, class_id, actual_subject_id, school_year_id)
    existing = fetch_existing_ranges([key], campus_id=campus_id).get(key, [])

    start, end = resolve_effective_range(
        start_date, end_date, application_type, school_year_id
    )

    overlaps = [
        row
        for row in existing
        if row["name"] != assignment_id
        and ranges_overlap(start, end, row["_start"], row["_end"])
    ]

    if overlaps:
        detail = ", ".join(
            format_range(row["_start"], row["_end"], school_year_id) for row in overlaps
        )
        return {
            "valid": False,
            "overlaps": overlaps,
            "message": _(
                "Khoảng {0} chồng lên phân công đã có ({1}). "
                "Cùng giáo viên, lớp và môn thì các đợt không được đè lên nhau."
            ).format(format_range(start, end, school_year_id), detail),
        }

    return {
        "valid": True,
        "overlaps": [],
        "message": _("No overlaps detected."),
    }


def find_overlaps_in_batch(rows: List[Dict], school_year_key: str = "school_year_id") -> List[Dict]:
    """
    Tìm các cặp chồng ngày NGAY TRONG một lô sắp ghi (chưa vào DB).

    Mỗi phần tử `rows` cần: teacher_id, class_id, actual_subject_id, school_year_id,
    application_type, start_date, end_date, và `index` để chỉ ra dòng nào lỗi.

    Returns: list các dict {index, other_index, key, range, other_range}
    """
    conflicts = []
    seen: Dict[AssignmentKey, List[Tuple[int, date, date]]] = {}

    for row in rows:
        school_year_id = row.get(school_year_key)
        key = make_key(
            row.get("teacher_id"),
            row.get("class_id"),
            row.get("actual_subject_id"),
            school_year_id,
        )
        start, end = resolve_effective_range(
            row.get("start_date"),
            row.get("end_date"),
            row.get("application_type"),
            school_year_id,
        )

        for other_index, other_start, other_end in seen.get(key, []):
            if ranges_overlap(start, end, other_start, other_end):
                conflicts.append(
                    {
                        "index": row.get("index"),
                        "other_index": other_index,
                        "key": key,
                        "range": format_range(start, end, school_year_id),
                        "other_range": format_range(
                            other_start, other_end, school_year_id
                        ),
                    }
                )

        seen.setdefault(key, []).append((row.get("index"), start, end))

    return conflicts


def validate_assignment_data(assignment_data: Dict) -> Dict:
    """
    Validate assignment data for completeness and correctness.

    Args:
        assignment_data: Dict with assignment fields

    Returns:
        Dict with:
            - valid: bool
            - errors: List[str] of validation errors
    """
    errors = []

    # Required fields
    required_fields = {
        "teacher_id": "Teacher",
        "class_id": "Class",
        "actual_subject_id": "Actual Subject",
        "application_type": "Application Type",
        "campus_id": "Campus",
        "school_year_id": "School Year",
    }

    for field, label in required_fields.items():
        if not assignment_data.get(field):
            errors.append(f"{label} is required")

    # Validate application_type
    if assignment_data.get("application_type") not in ["full_year", "from_date"]:
        errors.append("Application Type must be 'full_year' or 'from_date'")

    # Validate date logic
    start_date = assignment_data.get("start_date")
    end_date = assignment_data.get("end_date")

    if assignment_data.get("application_type") == "from_date":
        if not start_date:
            errors.append("Start Date is required for 'from_date' application type")
        elif end_date and _to_date(end_date) < _to_date(start_date):
            errors.append("End Date must be after Start Date")

    # Validate foreign keys exist
    # teacher_id là docname của SIS Teacher, không phải User.
    if assignment_data.get("teacher_id"):
        if not frappe.db.exists("SIS Teacher", assignment_data["teacher_id"]):
            errors.append(f"Teacher '{assignment_data['teacher_id']}' not found")

    if assignment_data.get("class_id"):
        if not frappe.db.exists("SIS Class", assignment_data["class_id"]):
            errors.append(f"Class '{assignment_data['class_id']}' not found")

    if assignment_data.get("actual_subject_id"):
        if not frappe.db.exists("SIS Actual Subject", assignment_data["actual_subject_id"]):
            errors.append(f"Actual Subject '{assignment_data['actual_subject_id']}' not found")

    if assignment_data.get("school_year_id"):
        if not frappe.db.exists("SIS School Year", assignment_data["school_year_id"]):
            errors.append(f"School Year '{assignment_data['school_year_id']}' not found")

    # school_year_id phải khớp lớp khi có class_id
    if assignment_data.get("school_year_id") and assignment_data.get("class_id"):
        class_year = frappe.db.get_value(
            "SIS Class",
            assignment_data["class_id"],
            "school_year_id",
        )
        if class_year and class_year != assignment_data["school_year_id"]:
            errors.append(
                f"School year '{assignment_data['school_year_id']}' "
                f"does not match class school year '{class_year}'"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def validate_bulk_assignments(assignments: List[Dict]) -> Dict:
    """
    Validate a list of assignments for bulk operations.

    Args:
        assignments: List of assignment dicts

    Returns:
        Dict with:
            - valid: bool
            - validation_results: List[Dict] with validation for each assignment
            - summary: Dict with counts
    """
    results = []
    total_valid = 0
    total_invalid = 0

    for idx, assignment in enumerate(assignments):
        # Data validation
        data_validation = validate_assignment_data(assignment)

        # Overlap validation (if data is valid)
        overlap_validation = {"valid": True, "overlaps": []}
        if data_validation["valid"]:
            overlap_validation = validate_no_overlap(
                teacher_id=assignment["teacher_id"],
                class_id=assignment["class_id"],
                actual_subject_id=assignment["actual_subject_id"],
                start_date=assignment.get("start_date"),
                end_date=assignment.get("end_date"),
                assignment_id=assignment.get("name"),
                school_year_id=assignment.get("school_year_id"),
                campus_id=assignment.get("campus_id"),
                application_type=assignment.get("application_type"),
            )

        # Combine results
        is_valid = data_validation["valid"] and overlap_validation["valid"]

        results.append({
            "index": idx,
            "assignment_id": assignment.get("name"),
            "valid": is_valid,
            "data_validation": data_validation,
            "overlap_validation": overlap_validation
        })

        if is_valid:
            total_valid += 1
        else:
            total_invalid += 1

    return {
        "valid": total_invalid == 0,
        "validation_results": results,
        "summary": {
            "total": len(assignments),
            "valid": total_valid,
            "invalid": total_invalid
        }
    }
