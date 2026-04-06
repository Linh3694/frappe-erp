# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Báo cáo kỷ luật gửi email hàng ngày (scheduler + gọi thủ công).
Logic phân THCS/THPT khớp DisciplineDashboard (parse khối từ tên lớp).
"""

import re
from collections import defaultdict
from datetime import datetime

import frappe
from frappe.utils import escape_html

from erp.api.erp_sis.attendance import is_production_server
from erp.api.erp_sis.discipline import (
    _enrich_discipline_records_list,
    _get_request_data,
    _normalize_deduction_points,
)
from erp.utils.email_service import send_email_via_service

# Người nhận tạm thời (giai đoạn triển khai)
DISCIPLINE_REPORT_RECIPIENTS = [
    "linh.nguyenhai@wellspring.edu.vn",
    "hieu.nguyenduy@wellspring.edu.vn",
]

# Link mở báo cáo tương tác trên WIS (tab Tổng quan)
DISCIPLINE_DASHBOARD_URL = (
    "https://wis.wellspring.edu.vn/reports/discipline-dashboard/overview"
)

# Regex lấy số khối từ tên lớp — giống frontend getGradeFromClassTitle
_GRADE_FROM_TITLE_RE = re.compile(r"(?:Lớp\s*)?(\d+)", re.IGNORECASE)


def _get_grade_from_class_title(class_title: str):
    """Lấy khối từ tên lớp (6A1 -> 6). Không khớp thì None."""
    if not (class_title or "").strip():
        return None
    m = _GRADE_FROM_TITLE_RE.search(class_title.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _get_class_titles_for_record(record: dict):
    """
    Danh sách tên lớp dùng để xác định THCS/THPT — khớp utils.ts isTHCS/isTHPT.
    target_type === 'student' -> student_class_title; ngược lại -> target_class_titles.
    """
    target_type = (record.get("target_type") or "").strip()
    if target_type == "student":
        st = record.get("student_class_title") or ""
        return [st] if st else []
    return list(record.get("target_class_titles") or [])


def _is_thcs(record: dict) -> bool:
    for t in _get_class_titles_for_record(record):
        g = _get_grade_from_class_title(t)
        if g is not None and 6 <= g <= 9:
            return True
    return False


def _is_thpt(record: dict) -> bool:
    for t in _get_class_titles_for_record(record):
        g = _get_grade_from_class_title(t)
        if g is not None and 10 <= g <= 12:
            return True
    return False


def _classification_label(record: dict) -> str:
    return (
        (record.get("classification_title") or "").strip()
        or (record.get("classification") or "").strip()
        or "Không xác định"
    )


def _violation_label(record: dict) -> str:
    return (
        (record.get("violation_title") or "").strip()
        or (record.get("violation") or "").strip()
        or "Không xác định"
    )


def _records_for_school_scope(records: list, scope: str) -> list:
    """scope: 'thcs' | 'thpt' — chỉ bản ghi thuộc cấp đó."""
    if scope == "thcs":
        return [r for r in records if _is_thcs(r)]
    if scope == "thpt":
        return [r for r in records if _is_thpt(r)]
    return []


def _target_type_label_vn(record: dict) -> str:
    t = (record.get("target_type") or "").strip()
    if t == "student":
        return "Học sinh"
    if t == "class":
        return "Lớp"
    if t == "mixed":
        return "Hỗn hợp"
    return t or "Không xác định"


def _display_classes_or_student_line(record: dict) -> str:
    """Một dòng mô tả lớp / HS cho bảng chi tiết."""
    tt = (record.get("target_type") or "").strip()
    if tt == "student":
        parts = [
            record.get("student_class_title") or "",
            record.get("student_name") or "",
            record.get("student_code") or "",
        ]
        line = " — ".join(p for p in parts if p)
        return line or "-"
    titles = record.get("target_class_titles") or []
    if titles:
        return ", ".join(titles)
    return "-"


def _aggregate_counts(records: list, label_fn):
    acc = defaultdict(int)
    for r in records:
        acc[label_fn(r)] += 1
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))


def _html_table_two_columns(title: str, rows, col2_header: str) -> str:
    if not rows:
        return f"""
        <h3 style="color: #37474f; margin: 24px 0 8px 0;">{escape_html(title)}</h3>
        <p style="color: #757575; font-size: 14px;">Không có dữ liệu.</p>
        """
    body = ""
    for label, cnt in rows:
        body += f"""
        <tr>
            <td style="padding: 8px 10px; border: 1px solid #e0e0e0;">{escape_html(label)}</td>
            <td style="padding: 8px 10px; border: 1px solid #e0e0e0; text-align: center; width: 90px;">{cnt}</td>
        </tr>
        """
    return f"""
    <h3 style="color: #37474f; margin: 24px 0 8px 0;">{escape_html(title)}</h3>
    <table style="width: 100%; border-collapse: collapse; margin: 0 0 8px 0; font-size: 14px;">
        <thead>
            <tr style="background: #eceff1;">
                <th style="padding: 10px; border: 1px solid #cfd8dc; text-align: left;">Tên</th>
                <th style="padding: 10px; border: 1px solid #cfd8dc; text-align: center;">{escape_html(col2_header)}</th>
            </tr>
        </thead>
        <tbody>{body}</tbody>
    </table>
    """


def _html_detail_records_table(records: list, limit: int = 25) -> str:
    """Bảng bản ghi chi tiết (giới hạn số dòng)."""
    subset = records[:limit]
    if not subset:
        return ""
    rows_html = ""
    for r in subset:
        rid = escape_html(r.get("name") or "")
        cls_viol = escape_html(_classification_label(r))
        viol = escape_html(_violation_label(r))
        tgt = escape_html(_target_type_label_vn(r))
        line = escape_html(_display_classes_or_student_line(r))
        rt = r.get("record_time") or ""
        time_s = escape_html(str(rt)) if rt else "—"
        rows_html += f"""
        <tr>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{rid}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{time_s}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{cls_viol}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{viol}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{tgt}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{line}</td>
        </tr>
        """
    more = ""
    if len(records) > limit:
        more = f'<p style="color:#757575;font-size:13px;margin-top:8px;">… và {len(records) - limit} bản ghi khác (xem đầy đủ trên WIS).</p>'
    return f"""
    <h3 style="color: #37474f; margin: 24px 0 8px 0;">Chi tiết bản ghi (tối đa {limit} dòng đầu)</h3>
    <table style="width: 100%; border-collapse: collapse; margin: 0 0 8px 0; font-size: 13px;">
        <thead>
            <tr style="background: #eceff1;">
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Mã</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Giờ ghi</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Phân loại</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Vi phạm</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Đối tượng</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Lớp / học sinh</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    {more}
    """


def _generate_scoped_report_html(
    scope: str,
    school_title_vn: str,
    school_blurb: str,
    report_date_display: str,
    scoped_records: list,
):
    """
    Email chỉ dành cho một cấp (THCS hoặc THPT): không lẫn cột/khái niệm cấp kia.
    """
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    n = len(scoped_records)

    # Sắp bản ghi chi tiết: theo giờ ghi / modified
    def _sort_key(r):
        return (r.get("record_time") or "", r.get("modified") or "")

    detail_list = sorted(scoped_records, key=_sort_key, reverse=True)

    by_class = _aggregate_counts(scoped_records, _classification_label)
    by_violation = _aggregate_counts(scoped_records, _violation_label)
    by_target = _aggregate_counts(scoped_records, _target_type_label_vn)
    by_campus = _aggregate_counts(
        scoped_records,
        lambda r: (r.get("campus") or "").strip() or "Không gán cơ sở",
    )

    accent = "#1565c0" if scope == "thcs" else "#6a1b9a"
    empty_msg = ""
    if n == 0:
        khoi_hint = "khối 6–9" if scope == "thcs" else "khối 10–12"
        empty_msg = f"""
        <div style="background: #fff8e1; padding: 16px; border-radius: 8px; border-left: 4px solid #ffc107; margin: 16px 0;">
            <p style="margin: 0;">Không có bản ghi kỷ luật nào trong ngày được xếp vào <strong>{escape_html(school_title_vn)}</strong>
            (theo tên lớp thuộc {khoi_hint}).</p>
        </div>
        """

    dashboard_url = escape_html(DISCIPLINE_DASHBOARD_URL)

    parts = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 820px; margin: 0 auto; color: #212121;">
        <h1 style="color: {accent}; text-align: center; border-bottom: 3px solid {accent}; padding-bottom: 12px; margin-bottom: 8px;">
            Báo cáo kỷ luật — {escape_html(school_title_vn)}
        </h1>
        <p style="text-align: center; color: #546e7a; margin: 0 0 4px 0;">Ngày {escape_html(report_date_display)}</p>
        <p style="text-align: center; color: #78909c; font-size: 14px; margin: 0 0 20px 0;">{escape_html(school_blurb)}</p>

        <div style="text-align: center; margin: 24px 0;">
            <a href="{DISCIPLINE_DASHBOARD_URL}" target="_blank" rel="noopener noreferrer"
               style="display: inline-block; padding: 14px 28px; background: {accent}; color: #ffffff !important;
                      text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px;
                      box-shadow: 0 2px 6px rgba(0,0,0,0.12);">
                Mở Báo cáo kỷ luật trên WIS
            </a>
            <p style="font-size: 12px; color: #90a4ae; margin-top: 10px;">{dashboard_url}</p>
        </div>

        <div style="background: #f5f5f5; padding: 20px; border-radius: 10px; margin: 16px 0; border: 1px solid #e0e0e0;">
            <h2 style="color: #263238; margin: 0 0 12px 0; font-size: 18px;">Tổng quan trong ngày</h2>
            <p style="margin: 6px 0; font-size: 15px;"><strong>Số bản ghi thuộc {escape_html(school_title_vn)}:</strong> {n}</p>
            <p style="margin: 6px 0; font-size: 13px; color: #616161;">
                Báo cáo này chỉ thống kê bản ghi có lớp/học sinh thuộc khối tương ứng (theo tên lớp). Không gộp dữ liệu của cấp học khác.
            </p>
        </div>
        {empty_msg}
    """

    if n > 0:
        parts += _html_table_two_columns(
            "Theo phân loại kỷ luật", by_class, "Số bản ghi"
        )
        parts += _html_table_two_columns(
            "Theo loại vi phạm", by_violation, "Số bản ghi"
        )
        parts += _html_table_two_columns(
            "Theo đối tượng ghi nhận", by_target, "Số bản ghi"
        )
        parts += _html_table_two_columns(
            "Theo cơ sở (campus)", by_campus, "Số bản ghi"
        )
        parts += _html_detail_records_table(detail_list)

    parts += f"""
        <div style="background: #e8f5e9; padding: 14px 16px; border-radius: 8px; margin: 24px 0; font-size: 13px; color: #33691e;">
            <strong>Ghi chú kỹ thuật:</strong> Phân khối THCS (6–9) / THPT (10–12) dựa trên tên lớp (học sinh hoặc lớp đích),
            cùng quy tắc với màn Discipline Dashboard trên WIS.
        </div>

        <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 28px 0;">
        <div style="text-align: center; color: #78909c; font-size: 13px;">
            <p style="margin: 4px 0;"><strong>Hệ thống quản lý trường học</strong> — Wellspring</p>
            <p style="margin: 4px 0;">Thời gian tạo email: {now_str}</p>
        </div>
    </div>
    """
    return parts


