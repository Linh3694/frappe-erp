# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

"""
Tiện ích xác định ngày có tiết học theo TKB (weekly_pattern + date_overrides).

Dùng cho scheduler email/push: chỉ gửi khi đủ ngưỡng lớp có tiết trong ngày,
tránh spam cuối tuần / ngày nghỉ; vẫn gửi khi học bù T7/CN nếu TKB có tiết.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import frappe


def _resolve_school_year_id(school_year_id: str | None) -> str | None:
    """Lấy năm học — ưu tiên tham số; không có thì năm đang is_enable."""
    if school_year_id:
        return school_year_id
    rows = frappe.get_all(
        "SIS School Year",
        filters={"is_enable": 1},
        fields=["name"],
        order_by="creation desc",
        limit=1,
    )
    return rows[0].name if rows else None


def is_school_instruction_day(
    date_str: str,
    *,
    campus_id: str | None = None,
    school_year_id: str | None = None,
    min_class_ratio: float = 0.05,
    min_class_count: int = 3,
) -> tuple[bool, dict[str, Any]]:
    """
    True nếu trong ngày ``date_str`` có đủ lớp ``regular`` (theo năm học active)
    có ít nhất một tiết học trên TKB (theo pattern tuần hoặc date_overrides).

    Ngưỡng: số lớp có tiết >= max(min_class_count, ceil(tổng_lớp_regular * min_class_ratio)).

    Args:
        date_str: YYYY-MM-DD
        campus_id: None = tất cả campus; có giá trị = chỉ lớp thuộc campus đó
        school_year_id: None = năm học is_enable=1
        min_class_ratio: tỷ lệ tối thiểu (mặc định 5%)
        min_class_count: số lớp tối thiểu tuyệt đối (mặc định 3)

    Returns:
        (is_instruction_day, meta dict — debug/logging)
    """
    meta: dict[str, Any] = {
        "date": date_str,
        "campus_id": campus_id,
        "school_year_id": None,
        "total_regular_classes": 0,
        "classes_with_lessons": 0,
        "threshold": 0,
        "reason": "",
    }

    sy = _resolve_school_year_id(school_year_id)
    meta["school_year_id"] = sy
    if not sy:
        meta["reason"] = "no_active_school_year"
        return False, meta

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        meta["reason"] = "invalid_date"
        return False, meta

    day_of_week = date_obj.strftime("%A").lower()[:3]

    class_filters: dict[str, Any] = {
        "docstatus": 0,
        "class_type": "regular",
        "school_year_id": sy,
    }
    if campus_id:
        class_filters["campus_id"] = campus_id

    total_regular = frappe.db.count("SIS Class", filters=class_filters)
    meta["total_regular_classes"] = int(total_regular)

    if total_regular <= 0:
        meta["reason"] = "no_regular_classes"
        meta["threshold"] = min_class_count
        return False, meta

    threshold = max(min_class_count, int(math.ceil(total_regular * min_class_ratio)))
    meta["threshold"] = threshold

    # Hai nhánh TKB: weekly_pattern (theo thứ + valid_from/to) và date_overrides (theo ngày)
    # Giữ khớp logic class_log / parent_portal timetable (period chứa "tiết"). Tiếng Việt không phân biệt hoa thường nhờ LOWER.
    class_sql_filters = ["c.docstatus = 0", "c.class_type = 'regular'", "c.school_year_id = %(sy)s"]
    sql_params: dict[str, Any] = {"sy": sy, "date": date_str, "dow": day_of_week}
    if campus_id:
        class_sql_filters.append("c.campus_id = %(campus_id)s")
        sql_params["campus_id"] = campus_id

    class_where = " AND ".join(class_sql_filters)

    weekly_sql = f"""
        SELECT DISTINCT ti.class_id AS class_id
        FROM `tabSIS Class` c
        INNER JOIN `tabSIS Timetable Instance` ti ON ti.class_id = c.name
            AND ti.start_date <= %(date)s AND ti.end_date >= %(date)s
        INNER JOIN `tabSIS Timetable Instance Row` tir ON tir.parent = ti.name
            AND tir.parentfield = 'weekly_pattern'
            AND tir.day_of_week = %(dow)s
            AND tir.subject_id IS NOT NULL
            AND (tir.valid_from IS NULL OR tir.valid_from <= %(date)s)
            AND (tir.valid_to IS NULL OR tir.valid_to >= %(date)s)
        INNER JOIN `tabSIS Timetable Column` tc ON tc.name = tir.timetable_column_id
            AND LOWER(IFNULL(tc.period_name, '')) LIKE %(period_like)s
        WHERE {class_where}
    """

    overrides_sql = f"""
        SELECT DISTINCT ti.class_id AS class_id
        FROM `tabSIS Class` c
        INNER JOIN `tabSIS Timetable Instance` ti ON ti.class_id = c.name
            AND ti.start_date <= %(date)s AND ti.end_date >= %(date)s
        INNER JOIN `tabSIS Timetable Instance Row` tir ON tir.parent = ti.name
            AND tir.parentfield = 'date_overrides'
            AND tir.date = %(date)s
            AND tir.subject_id IS NOT NULL
        INNER JOIN `tabSIS Timetable Column` tc ON tc.name = tir.timetable_column_id
            AND LOWER(IFNULL(tc.period_name, '')) LIKE %(period_like)s
        WHERE {class_where}
    """

    sql_params["period_like"] = "%tiết%"

    merged_sql = f"""
        SELECT COUNT(DISTINCT class_id) AS cnt FROM (
            {weekly_sql}
            UNION
            {overrides_sql}
        ) AS x
    """

    row = frappe.db.sql(merged_sql, sql_params, as_dict=True)
    cnt = int(row[0]["cnt"]) if row else 0
    meta["classes_with_lessons"] = cnt

    if cnt >= threshold:
        meta["reason"] = "instruction_day"
        return True, meta

    meta["reason"] = "below_threshold"
    return False, meta
