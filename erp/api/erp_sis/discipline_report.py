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
    titles = []
    for st in record.get("target_students") or []:
        title = (st.get("student_class_title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    if titles:
        return titles

    target_type = (record.get("target_type") or "").strip()
    if target_type == "student":
        st = (record.get("student_class_title") or "").strip()
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


def _severity_level_key(record: dict) -> str:
    raw = str(record.get("severity_level") or "").strip()
    if raw in {"1", "2", "3"}:
        return raw
    m = re.search(r"([123])", raw)
    if m:
        return m.group(1)
    return "unknown"


def _aggregate_severity_counts(records: list):
    counts = {"1": 0, "2": 0, "3": 0, "unknown": 0}
    for r in records:
        counts[_severity_level_key(r)] += 1
    rows = [(f"Mức độ {level}", counts[level]) for level in ("1", "2", "3")]
    if counts["unknown"]:
        rows.append(("Không xác định", counts["unknown"]))
    return rows


def _records_for_school_scope(records: list, scope: str) -> list:
    """scope: 'thcs' | 'thpt' — chỉ bản ghi thuộc cấp đó."""
    if scope == "thcs":
        return [r for r in records if _is_thcs(r)]
    if scope == "thpt":
        return [r for r in records if _is_thpt(r)]
    return []


def _collect_student_ids_from_record(record: dict):
    ids = []
    for st in record.get("target_students") or []:
        sid = st.get("student_id")
        if sid:
            ids.append(sid)
    if ids:
        return ids
    if (record.get("target_type") or "").strip() != "class" and record.get("target_student"):
        return [record.get("target_student")]
    if (record.get("target_type") or "").strip() != "class":
        return [sid for sid in record.get("target_student_ids") or [] if sid]
    return []


def _student_class_title_for_record(record: dict, student_id: str):
    for st in record.get("target_students") or []:
        if st.get("student_id") == student_id and st.get("student_class_title"):
            return st.get("student_class_title")
    if record.get("target_student") == student_id and record.get("student_class_title"):
        return record.get("student_class_title")
    if student_id in (record.get("target_student_ids") or []) and record.get("student_class_title"):
        return record.get("student_class_title")
    return ""


def _student_program_bucket(student_id: str, records: list):
    max_grade = None
    for r in records:
        if student_id not in _collect_student_ids_from_record(r):
            continue
        grade = _get_grade_from_class_title(_student_class_title_for_record(r, student_id) or "")
        if grade is not None and (max_grade is None or grade > max_grade):
            max_grade = grade
    if max_grade is None:
        return None
    if 6 <= max_grade <= 9:
        return "thcs"
    if 10 <= max_grade <= 12:
        return "thpt"
    return None


def _student_ids_for_scope(records: list, scope: str):
    ids = set()
    for r in records:
        for sid in _collect_student_ids_from_record(r):
            if _student_program_bucket(sid, records) == scope:
                ids.add(sid)
    return ids


def _aggregate_student_counts_for_scope(records: list, scope: str, label_fn):
    acc = defaultdict(set)
    for r in records:
        label = label_fn(r)
        for sid in _collect_student_ids_from_record(r):
            if _student_program_bucket(sid, records) == scope:
                acc[label].add(sid)
    return sorted(((label, len(ids)) for label, ids in acc.items()), key=lambda x: (-x[1], x[0]))


def _aggregate_student_severity_counts_for_scope(records: list, scope: str):
    student_max = {}
    for r in records:
        level = _severity_level_key(r)
        if level not in {"1", "2", "3"}:
            continue
        for sid in _collect_student_ids_from_record(r):
            if _student_program_bucket(sid, records) != scope:
                continue
            prev = student_max.get(sid)
            if prev is None or int(level) > int(prev):
                student_max[sid] = level

    counts = {"1": 0, "2": 0, "3": 0}
    for level in student_max.values():
        counts[level] += 1
    return [(f"Mức độ {level}", counts[level]) for level in ("1", "2", "3")]


def _aggregate_counts(records: list, label_fn):
    acc = defaultdict(int)
    for r in records:
        acc[label_fn(r)] += 1
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))


def _target_type_label_vn(record: dict) -> str:
    t = (record.get("target_type") or "").strip()
    if t == "student":
        return "Học sinh"
    if t == "class":
        return "Lớp"
    if t == "mixed":
        return "Hỗn hợp"
    return t or "Không xác định"


