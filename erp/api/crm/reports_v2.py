# -*- coding: utf-8 -*-
"""
CRM Reports V2 API — báo cáo Tuyển Sinh (UI-v2), bổ sung cho erp.api.crm.reports.

Các endpoint mới phục vụ 5 tab: Tổng quan (trạng thái theo khối + danh sách công
việc), Hoạt động (sự kiện + khóa học + khảo sát đầu vào), KPI (tái dùng reports.get_breakdown_by_pic),
Nguồn (nguồn 1/2/3), Tái ghi danh (tái dùng erp_sis.re_enrollment).

Tái sử dụng helper từ reports.py: phân quyền theo vai trò (PIC chỉ xem của mình),
khoảng thời gian, bộ lọc chiều + bộ lọc động trên trường CRM Lead.
"""

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import frappe

from erp.utils.api_response import paginated_response, success_response
from erp.api.crm.utils import check_crm_permission, STEP_STATUSES, QLEAD_TEST_STATUSES, CRM_LEAD_PIC_ELIGIBLE_ROLES
from erp.api.crm import reports as r

# Trạng thái HS theo loại hoạt động (đồng bộ doctype)
_EVENT_STUDENT_STATUSES = ["registered", "attended", "not_attended"]
_COURSE_STUDENT_STATUSES = [
    "registered_interest",
    "trial",
    "paid",
    "attended",
    "transferred",
    "refunded",
]
_ENTRANCE_EXAM_STUDENT_STATUSES = [
    "new",
    "schedule_notified",
    "not_attending",
    "exam_taken",
    "completed",
]

# Báo cáo trạng thái theo khối — Draft+Verify gộp "Hồ sơ mới", rồi các bước còn lại
_GRADE_REPORT_STEPS = ["Lead", "QLead", "Enrolled", "Nghi hoc"]
_GRADE_REPORT_ALWAYS_STEPS = frozenset({"Lead"})
_NEW_PROFILE_DRAFT_KEY = "Draft|status|"
_NEW_PROFILE_DRAFT_STATUS = "__draft__"


def _build_new_profile_group(step_statuses: Dict[str, set]) -> Dict[str, Any]:
    """Gộp Draft (cột Dữ liệu) + Verify (Cần kiểm tra, …) trong nhóm Hồ sơ mới."""
    columns: List[Dict[str, str]] = [
        {"key": _NEW_PROFILE_DRAFT_KEY, "status": _NEW_PROFILE_DRAFT_STATUS},
    ]
    verify_present = step_statuses.get("Verify", set())
    verify_sts = _order_status_values(verify_present, STEP_STATUSES.get("Verify", []))
    if not verify_sts:
        verify_sts = list(STEP_STATUSES.get("Verify", []))
    for st in verify_sts:
        columns.append({"key": f"Verify|status|{st}", "status": st})
    return {
        "step": "NewProfile",
        "sections": [{"field": "status", "columns": columns}],
    }


def _status_value_key(step: str, status: str) -> str:
    """Key cột ma trận trạng thái — Draft gộp vào nhóm Hồ sơ mới."""
    if step == "Draft":
        return _NEW_PROFILE_DRAFT_KEY
    return f"{step}|status|{status}"


def _build_status_report_groups(
    step_statuses: Dict[str, set],
    test_vals: set,
    deal_vals: set,
) -> List[Dict[str, Any]]:
    """Dựng cấu trúc nhóm cột dùng chung: Tổng quan (theo khối) & Nguồn."""
    groups: List[Dict[str, Any]] = [_build_new_profile_group(step_statuses)]

    for step in _GRADE_REPORT_STEPS:
        has_data = step in step_statuses
        if not has_data and step not in _GRADE_REPORT_ALWAYS_STEPS:
            continue
        if has_data:
            sts = _order_status_values(step_statuses[step], STEP_STATUSES.get(step, []))
        else:
            sts = list(STEP_STATUSES.get(step, []))
        if not sts:
            continue
        sections: List[Dict[str, Any]] = [
            {
                "field": "status",
                "columns": [{"key": f"{step}|status|{s}", "status": s} for s in sts],
            }
        ]
        if step == "QLead":
            if test_vals:
                tv = _order_status_values(test_vals, QLEAD_TEST_STATUSES)
                sections.append(
                    {
                        "field": "test_status",
                        "columns": [{"key": f"QLead|test_status|{v}", "status": v} for v in tv],
                    }
                )
        groups.append({"step": step, "sections": sections})

    return groups


def _count_enrolled_from_values(values: Dict[str, int]) -> int:
    """Đếm hồ sơ Nhập học từ ma trận values (mọi trạng thái Enrolled)."""
    return sum(v for k, v in values.items() if k.startswith("Enrolled|status|"))


def _order_status_values(present, canonical: List[str]) -> List[str]:
    """Sắp xếp trạng thái: theo thứ tự chuẩn trước, phần dư sort A→Z, rỗng cuối."""
    present_set = set(present)
    ordered = [v for v in canonical if v in present_set]
    extras = sorted(v for v in present_set if v not in canonical and v != "")
    tail = [""] if "" in present_set else []
    return ordered + extras + tail

# Fieldtype meta → kiểu cột filter phía frontend (types/filter.ts)
_FIELDTYPE_TO_FILTER_TYPE = {
    "Data": "string",
    "Small Text": "string",
    "Text": "string",
    "Long Text": "string",
    "Text Editor": "string",
    "Select": "string",
    "Link": "string",
    "Dynamic Link": "string",
    "Read Only": "string",
    "Code": "string",
    "Int": "number",
    "Float": "number",
    "Currency": "number",
    "Percent": "number",
    "Check": "boolean",
    "Date": "date",
    "Datetime": "date",
}


# --------------------------------------------------------------------------- #
# Bộ lọc động — danh mục trường CRM Lead
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_lead_filter_fields():
    """Danh sách trường CRM Lead cho bộ lọc động (UI dựng cột filter từ đây)."""
    check_crm_permission()
    meta = frappe.get_meta("CRM Lead")
    valid_cols = set(meta.get_valid_columns())

    out: List[Dict[str, Any]] = []
    for f in meta.fields:
        ft = f.fieldtype
        if ft not in _FIELDTYPE_TO_FILTER_TYPE:
            continue
        if f.fieldname not in valid_cols:
            continue
        options: List[str] = []
        link_doctype: Optional[str] = None
        if ft == "Select" and f.options:
            options = [o.strip() for o in str(f.options).split("\n") if o.strip()]
        elif ft in ("Link", "Dynamic Link"):
            link_doctype = f.options
        out.append(
            {
                "fieldname": f.fieldname,
                "label": (f.label or f.fieldname),
                "fieldtype": ft,
                "type": _FIELDTYPE_TO_FILTER_TYPE[ft],
                "options": options,
                "link_doctype": link_doctype,
            }
        )
    out.sort(key=lambda x: x["label"].lower())
    return success_response({"fields": out})


# --------------------------------------------------------------------------- #
# Tổng quan — Báo cáo trạng thái theo khối
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_status_by_grade():
    """CRM Lead theo khối × bước × trạng thái.

    Mỗi bước tách theo `status`; riêng QLead bổ sung thêm `test_status`
    (Khảo sát đầu vào) và `deal_status` (Thỏa thuận) làm các nhóm con.
    Tổng theo khối chỉ cộng cột trạng thái chính (status), không cộng
    cột test/deal (vì là chiều bổ sung của cùng tập QLead).
    """
    check_crm_permission()
    args = frappe.request.args or {}
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    status_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(l.`target_grade`), ''), '-') AS grade,
               l.`step` AS step,
               IFNULL(TRIM(l.`status`), '') AS status,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE l.`step` IN ('Lead','QLead','Enrolled','Nghi hoc','Verify','Draft')
          AND {dim_sql}
        GROUP BY grade, l.`step`, status
        """,
        dim_binds,
        as_dict=True,
    )

    def _qlead_sub_rows(field: str):
        return frappe.db.sql(
            f"""
            SELECT IFNULL(NULLIF(TRIM(l.`target_grade`), ''), '-') AS grade,
                   IFNULL(TRIM(l.`{field}`), '') AS val,
                   COUNT(*) AS cnt
            FROM `tabCRM Lead` l
            WHERE l.`step` = 'QLead'
              AND IFNULL(TRIM(l.`{field}`), '') != ''
              AND {dim_sql}
            GROUP BY grade, val
            """,
            dim_binds,
            as_dict=True,
        )

    test_rows = _qlead_sub_rows("test_status")

    # Thu thập trạng thái xuất hiện + giá trị theo khối
    step_statuses: Dict[str, set] = defaultdict(set)
    values_by_grade: Dict[str, Dict[str, int]] = defaultdict(dict)
    total_by_grade: Dict[str, int] = defaultdict(int)

    for row in status_rows:
        step_statuses[row["step"]].add(row["status"])
        key = _status_value_key(row["step"], row["status"])
        values_by_grade[row["grade"]][key] = values_by_grade[row["grade"]].get(key, 0) + int(
            row["cnt"]
        )
        total_by_grade[row["grade"]] += int(row["cnt"])

    test_vals: set = set()
    for row in test_rows:
        test_vals.add(row["val"])
        values_by_grade[row["grade"]][f"QLead|test_status|{row['val']}"] = int(row["cnt"])

    groups = _build_status_report_groups(step_statuses, test_vals, set())

    def _grade_sort_key(g: str):
        try:
            return (0, int(g))
        except (TypeError, ValueError):
            return (1, g)

    out_rows = []
    for g in sorted(values_by_grade.keys(), key=_grade_sort_key):
        out_rows.append(
            {
                "target_grade": g,
                "total": total_by_grade.get(g, 0),
                "values": values_by_grade.get(g, {}),
            }
        )

    return success_response(
        {
            "groups": groups,
            "rows": out_rows,
            "meta": {"pic_restricted_to_self": r._should_restrict_to_own_pic_only()},
        }
    )


# --------------------------------------------------------------------------- #
# Tổng quan — Danh sách công việc (CRM Lead Note, category = Nhiem vu)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_task_list():
    """Công việc (Nhiem vu) trong kỳ — lọc theo lead (chiều + động + PIC)."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = r._resolve_period(args)
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)
    page = int(args.get("page") or 1)
    per_page = int(args.get("per_page") or 20)
    offset = max(0, page - 1) * per_page

    base = f"""
        FROM `tabCRM Lead Note` n
        INNER JOIN `tabCRM Lead` l ON l.`name` = n.`lead`
        WHERE n.`category` = 'Nhiem vu'
          AND DATE(COALESCE(n.`deadline`, n.`creation`)) BETWEEN %(d_from)s AND %(d_to)s
          AND {dim_sql}
    """
    binds = {"d_from": fd, "d_to": td, **dim_binds}

    total_count = int(frappe.db.sql(f"SELECT COUNT(*) {base}", binds)[0][0] or 0)

    summary = frappe.db.sql(
        f"""
        SELECT
            SUM(IF(IFNULL(n.`is_completed`,0)=1,1,0)) AS completed,
            SUM(IF(IFNULL(n.`is_completed`,0)=0,1,0)) AS pending,
            SUM(IF(IFNULL(n.`is_completed`,0)=0
                   AND n.`deadline` IS NOT NULL
                   AND n.`deadline` < NOW(),1,0)) AS overdue
        {base}
        """,
        binds,
        as_dict=True,
    )
    s = summary[0] if summary else {}

    rows = frappe.db.sql(
        f"""
        SELECT n.`name`, n.`title`, n.`assignee`, n.`deadline`,
               n.`is_completed`, n.`communication_method`,
               n.`lead`, n.`campus_id`,
               l.`student_name`, l.`pic`, l.`step`
        {base}
        ORDER BY IFNULL(n.`is_completed`,0) ASC, n.`deadline` ASC
        LIMIT %(lim)s OFFSET %(off)s
        """,
        {**binds, "lim": per_page, "off": offset},
        as_dict=True,
    )

    assignee_emails = [x.get("assignee") or "" for x in rows] + [x.get("pic") or "" for x in rows]
    user_map = r._batch_user_map(assignee_emails)
    out = []
    for x in rows:
        ae = x.get("assignee") or ""
        pe = x.get("pic") or ""
        out.append(
            {
                "name": x.get("name"),
                "title": x.get("title"),
                "lead": x.get("lead"),
                "student_name": x.get("student_name"),
                "campus_id": x.get("campus_id"),
                "communication_method": x.get("communication_method"),
                "deadline": x.get("deadline"),
                "is_completed": int(x.get("is_completed") or 0),
                "assignee": ae,
                "assignee_name": user_map.get(ae, {}).get("full_name") or ae,
                "pic": pe,
                "pic_name": user_map.get(pe, {}).get("full_name") or pe,
            }
        )

    resp = paginated_response(
        data=out,
        current_page=page,
        total_count=total_count,
        per_page=per_page,
        message="OK",
    )
    resp["meta"] = {
        "completed": int(s.get("completed") or 0),
        "pending": int(s.get("pending") or 0),
        "overdue": int(s.get("overdue") or 0),
        "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
    }
    return resp


