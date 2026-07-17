# -*- coding: utf-8 -*-
"""
CRM Reports API — dashboard báo cáo tuyển sinh (CRM Lead).
Nguồn: tabCRM Lead, tabCRM Lead Step History, tabCRM Lead Source.
Số liệu vận hành theo ngày sự kiện (changed_at); hồ sơ mới = bước Draft (tab Dữ liệu) theo ngày nhập.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import frappe

from erp.utils.api_response import paginated_response, success_response
from erp.api.crm.utils import check_crm_permission

_ELEVATED_PIC_VIEW_ROLES = frozenset(
    {
        "System Manager",
        "SIS Manager",
        "SIS Sales Admin",
        "SIS Sales Care Admin",
        "Registrar",
        "SIS BOD",
    }
)
_RESTRICT_PIC_ROLES = frozenset({"SIS Sales", "SIS Sales Care"})

# Mốc phễu cohort (lead vào Lead trong kỳ → từng đạt mốc)
FUNNEL_STAGES: List[Dict[str, Any]] = [
    {"key": "lead", "label": "Học sinh quan tâm", "kind": "cohort"},
    {"key": "qlead", "label": "Học sinh tiềm năng", "kind": "step", "value": "QLead"},
    {
        "key": "test_attended",
        "label": "Khảo sát — Tham gia",
        "kind": "sub_status",
        "field": "test_status",
        "value": "Tham gia",
    },
    {
        "key": "test_proposed",
        "label": "Khảo sát — Đề xuất",
        "kind": "sub_status",
        "field": "test_status",
        "value": "De xuat",
    },
    {
        "key": "deal_committed",
        "label": "Thoả thuận (Đặt cọc / Đóng phí)",
        "kind": "deal_status_in",
        "values": ["Dat coc", "Dong phi"],
    },
    {"key": "enrolled", "label": "Nhập học", "kind": "step", "value": "Enrolled"},
]


def _should_restrict_to_own_pic_only() -> bool:
    roles = set(frappe.get_roles(frappe.session.user))
    if roles.intersection(_ELEVATED_PIC_VIEW_ROLES):
        return False
    return bool(roles.intersection(_RESTRICT_PIC_ROLES))


def _effective_pic_from_request(raw_pic: Optional[str]) -> Optional[str]:
    if _should_restrict_to_own_pic_only():
        return frappe.session.user
    s = (raw_pic or "").strip()
    return s or None


def _parse_date_range(args) -> Tuple[Any, Any]:
    from frappe.utils import getdate

    fd = getdate(args.get("from_date")) if args.get("from_date") else None
    td = getdate(args.get("to_date")) if args.get("to_date") else None
    if not td:
        td = getdate(datetime.utcnow())
    if not fd:
        fd = td - timedelta(days=29)
    if fd > td:
        fd, td = td, fd
    return fd, td


def _resolve_period(args) -> Tuple[Any, Any, Any, Any]:
    """Trả về (from, to, prev_from, prev_to) — kỳ trước cùng độ dài / cùng khung lịch."""
    from frappe.utils import add_to_date, get_last_day, getdate

    fd, td = _parse_date_range(args)
    fd, td = getdate(fd), getdate(td)
    gran = (args.get("compare_granularity") or "").strip().lower()

    if gran == "year":
        pdf = getdate(add_to_date(fd, years=-1))
        pdt = getdate(add_to_date(td, years=-1))
    elif gran == "month":
        pdf = getdate(add_to_date(fd, months=-1))
        pdt = getdate(add_to_date(td, months=-1))
        if td == get_last_day(td):
            pdt = get_last_day(pdf)
    else:
        # day / week — lùi đúng 1 bucket liền kề (hôm qua, tuần trước, …)
        span_days = (td - fd).days + 1
        pdt = getdate(add_to_date(fd, days=-1))
        pdf = getdate(add_to_date(pdt, days=-(span_days - 1)))

    return fd, td, pdf, pdt


def _append_dimension_filters(
    where_parts: List[str],
    binds: Dict[str, Any],
    args,
    alias: str = "l",
    prefix: str = "",
) -> None:
    """Bộ lọc chiều campus/pic/năm/khối/nguồn/referrer/data_source."""
    p = prefix or ""

    campus_id = (args.get("campus_id") or "").strip()
    if campus_id:
        binds[f"{p}_campus"] = campus_id
        where_parts.append(f"{alias}.`campus_id` = %({p}_campus)s")

    pic_eff = _effective_pic_from_request(args.get("pic"))
    if pic_eff:
        # Khop CA HAI cot: ho so nguoi nay phu trach o bat ky vai tro nao (quyet dinh 2.2/2.3).
        # Khong loc rieng theo role vi pic_sales KHONG rang buoc role — nguoi Care van co the
        # giu pic_sales (chuyen tay / cham hoc sinh chinh thuc), loc theo role se lam mat so lieu.
        binds[f"{p}_pic"] = pic_eff
        where_parts.append(
            f"({alias}.`pic_sales` = %({p}_pic)s OR {alias}.`pic_care` = %({p}_pic)s)"
        )

    tay = (args.get("target_academic_year") or "").strip()
    if tay:
        binds[f"{p}_tay"] = tay
        where_parts.append(f"{alias}.`target_academic_year` = %({p}_tay)s")

    tg = (args.get("target_grade") or "").strip()
    if tg:
        binds[f"{p}_tg"] = tg
        where_parts.append(f"{alias}.`target_grade` = %({p}_tg)s")

    referrer = (args.get("referrer") or "").strip()
    if referrer:
        binds[f"{p}_ref"] = referrer
        where_parts.append(f"{alias}.`referrer` = %({p}_ref)s")

    ds = (args.get("data_source") or "").strip()
    if ds:
        binds[f"{p}_ds"] = ds
        where_parts.append(f"{alias}.`data_source` = %({p}_ds)s")

    source = (args.get("source") or "").strip()
    if source:
        binds[f"{p}_src"] = source
        where_parts.append(
            f"EXISTS (SELECT 1 FROM `tabCRM Lead Source` s "
            f"WHERE s.`parent` = {alias}.`name` AND s.`source` = %({p}_src)s)"
        )

    _append_dynamic_lead_filters(where_parts, binds, args, alias, prefix)


# Toán tử filter động (đồng bộ FilterOperator phía frontend) → SQL
_DYNAMIC_OP_MAP: Dict[str, str] = {
    "is": "=",
    "is_not": "!=",
    "contains": "LIKE",
    "not_contains": "NOT LIKE",
    "starts_with": "LIKE",
    "ends_with": "LIKE",
    "gt": ">",
    "lt": "<",
    "gte": ">=",
    "lte": "<=",
}
_DYNAMIC_LIKE_OPS = {"contains", "not_contains", "starts_with", "ends_with"}


def _crm_lead_valid_columns() -> set:
    """Cột DB hợp lệ của CRM Lead (whitelist cho filter động)."""
    try:
        return set(frappe.get_meta("CRM Lead").get_valid_columns())
    except Exception:
        return set()


def _parse_lead_filters(args) -> List[Dict[str, Any]]:
    raw = args.get("lead_filters")
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        try:
            items = json.loads(raw)
        except Exception:
            return []
    return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []


def _append_dynamic_lead_filters(
    where_parts: List[str],
    binds: Dict[str, Any],
    args,
    alias: str = "l",
    prefix: str = "",
) -> None:
    """Filter động trên trường CRM Lead bất kỳ (validate theo meta, bind tham số)."""
    items = _parse_lead_filters(args)
    if not items:
        return
    valid_cols = _crm_lead_valid_columns()
    if not valid_cols:
        return
    p = prefix or ""
    for idx, cond in enumerate(items):
        field = str(cond.get("field") or cond.get("column") or "").strip()
        op = str(cond.get("operator") or "is").strip()
        if field not in valid_cols or op not in _DYNAMIC_OP_MAP:
            continue
        value = cond.get("value")
        if value is None or value == "":
            # cho phép is/is_not '' để lọc rỗng; còn lại bỏ qua
            if op not in ("is", "is_not"):
                continue
        if isinstance(value, bool):
            value = 1 if value else 0
        sql_op = _DYNAMIC_OP_MAP[op]
        bind_key = f"{p}_dyn_{idx}"
        if op in _DYNAMIC_LIKE_OPS:
            v = str(value)
            if op in ("contains", "not_contains"):
                value = f"%{v}%"
            elif op == "starts_with":
                value = f"{v}%"
            else:  # ends_with
                value = f"%{v}"
        binds[bind_key] = value
        where_parts.append(f"{alias}.`{field}` {sql_op} %({bind_key})s")


def _where_creation_between(date_from: Any, date_to: Any, args) -> Tuple[str, Dict[str, Any]]:
    where_parts = ["DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s"]
    binds: Dict[str, Any] = {"d_from": date_from, "d_to": date_to}
    _append_dimension_filters(where_parts, binds, args, "l")
    return " AND ".join(where_parts), binds


def _where_lead_dimensions_only(args, alias: str = "l") -> Tuple[str, Dict[str, Any]]:
    where_parts: List[str] = ["1=1"]
    binds: Dict[str, Any] = {}
    _append_dimension_filters(where_parts, binds, args, alias)
    return " AND ".join(where_parts), binds


def _full_image(user_image):
    if not user_image:
        return None
    su = str(user_image)
    if su.startswith("http"):
        return su
    path = su if su.startswith("/") else "/files/" + su
    try:
        return frappe.utils.get_url(path)
    except Exception:
        return su


def _batch_user_map(emails: List[str]) -> Dict[str, Dict[str, Any]]:
    """Gom User một lần — tránh N+1."""
    uniq = list({e.strip() for e in emails if e and str(e).strip()})
    if not uniq:
        return {}
    rows = frappe.get_all(
        "User",
        filters={"name": ["in", uniq]},
        fields=["name", "full_name", "user_image"],
    )
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        out[r["name"]] = {
            "full_name": r.get("full_name") or r["name"],
            "pic_avatar": _full_image(r.get("user_image")),
        }
    return out


def _batch_referrer_names(referrer_ids: List[str]) -> Dict[str, str]:
    uniq = list({x.strip() for x in referrer_ids if x and str(x).strip()})
    if not uniq:
        return {}
    rows = frappe.get_all(
        "CRM Referrer",
        filters={"name": ["in", uniq]},
        fields=["name", "referrer_name"],
    )
    return {r["name"]: (r.get("referrer_name") or r["name"]) for r in rows}


def _batch_source_names(source_ids: List[str]) -> Dict[str, str]:
    uniq = list({x.strip() for x in source_ids if x and str(x).strip()})
    if not uniq:
        return {}
    rows = frappe.get_all(
        "CRM Source",
        filters={"name": ["in", uniq]},
        fields=["name", "source_name"],
    )
    return {r["name"]: (r.get("source_name") or r["name"]) for r in rows}


def _pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None:
        return None
    if prev == 0:
        if curr == 0:
            return 0.0
        return 100.0
    return round(100.0 * (curr - prev) / prev, 1)


def _include_tu_choi_lost(args) -> bool:
    v = (args.get("include_tu_choi") or "").strip().lower()
    return v in ("1", "true", "yes")


def _lost_event_condition(include_tu_choi: bool) -> str:
    # Lost -> Tu choi (rename toan he thong): match ca 'Lost' (history cu) lan 'Tu choi' (moi)
    if include_tu_choi:
        return (
            "(IFNULL(h.`new_status`,'') IN ('Lost','Tu choi') "
            "OR IFNULL(h.`new_status`,'') LIKE '%:Tu choi')"
        )
    return "IFNULL(h.`new_status`,'') IN ('Lost','Tu choi')"


def _count_new_leads(date_from: Any, date_to: Any, args) -> int:
    """Hồ sơ mới: bước Draft (tab Dữ liệu), nhập trong kỳ — chưa chuyển Lead."""
    wsql, binds = _where_creation_between(date_from, date_to, args)
    return int(
        frappe.db.sql(
            f"SELECT COUNT(*) FROM `tabCRM Lead` l WHERE {wsql} AND l.`step` = 'Draft'",
            binds,
        )[0][0]
    )


def _count_total_profiles(date_from: Any, date_to: Any, args) -> int:
    """Tổng hồ sơ: mọi hồ sơ (CRM Lead) tạo trong kỳ, không phân biệt bước."""
    wsql, binds = _where_creation_between(date_from, date_to, args)
    return int(
        frappe.db.sql(
            f"SELECT COUNT(*) FROM `tabCRM Lead` l WHERE {wsql}",
            binds,
        )[0][0]
    )


def _count_enrolled_events(date_from: Any, date_to: Any, args) -> int:
    """Distinct lead nhập học trong kỳ (history + fallback enrollment_date)."""
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": date_from, "d_to": date_to, **dim_binds}
    row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT t.lead_id) FROM (
            SELECT h.`lead` AS lead_id
            FROM `tabCRM Lead Step History` h
            INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
            WHERE h.`new_step` = 'Enrolled'
              AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
            UNION
            SELECT l.`name` AS lead_id
            FROM `tabCRM Lead` l
            WHERE l.`step` = 'Enrolled'
              AND l.`enrollment_date` IS NOT NULL
              AND DATE(l.`enrollment_date`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
              AND NOT EXISTS (
                  SELECT 1 FROM `tabCRM Lead Step History` hx
                  WHERE hx.`lead` = l.`name` AND hx.`new_step` = 'Enrolled'
              )
        ) t
        """,
        binds,
    )[0][0]
    return int(row or 0)


