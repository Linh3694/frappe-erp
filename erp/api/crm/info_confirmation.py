"""
CRM Info Confirmation — Đợt xác nhận thông tin học sinh + báo thay đổi cho Tuyển sinh.

Gồm:
- Hằng số trạng thái (đồng bộ với Select trên CRM Lead).
- Helper dùng chung (settings, set cờ, ghi log, đẩy noti PIC) — gọi bởi cả
  parent_portal (commit / confirm_no_change) và staff endpoints.
- Staff endpoints: mở/đóng đợt, theo dõi danh sách, lịch sử, export Excel.

Phạm vi: chỉ Lead `step="Enrolled"`. Noti gửi PIC đang giữ hồ sơ (CRM Lead.pic_care,
rơi về pic_sales nếu trống — xem `current_lead_pic`), fallback
role `SIS Sales Care`. Ngoài mobile push còn gửi email thông báo (giai đoạn test
chỉ tới INFO_EDIT_NOTIFICATION_EMAILS).
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import escape_html, now_datetime

from erp.api.crm.utils import check_crm_permission, get_request_data
from erp.utils.search import build_search_condition
from erp.utils.email_service import send_email_via_service
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

# Email nhận thông báo PHHS sửa thông tin (giai đoạn test). Đổi/thêm khi go-live.
INFO_EDIT_NOTIFICATION_EMAILS = ["hieu.nguyenduy@wellspring.edu.vn"]

# Nhãn tiếng Việt cho field học sinh/phụ huynh (ưu tiên dùng thay cho meta label —
# meta có một số nhãn không dấu). Khớp EDITABLE_LEAD_FIELDS / EDITABLE_GUARDIAN_FIELDS
# trong parent_portal/student_profile_edit.py.
_FIELD_LABELS_VI = {
    # Học sinh
    "student_personal_id_number": "Số định danh cá nhân học sinh",
    "student_place_of_birth": "Nơi sinh",
    "student_nationality": "Quốc tịch",
    "student_ethnicity": "Dân tộc",
    "student_religion": "Tôn giáo",
    "registered_address_province": "Tỉnh/Thành phố (hộ khẩu)",
    "registered_address_ward": "Phường/Xã (hộ khẩu)",
    "registered_address_street": "Đường/Phố (hộ khẩu)",
    "registered_address_detail": "Địa chỉ chi tiết (hộ khẩu)",
    "current_address_province": "Tỉnh/Thành phố (hiện tại)",
    "current_address_ward": "Phường/Xã (hiện tại)",
    "current_address_street": "Đường/Phố (hiện tại)",
    "current_address_detail": "Địa chỉ chi tiết (hiện tại)",
    "student_health_insurance_card": "Số thẻ Bảo hiểm y tế",
    "student_initial_medical_registration": "Nơi đăng ký khám chữa bệnh ban đầu",
    "student_health_notes": "Ghi chú sức khỏe",
    "student_food_allergy": "Dị ứng thức ăn",
    "student_medical_history": "Tiền sử bệnh",
    "student_study_interruption": "Gián đoạn học tập",
    "student_study_interruption_reason": "Lý do gián đoạn học tập",
    "student_special_characteristics": "Đặc điểm đặc biệt",
    "student_discipline_issues": "Vấn đề kỷ luật",
    # Phụ huynh
    "guardian_name": "Họ và tên phụ huynh",
    "dob": "Ngày sinh",
    "email": "Email",
    "id_number": "Số CCCD/CMND",
    "occupation": "Nghề nghiệp",
    "position": "Chức vụ",
    "workplace": "Nơi làm việc",
    "address": "Địa chỉ",
    "nationality": "Quốc tịch",
    "note": "Ghi chú",
}

# Nhãn tiếng Việt cho các thao tác child-table (ops) — prefix khớp
# _CHILD_OP_PREFIXES trong parent_portal/student_profile_edit.py
_OP_LABELS = {
    "phone_add": "Thêm số điện thoại",
    "phone_remove": "Xóa số điện thoại",
    "phone_primary": "Đổi số điện thoại chính",
    "learning_add": "Thêm quá trình học tập",
    "learning_update": "Cập nhật quá trình học tập",
    "learning_remove": "Xóa quá trình học tập",
    "sibling_add": "Thêm anh/chị/em",
    "sibling_update": "Cập nhật anh/chị/em",
    "sibling_remove": "Xóa anh/chị/em",
    "bank_accounts": "Tài khoản ngân hàng",
    "primary_contact": "Đổi người liên lạc chính",
    "reorder": "Sắp xếp lại danh sách",
}


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
    """PIC đang phụ trách Lead; fallback toàn bộ user role SIS Sales Care (enabled).

    Định tuyến theo bước (quyết định 2.9): trước Enrolled → PIC Sales; từ Enrolled trở đi
    → PIC Care (nếu trống thì rơi về PIC Sales). Module này vốn chỉ chạy ở step=Enrolled
    nên thực tế gần như luôn là PIC Care.
    """
    from erp.api.crm.utils import current_lead_pic

    pic = current_lead_pic(lead_name) if lead_name else None
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
    guardian: str | None = None,
    changed_fields: dict | None = None,
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

    parent_name = ""
    if guardian:
        parent_name = (
            frappe.db.get_value("CRM Guardian", guardian, "guardian_name") or ""
        )

    groups_label = change_groups_label(changed_fields)
    title = "Cập nhật thông tin học sinh"
    body = (
        f"Phụ huynh {parent_name} đã cập nhật thông tin {groups_label} "
        f"của học sinh {student_name} - {student_code}"
    )
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

    # Ngoài mobile push, gửi thêm email thông báo (lỗi email không ảnh hưởng push).
    try:
        _send_info_edit_notification_email(
            student_name=student_name,
            student_code=student_code,
            parent_name=parent_name,
            changed_fields=changed_fields,
            edited_at=now_datetime(),
        )
    except Exception:
        frappe.log_error(
            title="info_confirmation.notify_pic.email",
            message=f"lead={lead_name} student={student}",
        )

    return sent


def change_groups_label(changed_fields: dict | None) -> str:
    """Danh sách nhóm field đổi, vd 'Học sinh, Phụ huynh'. Fallback 'hồ sơ'."""
    if not changed_fields:
        return "hồ sơ"
    groups: set[str] = set()
    for item in changed_fields.get("fields") or []:
        g = item.get("group")
        if g == "guardian":
            groups.add("Phụ huynh")
        else:
            groups.add("Học sinh")
    if changed_fields.get("ops"):
        groups.add("Liên hệ/Gia đình")
    return ", ".join(sorted(groups)) if groups else "hồ sơ"


def _field_label(group: str | None, fieldname: str) -> str:
    """Nhãn tiếng Việt của field: ưu tiên _FIELD_LABELS_VI, fallback meta, rồi tên field."""
    if fieldname in _FIELD_LABELS_VI:
        return _FIELD_LABELS_VI[fieldname]
    doctype = "CRM Guardian" if group == "guardian" else "CRM Lead"
    try:
        label = frappe.get_meta(doctype).get_label(fieldname)
        if label and label != fieldname:
            return label
    except Exception:
        pass
    return fieldname


# Field Link địa giới hành chính lưu MÃ tỉnh/xã (name ERP Province/ERP Ward);
# khi hiển thị (email/log) cần đổi mã -> tên đọc được.
_PROVINCE_CODE_FIELDS = frozenset(
    {"registered_address_province", "current_address_province"}
)
_WARD_CODE_FIELDS = frozenset(
    {"registered_address_ward", "current_address_ward"}
)


def _display_field_value(fieldname: str, value) -> str:
    """Giá trị hiển thị của field: đổi mã Tỉnh/Xã -> tên; còn lại giữ nguyên."""
    v = str(value or "").strip()
    if not v:
        return v
    if fieldname in _PROVINCE_CODE_FIELDS or fieldname in _WARD_CODE_FIELDS:
        try:
            from erp.utils.vn_location import province_name, ward_name

            return (
                province_name(v)
                if fieldname in _PROVINCE_CODE_FIELDS
                else ward_name(v)
            )
        except Exception:
            return v
    return v


def _render_changes_rows(changed_fields: dict | None) -> str:
    """Render danh sách field đã đổi (cũ → mới) + ops thành các <li> trong 1 cell."""
    items: list[str] = []
    for item in (changed_fields or {}).get("fields") or []:
        fieldname = item.get("field") or ""
        label = escape_html(_field_label(item.get("group"), fieldname))
        old = escape_html(
            _display_field_value(fieldname, item.get("old")).strip() or "(trống)"
        )
        new = escape_html(
            _display_field_value(fieldname, item.get("new")).strip() or "(trống)"
        )
        items.append(
            f"<li><b>{label}:</b> {old} &rarr; {new}</li>"
        )
    for op in (changed_fields or {}).get("ops") or []:
        prefix = str(op).split(":")[0]
        label = _OP_LABELS.get(prefix, prefix)
        items.append(f"<li>{escape_html(label)}</li>")

    if not items:
        items.append("<li>Cập nhật thông tin hồ sơ</li>")

    list_html = "".join(items)
    return f"""
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold; vertical-align: top;">
                            Nội dung thay đổi:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            <ul style="margin: 0; padding-left: 20px;">{list_html}</ul>
                        </td>
                    </tr>"""


def _send_info_edit_notification_email(
    *,
    student_name: str,
    student_code: str,
    parent_name: str,
    changed_fields: dict | None,
    edited_at=None,
) -> dict:
    """Gửi email thông báo PHHS sửa thông tin học sinh.

    Mẫu HTML tương tự email Tái ghi danh
    (parent_portal/re_enrollment.py:_send_submission_notification_email),
    các field thay thế theo ngữ cảnh sửa thông tin. Không raise — chỉ log.
    """
    try:
        from datetime import datetime

        dt = edited_at or datetime.now()
        if isinstance(dt, str):
            try:
                dt = (
                    datetime.fromisoformat(dt.replace("Z", "+00:00"))
                    if "T" in dt
                    else datetime.strptime(dt[:19], "%Y-%m-%d %H:%M:%S")
                )
            except (ValueError, TypeError):
                dt = datetime.now()

        time_str = dt.strftime("%H:%M")
        date_str = dt.strftime("%d/%m/%Y")

        subject = f"CẬP NHẬT THÔNG TIN HỌC SINH - {student_name}"

        changes_rows = _render_changes_rows(changed_fields)

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #002855; border-bottom: 2px solid #BED232; padding-bottom: 10px;">
                    CẬP NHẬT THÔNG TIN HỌC SINH - {escape_html(student_name)}
                </h2>

                <p>Phụ huynh đã cập nhật thông tin cho Học sinh:</p>

                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold; width: 40%;">
                            Họ và Tên Học sinh:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            {escape_html(student_name)} ({escape_html(student_code)})
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold;">
                            Phụ huynh cập nhật:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            {escape_html(parent_name or "")}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9; font-weight: bold;">
                            Thời gian cập nhật:
                        </td>
                        <td style="padding: 10px; border: 1px solid #ddd;">
                            {time_str}, Ngày {date_str}
                        </td>
                    </tr>
                    {changes_rows}
                </table>

                <p style="color: #00687F; font-weight: bold;">
                    Vui lòng kiểm tra thông tin trong thời gian sớm nhất.
                </p>

                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

                <p style="font-size: 12px; color: #666;">
                    Email này được gửi tự động từ hệ thống Wellspring SIS.<br>
                    Vui lòng không reply trực tiếp vào email này.
                </p>
            </div>
        </body>
        </html>
        """

        result = send_email_via_service(
            to_list=INFO_EDIT_NOTIFICATION_EMAILS,
            subject=subject,
            body=body,
        )
        if result.get("success"):
            frappe.logger().info(
                f"Info-edit notification email sent for {student_code}"
            )
        else:
            frappe.logger().error(
                f"Failed to send info-edit notification email: {result.get('message')}"
            )
        return result
    except Exception as e:
        frappe.logger().error(f"Error sending info-edit notification email: {e}")
        return {"success": False, "message": str(e)}


def summarize_changes(changed_fields: dict | None) -> str:
    """Tóm tắt nhóm field đổi cho body noti (theo quyết định: tóm tắt nhóm)."""
    if not changed_fields:
        return "Phụ huynh đã cập nhật thông tin hồ sơ học sinh."
    return f"Phụ huynh đã cập nhật: {change_groups_label(changed_fields)}."


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
        search_frag, search_params = build_search_condition(
            ["student_name", "student_code"], q
        )
        match_names = (
            frappe.db.sql_list(f"SELECT name FROM `tabCRM Lead` WHERE {search_frag}", search_params)
            if search_frag
            else []
        )
        or_filters = [["name", "in", match_names if match_names else ["__no_match__"]]]

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
        "pic_sales",
        "pic_care",
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
    # Giu key `pic` = nguoi DANG giu ho so (module nay chi chay o step=Enrolled nen la
    # pic_care), khong doi hop dong API voi FE.
    for row in rows:
        row["pic"] = row.get("pic_care") or row.get("pic_sales") or ""
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