# --------------------------------------------------------------------------- #
# Hoạt động — điều kiện lọc HS theo lead (PIC + filter động), bỏ qua campus/khối
# (campus/năm lọc ở cấp sự kiện/khóa học)
# --------------------------------------------------------------------------- #
def _activity_student_lead_match(args, student_alias: str, prefix: str) -> Tuple[str, Dict[str, Any]]:
    """Trả về (sql_bool, binds): TRUE nếu lead của HS khớp PIC-restriction + filter động."""
    parts: List[str] = []
    binds: Dict[str, Any] = {}
    pic_eff = r._effective_pic_from_request(args.get("pic"))
    if pic_eff:
        binds[f"{prefix}_apic"] = pic_eff
        parts.append(f"ml.`pic` = %({prefix}_apic)s")
    r._append_dynamic_lead_filters(parts, binds, args, "ml", f"{prefix}_a")
    if not parts:
        # không có ràng buộc lead → đếm tất cả HS
        return "1=1", {}
    cond = " AND ".join(parts)
    expr = (
        f"EXISTS (SELECT 1 FROM `tabCRM Lead` ml "
        f"WHERE ml.`name` = {student_alias}.`crm_lead_id` AND {cond})"
    )
    return expr, binds


def _activity_report(args, *, doctype: str, student_doctype: str, student_fk: str,
                     name_field: str, statuses: List[str],
                     date_field: str = "event_date",
                     date_coalesce: bool = False,
                     skip_campus_filter: bool = False,
                     skip_date_filter: bool = False) -> Dict[str, Any]:
    fd, td, _, _ = r._resolve_period(args)
    match_sql, match_binds = _activity_student_lead_match(args, "es", "act")

    # Kỳ khảo sát có thể chưa gán ngày thi — fallback creation để không bị loại khỏi báo cáo
    date_expr = (
        f"COALESCE(e.`{date_field}`, DATE(e.`creation`))"
        if date_coalesce
        else f"e.`{date_field}`"
    )
    ev_where: List[str] = []
    binds: Dict[str, Any] = {**match_binds}
    if not skip_date_filter:
        ev_where.append(f"DATE({date_expr}) BETWEEN %(d_from)s AND %(d_to)s")
        binds["d_from"] = fd
        binds["d_to"] = td

    campus_id = (args.get("campus_id") or "").strip()
    if campus_id and not skip_campus_filter:
        binds["e_campus"] = campus_id
        ev_where.append("e.`campus_id` = %(e_campus)s")
    tay = (args.get("target_academic_year") or "").strip()
    if tay:
        binds["e_year"] = tay
        ev_where.append("e.`school_year_id` = %(e_year)s")

    where_clause = " AND ".join(ev_where) if ev_where else "1=1"
    status_cols = ",\n".join(
        f"SUM(CASE WHEN es.`status` = '{st}' AND {match_sql} THEN 1 ELSE 0 END) AS `st_{st}`"
        for st in statuses
    )

    rows = frappe.db.sql(
        f"""
        SELECT e.`name`, e.`{name_field}` AS title, {date_expr} AS event_date,
               e.`campus_id`, e.`school_year_id`, e.`is_active`, e.`student_count`,
               SUM(CASE WHEN es.`name` IS NOT NULL AND {match_sql} THEN 1 ELSE 0 END) AS matched_total,
               {status_cols}
        FROM `tab{doctype}` e
        LEFT JOIN `tab{student_doctype}` es ON es.`{student_fk}` = e.`name`
        WHERE {where_clause}
        GROUP BY e.`name`
        ORDER BY {date_expr} DESC, e.`modified` DESC
        LIMIT 500
        """,
        binds,
        as_dict=True,
    )

    campus_ids = list({x["campus_id"] for x in rows if x.get("campus_id")})
    campus_titles: Dict[str, str] = {}
    if campus_ids:
        for c in frappe.get_all(
            "SIS Campus", filters={"name": ["in", campus_ids]},
            fields=["name", "title_vn", "short_title"],
        ):
            campus_titles[c["name"]] = c.get("title_vn") or c.get("short_title") or c["name"]

    out_rows = []
    totals = {f"st_{st}": 0 for st in statuses}
    total_matched = 0
    for x in rows:
        by_status = {st: int(x.get(f"st_{st}") or 0) for st in statuses}
        matched = int(x.get("matched_total") or 0)
        total_matched += matched
        for st in statuses:
            totals[f"st_{st}"] += by_status[st]
        out_rows.append(
            {
                "name": x["name"],
                "title": x.get("title"),
                "event_date": x.get("event_date"),
                "campus_id": x.get("campus_id"),
                "campus_title": campus_titles.get(x.get("campus_id"), x.get("campus_id")),
                "school_year_id": x.get("school_year_id"),
                "is_active": int(x.get("is_active") or 0),
                "student_count": int(x.get("student_count") or 0),
                "matched_total": matched,
                "by_status": by_status,
            }
        )

    return {
        "statuses": statuses,
        "rows": out_rows,
        "totals": {
            "count": len(out_rows),
            "matched_total": total_matched,
            "by_status": {st: totals[f"st_{st}"] for st in statuses},
        },
        "meta": {
            "period": {"from": str(fd), "to": str(td)},
            "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
        },
    }


@frappe.whitelist()
def get_events_report():
    """Báo cáo Sự kiện — CRM Admission Event + Event Student."""
    check_crm_permission()
    args = frappe.request.args or {}
    return success_response(
        _activity_report(
            args,
            doctype="CRM Admission Event",
            student_doctype="CRM Admission Event Student",
            student_fk="event_id",
            name_field="event_name",
            statuses=_EVENT_STUDENT_STATUSES,
        )
    )


@frappe.whitelist()
def get_courses_report():
    """Báo cáo hoạt động (Khóa học) — CRM Admission Course + Course Student."""
    check_crm_permission()
    args = frappe.request.args or {}
    return success_response(
        _activity_report(
            args,
            doctype="CRM Admission Course",
            student_doctype="CRM Admission Course Student",
            student_fk="course_id",
            name_field="course_name",
            statuses=_COURSE_STUDENT_STATUSES,
        )
    )


@frappe.whitelist()
def get_entrance_exams_report():
    """Báo cáo Khảo sát đầu vào — CRM Admission Entrance Exam + Entrance Exam Student."""
    check_crm_permission()
    args = frappe.request.args or {}
    return success_response(
        _activity_report(
            args,
            doctype="CRM Admission Entrance Exam",
            student_doctype="CRM Admission Entrance Exam Student",
            student_fk="entrance_exam_id",
            name_field="exam_name",
            date_field="exam_date",
            date_coalesce=True,
            # Đồng bộ module Khảo sát đầu vào — liệt kê tất cả kỳ, không lọc theo kỳ báo cáo
            skip_date_filter=True,
            skip_campus_filter=True,
            statuses=_ENTRANCE_EXAM_STUDENT_STATUSES,
        )
    )


# --------------------------------------------------------------------------- #
# Hoạt động V2 — dashboard KSNLTD / Sự kiện / Khóa học (chart + drill-down)
# --------------------------------------------------------------------------- #
_DEPOSIT_PAID_LEAD_STATUSES = frozenset({"Deposit", "Paid", "Booked"})
_TUITION_PAID_LEAD_STATUSES = frozenset({"Paid", "Booked"})

# Lead từ chối — dùng cho segment "Đạt nhưng hủy" (đạt kết quả nhưng lead bị từ chối)
_DENIED_LEAD_STATUSES = frozenset({"Lost", "Tu choi"})
# Nhóm "đã đóng phí tham gia khảo sát" cho chart kết quả theo khối (Đặt cọc / Nộp phí)
_EXAM_PAID_LEAD_STATUSES = frozenset({"Dat coc", "Dong phi"})


def _exam_result_segment(exam_result: Optional[str], lead_status: Optional[str]) -> Optional[str]:
    """Gộp exam_result × lead_status thành 1 segment biểu đồ kết quả theo khối.

    - fail            → 'fail'            (Trượt)
    - pass/cond + từ chối → 'pass_cancelled' (Đạt nhưng hủy)
    - pass            → 'pass'            (Đạt)
    - conditional_pass → 'conditional_pass' (Đạt có điều kiện)
    - retake          → 'retake'          (Thi lại — không hiển thị mặc định)
    - '' (chưa có kết quả) → None (bỏ qua)
    """
    res = (exam_result or "").strip()
    if res == "fail":
        return "fail"
    if res in ("pass", "conditional_pass"):
        if (lead_status or "").strip() in _DENIED_LEAD_STATUSES:
            return "pass_cancelled"
        return res
    if res == "retake":
        return "retake"
    return None


def _activity_granularity(args) -> str:
    gran = (args.get("activity_granularity") or "month").strip().lower()
    return gran if gran in ("day", "month", "year") else "month"


def _activity_dashboard_meta(args, fd, td) -> Dict[str, Any]:
    return {
        "period": {"from": str(fd), "to": str(td)},
        "granularity": _activity_granularity(args),
        "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
    }


def _grade_sort_key(g: str):
    try:
        return (0, int(g))
    except (TypeError, ValueError):
        return (1, g or "")


def _pic_names_map(pic_ids: List[str]) -> Dict[str, str]:
    ids = [p for p in pic_ids if p]
    if not ids:
        return {}
    out: Dict[str, str] = {}
    for u in frappe.get_all("User", filters={"name": ["in", ids]}, fields=["name", "full_name"]):
        out[u["name"]] = u.get("full_name") or u["name"]
    return out


def _activity_parent_where(args, date_expr: str, *, skip_campus: bool = False) -> Tuple[Any, Any, str, Dict[str, Any], str]:
    """Chuẩn bị kỳ + điều kiện lọc parent hoạt động."""
    fd, td, _, _ = r._resolve_period(args)
    match_sql, match_binds = _activity_student_lead_match(args, "es", "act")
    binds: Dict[str, Any] = {**match_binds, "d_from": fd, "d_to": td}
    parts = [f"DATE({date_expr}) BETWEEN %(d_from)s AND %(d_to)s"]
    campus_id = (args.get("campus_id") or "").strip()
    if campus_id and not skip_campus:
        binds["e_campus"] = campus_id
        parts.append("e.`campus_id` = %(e_campus)s")
    return fd, td, match_sql, binds, " AND ".join(parts)


def _is_lead_deposit_paid(status: Optional[str]) -> bool:
    return (status or "").strip() in _DEPOSIT_PAID_LEAD_STATUSES


def _is_lead_tuition_paid(status: Optional[str]) -> bool:
    return (status or "").strip() in _TUITION_PAID_LEAD_STATUSES


def _course_lead_bucket(course_status: str, lead_status: str, lead_step: str) -> str:
    """Phân loại HS khóa học: tiềm năng / paid / từ chối."""
    cs = (course_status or "").strip()
    ls = (lead_status or "").strip()
    if cs == "refunded" or ls == "Lost" or ls == "Tu choi":
        return "tu_choi"
    if cs == "paid" or _is_lead_tuition_paid(ls):
        return "paid"
    return "tiem_nang"


def _week_bounds_from_date(d) -> Tuple[str, str]:
    """Tuần ISO (bắt đầu thứ 2) chứa ngày d."""
    from datetime import timedelta

    if not d:
        return "", ""
    dt = frappe.utils.getdate(d)
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return str(monday), str(sunday)


