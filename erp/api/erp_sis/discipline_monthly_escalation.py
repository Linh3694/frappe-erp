# Copyright (c) 2026, Wellspring International School and contributors
# Nâng cấp cấp độ vi phạm theo chuỗi L1 trong tháng (timezone site).

from __future__ import annotations

import calendar
from datetime import date, datetime

import frappe


def calendar_month_bounds(ref_date) -> tuple[date, date]:
    """Đầu/cuối tháng dương lịch của ref_date (theo date object, không UTC shift)."""
    d = ref_date
    if isinstance(d, str):
        d = date.fromisoformat(str(d).strip()[:10])
    elif isinstance(d, datetime):
        d = d.date()
    first = d.replace(day=1)
    last_day = calendar.monthrange(d.year, d.month)[1]
    last = d.replace(day=last_day)
    return first, last


def _tier_row_for_level(rows: list, level: str) -> dict | None:
    """Lấy dòng bậc thang theo level (1/2/3) — ưu tiên violation_count nhỏ nhất trong cùng level."""
    level = str(level).strip()
    candidates = [r for r in (rows or []) if str(r.get("level", "")).strip() == level]
    if not candidates:
        return None
    return min(candidates, key=lambda x: int(x.get("violation_count") or 0))


def _points_to_deduction(points) -> str:
    """Map điểm tier sang Select deduction_points (1/5/10/15)."""
    allowed = {"1", "5", "10", "15"}
    s = str(int(points)) if points is not None else "10"
    return s if s in allowed else "10"


def _student_on_record_sql_fragment() -> str:
    """Điều kiện HS xuất hiện trên bản ghi (target_student / Student Entry / Class Entry)."""
    return """
        (
            r.target_student = %(student_id)s
            OR EXISTS (
                SELECT 1 FROM `tabSIS Discipline Record Student Entry` se
                WHERE se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
                    AND se.student_id = %(student_id)s
            )
            OR EXISTS (
                SELECT 1 FROM `tabSIS Discipline Record Class Entry` ce
                INNER JOIN `tabSIS Class Student` cs
                    ON cs.class_id = ce.class_id AND cs.student_id = %(student_id)s
                WHERE ce.parent = r.name AND ce.parenttype = 'SIS Discipline Record'
            )
        )
    """