def _html_count_list(title: str, rows) -> str:
    if not rows:
        return f"""
        <p style="margin: 18px 0 6px 0; font-weight: 700;">{escape_html(title)} :</p>
        <p style="margin: 4px 0 0 0; color: #757575;">Không có dữ liệu.</p>
        """
    body = []
    for label, cnt in rows:
        body.append(
            f'<li style="margin: 5px 0;"><span>{escape_html(label)}</span>: <strong>{cnt}</strong></li>'
        )
    return f"""
    <p style="margin: 18px 0 6px 0; font-weight: 700;">{escape_html(title)} :</p>
    <ul style="margin: 0 0 0 18px; padding: 0;">{''.join(body)}</ul>
    """


def _class_line_for_record(record: dict) -> str:
    titles = [t for t in record.get("target_class_titles") or [] if t]
    if titles:
        return ", ".join(titles)
    if record.get("student_class_title"):
        return record.get("student_class_title")
    students = record.get("target_students") or []
    class_titles = []
    for st in students:
        title = st.get("student_class_title")
        if title and title not in class_titles:
            class_titles.append(title)
    return ", ".join(class_titles) if class_titles else "-"


def _students_line_for_record(record: dict) -> str:
    students = record.get("target_students") or []
    if students:
        lines = []
        for st in students:
            name = st.get("student_name") or st.get("student_id") or ""
            code = st.get("student_code") or ""
            class_title = st.get("student_class_title") or ""
            main = f"{name} ({code})" if code else name
            lines.append(" - ".join(x for x in [class_title, main] if x))
        return "; ".join(lines)
    if record.get("student_name"):
        return " - ".join(
            x
            for x in [
                record.get("student_class_title") or "",
                record.get("student_name") or "",
                record.get("student_code") or "",
            ]
            if x
        )
    return ""


def _html_detail_records_table(records: list, limit: int = 50) -> str:
    """Bảng chi tiết giúp BGH/GVCN thấy rõ lớp nào phát sinh vi phạm trong ngày."""
    subset = records[:limit]
    if not subset:
        return ""
    rows_html = ""
    for r in subset:
        cls_viol = escape_html(_classification_label(r))
        viol = escape_html(_violation_label(r))
        class_line = escape_html(_class_line_for_record(r))
        student_line = escape_html(_students_line_for_record(r) or _target_type_label_vn(r))
        severity = _severity_level_key(r)
        severity_label = f"Mức độ {severity}" if severity != "unknown" else "Không xác định"
        desc = escape_html(r.get("description") or "")
        rt = r.get("record_time") or ""
        time_s = escape_html(str(rt)) if rt else "—"
        rows_html += f"""
        <tr>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{time_s}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{class_line}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{student_line}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{cls_viol}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{viol}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{escape_html(severity_label)}</td>
            <td style="padding: 6px 8px; border: 1px solid #e0e0e0; font-size: 13px;">{desc}</td>
        </tr>
        """
    more = ""
    if len(records) > limit:
        more = f'<p style="color:#757575;font-size:13px;margin-top:8px;">… và {len(records) - limit} bản ghi khác (xem đầy đủ trên WIS).</p>'
    return f"""
    <h3 style="color: #37474f; margin: 24px 0 8px 0;">Các vi phạm diễn ra trong ngày</h3>
    <table style="width: 100%; border-collapse: collapse; margin: 0 0 8px 0; font-size: 13px;">
        <thead>
            <tr style="background: #eceff1;">
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Giờ ghi</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Lớp</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Học sinh / đối tượng</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Loại vi phạm</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Vi phạm</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Mức độ</th>
                <th style="padding: 8px; border: 1px solid #cfd8dc;">Mô tả</th>
            </tr>
        </thead>
        <tbody>{rows_html}</tbody>
    </table>
    {more}
    """