@frappe.whitelist()
def get_entrance_exam_activity_dashboard():
    """Dashboard Khảo sát năng lực toàn diện — theo khối, chuyển đổi paid→enrolled, theo tuần/ca."""
    check_crm_permission()
    args = frappe.request.args or {}
    date_expr = "COALESCE(e.`exam_date`, DATE(e.`creation`))"
    fd, td, match_sql, binds, parent_where = _activity_parent_where(args, date_expr, skip_campus=False)

    exam_id = (args.get("exam_id") or "").strip()
    week_start = (args.get("week_start") or "").strip()

    rows = frappe.db.sql(
        f"""
        SELECT es.`name` AS student_row_id,
               es.`status` AS exam_status,
               IFNULL(es.`exam_result`, '') AS exam_result,
               IFNULL(es.`ksdv_fee_paid`, 0) AS ksdv_fee_paid,
               es.`crm_lead_id`,
               e.`name` AS exam_id,
               e.`exam_name`,
               {date_expr} AS exam_date,
               IFNULL(e.`exam_time`, '') AS exam_time,
               l.`student_name`,
               l.`student_dob`,
               IFNULL(l.`status`, '') AS lead_status,
               IFNULL(l.`step`, '') AS lead_step,
               TRIM(IFNULL(l.`target_grade`, '')) AS target_grade,
               IFNULL(l.`pic`, '') AS pic
        FROM `tabCRM Admission Entrance Exam Student` es
        INNER JOIN `tabCRM Admission Entrance Exam` e ON e.`name` = es.`entrance_exam_id`
        INNER JOIN `tabCRM Lead` l ON l.`name` = es.`crm_lead_id`
        WHERE {parent_where} AND {match_sql}
        """,
        binds,
        as_dict=True,
    )

    by_grade_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"by_status": defaultdict(int), "by_result": defaultdict(int), "result_segments": defaultdict(int), "result_segments_paid": defaultdict(int), "total": 0, "ksdv_paid": 0, "tested": 0})
    conv_map: Dict[str, Dict[str, int]] = defaultdict(lambda: {"paid": 0, "enrolled": 0})
    week_exams: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for row in rows:
        grade = row.get("target_grade") or "(Chưa có khối)"
        st = row.get("exam_status") or ""
        ls = (row.get("lead_status") or "").strip()
        by_grade_map[grade]["total"] += 1
        by_grade_map[grade]["by_status"][st] += 1
        by_grade_map[grade]["by_result"][row.get("exam_result") or ""] += 1
        seg = _exam_result_segment(row.get("exam_result"), ls)
        if seg:
            by_grade_map[grade]["result_segments"][seg] += 1
            if ls in _EXAM_PAID_LEAD_STATUSES:
                by_grade_map[grade]["result_segments_paid"][seg] += 1
        if int(row.get("ksdv_fee_paid") or 0):
            by_grade_map[grade]["ksdv_paid"] += 1
            conv_map[grade]["paid"] += 1
        if st in ("exam_taken", "completed"):
            by_grade_map[grade]["tested"] += 1
        if (row.get("lead_step") or "") == "Enrolled" and int(row.get("ksdv_fee_paid") or 0):
            conv_map[grade]["enrolled"] += 1

        ex_date = row.get("exam_date")
        if ex_date:
            ws, we = _week_bounds_from_date(ex_date)
            wk_key = ws
            ex_key = row.get("exam_id")
            if ex_key not in week_exams[wk_key]:
                week_exams[wk_key][ex_key] = {
                    "exam_id": ex_key,
                    "exam_name": row.get("exam_name"),
                    "exam_date": str(ex_date),
                    "exam_time": row.get("exam_time") or "",
                    "registered": 0,
                    "tested": 0,
                    "dropped": 0,
                }
            slot = week_exams[wk_key][ex_key]
            if st == "not_attending":
                slot["dropped"] += 1
            elif st in ("exam_taken", "completed"):
                slot["tested"] += 1
            else:
                slot["registered"] += 1

    by_grade = []
    for g in sorted(by_grade_map.keys(), key=_grade_sort_key):
        m = by_grade_map[g]
        by_grade.append(
            {
                "target_grade": g,
                "total": m["total"],
                "by_status": dict(m["by_status"]),
                "by_result": dict(m["by_result"]),
                "result_segments": dict(m["result_segments"]),
                "result_segments_paid": dict(m["result_segments_paid"]),
                "ksdv_paid": m["ksdv_paid"],
                "tested": m["tested"],
            }
        )

    by_grade_conversion = []
    for g in sorted(conv_map.keys(), key=_grade_sort_key):
        paid = conv_map[g]["paid"]
        enrolled = conv_map[g]["enrolled"]
        by_grade_conversion.append(
            {
                "target_grade": g,
                "paid": paid,
                "enrolled": enrolled,
                "conversion_pct": round(100.0 * enrolled / max(1, paid), 2),
            }
        )

    by_week = []
    for ws in sorted(week_exams.keys()):
        we = str(frappe.utils.add_days(ws, 6))
        exams_list = sorted(week_exams[ws].values(), key=lambda x: (x.get("exam_date") or "", x.get("exam_time") or ""))
        by_week.append({"week_start": ws, "week_end": we, "exams": exams_list})

    students: List[Dict[str, Any]] = []
    pic_map = _pic_names_map([r.get("pic") for r in rows if r.get("pic")])
    for row in rows:
        if exam_id and row.get("exam_id") != exam_id:
            continue
        if week_start:
            ws, _ = _week_bounds_from_date(row.get("exam_date"))
            if ws != week_start:
                continue
        pic = row.get("pic") or ""
        ex_date = row.get("exam_date")
        students.append(
            {
                "student_name": row.get("student_name") or "—",
                "student_dob": row.get("student_dob"),
                "lead_status": row.get("lead_status") or "",
                "exam_status": row.get("exam_status") or "",
                "ksdv_fee_paid": bool(int(row.get("ksdv_fee_paid") or 0)),
                "pic": pic,
                "pic_name": pic_map.get(pic, pic) if pic else "—",
                "exam_date": str(ex_date) if ex_date else "",
                "exam_time": row.get("exam_time") or "—",
                "target_grade": row.get("target_grade") or "",
                "exam_id": row.get("exam_id"),
                "exam_name": row.get("exam_name"),
            }
        )
    students.sort(
        key=lambda x: (
            x.get("exam_date") or "",
            x.get("exam_time") or "",
            x.get("student_name") or "",
        )
    )

    return success_response(
        {
            "by_grade": by_grade,
            "by_grade_conversion": by_grade_conversion,
            "by_week": by_week,
            "students": students,
            "meta": _activity_dashboard_meta(args, fd, td),
        }
    )


@frappe.whitelist()
def get_event_activity_dashboard():
    """Dashboard Sự kiện — theo tháng, theo khối (1 SK), danh sách HS."""
    check_crm_permission()
    args = frappe.request.args or {}
    date_expr = "e.`event_date`"
    fd, td, match_sql, binds, parent_where = _activity_parent_where(args, date_expr, skip_campus=False)

    event_id = (args.get("event_id") or "").strip()
    selected_month = (args.get("selected_month") or "").strip()

    rows = frappe.db.sql(
        f"""
        SELECT es.`status` AS event_status,
               es.`crm_lead_id`,
               e.`name` AS event_id,
               e.`event_name`,
               e.`event_date`,
               l.`student_name`,
               l.`student_dob`,
               IFNULL(l.`status`, '') AS lead_status,
               TRIM(IFNULL(l.`target_grade`, '')) AS target_grade,
               IFNULL(l.`pic`, '') AS pic
        FROM `tabCRM Admission Event Student` es
        INNER JOIN `tabCRM Admission Event` e ON e.`name` = es.`event_id`
        INNER JOIN `tabCRM Lead` l ON l.`name` = es.`crm_lead_id`
        WHERE {parent_where} AND {match_sql}
        """,
        binds,
        as_dict=True,
    )

    month_events: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    grade_map: Dict[str, Dict[str, int]] = defaultdict(lambda: {"registered": 0, "attended": 0, "deposit_paid": 0})

    for row in rows:
        ev_id = row.get("event_id")
        ev_date = row.get("event_date")
        month_key = str(ev_date)[:7] if ev_date else ""
        est = row.get("event_status") or ""
        lead_st = row.get("lead_status") or ""

        if month_key and ev_id:
            if ev_id not in month_events[month_key]:
                month_events[month_key][ev_id] = {
                    "event_id": ev_id,
                    "event_name": row.get("event_name"),
                    "event_date": str(ev_date),
                    "registered": 0,
                    "attended": 0,
                    "deposit_paid": 0,
                }
            slot = month_events[month_key][ev_id]
            if est == "registered":
                slot["registered"] += 1
            elif est == "attended":
                slot["attended"] += 1
                slot["registered"] += 1
            if _is_lead_deposit_paid(lead_st):
                slot["deposit_paid"] += 1

        if event_id and row.get("event_id") == event_id:
            grade = row.get("target_grade") or "(Chưa có khối)"
            if est == "registered":
                grade_map[grade]["registered"] += 1
            elif est == "attended":
                grade_map[grade]["attended"] += 1
                grade_map[grade]["registered"] += 1
            if _is_lead_deposit_paid(lead_st):
                grade_map[grade]["deposit_paid"] += 1

    by_month = []
    for mk in sorted(month_events.keys()):
        if selected_month and mk != selected_month:
            continue
        events_list = sorted(month_events[mk].values(), key=lambda x: x.get("event_date") or "")
        by_month.append({"month": mk, "events": events_list})

    by_grade = [
        {
            "target_grade": g,
            "registered": grade_map[g]["registered"],
            "attended": grade_map[g]["attended"],
            "deposit_paid": grade_map[g]["deposit_paid"],
        }
        for g in sorted(grade_map.keys(), key=_grade_sort_key)
    ]

    students: List[Dict[str, Any]] = []
    pic_map = _pic_names_map([r.get("pic") for r in rows if r.get("pic")])
    for row in rows:
        if event_id and row.get("event_id") != event_id:
            continue
        pic = row.get("pic") or ""
        lead_st = row.get("lead_status") or ""
        ev_date = row.get("event_date")
        students.append(
            {
                "student_name": row.get("student_name") or "—",
                "student_dob": row.get("student_dob"),
                "lead_status": lead_st,
                "event_status": row.get("event_status") or "",
                "tuition_paid": _is_lead_tuition_paid(lead_st),
                "pic": pic,
                "pic_name": pic_map.get(pic, pic) if pic else "—",
                "target_grade": row.get("target_grade") or "",
                "event_id": row.get("event_id"),
                "event_name": row.get("event_name"),
                "event_date": str(ev_date) if ev_date else "",
            }
        )
    students.sort(
        key=lambda x: (
            x.get("event_date") or "",
            x.get("event_name") or "",
            x.get("student_name") or "",
        )
    )

    return success_response(
        {
            "by_month": by_month,
            "by_grade": by_grade,
            "students": students,
            "meta": _activity_dashboard_meta(args, fd, td),
        }
    )


@frappe.whitelist()
def get_course_activity_dashboard():
    """Dashboard Khóa học khác — funnel theo tháng, theo khối, chuyển đổi paid."""
    check_crm_permission()
    args = frappe.request.args or {}
    date_expr = "e.`event_date`"
    fd, td, match_sql, binds, parent_where = _activity_parent_where(args, date_expr, skip_campus=False)

    course_id = (args.get("course_id") or "").strip()
    selected_month = (args.get("selected_month") or "").strip()

    rows = frappe.db.sql(
        f"""
        SELECT es.`status` AS course_status,
               es.`crm_lead_id`,
               e.`name` AS course_id,
               e.`course_name`,
               e.`event_date`,
               l.`student_name`,
               l.`student_dob`,
               IFNULL(l.`status`, '') AS lead_status,
               IFNULL(l.`step`, '') AS lead_step,
               TRIM(IFNULL(l.`target_grade`, '')) AS target_grade,
               IFNULL(l.`pic`, '') AS pic
        FROM `tabCRM Admission Course Student` es
        INNER JOIN `tabCRM Admission Course` e ON e.`name` = es.`course_id`
        INNER JOIN `tabCRM Lead` l ON l.`name` = es.`crm_lead_id`
        WHERE {parent_where} AND {match_sql}
        """,
        binds,
        as_dict=True,
    )

    month_courses: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    grade_map: Dict[str, Dict[str, int]] = defaultdict(lambda: {"registered": 0, "attended": 0, "deposit_paid": 0})
    grade_paid_conv: Dict[str, Dict[str, int]] = defaultdict(lambda: {"paid": 0, "enrolled": 0})

    for row in rows:
        cs = row.get("course_status") or ""
        lead_st = row.get("lead_status") or ""
        lead_step = row.get("lead_step") or ""
        c_id = row.get("course_id")
        c_date = row.get("event_date")
        month_key = str(c_date)[:7] if c_date else ""

        if month_key and c_id:
            if c_id not in month_courses[month_key]:
                month_courses[month_key][c_id] = {
                    "course_id": c_id,
                    "course_name": row.get("course_name"),
                    "event_date": str(c_date),
                    "total_lead": 0,
                    "potential": 0,
                    "short_term_paid": 0,
                    "enrolled": 0,
                    "lost": 0,
                }
            slot = month_courses[month_key][c_id]
            slot["total_lead"] += 1
            if cs in ("registered_interest", "trial"):
                slot["potential"] += 1
            if cs == "paid":
                slot["short_term_paid"] += 1
            if lead_step == "Enrolled":
                slot["enrolled"] += 1
            if cs == "refunded" or lead_st in ("Lost", "Tu choi"):
                slot["lost"] += 1

        if course_id and row.get("course_id") == course_id:
            grade = row.get("target_grade") or "(Chưa có khối)"
            grade_map[grade]["registered"] += 1
            if cs == "attended":
                grade_map[grade]["attended"] += 1
            if _is_lead_deposit_paid(lead_st) or cs == "paid":
                grade_map[grade]["deposit_paid"] += 1
            if cs == "paid":
                grade_paid_conv[grade]["paid"] += 1
                if lead_step == "Enrolled":
                    grade_paid_conv[grade]["enrolled"] += 1

    by_month = []
    for mk in sorted(month_courses.keys()):
        if selected_month and mk != selected_month:
            continue
        courses_list = sorted(month_courses[mk].values(), key=lambda x: x.get("event_date") or "")
        by_month.append({"month": mk, "courses": courses_list})

    by_grade = [
        {
            "target_grade": g,
            "registered": grade_map[g]["registered"],
            "attended": grade_map[g]["attended"],
            "deposit_paid": grade_map[g]["deposit_paid"],
        }
        for g in sorted(grade_map.keys(), key=_grade_sort_key)
    ]

    by_grade_paid_conversion = [
        {
            "target_grade": g,
            "paid": grade_paid_conv[g]["paid"],
            "enrolled": grade_paid_conv[g]["enrolled"],
            "conversion_pct": round(100.0 * grade_paid_conv[g]["enrolled"] / max(1, grade_paid_conv[g]["paid"]), 2),
        }
        for g in sorted(grade_paid_conv.keys(), key=_grade_sort_key)
    ]

    students: List[Dict[str, Any]] = []
    pic_map = _pic_names_map([r.get("pic") for r in rows if r.get("pic")])
    for row in rows:
        if course_id and row.get("course_id") != course_id:
            continue
        pic = row.get("pic") or ""
        cs = row.get("course_status") or ""
        c_date = row.get("event_date")
        students.append(
            {
                "student_name": row.get("student_name") or "—",
                "student_dob": row.get("student_dob"),
                "lead_bucket": _course_lead_bucket(cs, row.get("lead_status") or "", row.get("lead_step") or ""),
                "course_status": cs,
                "lead_status": row.get("lead_status") or "",
                # Cần cho bộ lọc legend "Nhập học" (lead_step == 'Enrolled') ở FE
                "lead_step": row.get("lead_step") or "",
                "pic": pic,
                "pic_name": pic_map.get(pic, pic) if pic else "—",
                "target_grade": row.get("target_grade") or "",
                "course_id": row.get("course_id"),
                "course_name": row.get("course_name"),
                "event_date": str(c_date) if c_date else "",
            }
        )
    students.sort(
        key=lambda x: (
            x.get("event_date") or "",
            x.get("course_name") or "",
            x.get("student_name") or "",
        )
    )

    return success_response(
        {
            "by_month": by_month,
            "by_grade": by_grade,
            "by_grade_paid_conversion": by_grade_paid_conversion,
            "students": students,
            "meta": _activity_dashboard_meta(args, fd, td),
        }
    )