def _fetch_discipline_records_for_date(report_date: str) -> list:
    """
    Lấy toàn bộ bản ghi kỷ luật trong ngày (không lọc campus), enrich giống get_discipline_records.
    """
    filters = {"date": report_date}
    list_kwargs = {
        "doctype": "SIS Discipline Record",
        "filters": filters,
        "fields": [
            "name",
            "date",
            "classification",
            "violation_count",
            "target_type",
            "target_student",
            "violation",
            "severity_level",
            "form",
            "penalty_points",
            "historical_deduction_points",
            "time_slot",
            "time_slot_id",
            "record_time",
            "description",
            "owner",
            "modified",
            "campus",
        ],
        "order_by": "modified desc",
    }
    records = frappe.get_all(**list_kwargs)
    record_ids = [r["name"] for r in records]

    if record_ids:
        class_entries = frappe.get_all(
            "SIS Discipline Record Class Entry",
            filters={"parent": ["in", record_ids]},
            fields=["parent", "class_id", "deduction_points"],
        )
        class_map_ids = {}
        class_map_entries = {}
        for ce in class_entries:
            cid = ce.get("class_id")
            if not cid:
                continue
            pid = ce["parent"]
            class_map_ids.setdefault(pid, []).append(cid)
            class_map_entries.setdefault(pid, []).append(
                {
                    "class_id": cid,
                    "deduction_points": _normalize_deduction_points(ce.get("deduction_points")),
                }
            )

        student_entries = frappe.get_all(
            "SIS Discipline Record Student Entry",
            filters={"parent": ["in", record_ids]},
            fields=["parent", "student_id", "deduction_points"],
        )
        student_entry_rows = {}
        for se in student_entries:
            sid = se.get("student_id")
            if not sid:
                continue
            pid = se["parent"]
            student_entry_rows.setdefault(pid, []).append(
                {
                    "student_id": sid,
                    "deduction_points": _normalize_deduction_points(se.get("deduction_points")),
                }
            )

        class_ids = list({c for ids in class_map_ids.values() for c in ids})
        class_titles = {}
        if class_ids:
            for c in frappe.get_all(
                "SIS Class",
                filters={"name": ["in", class_ids]},
                fields=["name", "title"],
            ):
                class_titles[c["name"]] = c.get("title") or c["name"]

        for r in records:
            r["target_class_ids"] = class_map_ids.get(r["name"], [])
            r["target_class_entries"] = class_map_entries.get(r["name"], [])
            r["target_class_titles"] = [
                class_titles.get(cid, cid) for cid in r["target_class_ids"]
            ]
            rows = student_entry_rows.get(r["name"], [])
            r["target_student_entry_rows"] = rows
            stu_ids = [x["student_id"] for x in rows]
            if not stu_ids and r.get("target_student"):
                stu_ids = [r["target_student"]]
                r["target_student_entry_rows"] = [
                    {"student_id": r["target_student"], "deduction_points": "10"}
                ]
            r["target_student_ids"] = stu_ids
    else:
        for r in records:
            r["target_class_ids"] = []
            r["target_class_titles"] = []
            r["target_student_ids"] = [r["target_student"]] if r.get("target_student") else []
            r["target_student_entry_rows"] = []

    _enrich_discipline_records_list(records)
    return records


