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


def _aggregate_by_classification(records: list):
    """
    Gom theo phân loại: mỗi dòng total / thcs / thpt (đếm số bản ghi), giống ViolationTypeTable.
    Trả về list dict sorted theo title.
    """
    acc = defaultdict(lambda: {"total": 0, "thcs": 0, "thpt": 0})
    for r in records:
        title = _classification_label(r)
        acc[title]["total"] += 1
        if _is_thcs(r):
            acc[title]["thcs"] += 1
        if _is_thpt(r):
            acc[title]["thpt"] += 1
    rows = [
        {
            "title": k,
            "total": v["total"],
            "thcs": v["thcs"],
            "thpt": v["thpt"],
        }
        for k, v in sorted(acc.items(), key=lambda x: x[0])
    ]
    return rows


def _generate_report_html(
    school_label: str,
    report_date_display: str,
    violation_rows: list,
    total_for_school: int,
    all_records_count: int,
):
    """Sinh HTML email (style tương tự báo cáo điểm danh homeroom)."""
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows_html = ""
    for row in violation_rows:
        rows_html += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{escape_html(row['title'])}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{row['total']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{row['thcs']}</td>
            <td style="padding: 8px; border: 1px solid #ddd; text-align: center;">{row['thpt']}</td>
        </tr>
        """

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
        <h1 style="color: #1565c0; text-align: center; border-bottom: 3px solid #1565c0; padding-bottom: 10px;">
            Báo cáo kỷ luật — {escape_html(school_label)}
        </h1>
        <p style="text-align: center; color: #555;">Ngày {escape_html(report_date_display)}</p>

        <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <h2 style="color: #002855; margin-top: 0;">Tổng quan</h2>
            <p><strong>Tổng số vi phạm ({school_label}) trong ngày:</strong> {total_for_school}</p>
            <p><strong>Tổng số bản ghi (toàn hệ thống, mọi cấp) trong ngày:</strong> {all_records_count}</p>
        </div>

        <h3 style="color: #424242;">Phân loại vi phạm (Tổng / THCS / THPT)</h3>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
            <thead>
                <tr style="background: #e3f2fd;">
                    <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Phân loại</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">Tổng</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">THCS</th>
                    <th style="padding: 10px; border: 1px solid #ddd;">THPT</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div style="background: #e8f5e9; padding: 16px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4caf50;">
            <p style="margin: 0; font-size: 14px;">
                <strong>Ghi chú:</strong> THCS = lớp khối 6–9; THPT = khối 10–12 (theo tên lớp).
                Bản ghi không gán được khối từ tên lớp có thể không tính vào THCS/THPT nhưng vẫn nằm trong cột Tổng.
            </p>
        </div>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
        <div style="text-align: center; color: #666; font-size: 14px;">
            <p><strong>Hệ thống quản lý trường học</strong></p>
            <p>Trường PTLC Song Ngữ Quốc tế Wellspring</p>
            <p>Thời gian tạo: {now_str}</p>
        </div>
    </div>
    """
    return html


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
    Gửi 2 email: một tiêu đề THCS, một THPT; nội dung bảng giống dashboard (Tổng/THCS/THPT).
    """
    records = _fetch_discipline_records_for_date(report_date)
    violation_rows = _aggregate_by_classification(records)
    all_count = len(records)
    thcs_count = sum(1 for r in records if _is_thcs(r))
    thpt_count = sum(1 for r in records if _is_thpt(r))

    try:
        d_obj = datetime.strptime(report_date, "%Y-%m-%d")
        report_date_display = d_obj.strftime("%d/%m/%Y")
    except Exception:
        report_date_display = report_date

    results = []

    # Email 1: Trường THCS (nhấn mạnh số liệu THCS trong tổng quan)
    body_thcs = _generate_report_html(
        "Trường THCS (Trung học cơ sở)",
        report_date_display,
        violation_rows,
        total_for_school=thcs_count,
        all_records_count=all_count,
    )
    r1 = send_email_via_service(
        DISCIPLINE_REPORT_RECIPIENTS,
        subject=f"[WSHN] Báo cáo kỷ luật THCS ngày {report_date_display}",
        body=body_thcs,
    )
    results.append({"school": "THCS", "email": r1})

    # Email 2: Trường THPT
    body_thpt = _generate_report_html(
        "Trường THPT (Trung học phổ thông)",
        report_date_display,
        violation_rows,
        total_for_school=thpt_count,
        all_records_count=all_count,
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
        report_date = (date or req.get("date") or "").strip() or frappe.utils.nowdate()

        return _send_discipline_reports_for_date(report_date)
    except Exception as e:
        frappe.logger().error(f"send_discipline_daily_report: {str(e)}")
        frappe.log_error(f"send_discipline_daily_report: {str(e)}")
        return {"success": False, "message": str(e)}