# --------------------------------------------------------------------------- #
# Nguồn — Danh sách Nguồn 1 × ma trận trạng thái (cùng cấu trúc Tổng quan), lọc 3 cấp nguồn
# --------------------------------------------------------------------------- #
_SOURCE_STEPS_SQL = "('Lead','QLead','Enrolled','Nghi hoc','Verify','Draft')"
# KPI tab PIC vẫn dùng breakdown phẳng theo bước
_SOURCE_REPORT_STEPS = ["Draft", "Verify", "Lead", "QLead", "Enrolled", "Nghi hoc"]


@frappe.whitelist()
def get_source_breakdown():
    """Danh sách Nguồn 1 (snapshot) × ma trận bước/trạng thái + tỉ lệ chuyển đổi; lọc Nguồn 1/2/3.

    Cột giống báo cáo trạng thái theo khối (Hồ sơ mới / Lead / QLead / … × trạng thái chi tiết).
    Tỉ lệ chuyển đổi = Nhập học / tổng hồ sơ.
    """
    check_crm_permission()
    args = frappe.request.args or {}
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    # --- options 3 cấp nguồn (không áp src filter) ---
    opt_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(ls.`source`), ''), '') AS s1,
               IFNULL(NULLIF(TRIM(ls.`sub_source`), ''), '') AS s2,
               IFNULL(NULLIF(TRIM(ls.`source_note`), ''), '') AS s3
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE l.`step` IN {_SOURCE_STEPS_SQL} AND {dim_sql}
        """,
        dim_binds,
        as_dict=True,
    )
    s1set, s2set, s3set = set(), set(), set()
    for o in opt_rows:
        if o["s1"]:
            s1set.add(o["s1"])
        if o["s2"]:
            s2set.add(o["s2"])
        if o["s3"]:
            s3set.add(o["s3"])
    s1_names = r._batch_source_names(list(s1set))
    note_names: Dict[str, str] = {}
    if s3set:
        for n in frappe.get_all(
            "CRM Source Note", filters={"name": ["in", list(s3set)]},
            fields=["name", "note_name"],
        ):
            note_names[n["name"]] = n.get("note_name") or n["name"]

    def _opts(values, label_map: Optional[Dict[str, str]] = None):
        items = [
            {"key": v, "label": (label_map.get(v, v) if label_map else v)} for v in values
        ]
        items.sort(key=lambda x: str(x["label"]).lower())
        return items

    options = {
        "src1": _opts(s1set, s1_names),
        "src2": _opts(s2set, None),
        "src3": _opts(s3set, note_names),
    }

    # --- breakdown (áp src filter trên cùng dòng nguồn con ls) ---
    binds = dict(dim_binds)
    src_where: List[str] = []
    s1 = (args.get("src1") or "").strip()
    s2 = (args.get("src2") or "").strip()
    s3 = (args.get("src3") or "").strip()
    if s1:
        binds["fsrc1"] = s1
        src_where.append("ls.`source` = %(fsrc1)s")
    if s2:
        binds["fsrc2"] = s2
        src_where.append("ls.`sub_source` = %(fsrc2)s")
    if s3:
        binds["fsrc3"] = s3
        src_where.append("ls.`source_note` = %(fsrc3)s")
    src_sql = (" AND " + " AND ".join(src_where)) if src_where else ""

    status_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(ls.`source`), ''), '(Trống)') AS src,
               l.`step` AS step,
               IFNULL(TRIM(l.`status`), '') AS status,
               COUNT(DISTINCT l.`name`) AS cnt
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE l.`step` IN {_SOURCE_STEPS_SQL} AND {dim_sql}{src_sql}
        GROUP BY src, l.`step`, status
        """,
        binds,
        as_dict=True,
    )

    def _qlead_sub_rows_by_src(field: str):
        return frappe.db.sql(
            f"""
            SELECT IFNULL(NULLIF(TRIM(ls.`source`), ''), '(Trống)') AS src,
                   IFNULL(TRIM(l.`{field}`), '') AS val,
                   COUNT(DISTINCT l.`name`) AS cnt
            FROM `tabCRM Lead` l
            INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
            WHERE l.`step` = 'QLead'
              AND IFNULL(TRIM(l.`{field}`), '') != ''
              AND {dim_sql}{src_sql}
            GROUP BY src, val
            """,
            binds,
            as_dict=True,
        )

    test_rows = _qlead_sub_rows_by_src("test_status")

    step_statuses: Dict[str, set] = defaultdict(set)
    values_by_src: Dict[str, Dict[str, int]] = defaultdict(dict)
    total_by_src: Dict[str, int] = defaultdict(int)

    for row in status_rows:
        step_statuses[row["step"]].add(row["status"])
        key = _status_value_key(row["step"], row["status"])
        values_by_src[row["src"]][key] = values_by_src[row["src"]].get(key, 0) + int(row["cnt"])
        total_by_src[row["src"]] += int(row["cnt"])

    test_vals: set = set()
    for row in test_rows:
        test_vals.add(row["val"])
        values_by_src[row["src"]][f"QLead|test_status|{row['val']}"] = int(row["cnt"])

    groups = _build_status_report_groups(step_statuses, test_vals, set())
    src_ids = [k for k in values_by_src if k and k != "(Trống)"]
    src_labels = r._batch_source_names(src_ids)

    out = []
    for src in sorted(values_by_src.keys(), key=lambda x: (-total_by_src.get(x, 0), str(x).lower())):
        values = values_by_src.get(src, {})
        total = total_by_src.get(src, 0)
        enrolled = _count_enrolled_from_values(values)
        out.append(
            {
                "key": src,
                "label": src_labels.get(src, src),
                "total": total,
                "values": values,
                "count_enrolled": enrolled,
                "conversion_rate_pct": round(100.0 * enrolled / max(1, total), 2),
            }
        )

    return success_response(
        {
            "groups": groups,
            "rows": out,
            "options": options,
            "meta": {"pic_restricted_to_self": r._should_restrict_to_own_pic_only()},
        }
    )


@frappe.whitelist()
def get_source_lead_levels():
    """Tổng Lead theo nguồn 3 cấp trong kỳ (ngày tạo hồ sơ)."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = r._resolve_period(args)
    wsql, binds = r._where_creation_between(fd, td, args)

    rows = frappe.db.sql(
        f"""
        SELECT
            IFNULL(NULLIF(TRIM(ls.`source`), ''), '') AS src1,
            IFNULL(NULLIF(TRIM(ls.`sub_source`), ''), '') AS src2,
            IFNULL(NULLIF(TRIM(ls.`source_note`), ''), '') AS src3,
            COUNT(DISTINCT l.`name`) AS cnt
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE {wsql}
        GROUP BY src1, src2, src3
        ORDER BY cnt DESC
        LIMIT 500
        """,
        binds,
        as_dict=True,
    )

    s1set = {row["src1"] for row in rows if row.get("src1")}
    s3set = {row["src3"] for row in rows if row.get("src3")}
    s1_names = r._batch_source_names(list(s1set))
    note_names: Dict[str, str] = {}
    if s3set:
        for n in frappe.get_all(
            "CRM Source Note",
            filters={"name": ["in", list(s3set)]},
            fields=["name", "note_name"],
        ):
            note_names[n["name"]] = n.get("note_name") or n["name"]

    out = []
    for row in rows:
        s1 = row.get("src1") or ""
        s2 = row.get("src2") or ""
        s3 = row.get("src3") or ""
        out.append(
            {
                "src1": s1,
                "src1_label": s1_names.get(s1, s1) if s1 else "",
                "src2": s2,
                "src3": s3,
                "src3_label": note_names.get(s3, s3) if s3 else "",
                "count": int(row.get("cnt") or 0),
            }
        )

    return success_response(
        {
            "rows": out,
            "meta": {
                "period": {"from": str(fd), "to": str(td)},
                "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
            },
        }
    )


@frappe.whitelist()
def get_source_funnel_detail():
    """Phễu 5 chỉ số + danh sách HS theo Nguồn 1 (creation trong kỳ)."""
    check_crm_permission()
    args = frappe.request.args or {}
    src1 = (args.get("src1") or "").strip()
    if not src1:
        frappe.throw("Thiếu tham số src1")

    fd, td, _, _ = r._resolve_period(args)
    wsql, binds = r._where_creation_between(fd, td, args)
    binds["fsrc1"] = src1
    src_filter = "ls.`source` = %(fsrc1)s"

    counts_row = frappe.db.sql(
        f"""
        SELECT
            COUNT(*) AS total_profiles,
            SUM(CASE WHEN l.`step` IN {_KPI_LEAD_STEPS_SQL} THEN 1 ELSE 0 END) AS total_leads,
            SUM(CASE WHEN l.`step` = 'QLead' THEN 1 ELSE 0 END) AS total_qlead,
            SUM(CASE WHEN l.`step` = 'Enrolled' THEN 1 ELSE 0 END) AS total_enrolled,
            SUM(CASE WHEN l.`status` IN ('Lost','Tu choi') THEN 1 ELSE 0 END) AS total_lost
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE {src_filter} AND {wsql}
        """,
        binds,
        as_dict=True,
    )
    counts = counts_row[0] if counts_row else {}

    student_rows = frappe.db.sql(
        f"""
        SELECT l.`name`, l.`student_name`, l.`student_dob` AS `dob`, l.`step`, l.`status`,
               l.`pic`, l.`target_grade`, l.`creation`
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE {src_filter} AND {wsql}
        ORDER BY l.`creation` DESC
        LIMIT 500
        """,
        binds,
        as_dict=True,
    )

    total_students_row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT l.`name`) AS c
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE {src_filter} AND {wsql}
        """,
        binds,
        as_dict=True,
    )
    total_students = int((total_students_row[0] if total_students_row else {}).get("c") or 0)

    pic_ids = [row["pic"] for row in student_rows if row.get("pic")]
    pic_map = r._batch_user_map(pic_ids)

    funnel = [
        {
            "key": "total_profiles",
            "label": "Tổng Hồ sơ",
            "count": int(counts.get("total_profiles") or 0),
        },
        {
            "key": "total_leads",
            "label": "Tổng lead",
            "count": int(counts.get("total_leads") or 0),
        },
        {
            "key": "total_qlead",
            "label": "Học sinh Tiềm năng",
            "count": int(counts.get("total_qlead") or 0),
        },
        {
            "key": "total_enrolled",
            "label": "Học sinh Chính thức",
            "count": int(counts.get("total_enrolled") or 0),
        },
    ]

    students = []
    for row in student_rows:
        pic = (row.get("pic") or "").strip()
        students.append(
            {
                "name": row["name"],
                "full_name": row.get("student_name") or "",
                "dob": str(row["dob"]) if row.get("dob") else None,
                "step": row.get("step") or "",
                "status": row.get("status") or "",
                "pic": pic,
                "pic_name": pic_map.get(pic, {}).get("full_name", pic) if pic else "—",
                "target_grade": row.get("target_grade") or "",
                "creation": str(row["creation"]) if row.get("creation") else "",
            }
        )

    return success_response(
        {
            "funnel": funnel,
            "total_lost": int(counts.get("total_lost") or 0),
            "students": students,
            "total_students": total_students,
            "meta": {
                "period": {"from": str(fd), "to": str(td)},
                "src1": src1,
                "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
            },
        }
    )