def _send_discipline_reports_for_date(report_date: str):
    """
    Gửi 2 email: THCS và THPT — mỗi email chỉ dữ liệu và ngữ cảnh của một cấp.
    """
    records = _fetch_discipline_records_for_date(report_date)
    all_count = len(records)
    thcs_records = _records_for_school_scope(records, "thcs")
    thpt_records = _records_for_school_scope(records, "thpt")
    thcs_count = len(thcs_records)
    thpt_count = len(thpt_records)

    try:
        d_obj = datetime.strptime(report_date, "%Y-%m-%d")
        report_date_display = d_obj.strftime("%d/%m/%Y")
    except Exception:
        report_date_display = report_date

    results = []

    body_thcs = _generate_scoped_report_html(
        "thcs",
        "Trường THCS (Trung học cơ sở)",
        "Khối lớp 6–9 — báo cáo chỉ gồm bản ghi thuộc phạm vi THCS.",
        report_date_display,
        thcs_records,
    )
    r1 = send_email_via_service(
        DISCIPLINE_REPORT_RECIPIENTS,
        subject=f"[WSHN] Báo cáo kỷ luật THCS ngày {report_date_display}",
        body=body_thcs,
    )
    results.append({"school": "THCS", "email": r1})

    body_thpt = _generate_scoped_report_html(
        "thpt",
        "Trường THPT (Trung học phổ thông)",
        "Khối lớp 10–12 — báo cáo chỉ gồm bản ghi thuộc phạm vi THPT.",
        report_date_display,
        thpt_records,
    )
    r2 = send_email_via_service(
        DISCIPLINE_REPORT_RECIPIENTS,
        subject=f"[WSHN] Báo cáo kỷ luật THPT ngày {report_date_display}",
        body=body_thpt,
    )
    results.append({"school": "THPT", "email": r2})

    return {
        "success": all(x["email"].get("success") for x in results),
        "results": results,
        "report_date": report_date,
        "stats": {
            "all_records": all_count,
            "thcs_records": thcs_count,
            "thpt_records": thpt_count,
        },
    }


