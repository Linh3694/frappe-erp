"""
CRM Issue Report API - Bao cao Van de chung.

Phuc vu dashboard tab "Van de chung" (Bao cao Tuyen sinh V2), canh tab Tai ghi danh.
Mot endpoint duy nhat tra ve tat ca section trong 1 lan goi (giong get_report_breakdown):
  - overview        : tong quan (tong, dang xu ly, da xu ly, qua han, ty le hai long...)
  - by_time         : tong hop theo thoi gian (Ngay / Thang / Nam)  -> Yeu cau 1
  - by_module       : phan loai theo Loai van de (issue_module)      -> Yeu cau 2
  - by_issue_group  : phan loai theo Nhom van de (Gop y / Su vu)
  - by_priority     : phan loai theo Muc do (gom Khan cap)
  - by_department   : phan loai theo Phong ban lien quan             -> Yeu cau 2
  - by_status       : tinh trang xu ly (Cho duyet/Tiep nhan/...)     -> Yeu cau 3
  - sla             : thoi han xu ly + alert qua han + danh sach qua han -> Yeu cau 3
  - satisfaction    : muc do hai long (Hai long/Chua hai long)       -> Yeu cau 4
  - by_pic          : bao cao theo PIC                               -> Yeu cau 5

Pham vi loc (scope) ap dung cho moi section:
  - occurred_at trong [from_date, to_date] (neu co)
  - campus_id = X (neu co)
  - pic = X (neu co)
  - approval_status != 'Tu choi' (loai van de da bi tu choi khoi bao cao)
"""

import frappe

from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
)
from erp.api.crm.issue import _can_access_crm_issue_list

# Trang thai "dang xu ly" (chua dong) vs "da xu ly" (dong)
OPEN_STATUSES = ("Cho duyet", "Tiep nhan", "Dang xu ly")
CLOSED_STATUSES = ("Hoan thanh", "Dong")

# Cua so "sap den han" (gio): con han nhung deadline trong vong 24h toi
DUE_SOON_HOURS = 24

# Dinh dang gom nhom theo thoi gian (an toan, khong nhan input truc tiep)
GRANULARITY_FORMATS = {
    "day": "%Y-%m-%d",
    "month": "%Y-%m",
    "year": "%Y",
}


def _build_scope():
    """Doc tham so loc tu request va dung WHERE base + values cho moi query.

    Tra ve (conditions: list[str], values: dict). Dung alias bang `i` = tabCRM Issue.
    """
    from_date = (frappe.request.args.get("from_date") or "").strip()
    to_date = (frappe.request.args.get("to_date") or "").strip()
    campus_id = (frappe.request.args.get("campus_id") or "").strip()
    pic = (frappe.request.args.get("pic") or "").strip()

    conditions = ["i.approval_status != 'Tu choi'"]
    values = {}

    if from_date:
        conditions.append("i.occurred_at >= %(from_date)s")
        values["from_date"] = from_date
    if to_date:
        conditions.append("i.occurred_at <= %(to_date)s")
        values["to_date"] = to_date
    if campus_id:
        conditions.append("i.campus_id = %(campus_id)s")
        values["campus_id"] = campus_id
    if pic:
        conditions.append("i.pic = %(pic)s")
        values["pic"] = pic

    return conditions, values


def _rate(part, whole):
    return round(part / whole * 100, 1) if whole else 0


