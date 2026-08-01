# -*- coding: utf-8 -*-
"""
Thông báo hộp thư NHÂN VIÊN cho quy trình duyệt Báo cáo học tập
===============================================================

Trước đây module report_card chỉ gửi push cho PHỤ HUYNH lúc publish
(`helpers.send_report_card_notification`) — giáo viên nhập liệu và người duyệt
không nhận được gì, nên trung tâm thông báo web/mobile không hề có nhóm
"Báo cáo học tập". Module này bù đúng phần còn thiếu.

Quy ước:
- `emit_staff_notify` publish envelope `notify.send` → notification-service; web SIS
  (`useNotifications` đọc `/api/notifications/inbox`) và workspace-mobile dùng chung
  hộp thư này. KHÔNG ghi ERP Notification vì web đã bỏ đọc doctype đó từ Phase 3.
- `data["url"]` là route web SIS để `resolveNotificationRoute` nhận thẳng.
- `event_type` luôn bắt đầu bằng `report_card_` → frontend gom vào danh mục
  "Báo cáo học tập" (`categories.tsx`).
- Mọi lỗi gửi đều bị nuốt: thông báo hỏng KHÔNG được làm hỏng nghiệp vụ duyệt.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

import frappe

# Trang hàng đợi duyệt (người duyệt) và trang nhập liệu của GV (tác giả báo cáo).
APPROVALS_URL = "/teaching/tasks/report-card-approvals"
MY_REPORTS_URL = "/teaching/tasks/report-card"

# Trạng thái MỚI của báo cáo -> cấp duyệt kế tiếp.
NEXT_LEVEL_BY_STATUS: Dict[str, str] = {
    "submitted": "level_1",
    "level_1_approved": "level_2",
    "level_2_approved": "level_3",
    "reviewed": "level_4",
}

LEVEL_CHAIN: List[str] = ["level_1", "level_2", "level_3", "level_4"]

LEVEL_LABELS: Dict[str, str] = {
    "level_1": "Khối trưởng (Level 1)",
    "level_2": "Tổ trưởng (Level 2)",
    "level_3": "Review (Level 3)",
    "level_4": "Xuất bản (Level 4)",
}

# Khớp `section_name_map` trong approval/batch.py.
SECTION_LABELS: Dict[str, str] = {
    "homeroom": "Nhận xét GVCN",
    "scores": "Bảng điểm",
    "subject_eval": "Đánh giá môn học",
    "main_scores": "Điểm INTL",
    "ielts": "IELTS",
    "comments": "Nhận xét",
}


# =============================================================================
# RESOLVE NGƯỜI NHẬN
# =============================================================================

def _parse_teacher_ids(raw) -> List[str]:
    """`homeroom_reviewer_level_1/2` là Small Text chứa JSON array (multi-select).

    Bản ghi cũ có thể còn lưu 1 teacher_id dạng chuỗi thường → chấp nhận cả hai.
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if x]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [text]
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if x]
    return [str(parsed).strip()] if parsed else []


def _emails_from_teacher_ids(teacher_ids: Iterable[str]) -> List[str]:
    ids = [t for t in (teacher_ids or []) if t]
    if not ids:
        return []
    rows = frappe.get_all(
        "SIS Teacher",
        filters={"name": ["in", ids]},
        fields=["user_id"],
        ignore_permissions=True,
    )
    return [str(r.get("user_id") or "").strip() for r in rows if r.get("user_id")]


def _config_emails(education_stage: Optional[str], campus_id: Optional[str], parentfield: str) -> List[str]:
    """Người duyệt L3/L4 lấy từ `SIS Report Card Approval Config` theo cấp học + campus."""
    if not education_stage or not campus_id:
        return []
    config = frappe.get_all(
        "SIS Report Card Approval Config",
        filters={
            "campus_id": campus_id,
            "education_stage_id": education_stage,
            "is_active": 1,
        },
        fields=["name"],
        limit=1,
        ignore_permissions=True,
    )
    if not config:
        return []
    rows = frappe.get_all(
        "SIS Report Card Approver",
        filters={"parent": config[0]["name"], "parentfield": parentfield},
        fields=["teacher_id", "user_id"],
        ignore_permissions=True,
    )
    emails: List[str] = []
    missing_teachers: List[str] = []
    for r in rows:
        if r.get("user_id"):
            emails.append(str(r["user_id"]).strip())
        elif r.get("teacher_id"):
            missing_teachers.append(r["teacher_id"])
    emails.extend(_emails_from_teacher_ids(missing_teachers))
    return emails


