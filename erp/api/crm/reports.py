# -*- coding: utf-8 -*-
"""
CRM Reports API — dashboard báo cáo tuyển sinh (CRM Lead).
Đọc từ: tabCRM Lead, tabCRM Lead Step History, tabCRM Lead Source.
"""

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


def _prev_period_dates(fd, td):
    delta = td - fd
    p_to = fd - timedelta(days=1)
    p_from = p_to - delta
    return p_from, p_to


def _append_common_filters(where_parts: List[str], binds: Dict[str, Any], args) -> None:
    campus_id = (args.get("campus_id") or "").strip()
    if campus_id:
        binds["_campus"] = campus_id
        where_parts.append("l.`campus_id` = %(_campus)s")

    pic_eff = _effective_pic_from_request(args.get("pic"))
    if pic_eff:
        binds["_pic"] = pic_eff
        where_parts.append("l.`pic` = %(_pic)s")

    tay = (args.get("target_academic_year") or "").strip()
    if tay:
        binds["_tay"] = tay
        where_parts.append("l.`target_academic_year` = %(_tay)s")

    tg = (args.get("target_grade") or "").strip()
    if tg:
        binds["_tg"] = tg
        where_parts.append("l.`target_grade` = %(_tg)s")

    referrer = (args.get("referrer") or "").strip()
    if referrer:
        binds["_ref"] = referrer
        where_parts.append("l.`referrer` = %(_ref)s")

    ds = (args.get("data_source") or "").strip()
    if ds:
        binds["_ds"] = ds
        where_parts.append("l.`data_source` = %(_ds)s")

    source = (args.get("source") or "").strip()
    if source:
        binds["_src"] = source
        where_parts.append(
            "EXISTS (SELECT 1 FROM `tabCRM Lead Source` s "
            "WHERE s.`parent` = l.`name` AND s.`source` = %(_src)s)"
        )


def _where_creation_between(date_from: Any, date_to: Any, args) -> Tuple[str, Dict[str, Any]]:
    where_parts = ["DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s"]
    binds = {"d_from": date_from, "d_to": date_to}
    _append_common_filters(where_parts, binds, args)
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


def _append_history_join_filters(
    frags: List[str],
    binds: Dict[str, Any],
    args,
    alias: str,
) -> None:
    campus_id = (args.get("campus_id") or "").strip()
    if campus_id:
        binds["_cj_campus"] = campus_id
        frags.append(f"{alias}.`campus_id` = %(_cj_campus)s")

    pic_eff = _effective_pic_from_request(args.get("pic"))
    if pic_eff:
        binds["_cj_pic"] = pic_eff
        frags.append(f"{alias}.`pic` = %(_cj_pic)s")

    tay = (args.get("target_academic_year") or "").strip()
    if tay:
        binds["_cj_tay"] = tay
        frags.append(f"{alias}.`target_academic_year` = %(_cj_tay)s")

    tg = (args.get("target_grade") or "").strip()
    if tg:
        binds["_cj_tg"] = tg
        frags.append(f"{alias}.`target_grade` = %(_cj_tg)s")

    referrer = (args.get("referrer") or "").strip()
    if referrer:
        binds["_cj_ref"] = referrer
        frags.append(f"{alias}.`referrer` = %(_cj_ref)s")

    ds = (args.get("data_source") or "").strip()
    if ds:
        binds["_cj_ds"] = ds
        frags.append(f"{alias}.`data_source` = %(_cj_ds)s")

    source = (args.get("source") or "").strip()
    if source:
        binds["_cj_src"] = source
        frags.append(
            f"EXISTS (SELECT 1 FROM `tabCRM Lead Source` s "
            f"WHERE s.`parent` = {alias}.`name` AND s.`source` = %(_cj_src)s)"
        )


