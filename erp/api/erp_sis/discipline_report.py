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
from erp.utils.school_day_utils import is_school_instruction_day

# Danh sách người nhận theo cấp THCS / THPT (production)
DISCIPLINE_REPORT_RECIPIENTS_THCS = [
    "nga.lt@wellspring.edu.vn",
    "linh.nguyenviet@wellspring.edu.vn",
    "chunhiem_thcs@wellspring.edu.vn",
]
DISCIPLINE_REPORT_RECIPIENTS_THPT = [
    "nhan.dothithanh@wellspring.edu.vn",
    "minh.hoangthi@wellspring.edu.vn",
    "chunhiem_thpt@wellspring.edu.vn",
]

# CC dùng chung cho cả 2 cấp — Ban An toàn học đường + lãnh đạo theo dõi
DISCIPLINE_REPORT_CC_COMMON = [
    "antoanhocduong@wellspring.edu.vn",
    "son.nguyenvinh@wellspring.edu.vn",
]

# Hộp thư gửi đi — đồng bộ các email tự động khác (xem finance/notification.py)
DISCIPLINE_REPORT_SENDER = "no-reply@wellspring.edu.vn"


def _is_production_server() -> bool:
    """
    Cờ production đọc từ site_config.json: "is_production": true.
    Trùng pattern với otp_auth.is_production_server / attendance.is_production_server.
    """
    try:
        return bool(frappe.get_site_config().get("is_production", False))
    except Exception:
        return False


def _recipients_for_scope(scope: str) -> list:
    if scope == "thcs":
        return list(DISCIPLINE_REPORT_RECIPIENTS_THCS)
    if scope == "thpt":
        return list(DISCIPLINE_REPORT_RECIPIENTS_THPT)
    return []


def _cc_for_scope(scope: str) -> list:
    """Hiện cả 2 cấp dùng chung danh sách CC; tách hàm sẵn cho tương lai cần khác nhau."""
    if scope in {"thcs", "thpt"}:
        return list(DISCIPLINE_REPORT_CC_COMMON)
    return []

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


def _collect_instances_from_record(record: dict):
    """
    Mỗi đối tượng (HS hoặc lớp) trong bản ghi sinh ra 1 instance — đồng bộ frontend
    collectInstancesFromRecord. Class được coi như 1 đối tượng độc lập (1 lượt).
    """
    out = []
    target_type = (record.get("target_type") or "").strip()

    target_students = record.get("target_students") or []
    if target_students:
        for st in target_students:
            sid = st.get("student_id")
            if not sid:
                continue
            out.append(
                {
                    "kind": "student",
                    "id": sid,
                    "class_title": (st.get("student_class_title") or "").strip() or None,
                }
            )
    elif target_type != "class" and record.get("target_student"):
        out.append(
            {
                "kind": "student",
                "id": record.get("target_student"),
                "class_title": (record.get("student_class_title") or "").strip() or None,
            }
        )
    elif target_type != "class":
        for sid in record.get("target_student_ids") or []:
            if not sid:
                continue
            out.append(
                {
                    "kind": "student",
                    "id": sid,
                    "class_title": (record.get("student_class_title") or "").strip() or None,
                }
            )

    class_entries = record.get("target_class_entries") or []
    target_class_ids = record.get("target_class_ids") or []
    target_class_titles = record.get("target_class_titles") or []
    if class_entries:
        for i, ce in enumerate(class_entries):
            cid = ce.get("class_id")
            if not cid:
                continue
            try:
                idx = target_class_ids.index(cid)
            except ValueError:
                idx = i
            title = (
                target_class_titles[idx]
                if 0 <= idx < len(target_class_titles)
                else cid
            )
            out.append({"kind": "class", "id": cid, "class_title": title or cid})
    elif target_type == "class":
        max_len = max(len(target_class_ids), len(target_class_titles))
        if max_len > 0:
            for i in range(max_len):
                cid = (
                    (target_class_ids[i] if i < len(target_class_ids) else None)
                    or (target_class_titles[i] if i < len(target_class_titles) else None)
                    or ""
                )
                if not cid:
                    continue
                title = target_class_titles[i] if i < len(target_class_titles) else cid
                out.append({"kind": "class", "id": cid, "class_title": title or cid})
        else:
            # Class-only nhưng không có thông tin lớp — giữ 1 instance
            out.append(
                {
                    "kind": "class",
                    "id": record.get("name") or "",
                    "class_title": None,
                }
            )

    return out