def _subject_manager_emails(subject_ids: Iterable[str]) -> List[str]:
    ids = [s for s in (subject_ids or []) if s]
    if not ids:
        return []
    rows = frappe.get_all(
        "SIS Actual Subject Manager",
        filters={"parent": ["in", ids]},
        fields=["teacher_id"],
        ignore_permissions=True,
    )
    return _emails_from_teacher_ids([r.get("teacher_id") for r in rows])


def _recipients_for_level(
    level: str,
    template,
    campus_id: Optional[str],
    subject_ids: Optional[Iterable[str]] = None,
) -> List[str]:
    if level == "level_1":
        return _emails_from_teacher_ids(
            _parse_teacher_ids(getattr(template, "homeroom_reviewer_level_1", None))
        )
    if level == "level_2":
        emails = _emails_from_teacher_ids(
            _parse_teacher_ids(getattr(template, "homeroom_reviewer_level_2", None))
        )
        emails.extend(_subject_manager_emails(subject_ids or []))
        return emails
    education_stage = getattr(template, "education_stage", None) if template else None
    if level == "level_3":
        return _config_emails(education_stage, campus_id, "level_3_reviewers")
    if level == "level_4":
        return _config_emails(education_stage, campus_id, "level_4_approvers")
    return []


def _clean(emails: Iterable[str], exclude: Optional[str] = None) -> List[str]:
    ex = str(exclude or "").strip().lower()
    seen = set()
    out: List[str] = []
    for raw in emails or []:
        em = str(raw or "").strip().lower()
        if not em or "@" not in em or em == ex or em in seen:
            continue
        seen.add(em)
        out.append(em)
    return out


def _class_label(class_id: Optional[str]) -> str:
    if not class_id:
        return ""
    title = frappe.db.get_value("SIS Class", class_id, "short_title") or frappe.db.get_value(
        "SIS Class", class_id, "title"
    )
    return str(title or "").strip()


def _section_label(section: Optional[str]) -> str:
    """Khoá lạ ("all", "both", …) → bỏ nhãn, tránh in "[both]" ra thông báo."""
    key = str(section or "").strip()
    if not key:
        return ""
    return SECTION_LABELS.get(key, "")


def _scope_text(class_id: Optional[str], count: int, section: Optional[str]) -> str:
    """'3 báo cáo lớp 10A1 [Nhận xét GVCN]' — đủ để nhận ra việc cần làm."""
    cls = _class_label(class_id)
    parts = [f"{count} báo cáo" if count and count > 1 else "Báo cáo"]
    if cls:
        parts.append(f"lớp {cls}")
    label = _section_label(section)
    if label:
        parts.append(f"[{label}]")
    return " ".join(parts)


def _send(emails: List[str], title: str, body: str, event_type: str, data: Dict[str, Any]) -> int:
    if not emails:
        return 0
    try:
        from erp.common.notification_emit import emit_staff_notify

        return emit_staff_notify(emails, title, body, event_type, data)
    except Exception as ex:
        frappe.logger().error(f"[Report Card] staff notify failed ({event_type}): {ex}")
        return 0


# =============================================================================
# API CÔNG KHAI — gọi SAU khi đã commit trạng thái
# =============================================================================