def _kpi_snapshot(date_from: Any, date_to: Any, args) -> Dict[str, Any]:
    wsql, binds = _where_creation_between(date_from, date_to, args)
    row = frappe.db.sql(
        f"""
        SELECT
            COUNT(*) AS total_leads,
            SUM(IF(l.`step` = 'Enrolled', 1, 0)) AS total_enrolled,
            SUM(IF(l.`status` = 'Lost', 1, 0)) AS total_lost,
            SUM(IF(l.`step` = 'QLead' AND IFNULL(TRIM(l.`status`),'') != 'Lost',
                1, 0)) AS total_qlead_active,
            AVG(IF(l.`step` = 'Enrolled' AND l.`enrollment_date` IS NOT NULL,
                DATEDIFF(l.`enrollment_date`, DATE(l.`creation`)), NULL))
                AS avg_days_to_enroll
        FROM `tabCRM Lead` l
        WHERE {wsql}
        """,
        binds,
        as_dict=True,
    )[0]
    tl = int(row.get("total_leads") or 0)
    te = int(row.get("total_enrolled") or 0)

    tl_lead_or_more = int(
        frappe.db.sql(
            f"""
            SELECT COUNT(*) FROM `tabCRM Lead` l
            WHERE {wsql} AND l.`step` IN ('Lead', 'QLead', 'Enrolled', 'Nghi hoc')
            """,
            binds,
        )[0][0]
    )

    conv = round(100.0 * te / max(1, tl_lead_or_more), 2)

    avg_days = row.get("avg_days_to_enroll")
    avg_days_out = None if avg_days is None else round(float(avg_days), 2)

    return {
        "total_leads": tl,
        "total_enrolled": te,
        "total_lost": int(row.get("total_lost") or 0),
        "total_qlead_active": int(row.get("total_qlead_active") or 0),
        "conversion_rate_pct": conv,
        "avg_days_to_enroll": avg_days_out,
    }


def _pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None:
        return None
    if prev == 0:
        if curr == 0:
            return 0.0
        return None
    return round(100.0 * (curr - prev) / prev, 2)


STEP_ORDER = ["Draft", "Verify", "Lead", "QLead", "Enrolled", "Nghi hoc"]


@frappe.whitelist()
def get_overview_kpis():
    """KPI tổng quan và so kỳ trước (cùng độ dài)."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td = _parse_date_range(args)
    pdf, pdt = _prev_period_dates(fd, td)

    curr = _kpi_snapshot(fd, td, args)
    prev = _kpi_snapshot(pdf, pdt, args)

    meta = {"pic_restricted_to_self": _should_restrict_to_own_pic_only()}
    changes = {
        "total_leads": _pct_change(curr["total_leads"], prev["total_leads"]),
        "total_enrolled": _pct_change(curr["total_enrolled"], prev["total_enrolled"]),
        "total_lost": _pct_change(curr["total_lost"], prev["total_lost"]),
        "conversion_rate_pct": _pct_change(
            curr["conversion_rate_pct"], prev["conversion_rate_pct"]
        ),
    }

    return success_response(
        {
            "kpis": {"current_period": curr, "prev_period": prev, "period": {"from": fd, "to": td}},
            "changes": changes,
            "meta": meta,
        }
    )


@frappe.whitelist()
def get_funnel():
    """Đếm theo step; tỉ lệ giữa hai bước liền nhau trong pipeline."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td = _parse_date_range(args)
    wsql, binds = _where_creation_between(fd, td, args)

    rows = frappe.db.sql(
        f"""
        SELECT l.`step` AS step, COUNT(*) AS c
        FROM `tabCRM Lead` l WHERE {wsql}
        GROUP BY l.`step`
        """,
        binds,
        as_dict=True,
    )
    cnt = {r["step"]: int(r["c"]) for r in rows}
    series = [{"step": s, "count": cnt.get(s, 0)} for s in STEP_ORDER]

    transitions = []
    for i in range(len(STEP_ORDER) - 1):
        a, b = STEP_ORDER[i], STEP_ORDER[i + 1]
        ca, cb = cnt.get(a, 0), cnt.get(b, 0)
        rate = round(100.0 * cb / max(1, ca), 2) if ca else None
        transitions.append({"from_step": a, "to_step": b, "rate_pct": rate})

    return success_response({"steps": series, "transitions": transitions})