def count_violation_records_in_month(
    student_id: str,
    violation_id: str,
    record_date,
    *,
    exclude_record_name: str | None = None,
) -> int:
    """Số bản ghi DISTINCT (cùng vi phạm) của HS trong tháng của record_date, tính đến ngày ghi nhận."""
    first, last = calendar_month_bounds(record_date)
    params = {
        "student_id": student_id,
        "violation_id": violation_id,
        "first_day": first,
        "last_day": last,
        "record_date": _as_date(record_date),
    }
    exclude_sql = ""
    if exclude_record_name:
        exclude_sql = " AND r.name != %(exclude_name)s "
        params["exclude_name"] = exclude_record_name

    row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT r.name) AS cnt
        FROM `tabSIS Discipline Record` r
        WHERE r.violation = %(violation_id)s
            AND r.date >= %(first_day)s AND r.date <= %(record_date)s
            AND {_student_on_record_sql_fragment()}
            {exclude_sql}
        """,
        params,
        as_dict=True,
    )
    return int(row[0]["cnt"]) if row else 0


def count_cross_level1_instances_in_month(
    student_id: str,
    record_date,
    *,
    exclude_record_name: str | None = None,
) -> int:
    """
    Đếm lượt vi phạm trong tháng đã áp dụng cấp 1 (applied_level=1 trên Student Entry).
  Dữ liệu cũ không có applied_level: không tính (phase 1).
    """
    first, _last = calendar_month_bounds(record_date)
    params = {
        "student_id": student_id,
        "first_day": first,
        "record_date": _as_date(record_date),
    }
    exclude_sql = ""
    if exclude_record_name:
        exclude_sql = " AND r.name != %(exclude_name)s "
        params["exclude_name"] = exclude_record_name

    row = frappe.db.sql(
        f"""
        SELECT COUNT(*) AS cnt
        FROM `tabSIS Discipline Record` r
        INNER JOIN `tabSIS Discipline Record Student Entry` se
            ON se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
            AND se.student_id = %(student_id)s
            AND IFNULL(se.applied_level, '') = '1'
        WHERE r.date >= %(first_day)s AND r.date <= %(record_date)s
            {exclude_sql}
        """,
        params,
        as_dict=True,
    )
    return int(row[0]["cnt"]) if row else 0


def count_student_violation_instances_in_month(
    student_id: str,
    record_date,
    *,
    exclude_record_name: str | None = None,
) -> int:
    """Tổng lượt HS trên mọi bản ghi trong tháng (mỗi Student Entry = 1 lượt)."""
    first, _last = calendar_month_bounds(record_date)
    params = {
        "student_id": student_id,
        "first_day": first,
        "record_date": _as_date(record_date),
    }
    exclude_sql = ""
    if exclude_record_name:
        exclude_sql = " AND r.name != %(exclude_name)s "
        params["exclude_name"] = exclude_record_name

    row = frappe.db.sql(
        f"""
        SELECT COUNT(*) AS cnt
        FROM `tabSIS Discipline Record` r
        INNER JOIN `tabSIS Discipline Record Student Entry` se
            ON se.parent = r.name AND se.parenttype = 'SIS Discipline Record'
            AND se.student_id = %(student_id)s
        WHERE r.date >= %(first_day)s AND r.date <= %(record_date)s
            {exclude_sql}
        """,
        params,
        as_dict=True,
    )
    legacy = frappe.db.sql(
        f"""
        SELECT COUNT(*) AS cnt
        FROM `tabSIS Discipline Record` r
        WHERE r.date >= %(first_day)s AND r.date <= %(record_date)s
            AND r.target_student = %(student_id)s
            AND NOT EXISTS (
                SELECT 1 FROM `tabSIS Discipline Record Student Entry` se2
                WHERE se2.parent = r.name
            )
            {exclude_sql}
        """,
        params,
        as_dict=True,
    )
    return (int(row[0]["cnt"]) if row else 0) + (int(legacy[0]["cnt"]) if legacy else 0)


def resolve_student_deduction_and_level(
    student_id: str,
    violation_id: str,
    record_date,
    *,
    exclude_record_name: str | None = None,
    client_deduction_points=None,
) -> dict:
    """
    Tính điểm trừ + applied_level cho một HS khi tạo/sửa bản ghi.
    Server ghi đè client nếu rule tháng yêu cầu nâng lên cấp 2.
    """
    from erp.api.erp_sis.discipline import (
        _get_violation_point_tables_for_stats,
        _match_tier_from_point_rows,
        _normalize_deduction_points,
    )

    prior_same = count_violation_records_in_month(
        student_id, violation_id, record_date, exclude_record_name=exclude_record_name
    )
    # Tier theo bảng điểm vi phạm: count sau khi ghi bản ghi này
    student_rows, _ = _get_violation_point_tables_for_stats(violation_id, record_date)
    tier = _match_tier_from_point_rows(student_rows, prior_same + 1)

    prior_l1 = count_cross_level1_instances_in_month(
        student_id, record_date, exclude_record_name=exclude_record_name
    )
    escalated = False
    if str(tier.get("level")) == "1" and prior_l1 >= 3:
        tier2 = _tier_row_for_level(student_rows, "2")
        if tier2:
            tier = {
                "level": "2",
                "points": tier2.get("points", tier.get("points")),
                "level_label": "Cấp độ 2",
            }
            escalated = True
        else:
            frappe.logger().warning(
                f"[discipline_monthly_escalation] Vi phạm {violation_id} không có tier cấp 2 — "
                f"giữ cấp 1 cho HS {student_id}"
            )

    dp = _points_to_deduction(tier.get("points"))
    if client_deduction_points is not None and not escalated:
        dp = _normalize_deduction_points(client_deduction_points)

    return {
        "deduction_points": dp,
        "applied_level": str(tier.get("level", "1")),
        "level_label": tier.get("level_label") or f"Cấp độ {tier.get('level', '1')}",
        "escalated_monthly": escalated,
        "prior_level1_count_month": prior_l1,
        "prior_same_violation_count_month": prior_same,
    }


def _as_date(ref_date) -> date:
    if isinstance(ref_date, date) and not isinstance(ref_date, datetime):
        return ref_date
    if isinstance(ref_date, datetime):
        return ref_date.date()
    return date.fromisoformat(str(ref_date).strip()[:10])


def enrich_records_with_monthly_student_stats(records: list) -> list:
    """Gắn thống kê tháng + cờ highlight cho từng HS trên bản ghi (dashboard/email)."""
    if not records:
        return records

    cache: dict[tuple[str, str], dict] = {}

    for r in records:
        rd = r.get("date")
        if not rd:
            continue
        month_key = str(rd)[:7]
        students = []
        for st in r.get("target_students") or []:
            if st.get("student_id"):
                students.append(st)
        if not students and r.get("target_student"):
            students.append({"student_id": r["target_student"]})

        for st in students:
            sid = st["student_id"]
            ck = (sid, month_key)
            if ck not in cache:
                total = count_student_violation_instances_in_month(sid, rd)
                l1 = count_cross_level1_instances_in_month(sid, rd)
                cache[ck] = {
                    "violations_total_this_month": total,
                    "violations_as_level1_this_month": l1,
                }
            st.update(cache[ck])
            applied = st.get("applied_level") or ""
            l1_count = int(cache[ck].get("violations_as_level1_this_month", 0))
            st["escalation_highlight"] = (
                l1_count >= 4 or str(applied) in ("2", "3")
            )

        r["escalation_highlight"] = any(
            st.get("escalation_highlight") for st in (r.get("target_students") or [])
        )
        if r.get("target_students"):
            counts = [st.get("violations_total_this_month", 0) for st in r["target_students"]]
            r["violations_count_display"] = max(counts) if counts else 0
        elif r.get("target_student"):
            ck = (r["target_student"], month_key)
            if ck not in cache:
                cache[ck] = {
                    "violations_total_this_month": count_student_violation_instances_in_month(
                        r["target_student"], rd
                    ),
                    "violations_as_level1_this_month": count_cross_level1_instances_in_month(
                        r["target_student"], rd
                    ),
                }
            r["violations_count_display"] = cache[ck]["violations_total_this_month"]
            r["escalation_highlight"] = (
                cache[ck]["violations_as_level1_this_month"] >= 4
                or str(r.get("severity_level") or "") in ("2", "3")
            )

    return records