def daily_discipline_email_report():
    """
    Scheduler: 17h hàng ngày. Giai đoạn test — không gửi khi is_production = true.
    """
    try:
        if is_production_server():
            frappe.logger().info(
                "⏭️ Bỏ qua daily_discipline_email_report — server production (chờ bật sau khi hoàn thiện)"
            )
            return {"success": True, "skipped": True, "reason": "production"}

        report_date = frappe.utils.nowdate()
        frappe.logger().info(f"📧 daily_discipline_email_report — ngày {report_date}")
        return _send_discipline_reports_for_date(report_date)
    except Exception as e:
        frappe.logger().error(f"❌ daily_discipline_email_report: {str(e)}")
        frappe.log_error(f"daily_discipline_email_report: {str(e)}")
        return {"success": False, "message": str(e)}


def _coerce_date_string(date_val, req):
    """
    Chuẩn hoá ngày YYYY-MM-DD.
    frappe.call(path, {"date": "..."}) có thể gán cả dict vào tham số date — lấy key date.
    """
    if isinstance(date_val, dict):
        date_val = date_val.get("date")

    def _to_str(v):
        if v is None:
            return ""
        if isinstance(v, dict):
            return _to_str(v.get("date"))
        return str(v).strip()

    s = _to_str(date_val)
    if not s and isinstance(req, dict):
        s = _to_str(req.get("date"))
    return s or frappe.utils.nowdate()


@frappe.whitelist(allow_guest=False)
def send_discipline_daily_report(date=None):
    """
    Gọi thủ công qua API để test (cùng điều kiện production: không gửi trên production).
    Params: date (YYYY-MM-DD), mặc định hôm nay.

    POST /api/method/erp.api.erp_sis.discipline_report.send_discipline_daily_report
    """
    try:
        if is_production_server():
            frappe.logger().info(
                "⏭️ Bỏ qua send_discipline_daily_report — server production"
            )
            return {
                "success": True,
                "skipped": True,
                "reason": "production",
            }

        req = _get_request_data()
        report_date = _coerce_date_string(date, req)

        return _send_discipline_reports_for_date(report_date)
    except Exception as e:
        frappe.logger().error(f"send_discipline_daily_report: {str(e)}")
        frappe.log_error(f"send_discipline_daily_report: {str(e)}")
        return {"success": False, "message": str(e)}
