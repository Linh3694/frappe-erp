# -*- coding: utf-8 -*-
"""Hạ tầng dùng chung cho báo cáo CRM — KHÔNG chứa endpoint nào.

Cả hai module báo cáo đều dựng trên đây:
  - `reports_period.py`      — đếm SỰ KIỆN trong khoảng ngày
  - `reports_school_year.py` — SNAPSHOT theo năm học mục tiêu

Nội dung: lọc chiều (campus/pic/năm học/khối/nguồn/referrer/data_source), phân quyền PIC,
giải kỳ + kỳ trước, filter động theo cột CRM Lead bất kỳ, batch tên user/referrer/nguồn.

Vì sao tách ra: trước đây khối này nằm trong `reports.py`, khiến file đó vừa là API vừa là
thư viện — `reports_v2.py` phải `import reports as r` chỉ để mượn helper, người đọc tưởng
báo cáo năm học phụ thuộc báo cáo theo kỳ. Sửa helper ở đây là ảnh hưởng CẢ HAI module.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import frappe


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