# --------------------------------------------------------------------------- #
# KPI — Xếp hạng PIC (cột giống báo cáo nguồn: snapshot × bước + tỉ lệ chuyển đổi)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_pic_breakdown():
    """Danh sách PIC (snapshot) × bước + tỉ lệ chuyển đổi — cùng cấu trúc báo cáo nguồn."""
    check_crm_permission()
    args = frappe.request.args or {}
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic`), '') AS pic,
               l.`step` AS step,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE l.`step` IN {_SOURCE_STEPS_SQL}
          AND IFNULL(TRIM(l.`pic`), '') != ''
          AND {dim_sql}
        GROUP BY pic, l.`step`
        """,
        dim_binds,
        as_dict=True,
    )

    by_pic: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in rows:
        by_pic[row["pic"]][row["step"]] = int(row["cnt"])
    user_map = r._batch_user_map(list(by_pic.keys()))

    out = []
    for pic, steps in by_pic.items():
        total = sum(steps.values())
        enrolled = steps.get("Enrolled", 0)
        ud = user_map.get(pic, {})
        out.append(
            {
                "pic": pic,
                "pic_name": ud.get("full_name") or pic,
                "pic_avatar": ud.get("pic_avatar"),
                "total": total,
                "by_step": {s: steps.get(s, 0) for s in _SOURCE_REPORT_STEPS},
                "count_enrolled": enrolled,
                "conversion_rate_pct": round(100.0 * enrolled / max(1, total), 2),
            }
        )
    out.sort(key=lambda x: x["total"], reverse=True)

    return success_response(
        {
            "steps": _SOURCE_REPORT_STEPS,
            "rows": out,
            "meta": {"pic_restricted_to_self": r._should_restrict_to_own_pic_only()},
        }
    )


# --------------------------------------------------------------------------- #
# KPI — Tiến độ mục tiêu nhập học (target vs actual Enrolled)
# --------------------------------------------------------------------------- #
def _get_active_crm_sales_user_names() -> List[str]:
    """User enabled có role Sales CRM — dùng cho danh sách KPI cá nhân."""
    roles = list(CRM_LEAD_PIC_ELIGIBLE_ROLES)
    if not roles:
        return []
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name
        FROM `tabUser` u
        INNER JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role IN %(roles)s AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.name
        """,
        {"roles": roles},
    )
    return [row[0] for row in rows] if rows else []


# Nhóm role để tách KPI theo team (Sales / Care)
_KPI_TEAM_ROLES = {
    "sales": ("SIS Sales", "SIS Sales Admin"),
    "care": ("SIS Sales Care", "SIS Sales Care Admin"),
}


def _get_users_with_roles(roles) -> List[str]:
    """User enabled có bất kỳ role nào trong danh sách (dùng tách KPI Sales/Care)."""
    role_list = [x for x in (roles or []) if x]
    if not role_list:
        return []
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name
        FROM `tabUser` u
        INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
        WHERE hr.role IN %(roles)s AND IFNULL(u.enabled, 0) = 1
        ORDER BY u.name
        """,
        {"roles": role_list},
    )
    return [row[0] for row in rows] if rows else []


def _load_target_doc(campus_id: str, target_academic_year: str):
    """Tải doc CRM Admission Target hoặc None."""
    from erp.api.crm.admission_target import _find_target_name

    name = _find_target_name(campus_id, target_academic_year)
    if not name:
        return None
    return frappe.get_doc("CRM Admission Target", name)


def _count_enrolled_by_grade(campus_id: str, target_academic_year: str) -> Dict[str, int]:
    """Đếm số lead Enrolled theo target_grade (snapshot)."""
    where = ["l.`step` = 'Enrolled'", "l.`target_academic_year` = %(tay)s"]
    binds: Dict[str, Any] = {"tay": target_academic_year}
    if campus_id:
        where.append("l.`campus_id` = %(campus)s")
        binds["campus"] = campus_id

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(l.`target_grade`), ''), '-') AS grade,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE {" AND ".join(where)}
        GROUP BY grade
        """,
        binds,
        as_dict=True,
    )
    return {row["grade"]: int(row["cnt"]) for row in rows}


def _count_enrolled_by_pic(campus_id: str, target_academic_year: str, pic_filter: Optional[str] = None) -> Dict[str, int]:
    """Đếm số lead Enrolled theo PIC (snapshot)."""
    where = [
        "l.`step` = 'Enrolled'",
        "l.`target_academic_year` = %(tay)s",
        "IFNULL(TRIM(l.`pic`), '') != ''",
    ]
    binds: Dict[str, Any] = {"tay": target_academic_year}
    if campus_id:
        where.append("l.`campus_id` = %(campus)s")
        binds["campus"] = campus_id
    if pic_filter:
        where.append("l.`pic` = %(pic)s")
        binds["pic"] = pic_filter

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic`), '') AS pic,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE {" AND ".join(where)}
        GROUP BY pic
        """,
        binds,
        as_dict=True,
    )
    return {row["pic"]: int(row["cnt"]) for row in rows}


def _pct(actual: int, target: int) -> float:
    if target <= 0:
        return 0.0 if actual <= 0 else 100.0
    return round(100.0 * actual / target, 2)


@frappe.whitelist()
def get_enrollment_target_progress():
    """Tiến độ mục tiêu nhập học: theo khối, tổng phòng ban, theo PIC."""
    check_crm_permission()
    args = frappe.request.args or {}
    campus_id = (args.get("campus_id") or "").strip()
    target_academic_year = (args.get("target_academic_year") or "").strip()

    if not target_academic_year:
        return success_response(
            {
                "by_grade": [],
                "dept_total": {"target": 0, "actual": 0, "pct": 0},
                "by_member": [],
                "meta": {
                    "configured": False,
                    "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
                },
            }
        )

    restricted = r._should_restrict_to_own_pic_only()
    pic_eff = r._effective_pic_from_request(args.get("pic")) if restricted else None

    target_doc = _load_target_doc(campus_id, target_academic_year) if campus_id else None

    grade_targets_map: Dict[str, int] = {}
    member_targets_map: Dict[str, int] = {}
    dept_target = 0
    if target_doc:
        for row in target_doc.grade_targets or []:
            g = (row.target_grade or "").strip()
            if g:
                grade_targets_map[g] = int(row.enrollment_target or 0)
        dept_target = int(target_doc.total_enrollment_target or 0)
        for row in target_doc.member_targets or []:
            p = (row.pic or "").strip()
            if p:
                member_targets_map[p] = int(row.enrollment_target or 0)

    actual_by_grade = _count_enrolled_by_grade(campus_id, target_academic_year)
    actual_by_pic = _count_enrolled_by_pic(campus_id, target_academic_year, pic_eff)

    # by_grade: union grades từ target + actual
    all_grades = sorted(
        set(grade_targets_map.keys()) | set(actual_by_grade.keys()),
        key=lambda g: (0, int(g)) if g.isdigit() else (1, g),
    )
    by_grade = []
    dept_actual = 0
    for g in all_grades:
        if g == "-":
            continue
        target = grade_targets_map.get(g, 0)
        actual = actual_by_grade.get(g, 0)
        dept_actual += actual
        by_grade.append(
            {
                "target_grade": g,
                "target": target,
                "actual": actual,
                "pct": _pct(actual, target),
            }
        )

    # dept_total: dùng tổng target từ doc hoặc sum grade targets
    if not dept_target and grade_targets_map:
        dept_target = sum(grade_targets_map.values())
    # actual tổng: đếm tất cả enrolled (không chỉ grades trong target)
    if campus_id:
        dept_actual_total = sum(
            v for k, v in actual_by_grade.items() if k != "-"
        )
    else:
        dept_actual_total = dept_actual

    dept_total = {
        "target": dept_target,
        "actual": dept_actual_total,
        "pct": _pct(dept_actual_total, dept_target),
    }

    # by_member — gồm target đã cấu hình, PIC có actual, và toàn bộ user Sales
    all_pics = (
        set(member_targets_map.keys())
        | set(actual_by_pic.keys())
        | set(_get_active_crm_sales_user_names())
    )
    if pic_eff:
        all_pics = {pic_eff}

    user_map = r._batch_user_map(list(all_pics))
    by_member = []
    for pic in sorted(all_pics):
        target = member_targets_map.get(pic, 0)
        actual = actual_by_pic.get(pic, 0)
        ud = user_map.get(pic, {})
        by_member.append(
            {
                "pic": pic,
                "pic_name": ud.get("full_name") or pic,
                "pic_avatar": ud.get("pic_avatar"),
                "target": target,
                "actual": actual,
                "pct": _pct(actual, target),
            }
        )
    by_member.sort(key=lambda x: (-x["actual"], x["pic_name"]))

    return success_response(
        {
            "by_grade": by_grade,
            "dept_total": dept_total,
            "by_member": by_member,
            "meta": {
                "configured": bool(target_doc),
                "campus_id": campus_id or None,
                "target_academic_year": target_academic_year,
                "pic_restricted_to_self": restricted,
            },
        }
    )


# --------------------------------------------------------------------------- #
# KPI — Báo cáo tổng quát đa chỉ số (Hồ sơ / Lead / Tiềm năng / Chính thức / Lost)
# --------------------------------------------------------------------------- #
# "Tổng Lead" = mọi hồ sơ đã qua bước Lead (Lead/QLead/Enrolled) — đồng bộ mapping FE
_KPI_LEAD_STEPS_SQL = "('Lead','QLead','Enrolled')"


def _count_kpi_metrics_snapshot(
    campus_id: str, target_academic_year: str, pic_filter: Optional[str] = None
) -> Dict[str, int]:
    """Snapshot 5 chỉ số KPI phòng ban theo năm học mục tiêu: hồ sơ / lead / qlead / enrolled / lost."""
    where = ["l.`target_academic_year` = %(tay)s"]
    binds: Dict[str, Any] = {"tay": target_academic_year}
    if campus_id:
        where.append("l.`campus_id` = %(campus)s")
        binds["campus"] = campus_id
    if pic_filter:
        where.append("l.`pic` = %(pic)s")
        binds["pic"] = pic_filter

    rows = frappe.db.sql(
        f"""
        SELECT
            COUNT(*) AS total_profiles,
            SUM(CASE WHEN l.`step` IN {_KPI_LEAD_STEPS_SQL} THEN 1 ELSE 0 END) AS total_leads,
            SUM(CASE WHEN l.`step` = 'QLead' THEN 1 ELSE 0 END) AS total_qlead,
            SUM(CASE WHEN l.`step` = 'Enrolled' THEN 1 ELSE 0 END) AS total_enrolled,
            SUM(CASE WHEN l.`status` IN ('Lost','Tu choi') THEN 1 ELSE 0 END) AS total_lost
        FROM `tabCRM Lead` l
        WHERE {" AND ".join(where)}
        """,
        binds,
        as_dict=True,
    )
    d = rows[0] if rows else {}
    return {
        "total_profiles": int(d.get("total_profiles") or 0),
        "total_leads": int(d.get("total_leads") or 0),
        "total_qlead": int(d.get("total_qlead") or 0),
        "total_enrolled": int(d.get("total_enrolled") or 0),
        "total_lost": int(d.get("total_lost") or 0),
    }


def _count_kpi_metrics_by_pic(
    campus_id: str, target_academic_year: str, pic_filter: Optional[str] = None
) -> Dict[str, Dict[str, int]]:
    """3 chỉ số (lead/qlead/enrolled) theo từng PIC — snapshot theo năm học mục tiêu."""
    where = [
        "l.`target_academic_year` = %(tay)s",
        "IFNULL(TRIM(l.`pic`), '') != ''",
        f"l.`step` IN {_KPI_LEAD_STEPS_SQL}",
    ]
    binds: Dict[str, Any] = {"tay": target_academic_year}
    if campus_id:
        where.append("l.`campus_id` = %(campus)s")
        binds["campus"] = campus_id
    if pic_filter:
        where.append("l.`pic` = %(pic)s")
        binds["pic"] = pic_filter

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic`), '') AS pic,
               l.`step` AS step,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE {" AND ".join(where)}
        GROUP BY pic, l.`step`
        """,
        binds,
        as_dict=True,
    )
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"lead": 0, "qlead": 0, "enrolled": 0})
    for row in rows:
        pic = row["pic"]
        step = row["step"]
        cnt = int(row["cnt"])
        # Lead tổng = cộng dồn cả 3 bước (Lead/QLead/Enrolled đều từng qua Lead)
        out[pic]["lead"] += cnt
        if step == "QLead":
            out[pic]["qlead"] += cnt
        elif step == "Enrolled":
            out[pic]["enrolled"] += cnt
    return out


