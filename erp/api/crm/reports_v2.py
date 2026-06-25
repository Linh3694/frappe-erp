# -*- coding: utf-8 -*-
"""
CRM Reports V2 API — báo cáo Tuyển Sinh (UI-v2), bổ sung cho erp.api.crm.reports.

Các endpoint mới phục vụ 5 tab: Tổng quan (trạng thái theo khối + danh sách công
việc), Hoạt động (sự kiện + khóa học + khảo sát đầu vào), KPI (tái dùng reports.get_breakdown_by_pic),
Nguồn (nguồn 1/2/3), Tái ghi danh (tái dùng erp_sis.re_enrollment).

Tái sử dụng helper từ reports.py: phân quyền theo vai trò (PIC chỉ xem của mình),
khoảng thời gian, bộ lọc chiều + bộ lọc động trên trường CRM Lead.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import frappe

from erp.utils.api_response import paginated_response, success_response
from erp.api.crm.utils import check_crm_permission, STEP_STATUSES, QLEAD_TEST_STATUSES
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
        if row["step"] == "Draft":
            key = _NEW_PROFILE_DRAFT_KEY
        else:
            key = f"{row['step']}|status|{row['status']}"
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

    # Dựng cấu trúc nhóm cột (bước → nhóm con → cột trạng thái)
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
                     skip_campus_filter: bool = False) -> Dict[str, Any]:
    fd, td, _, _ = r._resolve_period(args)
    match_sql, match_binds = _activity_student_lead_match(args, "es", "act")

    # Kỳ khảo sát có thể chưa gán ngày thi — fallback creation để không bị loại khỏi báo cáo
    date_expr = (
        f"COALESCE(e.`{date_field}`, DATE(e.`creation`))"
        if date_coalesce
        else f"e.`{date_field}`"
    )
    ev_where = [f"DATE({date_expr}) BETWEEN %(d_from)s AND %(d_to)s"]
    binds: Dict[str, Any] = {"d_from": fd, "d_to": td, **match_binds}

    campus_id = (args.get("campus_id") or "").strip()
    if campus_id and not skip_campus_filter:
        binds["e_campus"] = campus_id
        ev_where.append("e.`campus_id` = %(e_campus)s")
    tay = (args.get("target_academic_year") or "").strip()
    if tay:
        binds["e_year"] = tay
        ev_where.append("e.`school_year_id` = %(e_year)s")

    where_clause = " AND ".join(ev_where)
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
        ORDER BY {date_expr} DESC
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
            # Kỳ khảo sát thường không gán campus trên header — tránh lọc mất dòng khi sidebar chọn campus
            skip_campus_filter=True,
            statuses=_ENTRANCE_EXAM_STUDENT_STATUSES,
        )
    )


# --------------------------------------------------------------------------- #
# Nguồn — Danh sách Nguồn 1 × bước, lọc theo 3 cấp nguồn (Nguồn 1/2/3)
# --------------------------------------------------------------------------- #
# Bước hiển thị trong báo cáo nguồn / PIC — đủ 6 bước snapshot (khác grade report gộp Draft+Verify)
_SOURCE_REPORT_STEPS = ["Draft", "Verify", "Lead", "QLead", "Enrolled", "Nghi hoc"]
_SOURCE_STEPS_SQL = "('Lead','QLead','Enrolled','Nghi hoc','Verify','Draft')"


@frappe.whitelist()
def get_source_breakdown():
    """Danh sách Nguồn 1 (snapshot) × bước + tỉ lệ chuyển đổi; lọc theo Nguồn 1/2/3.

    Mỗi dòng = 1 Nguồn 1 (CRM Source). Cột: số hồ sơ (tổng), số ở từng bước
    (Lead/QLead/Nhập học/Nghỉ học/Xác minh/Nháp), tỉ lệ chuyển đổi = Nhập học / tổng.
    3 dropdown (src1/src2/src3) lọc hồ sơ theo cùng dòng nguồn con; options 3 cấp
    tính trên phạm vi chiều, KHÔNG bị thu hẹp bởi chính lựa chọn (để còn đổi lựa chọn).
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

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(ls.`source`), ''), '(Trống)') AS src,
               l.`step` AS step,
               COUNT(DISTINCT l.`name`) AS cnt
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE l.`step` IN {_SOURCE_STEPS_SQL} AND {dim_sql}{src_sql}
        GROUP BY src, l.`step`
        """,
        binds,
        as_dict=True,
    )

    by_src: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in rows:
        by_src[row["src"]][row["step"]] = int(row["cnt"])
    src_ids = [k for k in by_src if k and k != "(Trống)"]
    src_labels = r._batch_source_names(src_ids)

    out = []
    for src, steps in by_src.items():
        total = sum(steps.values())
        enrolled = steps.get("Enrolled", 0)
        out.append(
            {
                "key": src,
                "label": src_labels.get(src, src),
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

    # by_member
    all_pics = set(member_targets_map.keys()) | set(actual_by_pic.keys())
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