@frappe.whitelist()
def get_trend():
    """Xu hướng new lead / enrolled (lịch sử) / lost — theo granularity."""
    check_crm_permission()
    args = frappe.request.args or {}
    gran = (args.get("granularity") or "day").lower()
    fd, td = _parse_date_range(args)
    wlead, binds_lead = _where_creation_between(fd, td, args)

    if gran == "week":
        pn = "YEARWEEK(l.`creation`, 3)"
        ph = "YEARWEEK(DATE_SUB(h.`changed_at`, INTERVAL 0 SECOND), 3)"
    elif gran == "month":
        pn = "DATE_FORMAT(l.`creation`, '%%Y-%%m')"
        ph = "DATE_FORMAT(h.`changed_at`, '%%Y-%%m')"
    else:
        pn = "DATE(l.`creation`)"
        ph = "DATE(h.`changed_at`)"
        gran = "day"

    new_rows = frappe.db.sql(
        f"""
        SELECT {pn} AS period, COUNT(*) AS new_leads
        FROM `tabCRM Lead` l WHERE {wlead}
        GROUP BY {pn} ORDER BY period ASC
        """,
        binds_lead,
        as_dict=True,
    )

    hfr: List[str] = [
        "DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s",
        "DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s",
    ]
    binds_h = {"d_from": fd, "d_to": td}
    _append_history_join_filters(hfr, binds_h, args, "l")

    hj = " AND ".join(hfr)

    enrolled_rows = frappe.db.sql(
        f"""
        SELECT {ph} AS period, COUNT(DISTINCT h.`lead`) AS c
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE h.`new_step` = 'Enrolled' AND {hj}
        GROUP BY {ph}
        ORDER BY period ASC
        """,
        binds_h,
        as_dict=True,
    )

    lost_rows = frappe.db.sql(
        f"""
        SELECT {ph} AS period, COUNT(DISTINCT h.`lead`) AS c
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE IFNULL(h.`new_status`,'') = 'Lost' AND {hj}
        GROUP BY {ph}
        ORDER BY period ASC
        """,
        binds_h,
        as_dict=True,
    )

    emap = {str(r["period"]): int(r["c"]) for r in enrolled_rows}
    lmap = {str(r["period"]): int(r["c"]) for r in lost_rows}
    periods = {str(r["period"]) for r in new_rows} | set(emap) | set(lmap)

    points = []
    for pkey in sorted(periods):
        nr = next(
            (int(x["new_leads"]) for x in new_rows if str(x["period"]) == pkey),
            0,
        )
        points.append(
            {
                "period": pkey,
                "new_leads": nr,
                "enrolled": emap.get(pkey, 0),
                "lost": lmap.get(pkey, 0),
            }
        )

    return success_response({"granularity": gran, "points": points})


@frappe.whitelist()
def get_breakdown_by_source():
    """Phân nhóm CRM Lead Source, data_source, referrer."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td = _parse_date_range(args)
    wsql, binds = _where_creation_between(fd, td, args)

    src_rows = frappe.db.sql(
        f"""
        SELECT
            ls.`source` AS src,
            IFNULL(NULLIF(TRIM(ls.`sub_source`), ''), '-') AS sub_source,
            COUNT(DISTINCT l.`name`) AS total_count,
            SUM(IF(l.`step` = 'Enrolled', 1, 0)) AS enrolled_count
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
    breakdown = []
    for r in src_rows:
        tot = int(r.get("total_count") or 0)
        ec = int(r.get("enrolled_count") or 0)
        breakdown.append(
            {
                "source": r["src"],
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

    return success_response(
        {
            "by_source_rows": breakdown,
            "by_data_source": [{"data_source": r["ds"], "count": int(r["c"])} for r in ds_rows],
            "referrers_top": [{"referrer": r["ref"], "count": int(r["c"])} for r in ref_rows],
        }
    )


@frappe.whitelist()
def get_breakdown_by_pic():
    """Bảng hiệu suất PIC + thời gian Lead→chuyển QLead trung bình (giờ)."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td = _parse_date_range(args)
    wsql, binds = _where_creation_between(fd, td, args)

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic`),'') AS pic, COUNT(*) AS total_assigned,
            SUM(IF(l.`step` = 'Enrolled', 1, 0)) AS enrolled_count,
            SUM(IF(IFNULL(l.`status`,'')='Lost', 1, 0)) AS lost_count,
            SUM(IF(l.`step`='QLead' AND IFNULL(l.`status`,'')!='Lost', 1, 0)) AS qlead_count
        FROM `tabCRM Lead` l
        WHERE {wsql} AND IFNULL(TRIM(l.`pic`),'') != ''
        GROUP BY pic
        ORDER BY total_assigned DESC
        LIMIT 200
        """,
        binds,
        as_dict=True,
    )

    # Thời gian trung bình tạo HS → vào QLead (bản ghi lịch sử nhảy vào QLead)
    hfr_pic: List[str] = [
        "DATE(h.`changed_at`) BETWEEN %(d_from)s AND %(d_to)s",
        "DATE(l.`creation`) BETWEEN %(d_from)s AND %(d_to)s",
    ]
    bh_pic = {"d_from": fd, "d_to": td}
    _append_history_join_filters(hfr_pic, bh_pic, args, "l")
    where_pic_join = " AND ".join(hfr_pic)

    resp_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`pic`),'') AS pic,
            AVG(TIMESTAMPDIFF(SECOND, l.`creation`, h.`changed_at`) / 3600.0) AS avg_hours
        FROM `tabCRM Lead Step History` h
        INNER JOIN `tabCRM Lead` l ON l.`name` = h.`lead`
        WHERE h.`new_step` = 'QLead' AND IFNULL(TRIM(l.`pic`),'') != ''
          AND {where_pic_join}
        GROUP BY pic
        """,
        bh_pic,
        as_dict=True,
    )
    avg_hours_by_pic = {
        r["pic"]: None if r.get("avg_hours") is None else round(float(r["avg_hours"]), 2)
        for r in resp_rows
    }

    out = []
    for r in rows:
        pic_email = r["pic"]
        total = int(r["total_assigned"])
        ee = int(r["enrolled_count"])
        lf = int(r["lost_count"])
        qn = int(r["qlead_count"])
        full_name = pic_email
        pic_avatar = None
        if frappe.db.exists("User", pic_email):
            ud = frappe.db.get_value(
                "User", pic_email, ["full_name", "user_image"], as_dict=True
            )
            if ud:
                full_name = ud.get("full_name") or pic_email
                pic_avatar = _full_image(ud.get("user_image"))

        out.append(
            {
                "pic": pic_email,
                "pic_name": full_name,
                "pic_avatar": pic_avatar,
                "total_assigned": total,
                "qlead_count": qn,
                "enrolled_count": ee,
                "lost_count": lf,
                "conversion_rate_pct": round(100.0 * ee / max(1, total), 2),
                "avg_response_time_hours": avg_hours_by_pic.get(pic_email),
            }
        )

    return success_response({"rows": out})


@frappe.whitelist()
def get_breakdown_by_grade_campus():
    """Đếm theo (target_grade, campus_id) cho heatmap."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td = _parse_date_range(args)
    wsql, binds = _where_creation_between(fd, td, args)

    rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(l.`target_grade`),'-') AS g,
               IFNULL(TRIM(l.`campus_id`),'-') AS c,
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

    cells = [{"target_grade": r["g"], "campus_id": r["c"], "count": int(r["cnt"])} for r in rows]
    return success_response({"cells": cells})