@frappe.whitelist()
def get_kpi_overview():
    """Báo cáo KPI tổng quát — 5 chỉ số phòng ban (so KPI) + Lead/Tiềm năng/Chính thức theo thành viên (so target)."""
    check_crm_permission()
    args = frappe.request.args or {}
    campus_id = (args.get("campus_id") or "").strip()
    target_academic_year = (args.get("target_academic_year") or "").strip()
    team = (args.get("team") or "").strip().lower()
    restricted = r._should_restrict_to_own_pic_only()

    if not target_academic_year:
        return success_response(
            {
                "summary": [],
                "by_member": [],
                "meta": {"configured": False, "pic_restricted_to_self": restricted},
            }
        )

    pic_eff = r._effective_pic_from_request(args.get("pic")) if restricted else None

    target_doc = _load_target_doc(campus_id, target_academic_year) if campus_id else None
    dept_targets = {
        "total_profiles": int(getattr(target_doc, "total_profile_target", 0) or 0) if target_doc else 0,
        "total_leads": int(getattr(target_doc, "total_lead_target", 0) or 0) if target_doc else 0,
        "total_qlead": int(getattr(target_doc, "total_qlead_target", 0) or 0) if target_doc else 0,
        "total_enrolled": int(getattr(target_doc, "total_enrollment_target", 0) or 0) if target_doc else 0,
        "total_lost": int(getattr(target_doc, "total_lost_target", 0) or 0) if target_doc else 0,
    }

    actual = _count_kpi_metrics_snapshot(campus_id, target_academic_year, pic_eff)

    summary_defs = [
        ("total_profiles", "Tổng Hồ sơ"),
        ("total_leads", "Tổng lead"),
        ("total_qlead", "Học sinh Tiềm năng"),
        ("total_enrolled", "Học sinh Chính thức"),
        ("total_lost", "Từ chối"),
    ]
    summary = [
        {
            "key": key,
            "label": label,
            "target": dept_targets[key],
            "actual": actual[key],
            "pct": _pct(actual[key], dept_targets[key]),
        }
        for key, label in summary_defs
    ]

    # by_member — target từ member_targets (lead/qlead/enrollment), actual đếm theo PIC
    member_targets_map: Dict[str, Dict[str, int]] = {}
    if target_doc:
        for row in target_doc.member_targets or []:
            p = (row.pic or "").strip()
            if p:
                member_targets_map[p] = {
                    "lead": int(getattr(row, "lead_target", 0) or 0),
                    "qlead": int(getattr(row, "qlead_target", 0) or 0),
                    "enrolled": int(row.enrollment_target or 0),
                }

    actual_by_pic = _count_kpi_metrics_by_pic(campus_id, target_academic_year, pic_eff)

    if team in _KPI_TEAM_ROLES:
        # Tách theo role: chỉ thành viên có role của nhóm Sales/Care đang chọn
        all_pics = set(_get_users_with_roles(_KPI_TEAM_ROLES[team]))
        if pic_eff:
            all_pics = all_pics & {pic_eff}
    else:
        all_pics = (
            set(member_targets_map.keys())
            | set(actual_by_pic.keys())
            | set(_get_active_crm_sales_user_names())
        )
        if pic_eff:
            all_pics = {pic_eff}

    user_map = r._batch_user_map(list(all_pics))
    by_member = []
    for pic in sorted(all_pics):
        targets = member_targets_map.get(pic, {"lead": 0, "qlead": 0, "enrolled": 0})
        act = actual_by_pic.get(pic, {"lead": 0, "qlead": 0, "enrolled": 0})
        ud = user_map.get(pic, {})
        by_member.append(
            {
                "pic": pic,
                "pic_name": ud.get("full_name") or pic,
                "pic_avatar": ud.get("pic_avatar"),
                "lead": {
                    "target": targets["lead"],
                    "actual": act["lead"],
                    "pct": _pct(act["lead"], targets["lead"]),
                },
                "qlead": {
                    "target": targets["qlead"],
                    "actual": act["qlead"],
                    "pct": _pct(act["qlead"], targets["qlead"]),
                },
                "enrolled": {
                    "target": targets["enrolled"],
                    "actual": act["enrolled"],
                    "pct": _pct(act["enrolled"], targets["enrolled"]),
                },
            }
        )
    by_member.sort(key=lambda x: (-x["enrolled"]["actual"], x["pic_name"]))

    return success_response(
        {
            "summary": summary,
            "by_member": by_member,
            "meta": {
                "configured": bool(target_doc),
                "campus_id": campus_id or None,
                "target_academic_year": target_academic_year,
                "pic_restricted_to_self": restricted,
            },
        }
    )


@frappe.whitelist()
def get_enrollment_progress_gauge():
    """Gauge tiến độ tuyển sinh toàn trường (nửa hình tròn).

    - Học sinh hiện hữu (HSHH) = Học sinh chính thức = CRM Lead step='Enrolled'.
    - Học sinh mới (HSM) = QLead có test_status='De xuat' (KSĐV = Đề xuất)
      và deal_status IN ('Dat coc','Dong phi') (Thỏa thuận = Đặt cọc / Đóng phí).
    - kpi_target = Mục tiêu Tổng học sinh hiện hữu (config CRM Admission Target).
    - ratio = (HSHH + HSM) / kpi_target * 100.
    Scope theo campus + năm học mục tiêu (snapshot).
    """
    check_crm_permission()
    args = frappe.request.args or {}
    campus_id = (args.get("campus_id") or "").strip()
    target_academic_year = (args.get("target_academic_year") or "").strip()
    restricted = r._should_restrict_to_own_pic_only()
    pic_eff = r._effective_pic_from_request(args.get("pic")) if restricted else None

    if not target_academic_year:
        return success_response(
            {
                "hshh": 0,
                "hsm": 0,
                "kpi_target": 0,
                "ratio": 0,
                "meta": {"configured": False, "pic_restricted_to_self": restricted},
            }
        )

    where = ["l.`target_academic_year` = %(tay)s"]
    binds: Dict[str, Any] = {"tay": target_academic_year}
    if campus_id:
        where.append("l.`campus_id` = %(campus)s")
        binds["campus"] = campus_id
    if pic_eff:
        where.append("l.`pic` = %(pic)s")
        binds["pic"] = pic_eff

    row = frappe.db.sql(
        f"""
        SELECT
            SUM(CASE WHEN l.`step` = 'Enrolled' THEN 1 ELSE 0 END) AS hshh,
            SUM(CASE WHEN l.`step` = 'QLead'
                      AND l.`test_status` = 'De xuat'
                      AND l.`status` IN ('Dat coc', 'Dong phi')
                     THEN 1 ELSE 0 END) AS hsm
        FROM `tabCRM Lead` l
        WHERE {" AND ".join(where)}
        """,
        binds,
        as_dict=True,
    )
    d = row[0] if row else {}
    hshh = int(d.get("hshh") or 0)
    hsm = int(d.get("hsm") or 0)

    target_doc = _load_target_doc(campus_id, target_academic_year) if campus_id else None
    kpi_target = int(getattr(target_doc, "total_existing_target", 0) or 0) if target_doc else 0
    ratio = round((hshh + hsm) / kpi_target * 100, 1) if kpi_target else 0

    return success_response(
        {
            "hshh": hshh,
            "hsm": hsm,
            "kpi_target": kpi_target,
            "ratio": ratio,
            "meta": {
                "configured": bool(target_doc),
                "campus_id": campus_id or None,
                "target_academic_year": target_academic_year,
                "pic_restricted_to_self": restricted,
            },
        }
    )


# --------------------------------------------------------------------------- #
# KPI — Phễu cá nhân theo kỳ (ngày tạo hồ sơ) — báo cáo riêng lẻ từng thành viên
# --------------------------------------------------------------------------- #
def _count_kpi_metrics_period(campus_id: str, pic: str, from_date, to_date) -> Dict[str, int]:
    """5 chỉ số KPI theo PIC trong khoảng ngày tạo hồ sơ (creation) — dùng cho phễu cá nhân."""
    where = ["DATE(l.`creation`) BETWEEN %(fd)s AND %(td)s", "l.`pic` = %(pic)s"]
    binds: Dict[str, Any] = {"fd": from_date, "td": to_date, "pic": pic}
    if campus_id:
        where.append("l.`campus_id` = %(campus)s")
        binds["campus"] = campus_id

    rows = frappe.db.sql(
        f"""
        SELECT
            COUNT(*) AS total_profiles,
            SUM(CASE WHEN l.`step` IN {_KPI_LEAD_STEPS_SQL} THEN 1 ELSE 0 END) AS total_leads,
            SUM(CASE WHEN l.`step` = 'QLead' THEN 1 ELSE 0 END) AS total_qlead,
            SUM(CASE WHEN l.`step` = 'Enrolled' THEN 1 ELSE 0 END) AS total_enrolled,
            SUM(CASE WHEN l.`status` IN ('Lost','Tu choi') THEN 1 ELSE 0 END) AS total_lost
        FROM `tabCRM Lead` l
        WHERE {" AND ".join(where)}
        """,
        binds,
        as_dict=True,
    )
    d = rows[0] if rows else {}
    return {
        "total_profiles": int(d.get("total_profiles") or 0),
        "total_leads": int(d.get("total_leads") or 0),
        "total_qlead": int(d.get("total_qlead") or 0),
        "total_enrolled": int(d.get("total_enrolled") or 0),
        "total_lost": int(d.get("total_lost") or 0),
    }


@frappe.whitelist()
def get_kpi_member_funnel():
    """Phễu KPI cá nhân theo kỳ (ngày/tháng/năm): Hồ sơ → Lead → Tiềm năng → Chính thức, kèm Lost."""
    check_crm_permission()
    args = frappe.request.args or {}
    campus_id = (args.get("campus_id") or "").strip()
    restricted = r._should_restrict_to_own_pic_only()
    pic = r._effective_pic_from_request(args.get("pic"))
    fd, td, pdf, pdt = r._resolve_period(args)

    if not pic:
        return success_response(
            {
                "funnel": [],
                "total_lost": 0,
                "total_lost_change": None,
                "meta": {
                    "period": {"from": str(fd), "to": str(td)},
                    "pic": None,
                    "pic_name": None,
                    "pic_restricted_to_self": restricted,
                },
            }
        )

    counts = _count_kpi_metrics_period(campus_id, pic, fd, td)
    prev = _count_kpi_metrics_period(campus_id, pic, pdf, pdt)
    ud = r._batch_user_map([pic]).get(pic, {})

    def _ch(metric: str):
        return r._pct_change(counts[metric], prev[metric])

    funnel = [
        {"key": "total_profiles", "label": "Tổng Hồ sơ", "count": counts["total_profiles"], "change": _ch("total_profiles")},
        {"key": "total_leads", "label": "Tổng lead", "count": counts["total_leads"], "change": _ch("total_leads")},
        {"key": "total_qlead", "label": "Học sinh Tiềm năng", "count": counts["total_qlead"], "change": _ch("total_qlead")},
        {"key": "total_enrolled", "label": "Học sinh Chính thức", "count": counts["total_enrolled"], "change": _ch("total_enrolled")},
    ]

    return success_response(
        {
            "funnel": funnel,
            "total_lost": counts["total_lost"],
            "total_lost_change": _ch("total_lost"),
            "meta": {
                "period": {"from": str(fd), "to": str(td)},
                "pic": pic,
                "pic_name": ud.get("full_name") or pic,
                "pic_avatar": ud.get("pic_avatar"),
                "pic_restricted_to_self": restricted,
            },
        }
    )