def _count_lost_events(date_from: Any, date_to: Any, args) -> int:
    include_tc = _include_tu_choi_lost(args)
    lost_cond = _lost_event_condition(include_tc)
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": date_from, "d_to": date_to, **dim_binds}
    row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT h.`lead`)
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
          AND {lost_cond}
          AND {dim_sql}
        """,
        binds,
    )[0][0]
    return int(row or 0)


def _count_active_pipeline(args) -> int:
    """Snapshot: đang chăm sóc (Lead/QLead, chưa Lost)."""
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    row = frappe.db.sql(
        f"""
        SELECT COUNT(*)
        FROM `tabCRM Lead` l
        WHERE l.`step` IN ('Lead', 'QLead')
          AND IFNULL(TRIM(l.`status`), '') NOT IN ('Lost', 'Tu choi')
          AND {dim_sql}
        """,
        dim_binds,
    )[0][0]
    return int(row or 0)


def _count_leads_entered_pipeline(date_from: Any, date_to: Any, args) -> int:
    """Lead vào phễu (đạt Lead) trong kỳ — mẫu số tỷ lệ chuyển đổi."""
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": date_from, "d_to": date_to, **dim_binds}
    row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT t.lead_id) FROM (
            SELECT h.`lead` AS lead_id
            FROM `tabCRM Lead Step History` h
            INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
            WHERE h.`new_step` = 'Lead'
              AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
            UNION
            SELECT l.`name` AS lead_id
            FROM `tabCRM Lead` l
            WHERE DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s
              AND l.`step` IN ('Lead', 'QLead', 'Enrolled', 'Nghi hoc')
              AND {dim_sql}
              AND NOT EXISTS (
                  SELECT 1 FROM `tabCRM Lead Step History` hx
                  WHERE hx.`lead` = l.`name` AND hx.`new_step` = 'Lead'
              )
        ) t
        """,
        binds,
    )[0][0]
    return int(row or 0)


