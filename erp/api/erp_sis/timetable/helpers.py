# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Helper Functions

Shared utility functions for timetable operations.
"""

import frappe
from frappe import _
from datetime import datetime, timedelta
from typing import List, Dict


def period_match_key(value) -> str:
    """
    Khoá so khớp tên tiết giữa Excel và SIS Timetable Column: NGUYÊN VĂN, chỉ bỏ
    khoảng trắng thừa hai đầu.

    Cố tình KHÔNG đoán biến thể ('Tiết 1 + 2' ≠ 'Tiết 1+2', 'tiet 1' ≠ 'Tiết 1',
    1.0 ≠ 'Tiết 1'). Số biến thể là vô hạn, mỗi lần nới thêm một kiểu là mở thêm một
    đường âm thầm bám vào cột của khung giờ khác rồi lệch tiết. Tên không khớp thì
    validator báo lỗi kèm danh sách tiết hợp lệ để người dùng sửa file — sai thì báo
    sai, không tự đoán.

    Chỉ trim hai đầu vì chênh lệch khoảng trắng ở đầu/cuối mắt thường không thấy,
    báo lỗi "'Tiết 1' không khớp 'Tiết 1'" sẽ không ai hiểu.

    Dùng chung cho import_validator và import_executor để hai bên không bao giờ lệch
    chuẩn so khớp (validate pass nhưng executor miss, hoặc ngược lại).
    """
    if value is None:
        return ""
    return str(value).strip()


DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

DAY_LABELS_VN = {
    "mon": "Thứ 2",
    "tue": "Thứ 3",
    "wed": "Thứ 4",
    "thu": "Thứ 5",
    "fri": "Thứ 6",
    "sat": "Thứ 7",
    "sun": "Chủ nhật",
}

_DAY_OF_WEEK_MAP = {
    "2": "mon", "3": "tue", "4": "wed", "5": "thu", "6": "fri", "7": "sat",
    "CN": "sun", "cn": "sun",
    "Thứ 2": "mon", "Thứ 3": "tue", "Thứ 4": "wed", "Thứ 5": "thu",
    "Thứ 6": "fri", "Thứ 7": "sat", "Chủ nhật": "sun",
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}


def normalize_day_of_week(day_str, default: str = "mon") -> str:
    """
    Chuẩn hoá cột "Thứ" của Excel về mã 3 ký tự.

    Pandas hay đọc cột Thứ thành float (2.0) → str = '2.0' không khớp map thẳng nên phải
    hạ về int trước, nếu không cả tuần bị fallback về 'mon'.

    Dùng chung cho import_validator và import_executor để hai bên không lệch chuẩn: validator
    cảnh báo theo thứ này thì executor cũng phải xếp tiết vào đúng thứ đó.
    """
    if day_str is None:
        return default

    raw = str(day_str).strip()
    if raw in _DAY_OF_WEEK_MAP:
        return _DAY_OF_WEEK_MAP[raw]

    # Chuẩn hóa float/int Excel: 2.0 → "2"
    try:
        as_int = str(int(float(raw)))
        if as_int in _DAY_OF_WEEK_MAP:
            return _DAY_OF_WEEK_MAP[as_int]
    except (TypeError, ValueError):
        pass

    return default


def day_label_vn(day_code: str) -> str:
    """Nhãn tiếng Việt của mã thứ, để thông báo cho người dùng đọc được."""
    return DAY_LABELS_VN.get(day_code, day_code)


def format_time_for_html(time_value):
    """
    Format time for HTML time input (HH:MM format)
    
    Args:
        time_value: Can be timedelta, time object, or string
        
    Returns:
        str: Formatted time string in HH:MM format
    """
    if time_value is None:
        return ""
    
    # Handle timedelta (Frappe's default time storage)
    if isinstance(time_value, timedelta):
        total_seconds = int(time_value.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    
    # Handle time object
    if hasattr(time_value, 'hour') and hasattr(time_value, 'minute'):
        return f"{time_value.hour:02d}:{time_value.minute:02d}"
    
    # Handle string - try to parse and format
    if isinstance(time_value, str):
        time_value = time_value.strip()
        # If already in HH:MM format, return as is
        if ':' in time_value and len(time_value.split(':')) == 2:
            parts = time_value.split(':')
            try:
                hours = int(parts[0])
                minutes = int(parts[1].split()[0])  # Handle "HH:MM AM/PM"
                return f"{hours:02d}:{minutes:02d}"
            except:
                pass
    
    # Fallback - return string representation
    return str(time_value)


def _parse_iso_date(date_str: str) -> datetime:
    """Parse ISO date string to datetime object"""
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except Exception:
        frappe.throw(_(f"Invalid date format: {date_str}. Expect YYYY-MM-DD"))


def _add_days(d: datetime, n: int) -> datetime:
    """Add days to datetime"""
    return d + timedelta(days=n)


def _day_of_week_to_index(dow: str) -> int:
    """Convert day of week string to index (0-6)"""
    mapping = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }
    key = (dow or "").strip().lower()
    # Handle accidental storage of full options string where newline may be real or escaped
    # Case 1: actual newline characters
    if "\n" in key:
        key = key.split("\n")[0].strip()
    # Case 2: literal backslash-n sequence stored as text
    elif "\\n" in key:
        key = key.split("\\n")[0].strip()
    if key not in mapping:
        # Try Vietnamese labels
        vi = {
            "thứ 2": 0, "thu 2": 0,
            "thứ 3": 1, "thu 3": 1,
            "thứ 4": 2, "thu 4": 2,
            "thứ 5": 3, "thu 5": 3,
            "thứ 6": 4, "thu 6": 4,
            "thứ 7": 5, "thu 7": 5,
            "cn": 6, "chủ nhật": 6,
        }
        if key in vi:
            return vi[key]
        return -1
    return mapping[key]


def _build_entries(rows: list[dict], week_start: datetime) -> list[dict]:
    """
    Build timetable entries from instance rows.
    
    🎯 Date-specific override rows take precedence over pattern rows.
    - Date-specific rows (date != NULL) override pattern rows for specific dates
    - Pattern rows (date == NULL) fill remaining slots
    """
    return _build_entries_with_date_precedence(rows, week_start)


def _build_entries_legacy(rows: list[dict], week_start: datetime) -> list[dict]:
    """
    Legacy logic: All rows treated as patterns, date calculated from day_of_week.
    This is the SAFE default behavior.
    """
    # Load timetable columns map for period info
    column_ids = list({r.get("timetable_column_id") for r in rows if r.get("timetable_column_id")})
    columns_map = {}
    if column_ids:
        for col in frappe.get_all(
            "SIS Timetable Column",
            fields=["name", "period_priority", "period_name", "start_time", "end_time"],
            filters={"name": ["in", column_ids]},
        ):
            columns_map[col.name] = col

    result: list[dict] = []
    for r in rows:
        idx = _day_of_week_to_index(r.get("day_of_week"))
        if idx < 0:
            continue
        d = _add_days(week_start, idx)
        col = columns_map.get(r.get("timetable_column_id")) or {}
        result.append({
            "name": r.get("name"),  # Include row name for editing
            "date": d.strftime("%Y-%m-%d"),
            "day_of_week": r.get("day_of_week"),
            "timetable_column_id": r.get("timetable_column_id"),
            "period_priority": col.get("period_priority"),
            "subject_title": r.get("subject_title") or r.get("subject_name") or r.get("subject") or "",
            "teacher_names": r.get("teacher_names") or r.get("teacher_display") or "",
            "class_id": r.get("class_id"),
            "room_id": r.get("room_id"),
            "room_name": r.get("room_name"),
            "room_type": r.get("room_type"),
        })
    return result


def _build_entries_with_date_precedence(rows: list[dict], week_start: datetime) -> list[dict]:
    """
    🎯 NEW LOGIC: Date-specific override rows take precedence over pattern rows.
    
    Strategy:
    1. Separate rows into date-specific overrides vs patterns
    2. Build entries from patterns for all days
    3. Override with date-specific rows where they exist
    4. Add non-study periods from SIS Timetable Column
    
    This ensures:
    - Date-range assignments work correctly
    - Pattern rows remain as templates
    - No data duplication
    - Non-study periods (breaks, lunch) are included
    """
    # Load timetable columns map for period info
    column_ids = list({r.get("timetable_column_id") for r in rows if r.get("timetable_column_id")})
    columns_map = {}
    if column_ids:
        for col in frappe.get_all(
            "SIS Timetable Column",
            fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
            filters={"name": ["in", column_ids]},
        ):
            columns_map[col.name] = col
    
    # Get education_stage_id and campus_id from class for non-study periods
    education_stage_id = None
    campus_id = None
    class_ids = list({r.get("class_id") for r in rows if r.get("class_id")})
    frappe.logger().info(f"📊 _build_entries: class_ids from rows = {class_ids}")
    
    if class_ids:
        try:
            class_info = frappe.db.get_value(
                "SIS Class", 
                class_ids[0], 
                ["education_grade", "campus_id"], 
                as_dict=True
            )
            frappe.logger().info(f"📊 _build_entries: class_info = {class_info}")
            
            if class_info:
                campus_id = class_info.get("campus_id")
                # Get education_stage from grade
                if class_info.get("education_grade"):
                    # Field trên SIS Education Grade là education_stage_id. Trước đây hỏi
                    # 'education_stage' → OperationalError bị except nuốt → nhánh lấy
                    # non-study theo schedule active không bao giờ chạy.
                    grade_info = frappe.db.get_value(
                        "SIS Education Grade",
                        class_info["education_grade"],
                        ["education_stage_id"],
                        as_dict=True
                    )
                    frappe.logger().info(f"📊 _build_entries: grade_info = {grade_info}")
                    if grade_info:
                        education_stage_id = grade_info.get("education_stage_id")
                        
            frappe.logger().info(f"📊 _build_entries: education_stage_id={education_stage_id}, campus_id={campus_id}")
        except Exception as e:
            frappe.logger().warning(f"Failed to get education_stage for non-study periods: {str(e)}")
    
    # Load non-study columns for this education stage
    # ⚡ FIX: Chỉ lấy từ 1 nguồn - ưu tiên schedule active, fallback về legacy
    non_study_columns = []
    
    # First try: Use education_stage_id and campus_id from class
    if education_stage_id and campus_id:
        try:
            from frappe.utils import getdate
            
            # ⚡ NEW: Tìm schedule active cho tuần này
            ws_date = week_start.date() if hasattr(week_start, 'date') else week_start
            active_schedule = frappe.db.get_value(
                "SIS Schedule",
                {
                    "education_stage_id": education_stage_id,
                    "campus_id": campus_id,
                    "is_active": 1,
                    "start_date": ["<=", ws_date],
                    "end_date": [">=", ws_date]
                },
                "name"
            )
            
            if active_schedule:
                # Có schedule active → chỉ lấy non-study từ schedule này
                non_study_columns = frappe.get_all(
                    "SIS Timetable Column",
                    fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                    filters={
                        "schedule_id": active_schedule,
                        "period_type": "non-study"
                    },
                    order_by="period_priority asc, start_time asc"
                )
                frappe.logger().info(f"📊 Found {len(non_study_columns)} non-study columns from schedule {active_schedule}")
            else:
                # Không có schedule active → lấy legacy (schedule_id is not set)
                non_study_columns = frappe.get_all(
                    "SIS Timetable Column",
                    fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                    filters={
                        "education_stage_id": education_stage_id,
                        "campus_id": campus_id,
                        "period_type": "non-study",
                        "schedule_id": ["is", "not set"]
                    },
                    order_by="period_priority asc, start_time asc"
                )
                frappe.logger().info(f"📊 Found {len(non_study_columns)} legacy non-study columns")
            
            # Add to columns_map
            for col in non_study_columns:
                columns_map[col.name] = col
        except Exception as e:
            frappe.logger().warning(f"Failed to load non-study columns: {str(e)}")
    
    # Fallback: Get non-study columns from same education_stage/campus as existing study columns
    if not non_study_columns and column_ids:
        try:
            # Get education_stage_id, campus_id, và schedule_id từ study column đầu tiên
            first_col = frappe.db.get_value(
                "SIS Timetable Column",
                column_ids[0],
                ["education_stage_id", "campus_id", "schedule_id"],
                as_dict=True
            )
            if first_col:
                fallback_education_stage = first_col.get("education_stage_id")
                fallback_campus = first_col.get("campus_id")
                fallback_schedule = first_col.get("schedule_id")
                frappe.logger().info(f"📊 Fallback: Using education_stage={fallback_education_stage}, campus={fallback_campus}, schedule={fallback_schedule}")
                
                if fallback_education_stage and fallback_campus:
                    # ⚡ FIX: Match schedule của study columns
                    if fallback_schedule:
                        # Study columns từ schedule → lấy non-study từ cùng schedule
                        non_study_columns = frappe.get_all(
                            "SIS Timetable Column",
                            fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                            filters={
                                "schedule_id": fallback_schedule,
                                "period_type": "non-study"
                            },
                            order_by="period_priority asc, start_time asc"
                        )
                    else:
                        # Study columns là legacy → lấy legacy non-study
                        non_study_columns = frappe.get_all(
                            "SIS Timetable Column",
                            fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                            filters={
                                "education_stage_id": fallback_education_stage,
                                "campus_id": fallback_campus,
                                "period_type": "non-study",
                                "schedule_id": ["is", "not set"]
                            },
                            order_by="period_priority asc, start_time asc"
                        )
                    for col in non_study_columns:
                        columns_map[col.name] = col
                    frappe.logger().info(f"📊 Fallback found {len(non_study_columns)} non-study columns")
        except Exception as e:
            frappe.logger().warning(f"Fallback non-study columns lookup failed: {str(e)}")
    
    # Load teacher_ids for each row from child table
    row_ids = [r.get("name") for r in rows if r.get("name")]
    row_teachers_map = {}  # row_id -> list of teacher_ids
    
    if row_ids:
        try:
            teacher_children = frappe.get_all(
                "SIS Timetable Instance Row Teacher",
                fields=["parent", "teacher_id", "sort_order"],
                filters={"parent": ["in", row_ids]},
                order_by="parent asc, sort_order asc"
            )
            for child in teacher_children:
                row_id = child.parent
                if row_id not in row_teachers_map:
                    row_teachers_map[row_id] = []
                if child.teacher_id:
                    row_teachers_map[row_id].append(child.teacher_id)
        except Exception as e:
            frappe.logger().warning(f"Failed to load teacher_ids: {str(e)}")
    
    # Separate pattern rows vs date-specific override rows
    pattern_rows = []
    override_rows = []
    
    for r in rows:
        if r.get("date"):
            # Date-specific override
            override_rows.append(r)
        else:
            # Pattern row (date is NULL)
            pattern_rows.append(r)
    
    frappe.logger().info(f"📊 _build_entries: {len(pattern_rows)} pattern rows, {len(override_rows)} override rows")
    
    # ⚡ FIX: Lọc pattern row theo ĐÚNG NGÀY nó được render, không phải theo cả tuần.
    # Trước đây chỉ kiểm tra range có overlap với tuần hay không, nên TKB import từ giữa
    # tuần (vd valid_from = thứ 4) vẫn hiện ở thứ 2 và thứ 3 của chính tuần đó.
    #
    # Phải lọc TRƯỚC bước dedup bên dưới: nếu dedup trước, row cũ (còn hiệu lực đầu tuần)
    # bị row mới ghi đè theo valid_from rồi mới bị loại vì chưa tới hạn → ô đầu tuần trống
    # thay vì hiển thị TKB cũ.
    def _to_date(value):
        """Chuẩn hoá Date/Datetime/chuỗi ISO về datetime.date. None nếu rỗng/không parse được."""
        from datetime import date as _date_cls

        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, _date_cls):
            return value
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def get_pattern_render_date(row):
        """Ngày mà pattern row này sẽ hiển thị trong tuần đang xem."""
        idx = _day_of_week_to_index(row.get("day_of_week"))
        if idx < 0:
            return None
        return _add_days(week_start, idx).date()

    def is_pattern_valid_on(row, target_date):
        """Pattern row có hiệu lực đúng vào target_date không (NULL = không giới hạn)."""
        valid_from = _to_date(row.get("valid_from"))
        valid_to = _to_date(row.get("valid_to"))

        # Legacy pattern (không có date range) → luôn hiển thị
        if not valid_from and not valid_to:
            return True

        # day_of_week hỏng → giữ nguyên, vòng build bên dưới sẽ bỏ
        if target_date is None:
            return True

        if valid_from and target_date < valid_from:
            return False
        if valid_to and target_date > valid_to:
            return False

        return True

    # Lọc pattern rows theo ngày hiển thị thực tế của từng row
    filtered_pattern_rows = [
        r for r in pattern_rows if is_pattern_valid_on(r, get_pattern_render_date(r))
    ]
    frappe.logger().info(f"📊 _build_entries: After date filter: {len(filtered_pattern_rows)}/{len(pattern_rows)} pattern rows valid for week {week_start.strftime('%Y-%m-%d')}")
    
    # Ghi nhận các rows bị loại để debug
    excluded_count = len(pattern_rows) - len(filtered_pattern_rows)
    if excluded_count > 0:
        frappe.logger().info(f"  ⚠️ Excluded {excluded_count} pattern rows due to date range filter")
    
    pattern_rows = filtered_pattern_rows
    
    # 🔍 CRITICAL: Deduplicate pattern rows - if multiple rows have same subject/day/column,
    # prefer rows with:
    # 1. valid_from mới nhất (pattern rows mới hơn ưu tiên)
    # 2. Có teachers assigned (nếu valid_from bằng nhau)
    pattern_rows_deduped = {}
    
    def get_valid_from_date(row):
        """Lấy valid_from date để so sánh. NULL = rất cũ (1900-01-01)"""
        from datetime import datetime, date
        vf = row.get("valid_from")
        if vf:
            if isinstance(vf, str):
                return datetime.strptime(vf, "%Y-%m-%d").date()
            elif hasattr(vf, 'date'):
                return vf.date()
            elif isinstance(vf, date):
                return vf
        return date(1900, 1, 1)  # NULL = rất cũ
    
    for r in pattern_rows:
        key = (r.get("subject_id"), r.get("day_of_week"), r.get("timetable_column_id"))
        has_teacher = bool(r.get("teacher_1_id") or r.get("teacher_2_id"))
        current_valid_from = get_valid_from_date(r)
        
        if key not in pattern_rows_deduped:
            # First row with this key - use it
            pattern_rows_deduped[key] = r
        else:
            # Compare with existing row
            existing = pattern_rows_deduped[key]
            existing_has_teacher = bool(existing.get("teacher_1_id") or existing.get("teacher_2_id"))
            existing_valid_from = get_valid_from_date(existing)
            
            # ⚡ Priority 1: valid_from mới nhất (pattern rows mới hơn ưu tiên)
            if current_valid_from > existing_valid_from:
                pattern_rows_deduped[key] = r
                frappe.logger().debug(
                    f"  ⚡ Replaced pattern: {existing.get('name')} (valid_from={existing_valid_from}) "
                    f"→ {r.get('name')} (valid_from={current_valid_from})"
                )
            elif current_valid_from == existing_valid_from:
                # Priority 2: Prefer row with teacher over row without teacher
                if has_teacher and not existing_has_teacher:
                    pattern_rows_deduped[key] = r
                # Priority 3: Keep the one with more recent name (higher number = newer)
                elif has_teacher == existing_has_teacher:
                    if r.get("name", "") > existing.get("name", ""):
                        pattern_rows_deduped[key] = r
    
    pattern_rows = list(pattern_rows_deduped.values())
    frappe.logger().info(f"📊 _build_entries: After deduplication: {len(pattern_rows)} pattern rows")
    
    # Build override map: (date_str, column_id, day_of_week) → row
    # Include day_of_week to handle multiple subjects in same period
    override_map = {}
    for r in override_rows:
        row_date = r.get("date")
        if isinstance(row_date, str):
            date_str = row_date
        elif hasattr(row_date, 'strftime'):
            date_str = row_date.strftime("%Y-%m-%d")
        else:
            continue  # Skip invalid dates
        key = (date_str, r.get("timetable_column_id"), r.get("day_of_week"))
        override_map[key] = r
    
    result: list[dict] = []
    
    # Build from pattern rows first
    for r in pattern_rows:
        idx = _day_of_week_to_index(r.get("day_of_week"))
        if idx < 0:
            continue
        
        d = _add_days(week_start, idx)
        date_str = d.strftime("%Y-%m-%d")
        key = (date_str, r.get("timetable_column_id"), r.get("day_of_week"))
        
        # Only use pattern if no override exists for this date/period/day
        if key not in override_map:
            col = columns_map.get(r.get("timetable_column_id")) or {}
            # Convert timedelta to HH:MM format for start_time and end_time
            start_time = None
            if col.get('start_time'):
                if hasattr(col['start_time'], 'total_seconds'):
                    total_seconds = int(col['start_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    start_time = f"{hours:02d}:{minutes:02d}"
                else:
                    start_time = str(col['start_time'])[:5]  # "HH:MM:SS" -> "HH:MM"
            
            end_time = None
            if col.get('end_time'):
                if hasattr(col['end_time'], 'total_seconds'):
                    total_seconds = int(col['end_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    end_time = f"{hours:02d}:{minutes:02d}"
                else:
                    end_time = str(col['end_time'])[:5]
            
            # Get teacher_ids for this row
            row_teacher_ids = row_teachers_map.get(r.get("name"), [])
            
            result.append({
                "name": r.get("name"),
                "date": date_str,
                "day_of_week": r.get("day_of_week"),
                "timetable_column_id": r.get("timetable_column_id"),
                "period_priority": col.get("period_priority"),
                "period_name": col.get("period_name") or "",
                "start_time": start_time,
                "end_time": end_time,
                "period_type": col.get("period_type") or "study",
                "subject_id": r.get("subject_id") or "",  # ✅ Include subject_id for edit modal
                "subject_title": r.get("subject_title") or r.get("subject_name") or r.get("subject") or "",
                "curriculum_id": r.get("curriculum_id"),  # ✅ Include curriculum_id for border color
                "teacher_names": r.get("teacher_names") or r.get("teacher_display") or "",
                "teacher_ids": row_teacher_ids,  # ✅ Include teacher_ids array
                "class_id": r.get("class_id"),
                "room_id": r.get("room_id"),
                "room_name": r.get("room_name"),
                "room_type": r.get("room_type"),
                "is_pattern": True  # Mark as pattern for debugging
            })
    
    # Add date-specific overrides (these take precedence)
    week_end = _add_days(week_start, 6)
    for r in override_rows:
        row_date = r.get("date")
        if isinstance(row_date, str):
            # KHÔNG import datetime ở đây: import trong thân hàm biến `datetime` thành
            # biến local của cả _build_entries_with_date_precedence, khiến closure
            # _to_date() bên trên đọc phải local chưa gán → NameError và cả tuần trả rỗng.
            row_date = datetime.strptime(row_date, "%Y-%m-%d").date()
        
        # Convert datetime to date for comparison
        if hasattr(row_date, 'date'):
            row_date = row_date.date()
        
        # Convert week_start/week_end to date for comparison
        week_start_date = week_start.date() if hasattr(week_start, 'date') else week_start
        week_end_date = week_end.date() if hasattr(week_end, 'date') else week_end
        
        # Only include overrides within this week
        if week_start_date <= row_date <= week_end_date:
            col = columns_map.get(r.get("timetable_column_id")) or {}
            # Convert timedelta to HH:MM format for start_time and end_time
            start_time = None
            if col.get('start_time'):
                if hasattr(col['start_time'], 'total_seconds'):
                    total_seconds = int(col['start_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    start_time = f"{hours:02d}:{minutes:02d}"
                else:
                    start_time = str(col['start_time'])[:5]
            
            end_time = None
            if col.get('end_time'):
                if hasattr(col['end_time'], 'total_seconds'):
                    total_seconds = int(col['end_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    end_time = f"{hours:02d}:{minutes:02d}"
                else:
                    end_time = str(col['end_time'])[:5]
            
            # Get teacher_ids for this row
            row_teacher_ids = row_teachers_map.get(r.get("name"), [])
            
            result.append({
                "name": r.get("name"),
                "date": row_date.strftime("%Y-%m-%d"),
                "day_of_week": r.get("day_of_week"),
                "timetable_column_id": r.get("timetable_column_id"),
                "period_priority": col.get("period_priority"),
                "period_name": col.get("period_name") or "",
                "start_time": start_time,
                "end_time": end_time,
                "period_type": col.get("period_type") or "study",
                "subject_id": r.get("subject_id") or "",  # ✅ Include subject_id for edit modal
                "subject_title": r.get("subject_title") or r.get("subject_name") or r.get("subject") or "",
                "curriculum_id": r.get("curriculum_id"),  # ✅ Include curriculum_id for border color
                "teacher_names": r.get("teacher_names") or r.get("teacher_display") or "",
                "teacher_ids": row_teacher_ids,  # ✅ Include teacher_ids array
                "class_id": r.get("class_id"),
                "room_id": r.get("room_id"),
                "room_name": r.get("room_name"),
                "room_type": r.get("room_type"),
                "is_override": True  # Mark as override for debugging
            })
    
    # Add non-study periods for each day of the week
    if non_study_columns:
        # Get unique dates from result to know which days have entries
        all_dates = set()
        for entry in result:
            if entry.get("date"):
                all_dates.add(entry["date"])
        
        # If no dates from study periods, generate dates for the week
        if not all_dates:
            for i in range(7):
                d = _add_days(week_start, i)
                all_dates.add(d.strftime("%Y-%m-%d"))
        
        # Get class_id from first row
        class_id = rows[0].get("class_id") if rows else None
        
        # Add non-study entries for each date
        for date_str in all_dates:
            # Parse date to get day of week (dùng `datetime` module-level — xem ghi chú trên)
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            day_index = date_obj.weekday()  # 0=Monday, 6=Sunday
            day_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
            day_of_week = day_names[day_index]
            
            for col in non_study_columns:
                # Convert timedelta to HH:MM format
                start_time = None
                if col.get('start_time'):
                    if hasattr(col['start_time'], 'total_seconds'):
                        total_seconds = int(col['start_time'].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        start_time = f"{hours:02d}:{minutes:02d}"
                    else:
                        start_time = str(col['start_time'])[:5]
                
                end_time = None
                if col.get('end_time'):
                    if hasattr(col['end_time'], 'total_seconds'):
                        total_seconds = int(col['end_time'].total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        end_time = f"{hours:02d}:{minutes:02d}"
                    else:
                        end_time = str(col['end_time'])[:5]
                
                result.append({
                    "name": None,
                    "date": date_str,
                    "day_of_week": day_of_week,
                    "timetable_column_id": col.get("name"),
                    "period_priority": col.get("period_priority"),
                    "period_name": col.get("period_name") or "",
                    "start_time": start_time,
                    "end_time": end_time,
                    "period_type": "non-study",
                    "subject_id": None,
                    "subject_title": "",
                    "teacher_names": "",
                    "teacher_ids": [],
                    "class_id": class_id,
                    "room_id": None,
                    "room_name": "",
                    "room_type": None,
                    "is_non_study": True
                })
        
        frappe.logger().info(f"📊 Added {len(non_study_columns) * len(all_dates)} non-study entries")
    
    frappe.logger().info(f"✅ _build_entries: Built {len(result)} entries ({len([e for e in result if e.get('is_pattern')])} from patterns, {len([e for e in result if e.get('is_override')])} overrides, {len([e for e in result if e.get('is_non_study')])} non-study)")
    
    return result


def _apply_timetable_overrides(entries: list[dict], target_type: str, target_id, 
                              week_start: datetime, week_end: datetime) -> list[dict]:
    """Apply date-specific timetable overrides to entries"""
    try:
        # Convert datetime to date string for database query
        start_date_str = week_start.strftime("%Y-%m-%d")
        end_date_str = week_end.strftime("%Y-%m-%d")
        
        # Handle different target_id types: string for Class, set for Teacher
        if target_type == "Teacher":
            # For teacher, target_id is a set of resolved teacher IDs
            resolved_teacher_ids = list(target_id) if isinstance(target_id, set) else [target_id]
            primary_target_id = resolved_teacher_ids[0] if resolved_teacher_ids else str(target_id)
        else:
            # For class/student, target_id is a simple string
            resolved_teacher_ids = []
            primary_target_id = str(target_id)
        
        # Get all overrides for this target and date range from custom table
        # CROSS-TARGET SUPPORT: For teacher view, also get class overrides where this teacher is assigned
        overrides = []
        
        # Direct overrides for this target (only for Class/Student, not Teacher since teachers don't have direct overrides)
        if target_type != "Teacher":
            direct_overrides = frappe.db.sql("""
                SELECT name, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type
                FROM `tabTimetable_Date_Override`
                WHERE target_type = %s AND target_id = %s AND date BETWEEN %s AND %s
                ORDER BY date ASC, timetable_column_id ASC
            """, (target_type, primary_target_id, start_date_str, end_date_str), as_dict=True)
            overrides.extend(direct_overrides)
        
        # Cross-target support: If querying teacher timetable, also get class overrides where this teacher is assigned
        if target_type == "Teacher":
            # Build dynamic query for multiple teacher IDs
            teacher_conditions = []
            sql_params = [start_date_str, end_date_str]
            
            for teacher_id in resolved_teacher_ids:
                teacher_conditions.append("(teacher_1_id = %s OR teacher_2_id = %s)")
                sql_params.extend([teacher_id, teacher_id])
            
            teacher_where = " OR ".join(teacher_conditions)
            
            sql_query = f"""
                SELECT name, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type, target_id as source_class_id
                FROM `tabTimetable_Date_Override`
                WHERE target_type = 'Class' 
                AND date BETWEEN %s AND %s 
                AND ({teacher_where})
                ORDER BY date ASC, timetable_column_id ASC
            """
            
            cross_overrides = frappe.db.sql(sql_query, sql_params, as_dict=True)
            
            # Mark cross-target overrides 
            for override in cross_overrides:
                override["is_cross_target"] = True
                override["source_target_type"] = "Class"
                
            overrides.extend(cross_overrides)
        
        if not overrides:
            return entries
        
        # ⚡ BULK: Preload subjects and teachers for all overrides (avoid N+1)
        subject_ids = list({o.get("subject_id") for o in overrides if o.get("subject_id")})
        teacher_ids = list({o.get("teacher_1_id") for o in overrides if o.get("teacher_1_id")} | 
                          {o.get("teacher_2_id") for o in overrides if o.get("teacher_2_id")})
        
        # Bulk load subjects
        subject_title_map = {}
        if subject_ids:
            subjects = frappe.get_all("SIS Subject", fields=["name", "title"], filters={"name": ["in", subject_ids]})
            for s in subjects:
                subject_title_map[s.name] = s.title
        
        # Bulk load teachers and their users
        teacher_display_map = {}
        if teacher_ids:
            teachers = frappe.get_all("SIS Teacher", fields=["name", "user_id"], filters={"name": ["in", teacher_ids]})
            user_ids = [t.user_id for t in teachers if t.get("user_id")]
            
            user_display_map = {}
            if user_ids:
                users = frappe.get_all("User", fields=["name", "full_name", "first_name", "last_name"], filters={"name": ["in", user_ids]})
                for u in users:
                    display = u.full_name or f"{u.first_name or ''} {u.last_name or ''}".strip() or u.name
                    user_display_map[u.name] = display
            
            for t in teachers:
                teacher_display_map[t.name] = user_display_map.get(t.user_id, t.name)
            
        # Build override map: {date: {timetable_column_id: override_data}}
        override_map = {}
        for override in overrides:
            # Convert date to string format to match entries
            date = override["date"]
            if hasattr(date, 'strftime'):
                date = date.strftime("%Y-%m-%d")
            else:
                date = str(date)
                
            column_id = override["timetable_column_id"]
            
            if date not in override_map:
                override_map[date] = {}
                
            # Use preloaded data instead of individual queries
            subject_title = subject_title_map.get(override.get("subject_id"), "")
            
            teacher_names = []
            if override.get("teacher_1_id") and override["teacher_1_id"] in teacher_display_map:
                teacher_names.append(teacher_display_map[override["teacher_1_id"]])
            if override.get("teacher_2_id") and override["teacher_2_id"] in teacher_display_map:
                teacher_names.append(teacher_display_map[override["teacher_2_id"]])
                    
            # Determine class_id based on override type
            class_id_for_override = ""
            if override.get("is_cross_target"):
                # Cross-target override (class→teacher): use source class_id
                class_id_for_override = override.get("source_class_id", "")
            elif target_type == "Class":
                # Direct class override: use current target_id
                class_id_for_override = primary_target_id
                
            override_map[date][column_id] = {
                "name": f"override-{override['name']}",  # Mark as override entry
                "subject_title": subject_title,
                "teacher_names": ", ".join(teacher_names),
                "override_type": override.get("override_type", "replace"),
                "override_id": override["name"],
                "class_id": class_id_for_override,
                "is_cross_target": override.get("is_cross_target", False),
                "source_target_type": override.get("source_target_type", target_type),
                "source_class_id": override.get("source_class_id", "")
            }
            
        # Apply overrides to entries
        enhanced_entries = []
        matched_overrides = set()  # Track which overrides were matched to existing entries
        
        for entry in entries:
            entry_date = entry.get("date")
            entry_column = entry.get("timetable_column_id")
            
            # Check if there's an override for this date/column combination
            if (entry_date in override_map and 
                entry_column in override_map[entry_date]):
                
                override_data = override_map[entry_date][entry_column]
                matched_overrides.add(f"{entry_date}|{entry_column}")  # Track matched override
                
                if override_data["override_type"] == "replace":
                    # Replace entry with override data
                    enhanced_entry = {**entry}  # Copy original entry
                    enhanced_entry.update({
                        "name": override_data["name"],
                        "subject_title": override_data["subject_title"],
                        "teacher_names": override_data["teacher_names"],
                        "class_id": override_data.get("class_id", entry.get("class_id", "")),
                        "is_override": True,
                        "override_id": override_data["override_id"]
                    })
                    enhanced_entries.append(enhanced_entry)
                elif override_data["override_type"] == "remove":
                    # Skip this entry (effectively removing it)
                    continue
                else:  # "add" type
                    # Keep original entry and also add override
                    enhanced_entries.append(entry)
                    override_entry = {**entry}
                    override_entry.update({
                        "name": override_data["name"],
                        "subject_title": override_data["subject_title"], 
                        "teacher_names": override_data["teacher_names"],
                        "class_id": override_data.get("class_id", entry.get("class_id", "")),
                        "is_override": True,
                        "override_id": override_data["override_id"]
                    })
                    enhanced_entries.append(override_entry)
            else:
                # No override, keep original entry
                enhanced_entries.append(entry)
        
        # CRITICAL FIX: Create entries for unmatched overrides
        for date_str, date_overrides in override_map.items():
            for column_id, override_data in date_overrides.items():
                override_key = f"{date_str}|{column_id}"
                
                if override_key not in matched_overrides:
                    # This override didn't match any existing entry - create a new entry
                    try:
                        # Parse date to get day_of_week
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        day_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
                        day_of_week = day_names[date_obj.weekday()]
                        
                        # Get period info from timetable column
                        period_info = {}
                        try:
                            column = frappe.get_doc("SIS Timetable Column", column_id)
                            period_info = {
                                "period_priority": column.period_priority,
                                "period_name": column.period_name
                            }
                        except Exception:
                            pass
                        
                        # Create new entry for the override
                        new_entry = {
                            "name": override_data["name"],
                            "date": date_str,
                            "day_of_week": day_of_week,
                            "timetable_column_id": column_id,
                            "period_priority": period_info.get("period_priority"),
                            "subject_title": override_data["subject_title"],
                            "teacher_names": override_data["teacher_names"],
                            "class_id": override_data.get("class_id", ""),
                            "is_override": True,
                            "override_id": override_data["override_id"]
                        }
                        
                        enhanced_entries.append(new_entry)
                        
                    except Exception as create_error:
                        frappe.log_error(f"Error creating override entry: {str(create_error)}")
        
        return enhanced_entries
        
    except Exception as e:
        frappe.log_error(f"Error applying timetable overrides: {str(e)}")
        # Return original entries if override processing fails
        return entries


def _get_request_arg(arg_name: str):
    """Helper to get argument from various request sources"""
    import json
    
    # Try JSON data first
    if frappe.request.data:
        try:
            data = json.loads(frappe.request.data)
            return data.get(arg_name)
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Try form data
    if hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
        return frappe.local.form_dict.get(arg_name)
        
    # Try query params
    if hasattr(frappe.request, 'args') and frappe.request.args:
        return frappe.request.args.get(arg_name)
        
    return None