# --------------------------------------------------------------------------- #
# Tổng quan — Kỳ báo cáo (from_date / to_date từ toolbar tab Tổng quan)
# --------------------------------------------------------------------------- #
def _overview_period_bounds(args) -> Tuple[Any, Any, Any]:
    """Trả về (from_date, to_date_effective, as_of_end).

    `to_date_effective` = min(to_date, hôm nay) — snapshot không nhìn vào tương lai.
    `as_of_end` = cuối ngày effective, dùng tái dựng step/status từ lịch sử."""
    from frappe.utils import getdate, today

    fd, td, _, _ = r._resolve_period(args)
    fd = getdate(fd)
    td_raw = getdate(td)
    td_eff = min(td_raw, getdate(today()))
    as_of_end = f"{td_eff} 23:59:59.999999"
    return fd, td_eff, as_of_end


def _overview_period_meta(fd: Any, td_raw: Any, td_eff: Any) -> Dict[str, Any]:
    """Meta kỳ — mọi endpoint tab Tổng quan trả cùng cấu trúc để UI đồng bộ."""
    from frappe.utils import getdate

    return {
        "period_from": str(getdate(fd)),
        "period_to": str(getdate(td_raw)),
        "as_of": str(getdate(td_eff)),
    }


# --------------------------------------------------------------------------- #
# Tổng quan — Khối lớp của lead (fallback khi target_grade trống)
# --------------------------------------------------------------------------- #
def _sis_grade_map_for_students(student_ids: List[str]) -> Dict[str, str]:
    """Map CRM Student → khối ('K', '1'..'12') từ lớp Regular trong SIS,
    ưu tiên năm học mới nhất (start_date). Không map được thì bỏ qua."""
    from erp.api.crm.enrolled_class_sync import _normalize_grade_to_lead_select

    if not student_ids:
        return {}
    rows = frappe.db.sql(
        """
        SELECT t.student_id, t.grade_code, t.title_vn
        FROM (
            SELECT cs.`student_id` AS student_id, eg.`grade_code` AS grade_code,
                   eg.`title_vn` AS title_vn,
                   ROW_NUMBER() OVER (
                       PARTITION BY cs.`student_id`
                       ORDER BY sy.`start_date` DESC, cs.`modified` DESC
                   ) AS rn
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.`class_id` = c.`name`
            INNER JOIN `tabSIS Education Grade` eg ON c.`education_grade` = eg.`name`
            LEFT JOIN `tabSIS School Year` sy ON cs.`school_year_id` = sy.`name`
            WHERE cs.`student_id` IN %(students)s
              AND (IFNULL(NULLIF(TRIM(c.`class_type`), ''), 'regular') = 'regular')
        ) t
        WHERE t.rn = 1
        """,
        {"students": student_ids},
        as_dict=True,
    )
    out: Dict[str, str] = {}
    for row in rows:
        g = _normalize_grade_to_lead_select(row.get("grade_code"), row.get("title_vn"))
        if g:
            out[row["student_id"]] = g
    return out


def _resolve_lead_grade_rows(rows: List[Dict[str, Any]]) -> None:
    """Gán row['grade'] với fallback: target_grade → current_grade → khối SIS
    (qua linked_student) → '-'.

    Sửa lỗi báo cáo theo khối dồn hết vào «Khối -»: HS đã nhập học / migrate
    thường trống target_grade nhưng đã có lớp thật trong SIS."""
    unresolved_students = sorted(
        {
            (row.get("linked_student") or "").strip()
            for row in rows
            if not (row.get("target_grade") or "").strip()
            and not (row.get("current_grade") or "").strip()
            and (row.get("linked_student") or "").strip()
        }
    )
    sis_map = _sis_grade_map_for_students(unresolved_students)
    for row in rows:
        g = (row.get("target_grade") or "").strip() or (row.get("current_grade") or "").strip()
        if not g:
            g = sis_map.get((row.get("linked_student") or "").strip(), "")
        row["grade"] = g or "-"


def _grade_display_sort_key(g: str):
    """Thứ tự hiển thị khối: K → 1..12 → còn lại (chữ) → '-' cuối cùng."""
    if g == "K":
        return (0, 0, "")
    try:
        return (0, int(g), "")
    except (TypeError, ValueError):
        return (2, 0, g) if g == "-" else (1, 0, g)


# --------------------------------------------------------------------------- #
# Tổng quan — Snapshot as-of (trạng thái tại ngày cuối kỳ, tái dựng từ lịch sử)
# --------------------------------------------------------------------------- #
# Thứ tự hiển thị phễu trạng thái QLead (trạng thái chính, không phải test/deal_status)
_QLEAD_FUNNEL_ORDER = ["Dang cham soc", "Dat lich hen", "Tham gia su kien", "Tham quan truong", "Can nhac", "Dat cho", "Dat coc", "Dong phi", "Hoan phi", "Bao luu/Chuyen", "Khao sat dau vao", "Tu choi"]


