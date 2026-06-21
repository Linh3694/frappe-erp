"""
CRM Info Confirmation — Đợt xác nhận thông tin học sinh + báo thay đổi cho Tuyển sinh.

Gồm:
- Hằng số trạng thái (đồng bộ với Select trên CRM Lead).
- Helper dùng chung (settings, set cờ, ghi log, đẩy noti PIC) — gọi bởi cả
  parent_portal (commit / confirm_no_change) và staff endpoints.
- Staff endpoints: mở/đóng đợt, theo dõi danh sách, lịch sử, export Excel.

Phạm vi: chỉ Lead `step="Enrolled"`. Noti gửi PIC của HS (CRM Lead.pic), fallback
role `SIS Sales Care`. Không gửi email.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from erp.api.crm.utils import check_crm_permission, get_request_data
from erp.utils.api_response import (
    error_response,
    paginated_response,
    success_response,
    validation_error_response,
)

# ---------------------------------------------------------------------------
# Hằng số (đồng bộ với options Select trên CRM Lead)
# ---------------------------------------------------------------------------

STATUS_UNCONFIRMED = "Chưa xác nhận"
STATUS_CONFIRMED = "Đã xác nhận"
CHANGE_NONE = "Không thay đổi"
CHANGE_HAS = "Có thay đổi"

SETTINGS_DOCTYPE = "CRM Info Confirmation Settings"
LOG_DOCTYPE = "CRM Info Confirmation Log"

ACTION_NO_CHANGE = "confirm_no_change"
ACTION_WITH_CHANGE = "confirm_with_change"
ACTION_EDIT_OUT_OF_ROUND = "edit_out_of_round"

_CARE_ROLES = ["SIS Sales Care", "SIS Sales Care Admin", "System Manager"]
_CARE_ADMIN_ROLES = ["SIS Sales Care Admin", "System Manager"]


# ---------------------------------------------------------------------------
# Helper dùng chung
# ---------------------------------------------------------------------------


def get_settings() -> tuple[bool, str | None]:
    """Trả về ``(is_open, current_year)``. An toàn cả khi doctype chưa migrate."""
    try:
        s = frappe.get_single(SETTINGS_DOCTYPE)
        return bool(s.is_open), (s.current_year or None)
    except Exception:
        return False, None


def set_lead_confirmation(
    lead_name: str,
    *,
    confirmed: bool | None = None,
    has_change: bool | None = None,
    guardian: str | None = None,
) -> None:
    """Cập nhật cờ xác nhận trên CRM Lead (db.set_value — không trigger validate)."""
    if not lead_name:
        return
    _, year = get_settings()
    vals: dict = {}
    if confirmed is not None:
        vals["info_confirmation_status"] = (
            STATUS_CONFIRMED if confirmed else STATUS_UNCONFIRMED
        )
    if has_change is not None:
        vals["info_change_status"] = CHANGE_HAS if has_change else CHANGE_NONE
    if confirmed:
        vals["info_confirmed_at"] = now_datetime()
        if guardian:
            vals["info_confirmed_by"] = guardian
        if year:
            vals["info_confirmed_year"] = year
    if vals:
        frappe.db.set_value("CRM Lead", lead_name, vals, update_modified=False)


def write_log(
    *,
    student: str | None,
    lead: str | None,
    guardian: str | None,
    action: str,
    has_changes: bool,
    changed_fields=None,
    notified: bool = False,
) -> str | None:
    """Ghi 1 dòng CRM Info Confirmation Log (append-only). Không raise nếu lỗi."""
    try:
        _, year = get_settings()
        doc = frappe.new_doc(LOG_DOCTYPE)
        doc.student = student
        doc.lead = lead
        doc.guardian = guardian
        doc.school_year = year
        doc.action = action
        doc.has_changes = 1 if has_changes else 0
        doc.notified_pic = 1 if notified else 0
        doc.event_at = now_datetime()
        if changed_fields is not None:
            doc.changed_fields = json.dumps(
                changed_fields, ensure_ascii=False, default=str
            )
        doc.insert(ignore_permissions=True)
        return doc.name
    except Exception:
        frappe.log_error(
            title="info_confirmation.write_log",
            message=f"lead={lead} student={student} action={action}",
        )
        return None


def _recipients_for_lead(lead_name: str) -> list[str]:
    """PIC của Lead; fallback toàn bộ user role SIS Sales Care (enabled)."""
    pic = frappe.db.get_value("CRM Lead", lead_name, "pic") if lead_name else None
    if pic:
        return [pic]
    try:
        from erp.api.crm.assignment import _get_active_sis_sales_care_user_names

        return _get_active_sis_sales_care_user_names() or []
    except Exception:
        return []


def notify_pic(
    lead_name: str,
    *,
    student: str | None = None,
    student_name: str = "",
    student_code: str = "",
    body_summary: str = "",
) -> bool:
    """Đẩy mobile push (Expo) + in-app cho PIC của HS. Fallback role. Không email."""
    recipients = _recipients_for_lead(lead_name)
    if not recipients:
        return False
    try:
        from erp.api.erp_sis.mobile_push_notification import (
            send_mobile_notification_persisted,
        )
    except Exception:
        return False

    title = f"Cập nhật thông tin học sinh – {student_name} ({student_code})"
    body = body_summary or "Phụ huynh đã cập nhật thông tin hồ sơ học sinh."
    sent = False
    for user in recipients:
        if not user:
            continue
        try:
            send_mobile_notification_persisted(
                user,
                title,
                body,
                erp_notification_type="crm_info_confirmation",
                reference_doctype="CRM Student" if student else "CRM Lead",
                reference_name=student or lead_name,
            )
            sent = True
        except Exception:
            frappe.log_error(
                title="info_confirmation.notify_pic",
                message=f"user={user} lead={lead_name}",
            )
    return sent


def summarize_changes(changed_fields: dict | None) -> str:
    """Tóm tắt nhóm field đổi cho body noti (theo quyết định: tóm tắt nhóm)."""
    if not changed_fields:
        return "Phụ huynh đã cập nhật thông tin hồ sơ học sinh."
    groups: set[str] = set()
    for item in changed_fields.get("fields") or []:
        g = item.get("group")
        if g == "guardian":
            groups.add("Phụ huynh")
        else:
            groups.add("Học sinh")
    if changed_fields.get("ops"):
        groups.add("Liên hệ/Gia đình")
    label = ", ".join(sorted(groups)) if groups else "hồ sơ"
    return f"Phụ huynh đã cập nhật: {label}."


def _get_active_school_year() -> str | None:
    """Năm học đang bật (SIS School Year.is_enable=1), ưu tiên start_date mới nhất."""
    return frappe.db.get_value(
        "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
    )


# ---------------------------------------------------------------------------
# Staff endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def open_confirmation_round():
    """Mở đợt xác nhận mới: set năm + is_open, reset cờ TOÀN BỘ Lead Enrolled."""
    check_crm_permission(_CARE_ADMIN_ROLES)
    data = get_request_data() or {}
    # Năm học: ưu tiên override nếu gửi lên; mặc định tự lấy năm học đang bật.
    school_year = (data.get("school_year") or "").strip() or _get_active_school_year()
    if school_year and not frappe.db.exists("SIS School Year", school_year):
        return error_response(message="Năm học không tồn tại", code="YEAR_NOT_FOUND")

    frappe.db.sql(
        """
        UPDATE `tabCRM Lead`
        SET info_confirmation_status=%s,
            info_change_status=%s,
            info_confirmed_at=NULL,
            info_confirmed_by=NULL,
            info_confirmed_year=NULL
        WHERE step='Enrolled'
        """,
        (STATUS_UNCONFIRMED, CHANGE_NONE),
    )

    s = frappe.get_single(SETTINGS_DOCTYPE)
    s.current_year = school_year
    s.is_open = 1
    s.last_reset_at = now_datetime()
    s.save(ignore_permissions=True)
    frappe.db.commit()

    reset_count = frappe.db.count("CRM Lead", {"step": "Enrolled"})
    return success_response(
        data={"school_year": school_year, "reset_count": reset_count},
        message="Đã mở đợt xác nhận và reset trạng thái toàn trường",
    )


@frappe.whitelist(methods=["POST"])
def close_confirmation_round():
    """Đóng đợt (tắt popup) — không reset cờ."""
    check_crm_permission(_CARE_ADMIN_ROLES)
    s = frappe.get_single(SETTINGS_DOCTYPE)
    s.is_open = 0
    s.save(ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Đã đóng đợt xác nhận")


@frappe.whitelist()
def get_round_settings():
    """Trạng thái đợt hiện tại (cho màn cấu hình staff)."""
    check_crm_permission(_CARE_ROLES)
    is_open, year = get_settings()
    return success_response(data={"is_open": is_open, "current_year": year})


@frappe.whitelist()
def list_confirmation():
    """Danh sách HS Enrolled + 2 trạng thái + filter + phân trang."""
    check_crm_permission(_CARE_ROLES)
    data = get_request_data() or {}

    filters: dict = {"step": "Enrolled"}
    if data.get("confirmation_status"):
        filters["info_confirmation_status"] = data["confirmation_status"]
    if data.get("change_status"):
        filters["info_change_status"] = data["change_status"]
    if data.get("campus_id"):
        filters["campus_id"] = data["campus_id"]
    if data.get("target_grade"):
        filters["target_grade"] = data["target_grade"]

    or_filters = None
    q = (data.get("search") or "").strip()
    if q:
        or_filters = [
            ["student_name", "like", f"%{q}%"],
            ["student_code", "like", f"%{q}%"],
        ]

    try:
        page = max(1, int(data.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(200, max(1, int(data.get("page_size") or 50)))
    except (TypeError, ValueError):
        per_page = 50

    fields = [
        "name",
        "student_name",
        "student_code",
        "campus_id",
        "target_grade",
        "info_confirmation_status",
        "info_change_status",
        "info_confirmed_at",
        "info_confirmed_by",
        "linked_student",
        "pic",
    ]
    rows = frappe.get_all(
        "CRM Lead",
        filters=filters,
        or_filters=or_filters,
        fields=fields,
        limit_start=(page - 1) * per_page,
        limit_page_length=per_page,
        order_by="modified desc",
    )
    total = len(
        frappe.get_all(
            "CRM Lead",
            filters=filters,
            or_filters=or_filters,
            fields=["name"],
            limit_page_length=0,
        )
    )
    return paginated_response(
        data=rows, current_page=page, total_count=total, per_page=per_page
    )


@frappe.whitelist()
def get_student_confirmation_history():
    """Lịch sử log cũ→mới của 1 HS (theo CRM Student)."""
    check_crm_permission(_CARE_ROLES)
    data = get_request_data() or {}
    student = (data.get("student_id") or data.get("student") or "").strip()
    if not student:
        return validation_error_response("Thiếu student", {"student_id": ["Bắt buộc"]})
    rows = frappe.get_all(
        LOG_DOCTYPE,
        filters={"student": student},
        fields=[
            "name",
            "action",
            "has_changes",
            "changed_fields",
            "guardian",
            "school_year",
            "event_at",
            "notified_pic",
        ],
        order_by="event_at desc",
    )
    for r in rows:
        if r.get("changed_fields"):
            try:
                r["changed_fields"] = json.loads(r["changed_fields"])
            except Exception:
                pass
    return success_response(data=rows)


@frappe.whitelist()
def export_confirmation_excel():
    """Xuất Excel danh sách xác nhận theo filter (không phân trang)."""
    check_crm_permission(_CARE_ROLES)
    data = get_request_data() or {}

    filters: dict = {"step": "Enrolled"}
    for key in ("confirmation_status", "change_status", "campus_id", "target_grade"):
        mapped = {
            "confirmation_status": "info_confirmation_status",
            "change_status": "info_change_status",
            "campus_id": "campus_id",
            "target_grade": "target_grade",
        }[key]
        if data.get(key):
            filters[mapped] = data[key]

    rows = frappe.get_all(
        "CRM Lead",
        filters=filters,
        fields=[
            "student_code",
            "student_name",
            "campus_id",
            "target_grade",
            "info_confirmation_status",
            "info_change_status",
            "info_confirmed_at",
            "info_confirmed_by",
        ],
        order_by="modified desc",
        limit_page_length=0,
    )

    header = [
        "Mã HS",
        "Tên HS",
        "Campus",
        "Khối",
        "Trạng thái xác nhận",
        "Trạng thái thay đổi",
        "Thời điểm xác nhận",
        "Người xác nhận",
    ]
    table = [header]
    for r in rows:
        table.append(
            [
                r.get("student_code") or "",
                r.get("student_name") or "",
                r.get("campus_id") or "",
                r.get("target_grade") or "",
                r.get("info_confirmation_status") or "",
                r.get("info_change_status") or "",
                str(r.get("info_confirmed_at") or ""),
                r.get("info_confirmed_by") or "",
            ]
        )

    from frappe.utils.xlsxutils import make_xlsx

    xlsx_file = make_xlsx(table, "Xac nhan thong tin")
    frappe.response["filename"] = "info_confirmation.xlsx"
    frappe.response["filecontent"] = xlsx_file.getvalue()
    frappe.response["type"] = "binary"
