# -*- coding: utf-8 -*-
"""
CRM Reports V2 API — báo cáo Tuyển Sinh (UI-v2), bổ sung cho erp.api.crm.reports.

Các endpoint mới phục vụ 5 tab: Tổng quan (trạng thái theo khối + danh sách công
việc), Hoạt động (sự kiện + khóa học), KPI (tái dùng reports.get_breakdown_by_pic),
Nguồn (nguồn 1/2/3), Tái ghi danh (tái dùng erp_sis.re_enrollment).

Tái sử dụng helper từ reports.py: phân quyền theo vai trò (PIC chỉ xem của mình),
khoảng thời gian, bộ lọc chiều + bộ lọc động trên trường CRM Lead.
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe

from erp.utils.api_response import paginated_response, success_response
from erp.api.crm.utils import check_crm_permission
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

# Bước CRM hiển thị trong báo cáo trạng thái theo khối
_GRADE_REPORT_STEPS = ["Lead", "QLead", "Enrolled", "Nghi hoc", "Verify", "Draft"]

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
    """Số lượng CRM Lead hiện tại theo khối (target_grade) × bước (step)."""
    check_crm_permission()
    args = frappe.request.args or {}
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(l.`target_grade`), ''), '-') AS grade,
               l.`step` AS step,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE l.`step` IN ('Lead','QLead','Enrolled','Nghi hoc','Verify','Draft')
          AND {dim_sql}
        GROUP BY grade, l.`step`
        """,
        dim_binds,
        as_dict=True,
    )

    grade_map: Dict[str, Dict[str, int]] = {}
    for row in rows:
        g = row["grade"]
        grade_map.setdefault(g, {})
        grade_map[g][row["step"]] = int(row["cnt"])

    def _grade_sort_key(g: str):
        try:
            return (0, int(g))
        except (TypeError, ValueError):
            return (1, g)

    out_rows = []
    for g in sorted(grade_map.keys(), key=_grade_sort_key):
        by_step = grade_map[g]
        total = sum(by_step.values())
        out_rows.append(
            {
                "target_grade": g,
                "by_step": {s: by_step.get(s, 0) for s in _GRADE_REPORT_STEPS},
                "total": total,
            }
        )

    return success_response(
        {
            "steps": _GRADE_REPORT_STEPS,
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
                     name_field: str, statuses: List[str]) -> Dict[str, Any]:
    fd, td, _, _ = r._resolve_period(args)
    match_sql, match_binds = _activity_student_lead_match(args, "es", "act")

    ev_where = ["DATE(e.`event_date`) BETWEEN %(d_from)s AND %(d_to)s"]
    binds: Dict[str, Any] = {"d_from": fd, "d_to": td, **match_binds}

    campus_id = (args.get("campus_id") or "").strip()
    if campus_id:
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
        SELECT e.`name`, e.`{name_field}` AS title, e.`event_date`,
               e.`campus_id`, e.`school_year_id`, e.`is_active`, e.`student_count`,
               SUM(CASE WHEN es.`name` IS NOT NULL AND {match_sql} THEN 1 ELSE 0 END) AS matched_total,
               {status_cols}
        FROM `tab{doctype}` e
        LEFT JOIN `tab{student_doctype}` es ON es.`{student_fk}` = e.`name`
        WHERE {where_clause}
        GROUP BY e.`name`
        ORDER BY e.`event_date` DESC
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


# --------------------------------------------------------------------------- #
# Nguồn — Thống kê theo Nguồn 1 (source) / Nguồn 2 (sub_source) / Nguồn 3 (source_note)
# --------------------------------------------------------------------------- #
def _source_level_breakdown(args, level_field: str) -> List[Dict[str, Any]]:
    """Tổng & nhập học theo 1 cấp nguồn (cột con trên tabCRM Lead Source)."""
    fd, td, _, _ = r._resolve_period(args)
    wsql, binds = r._where_creation_between(fd, td, args)
    dim_sql, dim_binds = r._where_lead_dimensions_only(args)
    eb = {"d_from": fd, "d_to": td, **dim_binds}

    total_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(ls.`{level_field}`), ''), '(Trống)') AS k,
               COUNT(DISTINCT l.`name`) AS total_count
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE {wsql}
        GROUP BY k
        ORDER BY total_count DESC
        LIMIT 200
        """,
        binds,
        as_dict=True,
    )

    enrolled_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(ls.`{level_field}`), ''), '(Trống)') AS k,
               COUNT(DISTINCT ev.lead_id) AS enrolled_count
        FROM (
            SELECT h.`lead` AS lead_id FROM `tabCRM Lead Step History` h
            INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
            WHERE h.`new_step` = 'Enrolled'
              AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
            UNION
            SELECT l.`name` FROM `tabCRM Lead` l
            WHERE l.`step` = 'Enrolled' AND l.`enrollment_date` IS NOT NULL
              AND DATE(l.`enrollment_date`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
        ) ev
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = ev.lead_id
        GROUP BY k
        """,
        eb,
        as_dict=True,
    )
    enrolled_map = {row["k"]: int(row["enrolled_count"]) for row in enrolled_rows}

    # Resolve nhãn cho cấp là Link (source → CRM Source, source_note → CRM Source Note)
    keys = [row["k"] for row in total_rows if row["k"] and row["k"] != "(Trống)"]
    label_map: Dict[str, str] = {}
    if level_field == "source":
        label_map = r._batch_source_names(keys)
    elif level_field == "source_note" and keys:
        for n in frappe.get_all(
            "CRM Source Note", filters={"name": ["in", keys]},
            fields=["name", "note_name"],
        ):
            label_map[n["name"]] = n.get("note_name") or n["name"]

    out = []
    for row in total_rows:
        k = row["k"]
        tot = int(row["total_count"])
        ec = enrolled_map.get(k, 0)
        out.append(
            {
                "key": k,
                "label": label_map.get(k, k),
                "count_total": tot,
                "count_enrolled": ec,
                "conversion_rate_pct": round(100.0 * ec / max(1, tot), 2),
            }
        )
    return out


@frappe.whitelist()
def get_source_levels():
    """Thống kê nguồn 1/2/3."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = r._resolve_period(args)
    return success_response(
        {
            "by_source": _source_level_breakdown(args, "source"),
            "by_sub_source": _source_level_breakdown(args, "sub_source"),
            "by_source_note": _source_level_breakdown(args, "source_note"),
            "meta": {
                "period": {"from": str(fd), "to": str(td)},
                "labels": {
                    "by_source": "Nguồn 1",
                    "by_sub_source": "Nguồn 2",
                    "by_source_note": "Nguồn 3",
                },
            },
        }
    )