def _instance_program_bucket(inst: dict, records: list):
    """Khối THCS/THPT cho 1 instance — theo class title; fallback theo records (HS)."""
    grade = _get_grade_from_class_title((inst.get("class_title") or ""))
    if grade is not None:
        if 6 <= grade <= 9:
            return "thcs"
        if 10 <= grade <= 12:
            return "thpt"
    if inst.get("kind") == "student":
        return _student_program_bucket(inst.get("id"), records)
    return None


def _records_for_school_scope(records: list, scope: str) -> list:
    """scope: 'thcs' | 'thpt' — bản ghi có ít nhất 1 instance (HS hoặc lớp) thuộc cấp."""
    if scope not in {"thcs", "thpt"}:
        return []
    out = []
    for r in records:
        for inst in _collect_instances_from_record(r):
            if _instance_program_bucket(inst, records) == scope:
                out.append(r)
                break
    return out


def _count_instances_for_scope(records: list, scope: str) -> int:
    """Tổng số lượt vi phạm thuộc cấp (mỗi HS/lớp × bản ghi = 1 lượt)."""
    n = 0
    for r in records:
        for inst in _collect_instances_from_record(r):
            if _instance_program_bucket(inst, records) == scope:
                n += 1
    return n


def _aggregate_instance_counts_for_scope(records: list, scope: str, label_fn):
    """Đếm số lượt theo label (vd phân loại) cho cấp THCS/THPT."""
    acc = defaultdict(int)
    for r in records:
        label = label_fn(r)
        for inst in _collect_instances_from_record(r):
            if _instance_program_bucket(inst, records) == scope:
                acc[label] += 1
    return sorted(acc.items(), key=lambda x: (-x[1], x[0]))


def _aggregate_instance_severity_counts_for_scope(records: list, scope: str):
    """Đếm số lượt theo cấp độ (lấy trực tiếp severity_level trên record) cho cấp THCS/THPT."""
    counts = {"1": 0, "2": 0, "3": 0, "unknown": 0}
    for r in records:
        level = _severity_level_key(r)
        if level not in counts:
            continue
        for inst in _collect_instances_from_record(r):
            if _instance_program_bucket(inst, records) == scope:
                counts[level] += 1
    rows = [(f"Mức độ {level}", counts[level]) for level in ("1", "2", "3")]
    if counts["unknown"]:
        rows.append(("Không xác định", counts["unknown"]))
    return rows


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
        return (
            f'<p style="margin:14px 0 4px 0;"><strong>{escape_html(title)}:</strong> '
            f'<span style="color:#666;">Không có dữ liệu.</span></p>'
        )
    items = "".join(
        f'<li>{escape_html(label)}: <strong>{cnt}</strong></li>' for label, cnt in rows
    )
    return (
        f'<p style="margin:14px 0 4px 0;"><strong>{escape_html(title)}:</strong></p>'
        f'<ul style="margin:0 0 0 20px;padding:0;">{items}</ul>'
    )


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


def _violation_count_display_for_record(record: dict) -> str:
    """Số lần vi phạm trong tháng (enrich từ discipline_monthly_escalation)."""
    if record.get("violations_count_display") is not None:
        return str(record["violations_count_display"])
    students = record.get("target_students") or []
    counts = [
        s.get("violations_total_this_month")
        for s in students
        if s.get("violations_total_this_month") is not None
    ]
    if counts:
        return str(max(counts))
    return "—"


def _record_row_highlight_attr(record: dict) -> str:
    """Tô nền hàng email khi HS đã vượt ngưỡng lặp vi phạm trong tháng."""
    if record.get("escalation_highlight"):
        return ' style="background:#fff8e6;"'
    for st in record.get("target_students") or []:
        if st.get("escalation_highlight"):
            return ' style="background:#fff8e6;"'
    return ""