def _avg_days_to_enroll(date_from: Any, date_to: Any, args) -> Optional[float]:
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": date_from, "d_to": date_to, **dim_binds}
    row = frappe.db.sql(
        f"""
        SELECT AVG(
            DATEDIFF(
                COALESCE(
                    (SELECT MIN(DATE(h2.`changed_at`))
                     FROM `tabCRM Lead Step History` h2
                     WHERE h2.`lead` = l.`name` AND h2.`new_step` = 'Enrolled'),
                    l.`enrollment_date`
                ),
                DATE(l.`creation`)
            )
        ) AS avg_days
        FROM `tabCRM Lead` l
        WHERE (
            EXISTS (
                SELECT 1 FROM `tabCRM Lead Step History` h
                WHERE h.`lead` = l.`name`
                  AND h.`new_step` = 'Enrolled'
                  AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
            )
            OR (
                l.`step` = 'Enrolled'
                AND l.`enrollment_date` IS NOT NULL
                AND DATE(l.`enrollment_date`) BETWEEN %(d_from)s AND %(d_to)s
            )
        )
        AND {dim_sql}
        """,
        binds,
        as_dict=True,
    )
    avg = row[0].get("avg_days") if row else None
    return None if avg is None else round(float(avg), 2)


def _count_qlead_events(date_from: Any, date_to: Any, args) -> int:
    """Học sinh tiềm năng — đạt QLead trong kỳ (sự kiện)."""
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": date_from, "d_to": date_to, **dim_binds}
    row = frappe.db.sql(
        f"""
        SELECT COUNT(DISTINCT t.lead_id) FROM (
            SELECT h.`lead` AS lead_id
            FROM `tabCRM Lead Step History` h
            INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
            WHERE h.`new_step` = 'QLead'
              AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
            UNION
            SELECT l.`name` AS lead_id
            FROM `tabCRM Lead` l
            WHERE DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s
              AND l.`step` = 'QLead'
              AND {dim_sql}
              AND NOT EXISTS (
                  SELECT 1 FROM `tabCRM Lead Step History` hx
                  WHERE hx.`lead` = l.`name` AND hx.`new_step` = 'QLead'
              )
        ) t
        """,
        binds,
    )[0][0]
    return int(row or 0)