def _generate_scoped_report_html(
    scope: str,
    report_date_display: str,
    scoped_records: list,
    all_records: list,
):
    """Email chỉ dành cho một cấp (THCS hoặc THPT): không lẫn dữ liệu cấp kia."""
    n = len(_student_ids_for_scope(all_records, scope))

    by_classification = _aggregate_student_counts_for_scope(
        all_records,
        scope,
        _classification_label,
    )
    by_severity = _aggregate_student_severity_counts_for_scope(all_records, scope)
    accent = "#1565c0" if scope == "thcs" else "#6a1b9a"
    dashboard_url = escape_html(DISCIPLINE_DASHBOARD_URL)
    school_short = "THCS" if scope == "thcs" else "THPT"
    detail_records = sorted(
        scoped_records,
        key=lambda r: (r.get("record_time") or "", r.get("modified") or ""),
        reverse=True,
    )

    parts = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 820px; margin: 0 auto; color: #212121; line-height: 1.55;">
        <p style="margin: 0 0 12px 0;">Kính gửi Ban Giám hiệu và các Thầy/Cô Chủ nhiệm khối {escape_html(school_short)},</p>

        <p style="margin: 0 0 14px 0;">
            Ban An toàn học đường kính gửi Quý Thầy Cô thông tin tóm tắt về nề nếp, kỷ luật học sinh ngày
            {escape_html(report_date_display)} cụ thể:
        </p>

        <p style="margin: 0 0 12px 0; font-weight: 700;">Chi tiết Học sinh vi phạm đính kèm trong email này:</p>

        <div style="background: #f7fbff; border-left: 4px solid {accent}; padding: 14px 16px; margin: 12px 0 16px 0;">
            <p style="margin: 4px 0;"><strong>Thời gian :</strong> {escape_html(report_date_display)}</p>
            <p style="margin: 4px 0;"><strong>Trường :</strong> {escape_html(school_short)}</p>
            <p style="margin: 4px 0;"><strong>Tổng số học sinh vi phạm :</strong> {n}</p>
        </div>
    """

    parts += _html_count_list("Loại Vi phạm", by_classification)
    parts += _html_count_list("Mức độ vi phạm", by_severity)
    parts += _html_detail_records_table(detail_records)
    parts += f"""
        <p style="margin: 18px 0 10px 0;">
            Đồng thời Ban An toàn học đường gửi Ban Giám hiệu và Quý Thầy Cô file theo dõi vi phạm và điểm thi đua lớp
            hàng tháng để tiện theo dõi và có hướng hỗ trợ cho học sinh vi phạm.
        </p>

        <p style="margin: 0 0 16px 0;">
            <a href="{DISCIPLINE_DASHBOARD_URL}" target="_blank" rel="noopener noreferrer"
               style="color: {accent}; font-weight: 700; text-decoration: underline;">{dashboard_url}</a>
        </p>

        <p style="margin: 0 0 14px 0;">
            Rất mong Quý Thầy Cô hỗ trợ theo dõi, kịp thời nhắc nhở học sinh trong tiết sinh hoạt đầu giờ và phối hợp
            chặt chẽ với Phụ huynh để cùng Ban An toàn học đường cải thiện nề nếp – kỷ luật của học sinh.
        </p>

        <p style="margin: 0 0 12px 0;">Trân trọng cảm ơn Quý Thầy Cô</p>
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
    thcs_count = len(_student_ids_for_scope(records, "thcs"))
    thpt_count = len(_student_ids_for_scope(records, "thpt"))

    try:
        d_obj = datetime.strptime(report_date, "%Y-%m-%d")
        report_date_display = d_obj.strftime("%d/%m/%Y")
    except Exception:
        report_date_display = report_date

    results = []

    body_thcs = _generate_scoped_report_html(
        "thcs",
        report_date_display,
        thcs_records,
        records,
    )
    r1 = send_email_via_service(
        DISCIPLINE_REPORT_RECIPIENTS,
        subject=f"[WSHN] Báo cáo kỷ luật THCS ngày {report_date_display}",
        body=body_thcs,
    )
    results.append({"school": "THCS", "email": r1})

    body_thpt = _generate_scoped_report_html(
        "thpt",
        report_date_display,
        thpt_records,
        records,
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
    Scheduler: 17h hàng ngày.
    """
    try:
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
    Gọi thủ công qua API để gửi/test báo cáo theo ngày.
    Params: date (YYYY-MM-DD), mặc định hôm nay.

    POST /api/method/erp.api.erp_sis.discipline_report.send_discipline_daily_report
    """
    try:
        req = _get_request_data()
        report_date = _coerce_date_string(date, req)

        return _send_discipline_reports_for_date(report_date)
    except Exception as e:
        frappe.logger().error(f"send_discipline_daily_report: {str(e)}")
        frappe.log_error(f"send_discipline_daily_report: {str(e)}")
        return {"success": False, "message": str(e)}