def _as_of_state_rows(as_of_end: str, dim_sql: str, dim_binds: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Tái dựng step/status của từng CRM Lead tại thời điểm `as_of_end` từ CRM Lead Step History.

    - as_of_step: `new_step` của bản ghi lịch sử mới nhất có `changed_at` <= as_of; nếu chưa có
      bản ghi nào trước as_of, dùng `old_step` của bản ghi sớm nhất có `changed_at` > as_of (trạng
      thái đó đã tồn tại từ trước, chưa đổi cho tới lần đổi đầu tiên sau as_of); nếu lead chưa từng
      có lịch sử, dùng step hiện tại (chưa từng đổi kể từ khi tạo).
    - as_of_status: tương tự nhưng chỉ xét bản ghi đổi `status` chính — bỏ qua bản ghi đổi
      test_status/deal_status (lưu dạng "field:value" trong new_status/old_status, khác trường).
    """
    binds = {"as_of": as_of_end, **dim_binds}
    return frappe.db.sql(
        f"""
        WITH base_leads AS (
            SELECT l.`name` AS lead_id, l.`step` AS cur_step, l.`status` AS cur_status,
                   IFNULL(TRIM(l.`target_grade`), '') AS target_grade,
                   IFNULL(TRIM(l.`current_grade`), '') AS current_grade,
                   IFNULL(TRIM(l.`linked_student`), '') AS linked_student,
                   l.`student_name`, l.`student_dob`, IFNULL(l.`pic`, '') AS pic
            FROM `tabCRM Lead` l
            WHERE l.`creation` <= %(as_of)s AND {dim_sql}
        ),
        step_before AS (
            SELECT h.`lead` AS lead_id, h.`new_step` AS val,
                   ROW_NUMBER() OVER (PARTITION BY h.`lead` ORDER BY h.`changed_at` DESC, h.`name` DESC) AS rn
            FROM `tabCRM Lead Step History` h
            INNER JOIN base_leads bl ON bl.lead_id = h.`lead`
            WHERE h.`changed_at` <= %(as_of)s
        ),
        step_after AS (
            SELECT h.`lead` AS lead_id, h.`old_step` AS val,
                   ROW_NUMBER() OVER (PARTITION BY h.`lead` ORDER BY h.`changed_at` ASC, h.`name` ASC) AS rn
            FROM `tabCRM Lead Step History` h
            INNER JOIN base_leads bl ON bl.lead_id = h.`lead`
            WHERE h.`changed_at` > %(as_of)s
        ),
        status_before AS (
            SELECT h.`lead` AS lead_id, h.`new_status` AS val,
                   ROW_NUMBER() OVER (PARTITION BY h.`lead` ORDER BY h.`changed_at` DESC, h.`name` DESC) AS rn
            FROM `tabCRM Lead Step History` h
            INNER JOIN base_leads bl ON bl.lead_id = h.`lead`
            WHERE h.`changed_at` <= %(as_of)s
              AND h.`new_status` NOT LIKE 'test_status:%%'
              AND h.`new_status` NOT LIKE 'deal_status:%%'
        ),
        status_after AS (
            SELECT h.`lead` AS lead_id, h.`old_status` AS val,
                   ROW_NUMBER() OVER (PARTITION BY h.`lead` ORDER BY h.`changed_at` ASC, h.`name` ASC) AS rn
            FROM `tabCRM Lead Step History` h
            INNER JOIN base_leads bl ON bl.lead_id = h.`lead`
            WHERE h.`changed_at` > %(as_of)s
              AND h.`old_status` NOT LIKE 'test_status:%%'
              AND h.`old_status` NOT LIKE 'deal_status:%%'
        )
        SELECT bl.lead_id, bl.target_grade, bl.current_grade, bl.linked_student,
               bl.student_name, bl.student_dob, bl.pic,
               COALESCE(sb.val, sa.val, bl.cur_step) AS as_of_step,
               COALESCE(stb.val, sta.val, bl.cur_status) AS as_of_status
        FROM base_leads bl
        LEFT JOIN step_before sb ON sb.lead_id = bl.lead_id AND sb.rn = 1
        LEFT JOIN step_after sa ON sa.lead_id = bl.lead_id AND sa.rn = 1
        LEFT JOIN status_before stb ON stb.lead_id = bl.lead_id AND stb.rn = 1
        LEFT JOIN status_after sta ON sta.lead_id = bl.lead_id AND sta.rn = 1
        """,
        binds,
        as_dict=True,
    )


@frappe.whitelist()
def get_overview_snapshot():
    """Snapshot trạng thái CRM Lead tại ngày cuối kỳ lọc (`to_date`), tái dựng từ lịch sử
    chuyển bước — phục vụ tab Tổng quan: phễu trạng thái HS tiềm năng (QLead) và 2 báo cáo
    theo khối lớp (5 chỉ số theo bước + trạng thái QLead theo khối).

    Khác với `get_status_by_grade` (snapshot hiện tại), endpoint này trả về trạng thái đúng
    tại thời điểm `to_date` — phù hợp khi user chọn 1 khoảng thời gian trong quá khứ.
    Chỉ tính 5 nhóm bước (Draft/Lead/QLead/Enrolled/Lost); lead đang ở Verify/Nghi hoc tại
    thời điểm đó không thuộc phạm vi báo cáo này.
    """
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td_eff, as_of_end = _overview_period_bounds(args)
    _, td_raw, _, _ = r._resolve_period(args)
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    rows = _as_of_state_rows(as_of_end, dim_sql, dim_binds)
    # Khối theo fallback target_grade → current_grade → SIS — tránh dồn vào "Khối -"
    _resolve_lead_grade_rows(rows)

    funnel_counts: Dict[str, int] = defaultdict(int)
    grade_steps: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    grade_qlead_status: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Danh sách HS kèm `metric` = đúng ô đã đếm ở `grade_steps` → FE lọc theo khối (cột) + chỉ số (chú thích)
    students: List[Dict[str, Any]] = []

    for row in rows:
        grade = row["grade"]
        step = row["as_of_step"] or ""
        status = (row["as_of_status"] or "").strip()
        # Chuan hoa code cu -> moi (rename Lost->Tu choi, Thoa thuan->Can nhac) cho pheu nhat quan
        if status == "Lost":
            status = "Tu choi"
        elif status == "Thoa thuan":
            status = "Can nhac"

        metric = ""
        if step == "Draft":
            grade_steps[grade]["draft"] += 1
            metric = "draft"
        elif step == "Lead":
            if status == "Tu choi":
                grade_steps[grade]["lost"] += 1
                metric = "lost"
            else:
                grade_steps[grade]["lead"] += 1
                metric = "lead"
        elif step == "QLead":
            if status == "Tu choi":
                grade_steps[grade]["lost"] += 1
                metric = "lost"
            else:
                grade_steps[grade]["qlead"] += 1
                metric = "qlead"
            if status:
                funnel_counts[status] += 1
                grade_qlead_status[grade][status] += 1
        elif step == "Enrolled":
            grade_steps[grade]["enrolled"] += 1
            metric = "enrolled"

        # Chỉ lấy HS thuộc 1 trong 5 ô của báo cáo (bỏ lead ngoài phạm vi: Verify/Nghi hoc…)
        if metric:
            students.append(
                {
                    "student_name": row.get("student_name") or "",
                    "student_dob": str(row["student_dob"]) if row.get("student_dob") else None,
                    "target_grade": grade,
                    "metric": metric,
                    "status": status,
                    "pic": row.get("pic") or "",
                }
            )

    funnel = [
        {"status": st, "count": funnel_counts.get(st, 0)}
        for st in _order_status_values(set(funnel_counts.keys()), _QLEAD_FUNNEL_ORDER)
    ]

    by_grade_steps = []
    for g in sorted(grade_steps.keys(), key=_grade_display_sort_key):
        m = grade_steps[g]
        draft, lead, qlead = m.get("draft", 0), m.get("lead", 0), m.get("qlead", 0)
        enrolled, lost = m.get("enrolled", 0), m.get("lost", 0)
        by_grade_steps.append(
            {
                "target_grade": g,
                "total": draft + lead + qlead + enrolled + lost,
                "draft": draft,
                "lead": lead,
                "qlead": qlead,
                "enrolled": enrolled,
                "lost": lost,
            }
        )

    by_grade_qlead_status = [
        {"target_grade": g, "values": dict(grade_qlead_status[g])}
        for g in sorted(grade_qlead_status.keys(), key=_grade_display_sort_key)
    ]

    pic_names = _pic_names_map([s["pic"] for s in students if s["pic"]])
    for s in students:
        s["pic_name"] = pic_names.get(s["pic"], "")

    period_meta = _overview_period_meta(fd, td_raw, td_eff)
    return success_response(
        {
            "funnel_qlead": funnel,
            "by_grade_steps": by_grade_steps,
            "by_grade_qlead_status": by_grade_qlead_status,
            "students": students,
            "meta": {
                **period_meta,
                "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
            },
        }
    )


# --------------------------------------------------------------------------- #
# Tổng quan — Tiến độ thu hồ sơ nhập học (theo khối, theo PIC)
# --------------------------------------------------------------------------- #
def _required_profile_types_by_grade() -> Dict[str, List[str]]:
    """Map target_grade (dạng số, '1'..'12') → danh sách profile_type bắt buộc theo cấu hình
    CRM Admission Profile Type (applicable_grades: JSON ["Khối 1", ...])."""
    profile_types = frappe.get_all(
        "CRM Admission Profile Type", fields=["profile_type", "applicable_grades"]
    )
    by_grade: Dict[str, List[str]] = defaultdict(list)
    for pt in profile_types:
        name = (pt.get("profile_type") or "").strip()
        raw = pt.get("applicable_grades")
        if not name or not raw:
            continue
        try:
            items = json.loads(raw)
        except Exception:
            continue
        if not isinstance(items, list):
            continue
        for it in items:
            s = str(it).strip()
            if s.startswith("Khối "):
                n = s[len("Khối ") :].strip()
                if n.isdigit():
                    by_grade[n].append(name)
    return by_grade



def _collected_profile_docs_by_lead(lead_names: List[str]) -> Dict[str, set]:
    """Loại hồ sơ đã thu của từng lead — có file đính kèm (`attachment`).

    Báo cáo «thu hồ sơ» đo mức đã nhận được tài liệu; checkbox `is_submitted` là bước
    xác nhận sau (NV thường upload trước, tick sau) nên không dùng làm tử số ở đây."""
    docs_by_lead: Dict[str, set] = defaultdict(set)
    if not lead_names:
        return docs_by_lead
    doc_rows = frappe.db.sql(
        """
        SELECT d.`parent` AS lead_name, d.`document_name` AS document_name
        FROM `tabCRM Lead Document` d
        WHERE d.`parenttype` = 'CRM Lead'
          AND d.`parent` IN %(leads)s
          AND IFNULL(TRIM(d.`attachment`), '') != ''
        """,
        {"leads": lead_names},
        as_dict=True,
    )
    for d in doc_rows:
        name = (d.get("document_name") or "").strip()
        if name:
            docs_by_lead[d["lead_name"]].add(name)
    return docs_by_lead


@frappe.whitelist()
def get_admission_profile_progress():
    """Tiến độ thu hồ sơ nhập học — tính theo đơn vị VĂN BẢN, tổng hợp theo khối dự tuyển và PIC.

    Phạm vi: CRM Lead đang ở bước QLead hoặc Enrolled (trạng thái HIỆN TẠI trên hồ sơ — không
    dùng snapshot as-of vì dễ bỏ sót HS Enrolled khi lịch sử chuyển bước thiếu hoặc nhập học
    sau ngày cuối kỳ cũ). Lọc kỳ: hồ sơ tạo trước hoặc bằng cuối kỳ (`to_date`).

    Mỗi hồ sơ: số văn bản cần nộp = số loại hồ sơ bắt buộc theo khối dự tuyển. Đã thu = có
    file đính kèm (`attachment`) trong `enrollment_documents`."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td_eff, _ = _overview_period_bounds(args)
    _, td_raw, _, _ = r._resolve_period(args)
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    required_by_grade = _required_profile_types_by_grade()
    period_meta = _overview_period_meta(fd, td_raw, td_eff)
    if not required_by_grade:
        return success_response(
            {
                "by_grade": [],
                "by_pic": [],
                "meta": {
                    "configured": False,
                    **period_meta,
                    "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
                },
            }
        )

    binds = {"to_date": str(td_eff), **dim_binds}
    # Lấy trực tiếp step hiện tại — đảm bảo HS Enrolled (và QLead) đang trên hệ thống được tính.
    # Không lọc khối trong SQL: khối resolve ở Python với fallback current_grade / SIS,
    # tránh loại nhầm HS nhập học trống target_grade.
    lead_rows = frappe.db.sql(
        f"""
        SELECT l.`name` AS name,
               IFNULL(TRIM(l.`target_grade`), '') AS target_grade,
               IFNULL(TRIM(l.`current_grade`), '') AS current_grade,
               IFNULL(TRIM(l.`linked_student`), '') AS linked_student,
               IFNULL(TRIM(l.`pic`), '') AS pic,
               l.`step` AS step
        FROM `tabCRM Lead` l
        WHERE l.`step` IN ('QLead', 'Enrolled')
          AND IFNULL(l.`status`, '') NOT IN ('Lost','Tu choi')
          AND DATE(l.`creation`) <= %(to_date)s
          AND {dim_sql}
        """,
        binds,
        as_dict=True,
    )
    _resolve_lead_grade_rows(lead_rows)
    # Chỉ giữ lead có khối thuộc cấu hình loại hồ sơ bắt buộc
    lead_rows = [row for row in lead_rows if row["grade"] in required_by_grade]

    scoped_lead_ids = [row["name"] for row in lead_rows]
    docs_by_lead = _collected_profile_docs_by_lead(scoped_lead_ids)

    grade_students: Dict[str, int] = defaultdict(int)
    grade_total_docs: Dict[str, int] = defaultdict(int)
    grade_completed_docs: Dict[str, int] = defaultdict(int)
    grade_students_done: Dict[str, int] = defaultdict(int)
    pic_students: Dict[str, int] = defaultdict(int)
    pic_total_docs: Dict[str, int] = defaultdict(int)
    pic_completed_docs: Dict[str, int] = defaultdict(int)
    step_counts: Dict[str, int] = defaultdict(int)

    for row in lead_rows:
        grade = row["grade"]
        required = required_by_grade.get(grade)
        if not required:
            continue
        step = (row.get("step") or "").strip()
        if step:
            step_counts[step] += 1
        have = docs_by_lead.get(row["name"], set())
        matched = sum(1 for doc_type in required if doc_type in have)
        needed = len(required)
        is_fully_done = matched == needed

        grade_students[grade] += 1
        grade_total_docs[grade] += needed
        grade_completed_docs[grade] += matched
        if is_fully_done:
            grade_students_done[grade] += 1

        pic = row.get("pic") or ""
        pic_key = pic if pic else "__unassigned__"
        pic_students[pic_key] += 1
        pic_total_docs[pic_key] += needed
        pic_completed_docs[pic_key] += matched

    def _grade_sort_key(g: str):
        try:
            return (0, int(g))
        except (TypeError, ValueError):
            return (1, g)

    by_grade = []
    for g in sorted(grade_students.keys(), key=_grade_sort_key):
        total = grade_total_docs[g]
        completed = grade_completed_docs.get(g, 0)
        by_grade.append(
            {
                "target_grade": g,
                "students": grade_students[g],
                "required_types": len(required_by_grade.get(g) or []),
                "students_completed": grade_students_done.get(g, 0),
                "total": total,
                "completed": completed,
                "pct": round(100.0 * completed / max(1, total), 2),
            }
        )

    user_map = r._batch_user_map(list(pic_students.keys()))
    by_pic = []
    for pic, students in pic_students.items():
        total = pic_total_docs[pic]
        completed = pic_completed_docs.get(pic, 0)
        if pic == "__unassigned__":
            pic_name = "Chưa gán PIC"
            pic_id = ""
        else:
            ud = user_map.get(pic, {})
            pic_name = ud.get("full_name") or pic
            pic_id = pic
        by_pic.append(
            {
                "pic": pic_id,
                "pic_name": pic_name,
                "students": students,
                "total": total,
                "completed": completed,
                "pct": round(100.0 * completed / max(1, total), 2),
            }
        )
    by_pic.sort(key=lambda x: x["total"], reverse=True)

    return success_response(
        {
            "by_grade": by_grade,
            "by_pic": by_pic,
            "meta": {
                "configured": True,
                **period_meta,
                "students_qlead": step_counts.get("QLead", 0),
                "students_enrolled": step_counts.get("Enrolled", 0),
                "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
            },
        }
    )


# --------------------------------------------------------------------------- #
# Tổng quan — Giới tính theo khối + phân bố Phường/Xã (HS chính thức Enrolled)
# --------------------------------------------------------------------------- #
def _normalize_lead_gender(raw: Optional[str]) -> str:
    """Chuẩn hóa giới tính CRM Lead → male / female / unknown."""
    val = (raw or "").strip()
    if val in ("Nam", "nam", "Male", "male"):
        return "male"
    if val in ("Nu", "Nữ", "nu", "Female", "female"):
        return "female"
    return "unknown"


@frappe.whitelist()
def get_enrolled_demographics():
    """Tỉ lệ Nam/Nữ theo khối và phân bố Phường/Xã của HS chính thức (Enrolled).

    Phạm vi: CRM Lead step = Enrolled, tạo trước hoặc bằng cuối kỳ lọc (`to_date`).
    Giới tính: `student_gender` (Nam/Nu). Địa chỉ: `current_address_ward` (nơi ở hiện nay).
    Khối: fallback target_grade → current_grade → lớp SIS qua linked_student.
    """
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td_eff, _ = _overview_period_bounds(args)
    _, td_raw, _, _ = r._resolve_period(args)
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)
    period_meta = _overview_period_meta(fd, td_raw, td_eff)

    lead_rows = frappe.db.sql(
        f"""
        SELECT l.`name` AS name,
               IFNULL(TRIM(l.`student_gender`), '') AS student_gender,
               IFNULL(TRIM(l.`current_address_ward`), '') AS current_address_ward,
               IFNULL(TRIM(l.`current_address_ward_name`), '') AS current_address_ward_name,
               IFNULL(TRIM(l.`target_grade`), '') AS target_grade,
               IFNULL(TRIM(l.`current_grade`), '') AS current_grade,
               IFNULL(TRIM(l.`linked_student`), '') AS linked_student
        FROM `tabCRM Lead` l
        WHERE l.`step` = 'Enrolled'
          AND IFNULL(l.`status`, '') NOT IN ('Lost','Tu choi')
          AND DATE(l.`creation`) <= %(to_date)s
          AND {dim_sql}
        """,
        {"to_date": str(td_eff), **dim_binds},
        as_dict=True,
    )
    _resolve_lead_grade_rows(lead_rows)

    gender_by_grade_map: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"male": 0, "female": 0, "unknown": 0, "total": 0}
    )
    ward_counts: Dict[str, int] = defaultdict(int)
    ward_names: Dict[str, str] = {}

    for row in lead_rows:
        grade = row.get("grade") or "-"
        bucket = gender_by_grade_map[grade]
        gender_key = _normalize_lead_gender(row.get("student_gender"))
        bucket[gender_key] += 1
        bucket["total"] += 1

        ward_raw = (row.get("current_address_ward") or "").strip()
        ward_key = ward_raw if ward_raw else "(Chưa có)"
        ward_counts[ward_key] += 1
        # Ưu tiên tên phường/xã (fetch từ ERP Ward) để hiển thị thay vì mã
        ward_name = (row.get("current_address_ward_name") or "").strip()
        if ward_name and ward_key not in ward_names:
            ward_names[ward_key] = ward_name

    gender_by_grade = []
    for g in sorted(gender_by_grade_map.keys(), key=_grade_display_sort_key):
        m = gender_by_grade_map[g]
        gender_by_grade.append(
            {
                "target_grade": g,
                "male": m["male"],
                "female": m["female"],
                "unknown": m["unknown"],
                "total": m["total"],
            }
        )

    by_ward = [
        {"ward": ward, "ward_name": ward_names.get(ward, ""), "count": count}
        for ward, count in sorted(ward_counts.items(), key=lambda x: (-x[1], x[0].lower()))
    ]

    return success_response(
        {
            "gender_by_grade": gender_by_grade,
            "by_ward": by_ward,
            "meta": {
                **period_meta,
                "total_enrolled": len(lead_rows),
                "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
            },
        }
    )