@frappe.whitelist()
def get_issue_report():
    """Bao cao Van de chung (CRM Issue) cho dashboard tab Van de chung.

    Args (query string):
      from_date, to_date : YYYY-MM-DD (tuy chon, loc theo occurred_at)
      campus_id          : tuy chon
      pic                : tuy chon
      granularity        : day | month | year (mac dinh month) — chi anh huong by_time
    """
    logs = []
    try:
        if not _can_access_crm_issue_list():
            return error_response("Ban khong co quyen truy cap bao cao van de", logs=logs)

        granularity = (frappe.request.args.get("granularity") or "month").strip().lower()
        time_format = GRANULARITY_FORMATS.get(granularity, GRANULARITY_FORMATS["month"])

        conditions, values = _build_scope()
        where = " AND ".join(conditions)

        open_in = "', '".join(OPEN_STATUSES)
        open_clause = f"i.status IN ('{open_in}')"

        # ---------- (1) Tong quan ----------
        ov = frappe.db.sql(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {open_clause} THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN i.status IN ('Hoan thanh', 'Dong') THEN 1 ELSE 0 END) AS resolved_count,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue_count,
                SUM(CASE WHEN i.result = 'Hai long' THEN 1 ELSE 0 END) AS hai_long,
                SUM(CASE WHEN i.result = 'Chua hai long' THEN 1 ELSE 0 END) AS chua_hai_long
            FROM `tabCRM Issue` i
            WHERE {where}
            """,
            values,
            as_dict=True,
        )
        r = ov[0] if ov else {}
        total = r.get("total") or 0
        open_count = r.get("open_count") or 0
        resolved_count = r.get("resolved_count") or 0
        overdue_count = r.get("overdue_count") or 0
        hai_long = r.get("hai_long") or 0
        chua_hai_long = r.get("chua_hai_long") or 0
        rated = hai_long + chua_hai_long

        overview = {
            "total": total,
            "open": open_count,
            "resolved": resolved_count,
            "overdue": overdue_count,
            "resolution_rate": _rate(resolved_count, total),
            "satisfaction_rate": _rate(hai_long, rated),
        }

        # ---------- (2) Theo thoi gian (Ngay/Thang/Nam) ----------
        time_values = dict(values)
        time_values["time_format"] = time_format
        time_rows = frappe.db.sql(
            f"""
            SELECT
                DATE_FORMAT(i.occurred_at, %(time_format)s) AS period,
                COUNT(*) AS count,
                SUM(CASE WHEN i.status IN ('Hoan thanh', 'Dong') THEN 1 ELSE 0 END) AS resolved
            FROM `tabCRM Issue` i
            WHERE {where} AND i.occurred_at IS NOT NULL
            GROUP BY period
            ORDER BY period
            """,
            time_values,
            as_dict=True,
        )
        by_time = [
            {
                "period": tr.period or "",
                "count": tr.count or 0,
                "resolved": tr.resolved or 0,
            }
            for tr in time_rows
        ]

        # ---------- (3) Theo Loai van de (issue_module) ----------
        module_rows = frappe.db.sql(
            f"""
            SELECT
                i.issue_module AS module,
                MAX(m.module_name) AS module_name,
                COUNT(*) AS count,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue
            FROM `tabCRM Issue` i
            LEFT JOIN `tabCRM Issue Module` m ON m.name = i.issue_module
            WHERE {where}
            GROUP BY i.issue_module
            ORDER BY count DESC
            """,
            values,
            as_dict=True,
        )
        by_module = [
            {
                "module": mr.module or "",
                "module_name": mr.module_name or mr.module or "Khac",
                "count": mr.count or 0,
                "overdue": mr.overdue or 0,
            }
            for mr in module_rows
        ]

        # ---------- (3b) Theo Nhom van de (Gop y / Su vu) ----------
        group_rows = frappe.db.sql(
            f"""
            SELECT
                COALESCE(NULLIF(i.issue_group, ''), '') AS issue_group,
                COUNT(*) AS count,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue
            FROM `tabCRM Issue` i
            WHERE {where}
            GROUP BY issue_group
            ORDER BY count DESC
            """,
            values,
            as_dict=True,
        )
        by_issue_group = [
            {
                "issue_group": gr.issue_group or "",
                "count": gr.count or 0,
                "overdue": gr.overdue or 0,
            }
            for gr in group_rows
        ]

        # ---------- (3c) Theo Muc do (gom Khan cap) ----------
        priority_rows = frappe.db.sql(
            f"""
            SELECT
                COALESCE(NULLIF(i.priority, ''), '') AS priority,
                COUNT(*) AS count,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue
            FROM `tabCRM Issue` i
            WHERE {where}
            GROUP BY priority
            ORDER BY count DESC
            """,
            values,
            as_dict=True,
        )
        by_priority = [
            {
                "priority": pr.priority or "",
                "count": pr.count or 0,
                "overdue": pr.overdue or 0,
            }
            for pr in priority_rows
        ]

        # ---------- (4) Theo Phong ban lien quan (cot department = phong ban chinh) ----------
        dept_rows = frappe.db.sql(
            f"""
            SELECT
                COALESCE(NULLIF(i.department, ''), '') AS department,
                MAX(ou.unit_name_vn) AS department_name,
                COUNT(*) AS count,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue
            FROM `tabCRM Issue` i
            LEFT JOIN `tabERP Organization Unit` ou ON ou.name = i.department
            WHERE {where}
            GROUP BY department
            ORDER BY count DESC
            """,
            values,
            as_dict=True,
        )
        by_department = [
            {
                "department": dr.department or "",
                "department_name": dr.department_name or "",
                "count": dr.count or 0,
                "overdue": dr.overdue or 0,
            }
            for dr in dept_rows
        ]

        # ---------- (5) Tinh trang xu ly ----------
        status_rows = frappe.db.sql(
            f"""
            SELECT i.status AS status, COUNT(*) AS count
            FROM `tabCRM Issue` i
            WHERE {where}
            GROUP BY i.status
            """,
            values,
            as_dict=True,
        )
        by_status = [{"status": sr.status or "", "count": sr.count or 0} for sr in status_rows]

        # ---------- (6) Thoi han xu ly + alert qua han ----------
        sla_values = dict(values)
        sla_values["due_soon_hours"] = DUE_SOON_HOURS
        sla_row = frappe.db.sql(
            f"""
            SELECT
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL
                         AND i.sla_deadline >= NOW()
                         AND i.sla_deadline < (NOW() + INTERVAL %(due_soon_hours)s HOUR)
                         THEN 1 ELSE 0 END) AS due_soon,
                SUM(CASE WHEN {open_clause}
                         AND (i.sla_deadline IS NULL OR i.sla_deadline >= (NOW() + INTERVAL %(due_soon_hours)s HOUR))
                         THEN 1 ELSE 0 END) AS on_track
            FROM `tabCRM Issue` i
            WHERE {where}
            """,
            sla_values,
            as_dict=True,
        )
        sr = sla_row[0] if sla_row else {}

        # Danh sach van de dang qua han (top theo deadline cu nhat) — phuc vu Alert qua han
        overdue_rows = frappe.db.sql(
            f"""
            SELECT
                i.name AS name,
                i.issue_code AS issue_code,
                i.title AS title,
                i.status AS status,
                i.occurred_at AS occurred_at,
                i.sla_deadline AS sla_deadline,
                i.pic AS pic,
                u.full_name AS pic_name,
                m.module_name AS module_name,
                ou.unit_name_vn AS department_name,
                TIMESTAMPDIFF(HOUR, i.sla_deadline, NOW()) AS hours_overdue
            FROM `tabCRM Issue` i
            LEFT JOIN `tabUser` u ON u.name = i.pic
            LEFT JOIN `tabCRM Issue Module` m ON m.name = i.issue_module
            LEFT JOIN `tabERP Organization Unit` ou ON ou.name = i.department
            WHERE {where} AND {open_clause}
              AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
            ORDER BY i.sla_deadline ASC
            LIMIT 20
            """,
            values,
            as_dict=True,
        )
        overdue_list = [
            {
                "name": orr.name,
                "issue_code": orr.issue_code or "",
                "title": orr.title or "",
                "status": orr.status or "",
                "occurred_at": str(orr.occurred_at)[:10] if orr.occurred_at else "",
                "sla_deadline": str(orr.sla_deadline)[:16] if orr.sla_deadline else "",
                "pic_name": (orr.pic_name or "").strip() or (orr.pic or ""),
                "module_name": orr.module_name or "",
                "department_name": orr.department_name or "",
                "hours_overdue": orr.hours_overdue or 0,
            }
            for orr in overdue_rows
        ]

        sla = {
            "overdue": sr.get("overdue") or 0,
            "due_soon": sr.get("due_soon") or 0,
            "on_track": sr.get("on_track") or 0,
            "due_soon_hours": DUE_SOON_HOURS,
            "overdue_list": overdue_list,
        }

        # ---------- (7) Muc do hai long ----------
        chua_danh_gia = total - rated
        satisfaction = {
            "hai_long": hai_long,
            "chua_hai_long": chua_hai_long,
            "chua_danh_gia": chua_danh_gia if chua_danh_gia > 0 else 0,
            "satisfaction_rate": _rate(hai_long, rated),
        }

        # ---------- (8) Theo PIC ----------
        pic_rows = frappe.db.sql(
            f"""
            SELECT
                COALESCE(NULLIF(i.pic, ''), '') AS pic,
                MAX(u.full_name) AS pic_name,
                COUNT(*) AS total,
                SUM(CASE WHEN {open_clause} THEN 1 ELSE 0 END) AS open_count,
                SUM(CASE WHEN i.status IN ('Hoan thanh', 'Dong') THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN {open_clause} AND i.sla_deadline IS NOT NULL AND i.sla_deadline < NOW()
                         THEN 1 ELSE 0 END) AS overdue,
                SUM(CASE WHEN i.result = 'Hai long' THEN 1 ELSE 0 END) AS hai_long,
                SUM(CASE WHEN i.result = 'Chua hai long' THEN 1 ELSE 0 END) AS chua_hai_long
            FROM `tabCRM Issue` i
            LEFT JOIN `tabUser` u ON u.name = i.pic
            WHERE {where}
            GROUP BY pic
            ORDER BY total DESC
            """,
            values,
            as_dict=True,
        )
        by_pic = []
        for pr in pic_rows:
            p_hai_long = pr.hai_long or 0
            p_chua = pr.chua_hai_long or 0
            p_rated = p_hai_long + p_chua
            by_pic.append(
                {
                    "pic": pr.pic or "",
                    "pic_name": (pr.pic_name or "").strip() or (pr.pic or ""),
                    "total": pr.total or 0,
                    "open": pr.open_count or 0,
                    "resolved": pr.resolved or 0,
                    "overdue": pr.overdue or 0,
                    "hai_long": p_hai_long,
                    "chua_hai_long": p_chua,
                    "satisfaction_rate": _rate(p_hai_long, p_rated),
                }
            )

        logs.append(f"Bao cao van de chung: {total} van de trong pham vi loc")
        return success_response(
            data={
                "granularity": granularity if granularity in GRANULARITY_FORMATS else "month",
                "overview": overview,
                "by_time": by_time,
                "by_module": by_module,
                "by_issue_group": by_issue_group,
                "by_priority": by_priority,
                "by_department": by_department,
                "by_status": by_status,
                "sla": sla,
                "satisfaction": satisfaction,
                "by_pic": by_pic,
            },
            message="Lay bao cao van de chung thanh cong",
            logs=logs,
        )

    except Exception as e:
        logs.append(f"Loi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "CRM Issue Report Error")
        return error_response(message=f"Loi: {str(e)}", logs=logs)