def _kpi_snapshot(date_from: Any, date_to: Any, args) -> Dict[str, Any]:
    total_profiles = _count_total_profiles(date_from, date_to, args)
    total_leads = _count_new_leads(date_from, date_to, args)
    total_enrolled = _count_enrolled_events(date_from, date_to, args)
    total_lost = _count_lost_events(date_from, date_to, args)
    active_pipeline = _count_active_pipeline(args)
    entered = _count_leads_entered_pipeline(date_from, date_to, args)
    conv = round(100.0 * total_enrolled / max(1, entered), 2)
    avg_days = _avg_days_to_enroll(date_from, date_to, args)

    # Học sinh quan tâm / tiềm năng — sự kiện chuyển bước trong kỳ (đồng bộ biểu đồ xu hướng)
    count_lead_interested = entered
    count_qlead = _count_qlead_events(date_from, date_to, args)

    return {
        "total_profiles": total_profiles,
        "total_leads": total_leads,
        "count_lead_interested": count_lead_interested,
        "count_qlead": count_qlead,
        "total_enrolled": total_enrolled,
        "total_lost": total_lost,
        "active_pipeline": active_pipeline,
        "total_qlead_active": active_pipeline,
        "conversion_rate_pct": conv,
        "avg_days_to_enroll": avg_days,
        "leads_entered_pipeline": entered,
    }


def _cohort_leads_subquery(args) -> Tuple[str, Dict[str, Any]]:
    """Subquery trả về lead_id thuộc cohort (vào Lead trong kỳ)."""
    fd, td, _, _ = _resolve_period(args)
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": fd, "d_to": td, **dim_binds}
    sql = f"""
        SELECT DISTINCT t.lead_id FROM (
            SELECT h.`lead` AS lead_id
            FROM `tabCRM Lead Step History` h
            INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
            WHERE h.`new_step` = 'Lead'
              AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
              AND {dim_sql}
            UNION
            SELECT l.`name` AS lead_id
            FROM `tabCRM Lead` l
            WHERE DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s
              AND l.`step` IN ('Lead', 'QLead', 'Enrolled', 'Nghi hoc')
              AND {dim_sql}
              AND NOT EXISTS (
                  SELECT 1 FROM `tabCRM Lead Step History` hx
                  WHERE hx.`lead` = l.`name` AND hx.`new_step` = 'Lead'
              )
        ) t
    """
    return sql, binds


def _stage_reached_sql(stage: Dict[str, Any]) -> str:
    """Điều kiện EXISTS — lead trong cohort đã từng đạt mốc."""
    kind = stage.get("kind")
    if kind == "cohort":
        return "1=1"
    if kind == "step":
        step = stage["value"]
        return f"""(
            EXISTS (
                SELECT 1 FROM `tabCRM Lead Step History` hx
                WHERE hx.`lead` = c.lead_id AND hx.`new_step` = '{step}'
            )
            OR EXISTS (
                SELECT 1 FROM `tabCRM Lead` lx
                WHERE lx.`name` = c.lead_id AND lx.`step` = '{step}'
            )
        )"""
    if kind == "sub_status":
        field = stage["field"]
        val = stage["value"]
        ev = f"{field}:{val}"
        return f"""(
            EXISTS (
                SELECT 1 FROM `tabCRM Lead Step History` hx
                WHERE hx.`lead` = c.lead_id
                  AND (hx.`new_status` = '{ev}' OR hx.`new_status` = '{val}')
            )
            OR EXISTS (
                SELECT 1 FROM `tabCRM Lead` lx
                WHERE lx.`name` = c.lead_id AND lx.`{field}` = '{val}'
            )
        )"""
    if kind == "deal_status_in":
        vals = stage["values"]
        parts = []
        for v in vals:
            ev = f"deal_status:{v}"
            parts.append(f"hx.`new_status` IN ('{ev}', '{v}')")
            parts.append(f"lx.`status` = '{v}'")
        hist_or = " OR ".join([p for p in parts if "hx." in p])
        lead_or = " OR ".join([p for p in parts if "lx." in p])
        return f"""(
            EXISTS (
                SELECT 1 FROM `tabCRM Lead Step History` hx
                WHERE hx.`lead` = c.lead_id AND ({hist_or})
            )
            OR EXISTS (
                SELECT 1 FROM `tabCRM Lead` lx
                WHERE lx.`name` = c.lead_id AND ({lead_or})
            )
        )"""
    return "1=0"


