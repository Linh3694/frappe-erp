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
_DEAL_STATUS_ORDER = ["Dat cho", "Dat coc", "Dong phi", "Hoan phi", "Bao luu/Chuyen", "Tu choi"]


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
            if deal_vals:
                dv = _order_status_values(deal_vals, _DEAL_STATUS_ORDER)
                sections.append(
                    {
                        "field": "deal_status",
                        "columns": [{"key": f"QLead|deal_status|{v}", "status": v} for v in dv],
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
    deal_rows = _qlead_sub_rows("deal_status")

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

    deal_vals: set = set()
    for row in deal_rows:
        deal_vals.add(row["val"])
        values_by_grade[row["grade"]][f"QLead|deal_status|{row['val']}"] = int(row["cnt"])

    groups = _build_status_report_groups(step_statuses, test_vals, deal_vals)

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
    deal_rows = _qlead_sub_rows_by_src("deal_status")

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

    deal_vals: set = set()
    for row in deal_rows:
        deal_vals.add(row["val"])
        values_by_src[row["src"]][f"QLead|deal_status|{row['val']}"] = int(row["cnt"])

    groups = _build_status_report_groups(step_statuses, test_vals, deal_vals)
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
# Tổng quan — Snapshot as-of (trạng thái tại ngày cuối kỳ, tái dựng từ lịch sử)
# --------------------------------------------------------------------------- #
# Thứ tự hiển thị phễu trạng thái QLead (trạng thái chính, không phải test/deal_status)
_QLEAD_FUNNEL_ORDER = ["Dang cham soc", "Dat lich hen", "Thoa thuan", "Khao sat dau vao", "Lost"]


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
                   IFNULL(NULLIF(TRIM(l.`target_grade`), ''), '-') AS target_grade
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
        SELECT bl.lead_id, bl.target_grade,
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
    _, td, _, _ = r._resolve_period(args)
    as_of_end = f"{td} 23:59:59.999999"
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    rows = _as_of_state_rows(as_of_end, dim_sql, dim_binds)

    funnel_counts: Dict[str, int] = defaultdict(int)
    grade_steps: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    grade_qlead_status: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for row in rows:
        grade = row["target_grade"]
        step = row["as_of_step"] or ""
        status = (row["as_of_status"] or "").strip()

        if step == "Draft":
            grade_steps[grade]["draft"] += 1
        elif step == "Lead":
            if status == "Lost":
                grade_steps[grade]["lost"] += 1
            else:
                grade_steps[grade]["lead"] += 1
        elif step == "QLead":
            if status == "Lost":
                grade_steps[grade]["lost"] += 1
            else:
                grade_steps[grade]["qlead"] += 1
            if status:
                funnel_counts[status] += 1
                grade_qlead_status[grade][status] += 1
        elif step == "Enrolled":
            grade_steps[grade]["enrolled"] += 1

    def _grade_sort_key(g: str):
        try:
            return (0, int(g))
        except (TypeError, ValueError):
            return (1, g)

    funnel = [
        {"status": st, "count": funnel_counts.get(st, 0)}
        for st in _order_status_values(set(funnel_counts.keys()), _QLEAD_FUNNEL_ORDER)
    ]

    by_grade_steps = []
    for g in sorted(grade_steps.keys(), key=_grade_sort_key):
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
        for g in sorted(grade_qlead_status.keys(), key=_grade_sort_key)
    ]

    return success_response(
        {
            "funnel_qlead": funnel,
            "by_grade_steps": by_grade_steps,
            "by_grade_qlead_status": by_grade_qlead_status,
            "meta": {
                "as_of": str(td),
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


@frappe.whitelist()
def get_admission_profile_progress():
    """Tiến độ thu hồ sơ nhập học — tính theo ĐƠN VỊ VĂN BẢN (không phải theo HS), vì đếm
    theo HS hoàn thiện 100% sẽ luôn ~0% trong lúc đang thu thập dần từng loại. Phạm vi
    (mẫu số): CRM Lead có target_grade thuộc khối yêu cầu hồ sơ (theo cấu hình CRM Admission
    Profile Type) và `step = 'Enrolled'` (HS chính thức — đây là lúc cần nộp hồ sơ nhập học,
    không tính HS đang ở bước QLead vì chưa tới hạn nộp).

    Tổng cần (total) = số HS chính thức trong khối × số loại hồ sơ bắt buộc của khối đó.
    Ví dụ: 1515 HS, mỗi HS cần 3 loại hồ sơ → tổng cần = 1515 x 3 = 4545 văn bản.
    Đã thu (completed) = tổng số loại hồ sơ đã có tài liệu đính kèm (`attachment`) trong
    `enrollment_documents`, cộng dồn qua tất cả HS (không phụ thuộc checkbox `is_submitted`,
    vì thực tế nhân viên thường chỉ upload mà không tick riêng). Mỗi loại hồ sơ của 1 HS chỉ
    tính tối đa 1 (dù có nhiều file) — 1 học sinh cần đủ cả 3 loại thì mới tính là 3/3."""
    check_crm_permission()
    args = frappe.request.args or {}
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    required_by_grade = _required_profile_types_by_grade()
    grades_in_scope = sorted(required_by_grade.keys(), key=lambda g: int(g))
    if not grades_in_scope:
        return success_response(
            {
                "by_grade": [],
                "by_pic": [],
                "meta": {
                    "configured": False,
                    "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
                },
            }
        )

    binds = {"grades": grades_in_scope, **dim_binds}
    lead_rows = frappe.db.sql(
        f"""
        SELECT l.`name` AS name,
               l.`target_grade` AS target_grade,
               IFNULL(TRIM(l.`pic`), '') AS pic
        FROM `tabCRM Lead` l
        WHERE l.`step` = 'Enrolled'
          AND l.`target_grade` IN %(grades)s
          AND {dim_sql}
        """,
        binds,
        as_dict=True,
    )

    # Tài liệu đã đính kèm theo lead — chỉ cần có attachment, không xét is_submitted
    docs_by_lead: Dict[str, set] = defaultdict(set)
    lead_names = [row["name"] for row in lead_rows]
    if lead_names:
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

    grade_students: Dict[str, int] = defaultdict(int)
    grade_total_docs: Dict[str, int] = defaultdict(int)
    grade_completed_docs: Dict[str, int] = defaultdict(int)
    grade_students_done: Dict[str, int] = defaultdict(int)
    pic_students: Dict[str, int] = defaultdict(int)
    pic_total_docs: Dict[str, int] = defaultdict(int)
    pic_completed_docs: Dict[str, int] = defaultdict(int)

    for row in lead_rows:
        grade = (row.get("target_grade") or "").strip()
        required = required_by_grade.get(grade)
        if not required:
            continue
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
        if pic:
            pic_students[pic] += 1
            pic_total_docs[pic] += needed
            pic_completed_docs[pic] += matched

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
        ud = user_map.get(pic, {})
        by_pic.append(
            {
                "pic": pic,
                "pic_name": ud.get("full_name") or pic,
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
                "pic_restricted_to_self": r._should_restrict_to_own_pic_only(),
            },
        }
    )