def _html_detail_records_table(records: list, limit: int = 50) -> str:
    """Bảng chi tiết giúp BGH/GVCN thấy rõ lớp nào phát sinh vi phạm trong ngày."""
    subset = records[:limit]
    if not subset:
        return ""

    cell = 'style="padding:6px 8px;border:1px solid #ddd;vertical-align:top;"'
    rows_html = []
    for r in subset:
        cls_viol = escape_html(_classification_label(r))
        viol = escape_html(_violation_label(r))
        class_line = escape_html(_class_line_for_record(r))
        student_line = escape_html(_students_line_for_record(r) or _target_type_label_vn(r))
        severity = _severity_level_key(r)
        severity_label = f"Mức độ {severity}" if severity != "unknown" else "Không xác định"
        desc = escape_html(r.get("description") or "")
        viol_count = escape_html(_violation_count_display_for_record(r))
        rt = r.get("record_time") or ""
        time_s = escape_html(str(rt)) if rt else "—"
        row_style = _record_row_highlight_attr(r)
        rows_html.append(
            f"<tr{row_style}>"
            f"<td {cell}>{time_s}</td>"
            f"<td {cell}>{class_line}</td>"
            f"<td {cell}>{student_line}</td>"
            f"<td {cell}>{cls_viol}</td>"
            f"<td {cell}>{viol}</td>"
            f"<td {cell}>{escape_html(severity_label)}</td>"
            f"<td {cell}>{viol_count}</td>"
            f"<td {cell}>{desc}</td>"
            f"</tr>"
        )
    more = ""
    if len(records) > limit:
        more = (
            f'<p style="color:#666;margin:6px 0 0 0;">'
            f'… và {len(records) - limit} bản ghi khác (xem đầy đủ trên WIS).</p>'
        )
    head = 'style="padding:6px 8px;border:1px solid #ddd;text-align:left;background:#f5f5f5;"'
    return (
        '<p style="margin:18px 0 6px 0;"><strong>Chi tiết vi phạm trong ngày:</strong></p>'
        '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
        "<thead><tr>"
        f'<th {head}>Giờ ghi</th>'
        f'<th {head}>Lớp</th>'
        f'<th {head}>Học sinh / đối tượng</th>'
        f'<th {head}>Loại vi phạm</th>'
        f'<th {head}>Vi phạm</th>'
        f'<th {head}>Mức độ</th>'
        f'<th {head}>Số lần VP (tháng)</th>'
        f'<th {head}>Mô tả</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
        f"{more}"
    )


def _generate_scoped_report_html(
    scope: str,
    report_date_display: str,
    scoped_records: list,
    all_records: list,
):
    """
    Email cho một cấp (THCS hoặc THPT) — định dạng tối giản, formal:
    không nền màu, không accent, chỉ dùng <p>/<ul>/<table> với border xám nhạt.
    """
    n = _count_instances_for_scope(all_records, scope)

    by_classification = _aggregate_instance_counts_for_scope(
        all_records,
        scope,
        _classification_label,
    )
    by_severity = _aggregate_instance_severity_counts_for_scope(all_records, scope)
    school_short = "THCS" if scope == "thcs" else "THPT"
    dashboard_url = escape_html(DISCIPLINE_DASHBOARD_URL)
    detail_records = sorted(
        scoped_records,
        key=lambda r: (r.get("record_time") or "", r.get("modified") or ""),
        reverse=True,
    )

    parts = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.55;max-width:820px;">'
        f'<p style="margin:0 0 12px 0;">Kính gửi Ban Giám hiệu và các Thầy/Cô Chủ nhiệm khối {escape_html(school_short)},</p>'
        '<p style="margin:0 0 12px 0;">'
        'Ban An toàn học đường kính gửi Quý Thầy Cô báo cáo nề nếp, kỷ luật học sinh ngày '
        f'<strong>{escape_html(report_date_display)}</strong> như sau:</p>'
        '<ul style="margin:0 0 12px 20px;padding:0;">'
        f'<li>Trường: <strong>{escape_html(school_short)}</strong></li>'
        f'<li>Ngày: <strong>{escape_html(report_date_display)}</strong></li>'
        f'<li>Tổng số lượt vi phạm: <strong>{n}</strong></li>'
        '</ul>'
    )

    parts += _html_count_list("Phân loại vi phạm", by_classification)
    parts += _html_count_list("Mức độ vi phạm", by_severity)
    parts += _html_detail_records_table(detail_records)

    parts += (
        '<p style="margin:18px 0 8px 0;">'
        'Quý Thầy Cô có thể xem báo cáo đầy đủ trên hệ thống WIS tại: '
        f'<a href="{DISCIPLINE_DASHBOARD_URL}">{dashboard_url}</a>'
        '</p>'
        '<p style="margin:0 0 12px 0;">'
        'Rất mong Quý Thầy Cô hỗ trợ theo dõi, nhắc nhở học sinh trong tiết sinh hoạt đầu giờ và phối hợp '
        'với Phụ huynh để cùng Ban An toàn học đường cải thiện nề nếp – kỷ luật của học sinh.'
        '</p>'
        '<p style="margin:0 0 4px 0;">Trân trọng cảm ơn Quý Thầy Cô.</p>'
        '<p style="margin:18px 0 0 0;">'
        'Trân trọng,<br>'
        '<strong>Ban An toàn học đường — Wellspring Hanoi</strong>'
        '</p>'
        '</div>'
    )
    # Chân chữ ký Wellspring (địa chỉ các trường + banner) sẽ được email-service
    # tự động chèn vào khi gửi từ mailbox no-reply — không append thủ công ở đây.
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