def _count_cohort_stage(cohort_sql: str, cohort_binds: Dict[str, Any], stage: Dict[str, Any]) -> int:
    cond = _stage_reached_sql(stage)
    row = frappe.db.sql(
        f"""
        SELECT COUNT(*) FROM (
            {cohort_sql}
        ) c
        WHERE {cond}
        """,
        cohort_binds,
    )[0][0]
    return int(row or 0)


@frappe.whitelist()
def get_overview_kpis():
    """KPI tổng quan theo ngày sự kiện + so kỳ trước."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, pdf, pdt = _resolve_period(args)

    curr = _kpi_snapshot(fd, td, args)
    prev = _kpi_snapshot(pdf, pdt, args)

    meta = {
        "pic_restricted_to_self": _should_restrict_to_own_pic_only(),
        "measure_basis": "event_date",
        "period_label": f"{fd} — {td}",
        "prev_period_label": f"{pdf} — {pdt}",
    }
    changes = {
        "total_profiles": _pct_change(curr["total_profiles"], prev["total_profiles"]),
        "total_leads": _pct_change(curr["total_leads"], prev["total_leads"]),
        "count_lead_interested": _pct_change(
            curr["count_lead_interested"], prev["count_lead_interested"]
        ),
        "count_qlead": _pct_change(curr["count_qlead"], prev["count_qlead"]),
        "total_enrolled": _pct_change(curr["total_enrolled"], prev["total_enrolled"]),
        "total_lost": _pct_change(curr["total_lost"], prev["total_lost"]),
        "conversion_rate_pct": _pct_change(
            curr["conversion_rate_pct"], prev["conversion_rate_pct"]
        ),
    }

    return success_response(
        {
            "kpis": {
                "current_period": curr,
                "prev_period": prev,
                "period": {"from": str(fd), "to": str(td)},
            },
            "changes": changes,
            "meta": meta,
        }
    )


@frappe.whitelist()
def get_funnel():
    """Phễu cohort — lead vào Lead trong kỳ, đếm từng mốc đã từng đạt."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = _resolve_period(args)
    cohort_sql, cohort_binds = _cohort_leads_subquery(args)

    steps = []
    transitions = []
    prev_count: Optional[int] = None
    prev_key: Optional[str] = None

    for stage in FUNNEL_STAGES:
        cnt = _count_cohort_stage(cohort_sql, cohort_binds, stage)
        steps.append({"step": stage["key"], "label": stage["label"], "count": cnt})
        if prev_count is not None and prev_key is not None:
            rate = round(100.0 * cnt / max(1, prev_count), 2) if prev_count else None
            drop = round(100.0 * (prev_count - cnt) / max(1, prev_count), 2) if prev_count else None
            transitions.append(
                {
                    "from_step": prev_key,
                    "to_step": stage["key"],
                    "rate_pct": rate,
                    "drop_off_pct": drop,
                }
            )
        prev_count = cnt
        prev_key = stage["key"]

    return success_response(
        {
            "steps": steps,
            "transitions": transitions,
            "meta": {
                "cohort_definition": "Lead vào phễu trong kỳ lọc",
                "period": {"from": str(fd), "to": str(td)},
            },
        }
    )