@frappe.whitelist()
def get_lost_analysis():
    """Lost: nhóm reject_reason + trang HS Lost."""
    check_crm_permission()
    args = frappe.request.args or {}
    fd, td = _parse_date_range(args)
    wsql, binds = _where_creation_between(fd, td, args)
    page = int(args.get("page") or 1)
    per_page = int(args.get("per_page") or 20)
    offset = max(0, page - 1) * per_page

    tlost_rs = frappe.db.sql(
        f"SELECT COUNT(*) FROM `tabCRM Lead` l WHERE {wsql} AND l.`status`='Lost'", binds,
    )

    tlost = tlost_rs[0][0] if tlost_rs else 0

    summary_rows = frappe.db.sql(
        f"""
        SELECT IFNULL(TRIM(IFNULL(l.`reject_reason`,'')), '(Không ghi)') AS rr, COUNT(*) AS c
        FROM `tabCRM Lead` l
        WHERE {wsql} AND l.`status`='Lost'
        GROUP BY rr ORDER BY c DESC LIMIT 80
        """,
        binds,
        as_dict=True,
    )
    pct_denom = int(tlost) if tlost else 1
    summary = [
        {
            "reason": r["rr"],
            "count": int(r["c"]),
            "percentage": round(100.0 * int(r["c"]) / pct_denom, 2),
        }
        for r in summary_rows
    ]

    total_count = frappe.db.sql(
        f"SELECT COUNT(*) FROM `tabCRM Lead` l WHERE {wsql} AND l.`status`='Lost'", binds,
    )[0][0]

    leads = frappe.db.sql(
        f"""
        SELECT l.`name`, l.`student_name`, l.`pic`, l.`campus_id`,
               l.`reject_reason`, l.`reject_detail`, IFNULL(l.`modified`, l.`creation`) AS lost_dt
        FROM `tabCRM Lead` l
        WHERE {wsql} AND l.`status`='Lost'
        ORDER BY l.`modified` DESC
        LIMIT %(lim)s OFFSET %(off)s
        """,
        {**binds, "lim": per_page, "off": offset},
        as_dict=True,
    )

    out_leads = []
    for lw in leads:
        pic_avatar = None
        pe = lw.get("pic") or ""
        if pe and frappe.db.exists("User", pe):
            ui = frappe.db.get_value("User", pe, "user_image")
            pic_avatar = _full_image(ui)
        full_name_pic = lw.get("pic")
        if pe and frappe.db.exists("User", pe):
            fn = frappe.db.get_value("User", pe, "full_name")
            full_name_pic = fn or lw.get("pic")

        out_leads.append(
            {
                **lw,
                "pic_name": full_name_pic,
                "pic_avatar": pic_avatar,
                "lost_at": lw.get("lost_dt"),
                "lost_dt": None,
            }
        )
    for lw in out_leads:
        lw.pop("lost_dt", None)

    pag_out = paginated_response(
        data=out_leads,
        current_page=page,
        total_count=int(total_count),
        per_page=per_page,
        message="OK",
    )
    pag_out["meta"] = {"reason_summary": summary}
    return pag_out