def _send_discipline_reports_for_date(report_date: str, force: bool = False):
    """
    Gửi 2 email: THCS và THPT — mỗi email chỉ dữ liệu và ngữ cảnh của một cấp.

    Chỉ gửi thật trên production (site_config.is_production = true). Trên môi
    trường staging/dev, hàm trả về `success=True, skipped="dev"` để tránh spam
    người nhận thật. Dev có thể truyền `force=True` (qua API thủ công) để test.
    """
    if not force and not _is_production_server():
        frappe.logger().info(
            f"[discipline_report] Bỏ qua gửi email ngày {report_date} — không phải production server."
        )
        return {
            "success": True,
            "skipped": "non_production",
            "message": "Không phải production server — bỏ qua gửi email kỷ luật.",
            "report_date": report_date,
        }

    # Scheduler / gửi thông thường: chỉ gửi ngày có tiết theo TKB (toàn site — mọi campus)
    if not force:
        ok_day, day_meta = is_school_instruction_day(report_date, campus_id=None)
        if not ok_day:
            frappe.logger().info(
                f"[discipline_report] Bỏ qua gửi email ngày {report_date} — không phải ngày học theo TKB: "
                f"{day_meta.get('reason')} ({day_meta})"
            )
            return {
                "success": True,
                "skipped": "school_day_off",
                "message": "Không phải ngày học theo TKB — bỏ qua gửi email kỷ luật.",
                "report_date": report_date,
                "school_day_meta": day_meta,
            }

    records = _fetch_discipline_records_for_date(report_date)
    all_count = len(records)
    thcs_records = _records_for_school_scope(records, "thcs")
    thpt_records = _records_for_school_scope(records, "thpt")
    thcs_count = _count_instances_for_scope(records, "thcs")
    thpt_count = _count_instances_for_scope(records, "thpt")

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
        _recipients_for_scope("thcs"),
        subject=f"[WSHN] Báo cáo kỷ luật THCS ngày {report_date_display}",
        body=body_thcs,
        from_email=DISCIPLINE_REPORT_SENDER,
        cc_list=_cc_for_scope("thcs"),
    )
    results.append({"school": "THCS", "email": r1})

    body_thpt = _generate_scoped_report_html(
        "thpt",
        report_date_display,
        thpt_records,
        records,
    )
    r2 = send_email_via_service(
        _recipients_for_scope("thpt"),
        subject=f"[WSHN] Báo cáo kỷ luật THPT ngày {report_date_display}",
        body=body_thpt,
        from_email=DISCIPLINE_REPORT_SENDER,
        cc_list=_cc_for_scope("thpt"),
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
def send_discipline_daily_report(date=None, force=None):
    """
    Gọi thủ công qua API để gửi/test báo cáo theo ngày.
    Params:
        date: YYYY-MM-DD, mặc định hôm nay.
        force: "1"/"true" để gửi thật trên dev (bỏ qua kiểm tra production).
               Mặc định KHÔNG gửi trên dev/staging — chỉ gửi trên production server.

    POST /api/method/erp.api.erp_sis.discipline_report.send_discipline_daily_report
    """
    try:
        req = _get_request_data()
        report_date = _coerce_date_string(date, req)

        force_val = force if force is not None else (req.get("force") if isinstance(req, dict) else None)
        force_flag = str(force_val or "").strip().lower() in {"1", "true", "yes"}

        return _send_discipline_reports_for_date(report_date, force=force_flag)
    except Exception as e:
        frappe.logger().error(f"send_discipline_daily_report: {str(e)}")
        frappe.log_error(f"send_discipline_daily_report: {str(e)}")
        return {"success": False, "message": str(e)}