def notify_pending_approvers(
    template,
    campus_id: Optional[str],
    status: str,
    *,
    class_id: Optional[str] = None,
    count: int = 1,
    section: Optional[str] = None,
    actor: Optional[str] = None,
    subject_ids: Optional[Iterable[str]] = None,
) -> int:
    """Báo cho cấp duyệt KẾ TIẾP sau khi submit / duyệt xong một cấp.

    `status` là trạng thái MỚI của báo cáo (submitted, level_1_approved, …).
    Cấp kế tiếp bỏ trống (template không khai reviewer, config chưa lập) thì tụt tiếp
    xuống cấp sau — giống logic skip level của `submit_class_reports`; hết cấp thì im lặng.
    """
    try:
        first = NEXT_LEVEL_BY_STATUS.get(str(status or ""))
        if not first:
            return 0

        emails: List[str] = []
        level = first
        for candidate in LEVEL_CHAIN[LEVEL_CHAIN.index(first):]:
            found = _clean(
                _recipients_for_level(candidate, template, campus_id, subject_ids),
                exclude=actor,
            )
            if found:
                level, emails = candidate, found
                break
        if not emails:
            return 0

        scope = _scope_text(class_id, count, section)
        body = f"{scope} đang chờ {LEVEL_LABELS.get(level, level)} phê duyệt."
        return _send(
            emails,
            "Báo cáo học tập chờ duyệt",
            body,
            f"report_card_pending_{level}",
            {
                "url": APPROVALS_URL,
                "class_id": class_id or "",
                "template_id": getattr(template, "name", "") or "",
                "approval_status": status,
                "level": level,
                "count": count,
            },
        )
    except Exception as ex:
        frappe.logger().error(f"[Report Card] notify_pending_approvers error: {ex}")
        return 0


def _authors_of(report_names: Iterable[str]) -> List[str]:
    names = [n for n in (report_names or []) if n]
    if not names:
        return []
    rows = frappe.get_all(
        "SIS Student Report Card",
        filters={"name": ["in", names]},
        fields=["submitted_by", "homeroom_submitted_by", "scores_submitted_by"],
        ignore_permissions=True,
    )
    emails: List[str] = []
    for r in rows:
        for field in ("submitted_by", "homeroom_submitted_by", "scores_submitted_by"):
            if r.get(field):
                emails.append(str(r[field]).strip())
    return emails


def notify_reports_rejected(
    report_names: Iterable[str],
    *,
    reason: Optional[str] = None,
    actor: Optional[str] = None,
    class_id: Optional[str] = None,
    section: Optional[str] = None,
) -> int:
    """Báo cho người đã submit khi báo cáo bị trả lại."""
    try:
        names = [n for n in (report_names or []) if n]
        emails = _clean(_authors_of(names), exclude=actor)
        if not emails:
            return 0
        scope = _scope_text(class_id, len(names), section)
        body = f"{scope} bị trả lại, cần chỉnh sửa và nộp lại."
        if reason and str(reason).strip():
            body += f" Lý do: {str(reason).strip()[:200]}"
        return _send(
            emails,
            "Báo cáo học tập bị trả lại",
            body,
            "report_card_rejected",
            {
                "url": MY_REPORTS_URL,
                "class_id": class_id or "",
                "report_ids": names[:50],
                "count": len(names),
            },
        )
    except Exception as ex:
        frappe.logger().error(f"[Report Card] notify_reports_rejected error: {ex}")
        return 0


def notify_reports_published(
    report_names: Iterable[str],
    *,
    actor: Optional[str] = None,
    class_id: Optional[str] = None,
) -> int:
    """Báo cho người đã submit khi báo cáo được xuất bản tới phụ huynh."""
    try:
        names = [n for n in (report_names or []) if n]
        emails = _clean(_authors_of(names), exclude=actor)
        if not emails:
            return 0
        scope = _scope_text(class_id, len(names), None)
        return _send(
            emails,
            "Báo cáo học tập đã xuất bản",
            f"{scope} đã được xuất bản, phụ huynh đã có thể xem.",
            "report_card_published",
            {
                "url": MY_REPORTS_URL,
                "class_id": class_id or "",
                "report_ids": names[:50],
                "count": len(names),
            },
        )
    except Exception as ex:
        frappe.logger().error(f"[Report Card] notify_reports_published error: {ex}")
        return 0