@frappe.whitelist()
def get_status_distribution():
    """Phân bố status / test_status / deal_status hiện tại."""
    check_crm_permission()
    args = frappe.request.args or {}
    dim_sql, dim_binds = _where_lead_dimensions_only(args)

    status_rows = frappe.db.sql(
        f"""
        SELECT l.`step`, IFNULL(NULLIF(TRIM(l.`status`), ''), '(Trống)') AS st, COUNT(*) AS c
        FROM `tabCRM Lead` l
        WHERE l.`step` IN ('Lead', 'QLead', 'Enrolled', 'Verify', 'Draft')
          AND {dim_sql}
        GROUP BY l.`step`, st
        ORDER BY l.`step`, c DESC
        """,
        dim_binds,
        as_dict=True,
    )

    test_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(l.`test_status`), ''), '(Trống)') AS st, COUNT(*) AS c
        FROM `tabCRM Lead` l
        WHERE l.`step` = 'QLead' AND {dim_sql}
        GROUP BY st ORDER BY c DESC
        """,
        dim_binds,
        as_dict=True,
    )

    return success_response(
        {
            "by_step_status": [
                {"step": r["step"], "status": r["st"], "count": int(r["c"])} for r in status_rows
            ],
            "by_test_status": [{"status": r["st"], "count": int(r["c"])} for r in test_rows],
        }
    )


@frappe.whitelist()
def get_trend():
    """Xu hướng: hồ sơ Draft mới nhập / vào Lead / đạt QLead theo bucket thời gian."""
    check_crm_permission()
    args = frappe.request.args or {}
    gran = (args.get("granularity") or "day").lower()
    fd, td, _, _ = _resolve_period(args)

    wlead, binds_lead = _where_creation_between(fd, td, args)

    if gran == "week":
        pn = "YEARWEEK(l.`creation`, 3)"
        ph = "YEARWEEK(h.`changed_at`, 3)"
    elif gran == "month":
        pn = "DATE_FORMAT(l.`creation`, '%%Y-%%m')"
        ph = "DATE_FORMAT(h.`changed_at`, '%%Y-%%m')"
    elif gran == "year":
        pn = "DATE_FORMAT(l.`creation`, '%%Y')"
        ph = "DATE_FORMAT(h.`changed_at`, '%%Y')"
    else:
        pn = "DATE(l.`creation`)"
        ph = "DATE(h.`changed_at`)"
        gran = "day"

    new_rows = frappe.db.sql(
        f"""
        SELECT {pn} AS period, COUNT(*) AS new_leads
        FROM `tabCRM Lead` l
        WHERE {wlead} AND l.`step` = 'Draft'
        GROUP BY {pn} ORDER BY period ASC
        """,
        binds_lead,
        as_dict=True,
    )

    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds_h = {"d_from": fd, "d_to": td, **dim_binds}
    hj = f"DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s AND {dim_sql}"

    # Học sinh quan tâm — vào phễu Lead trong bucket (lịch sử bước + tạo mới không có history Lead)
    interested_hist_rows = frappe.db.sql(
        f"""
        SELECT {ph} AS period, COUNT(DISTINCT h.`lead`) AS c
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE h.`new_step` = 'Lead' AND {hj}
        GROUP BY {ph}
        ORDER BY period ASC
        """,
        binds_h,
        as_dict=True,
    )
    interested_creation_rows = frappe.db.sql(
        f"""
        SELECT {pn} AS period, COUNT(*) AS c
        FROM `tabCRM Lead` l
        WHERE DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s
          AND l.`step` IN ('Lead', 'QLead', 'Enrolled', 'Nghi hoc')
          AND {dim_sql}
          AND NOT EXISTS (
              SELECT 1 FROM `tabCRM Lead Step History` hx
              WHERE hx.`lead` = l.`name` AND hx.`new_step` = 'Lead'
          )
        GROUP BY {pn}
        ORDER BY period ASC
        """,
        binds_h,
        as_dict=True,
    )

    # Học sinh tiềm năng — đạt QLead trong bucket
    qlead_hist_rows = frappe.db.sql(
        f"""
        SELECT {ph} AS period, COUNT(DISTINCT h.`lead`) AS c
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE h.`new_step` = 'QLead' AND {hj}
        GROUP BY {ph}
        ORDER BY period ASC
        """,
        binds_h,
        as_dict=True,
    )
    qlead_creation_rows = frappe.db.sql(
        f"""
        SELECT {pn} AS period, COUNT(*) AS c
        FROM `tabCRM Lead` l
        WHERE DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s
          AND l.`step` = 'QLead'
          AND {dim_sql}
          AND NOT EXISTS (
              SELECT 1 FROM `tabCRM Lead Step History` hx
              WHERE hx.`lead` = l.`name` AND hx.`new_step` = 'QLead'
          )
        GROUP BY {pn}
        ORDER BY period ASC
        """,
        binds_h,
        as_dict=True,
    )

    def _merge_period_counts(*row_sets):
        merged: Dict[str, int] = {}
        for rows in row_sets:
            for r in rows:
                key = str(r["period"])
                merged[key] = merged.get(key, 0) + int(r["c"])
        return merged

    imap = _merge_period_counts(interested_hist_rows, interested_creation_rows)
    qmap = _merge_period_counts(qlead_hist_rows, qlead_creation_rows)
    periods = {str(r["period"]) for r in new_rows} | set(imap) | set(qmap)

    points = []
    for pkey in sorted(periods):
        nr = next((int(x["new_leads"]) for x in new_rows if str(x["period"]) == pkey), 0)
        points.append(
            {
                "period": pkey,
                "new_leads": nr,
                "lead_interested": imap.get(pkey, 0),
                "qlead": qmap.get(pkey, 0),
            }
        )

    return success_response({"granularity": gran, "points": points})


@frappe.whitelist()
def get_breakdown_by_source():
    """Phân nhóm nguồn — enrolled theo sự kiện trong kỳ."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = _resolve_period(args)
    wsql, binds = _where_creation_between(fd, td, args)
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    eb = {"d_from": fd, "d_to": td, **dim_binds}

    src_rows = frappe.db.sql(
        f"""
        SELECT
            ls.`source` AS src,
            IFNULL(NULLIF(TRIM(ls.`sub_source`), ''), '-') AS sub_source,
            COUNT(DISTINCT l.`name`) AS total_count
        FROM `tabCRM Lead` l
        INNER JOIN `tabCRM Lead Source` ls ON ls.`parent` = l.`name`
        WHERE {wsql}
        GROUP BY ls.`source`, ls.`sub_source`
        ORDER BY total_count DESC
        LIMIT 200
        """,
        binds,
        as_dict=True,
    )

    enrolled_by_src = frappe.db.sql(
        f"""
        SELECT ls.`source` AS src,
               IFNULL(NULLIF(TRIM(ls.`sub_source`), ''), '-') AS sub_source,
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
        GROUP BY ls.`source`, ls.`sub_source`
        """,
        eb,
        as_dict=True,
    )
    enrolled_map = {
        (r["src"], r.get("sub_source") or ""): int(r["enrolled_count"]) for r in enrolled_by_src
    }

    source_ids = [r["src"] for r in src_rows if r.get("src")]
    source_names = _batch_source_names(source_ids)

    breakdown = []
    for r in src_rows:
        tot = int(r.get("total_count") or 0)
        key = (r["src"], r.get("sub_source") or "")
        ec = enrolled_map.get(key, 0)
        breakdown.append(
            {
                "source": r["src"],
                "source_name": source_names.get(r["src"], r["src"]),
                "sub_source": r.get("sub_source") or "",
                "count_total": tot,
                "count_enrolled": ec,
                "conversion_rate_pct": round(100.0 * ec / max(1, tot), 2),
            }
        )

    ds_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(NULLIF(TRIM(l.`data_source`), ''), '-') AS ds, COUNT(*) AS c
        FROM `tabCRM Lead` l WHERE {wsql}
        GROUP BY ds ORDER BY c DESC
        """,
        binds,
        as_dict=True,
    )
    ref_rows = frappe.db.sql(
        f"""
        SELECT l.`referrer` AS ref, COUNT(*) AS c
        FROM `tabCRM Lead` l
        WHERE {wsql} AND IFNULL(TRIM(l.`referrer`), '') != ''
        GROUP BY ref ORDER BY c DESC LIMIT 10
        """,
        binds,
        as_dict=True,
    )
    ref_names = _batch_referrer_names([r["ref"] for r in ref_rows if r.get("ref")])

    return success_response(
        {
            "by_source_rows": breakdown,
            "by_data_source": [{"data_source": r["ds"], "count": int(r["c"])} for r in ds_rows],
            "referrers_top": [
                {
                    "referrer": r["ref"],
                    "referrer_name": ref_names.get(r["ref"], r["ref"]),
                    "count": int(r["c"]),
                }
                for r in ref_rows
            ],
        }
    )


@frappe.whitelist()
def get_breakdown_by_pic():
    """Hiệu suất PIC — assigned theo creation; enrolled/lost theo sự kiện."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = _resolve_period(args)
    wsql, binds = _where_creation_between(fd, td, args)
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    include_tc = _include_tu_choi_lost(args)
    lost_cond = _lost_event_condition(include_tc)
    eb = {"d_from": fd, "d_to": td, **dim_binds}

    assigned_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic_sales`), '') AS pic, COUNT(*) AS total_assigned
        FROM `tabCRM Lead` l
        WHERE {wsql} AND IFNULL(TRIM(l.`pic_sales`), '') != ''
        GROUP BY pic
        """,
        binds,
        as_dict=True,
    )

    enrolled_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic_sales`), '') AS pic, COUNT(DISTINCT h.`lead`) AS enrolled_count
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE h.`new_step` = 'Enrolled'
          AND DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
          AND IFNULL(TRIM(l.`pic_sales`), '') != ''
          AND {dim_sql}
        GROUP BY pic
        """,
        eb,
        as_dict=True,
    )

    lost_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic_sales`), '') AS pic, COUNT(DISTINCT h.`lead`) AS lost_count
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
          AND {lost_cond}
          AND IFNULL(TRIM(l.`pic_sales`), '') != ''
          AND {dim_sql}
        GROUP BY pic
        """,
        eb,
        as_dict=True,
    )

    active_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic_sales`), '') AS pic,
               SUM(IF(l.`step` IN ('Lead','QLead') AND IFNULL(TRIM(l.`status`),'') NOT IN ('Lost','Tu choi'), 1, 0)) AS qlead_count
        FROM `tabCRM Lead` l
        WHERE IFNULL(TRIM(l.`pic_sales`), '') != '' AND {dim_sql}
        GROUP BY pic
        """,
        dim_binds,
        as_dict=True,
    )

    hj = f"DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s AND {dim_sql}"
    resp_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic_sales`), '') AS pic,
            AVG(TIMESTAMPDIFF(SECOND, l.`creation`, h.`changed_at`) / 3600.0) AS avg_hours
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE h.`new_step` = 'QLead' AND IFNULL(TRIM(l.`pic_sales`), '') != ''
          AND {hj}
        GROUP BY pic
        """,
        eb,
        as_dict=True,
    )

    enrolled_map = {r["pic"]: int(r["enrolled_count"]) for r in enrolled_rows}
    lost_map = {r["pic"]: int(r["lost_count"]) for r in lost_rows}
    active_map = {r["pic"]: int(r["qlead_count"]) for r in active_rows}
    assigned_map = {r["pic"]: int(r["total_assigned"]) for r in assigned_rows}
    resp_map = {
        r["pic"]: None if r.get("avg_hours") is None else round(float(r["avg_hours"]), 2)
        for r in resp_rows
    }

    all_pics = sorted(
        set(assigned_map) | set(enrolled_map) | set(lost_map) | set(active_map),
        key=lambda p: assigned_map.get(p, 0) + enrolled_map.get(p, 0),
        reverse=True,
    )[:200]

    user_map = _batch_user_map(all_pics)
    out = []
    for pic_email in all_pics:
        if not pic_email:
            continue
        total = assigned_map.get(pic_email, 0)
        ee = enrolled_map.get(pic_email, 0)
        lf = lost_map.get(pic_email, 0)
        qn = active_map.get(pic_email, 0)
        ud = user_map.get(pic_email, {})
        out.append(
            {
                "pic": pic_email,
                "pic_name": ud.get("full_name") or pic_email,
                "pic_avatar": ud.get("pic_avatar"),
                "total_assigned": total,
                "qlead_count": qn,
                "enrolled_count": ee,
                "lost_count": lf,
                "conversion_rate_pct": round(100.0 * ee / max(1, total), 2),
                "avg_response_time_hours": resp_map.get(pic_email),
            }
        )

    return success_response({"rows": out})


@frappe.whitelist()
def get_breakdown_by_grade_campus():
    """Heatmap khối × campus — hồ sơ mới trong kỳ."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = _resolve_period(args)
    wsql, binds = _where_creation_between(fd, td, args)

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`target_grade`), '-') AS g,
               IFNULL(TRIM(l.`campus_id`), '-') AS c,
               COUNT(*) AS cnt
        FROM `tabCRM Lead` l
        WHERE {wsql}
        GROUP BY g, c
        ORDER BY cnt DESC
        LIMIT 500
        """,
        binds,
        as_dict=True,
    )

    campus_ids = list({r["c"] for r in rows if r.get("c") and r["c"] != "-"})
    campus_titles: Dict[str, str] = {}
    if campus_ids:
        for c in frappe.get_all(
            "SIS Campus",
            filters={"name": ["in", campus_ids]},
            fields=["name", "title_vn", "short_title"],
        ):
            campus_titles[c["name"]] = c.get("title_vn") or c["name"]

    cells = [
        {
            "target_grade": r["g"],
            "campus_id": r["c"],
            "campus_title": campus_titles.get(r["c"], r["c"]),
            "count": int(r["cnt"]),
        }
        for r in rows
    ]
    return success_response({"cells": cells})


@frappe.whitelist()
def get_lost_analysis():
    """Lost theo ngày sự kiện + nhóm lý do."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td, _, _ = _resolve_period(args)
    include_tc = _include_tu_choi_lost(args)
    lost_cond = _lost_event_condition(include_tc)
    dim_sql, dim_binds = _where_lead_dimensions_only(args)
    binds = {"d_from": fd, "d_to": td, **dim_binds}
    page = int(args.get("page") or 1)
    per_page = int(args.get("per_page") or 20)
    offset = max(0, page - 1) * per_page

    lost_base = f"""
        SELECT DISTINCT h.`lead` AS lead_id,
               MIN(h.`changed_at`) AS lost_at
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s
          AND {lost_cond}
          AND {dim_sql}
        GROUP BY h.`lead`
    """

    total_count = int(
        frappe.db.sql(f"SELECT COUNT(*) FROM ({lost_base}) lb", binds)[0][0] or 0
    )

    summary_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(IFNULL(l.`reject_reason`, '')), '(Không ghi)') AS rr,
               COUNT(*) AS c
        FROM ({lost_base}) lb
        INNER JOIN `tabCRM Lead` l ON l.`name` = lb.lead_id
        GROUP BY rr ORDER BY c DESC LIMIT 80
        """,
        binds,
        as_dict=True,
    )
    pct_denom = total_count if total_count else 1
    summary = [
        {
            "reason": r["rr"],
            "count": int(r["c"]),
            "percentage": round(100.0 * int(r["c"]) / pct_denom, 2),
        }
        for r in summary_rows
    ]

    leads = frappe.db.sql(
        f"""
        SELECT l.`name`, l.`student_name`,
               COALESCE(l.`pic_care`, l.`pic_sales`) AS pic, l.`campus_id`,
               l.`reject_reason`, l.`reject_detail`, lb.lost_at
        FROM ({lost_base}) lb
        INNER JOIN `tabCRM Lead` l ON l.`name` = lb.lead_id
        ORDER BY lb.lost_at DESC
        LIMIT %(lim)s OFFSET %(off)s
        """,
        {**binds, "lim": per_page, "off": offset},
        as_dict=True,
    )

    pic_emails = [lw.get("pic") or "" for lw in leads]
    user_map = _batch_user_map(pic_emails)
    out_leads = []
    for lw in leads:
        pe = lw.get("pic") or ""
        ud = user_map.get(pe, {})
        out_leads.append(
            {
                "name": lw.get("name"),
                "student_name": lw.get("student_name"),
                "pic": pe,
                "pic_name": ud.get("full_name") or pe,
                "pic_avatar": ud.get("pic_avatar"),
                "campus_id": lw.get("campus_id"),
                "reject_reason": lw.get("reject_reason"),
                "reject_detail": lw.get("reject_detail"),
                "lost_at": lw.get("lost_at"),
            }
        )

    pag_out = paginated_response(
        data=out_leads,
        current_page=page,
        total_count=total_count,
        per_page=per_page,
        message="OK",
    )
    pag_out["meta"] = {"reason_summary": summary, "measure_basis": "event_date"}
    return pag_out
