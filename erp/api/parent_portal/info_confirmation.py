"""
Parent Portal — Xác nhận thông tin học sinh (đợt đầu năm).

- ``get_confirmation_state``: điều kiện popup (BR-002) + danh sách con cần xác
  nhận của phụ huynh đang đăng nhập (chỉ HS mà PH là người liên lạc chính).
- ``confirm_no_change``: "Xác nhận giữ nguyên" — set cờ Đã xác nhận, không gửi
  noti. Chặn nếu còn trường bắt buộc trống (D11).

Việc SỬA hồ sơ (kèm thông báo + lật cờ) đi qua ``commit_profile_changes`` ở
``student_profile_edit.py``. File này chỉ lo trạng thái + xác nhận giữ nguyên.
"""

from __future__ import annotations

import frappe

from erp.api.crm.info_confirmation import (
    ACTION_NO_CHANGE,
    CHANGE_NONE,
    STATUS_CONFIRMED,
    STATUS_UNCONFIRMED,
    get_settings,
    set_lead_confirmation,
    write_log,
)
from erp.api.crm.utils import get_request_data
from erp.api.parent_portal.student_profile import _get_current_parent
from erp.api.parent_portal.student_profile_edit import (
    _resolve_lead_for_current_parent,
    missing_required_guardian_fields,
)
from erp.utils.api_response import (
    error_response,
    success_response,
    validation_error_response,
)


@frappe.whitelist()
def get_confirmation_state():
    """Trạng thái đợt + danh sách con (PH là người liên lạc chính) ∩ Lead Enrolled."""
    parent_id = _get_current_parent()
    if not parent_id:
        return error_response(
            message="Không tìm thấy thông tin phụ huynh", code="PARENT_NOT_FOUND"
        )

    is_open, year = get_settings()

    # Tất cả HS mà PH có quyền truy cập (access=1) — lọc primary ở dưới.
    rels = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": parent_id, "access": 1},
        fields=["student"],
    )
    student_ids = list({r["student"] for r in rels if r.get("student")})

    students: list[dict] = []
    pending = 0
    for sid in student_ids:
        # Chỉ giữ HS mà PH là NGƯỜI LIÊN LẠC CHÍNH — dùng đúng check của
        # confirm/commit (_resolve_lead_for_current_parent), và Lead Enrolled.
        resolved, err = _resolve_lead_for_current_parent(sid)
        if err:
            continue
        lead_doc, _parent, _fam = resolved
        if getattr(lead_doc, "step", None) != "Enrolled":
            continue
        status = lead_doc.get("info_confirmation_status") or STATUS_UNCONFIRMED
        if status != STATUS_CONFIRMED:
            pending += 1
        students.append(
            {
                "student_id": sid,
                "student_name": lead_doc.get("student_name"),
                "student_code": lead_doc.get("student_code"),
                "confirmation_status": status,
                "change_status": lead_doc.get("info_change_status") or CHANGE_NONE,
            }
        )

    return success_response(
        data={
            "is_open": is_open,
            "current_year": year,
            "show_popup": bool(is_open and pending > 0),
            "pending_count": pending,
            "students": students,
        }
    )


@frappe.whitelist(methods=["POST"])
def confirm_no_change():
    """Xác nhận giữ nguyên cho 1 học sinh. Yêu cầu là người liên lạc chính."""
    data = get_request_data() or {}
    student_id = (data.get("student_id") or "").strip()

    resolved, err = _resolve_lead_for_current_parent(student_id)
    if err:
        return err
    lead_doc, parent_id, _family_payload = resolved

    if getattr(lead_doc, "step", None) != "Enrolled":
        return error_response(
            message="Học sinh không thuộc phạm vi xác nhận", code="NOT_ENROLLED"
        )

    # D11: chặn nếu còn trường bắt buộc trống → buộc PH đi qua luồng sửa
    missing = missing_required_guardian_fields(parent_id)
    if missing:
        return validation_error_response(
            "Vui lòng điền đủ các trường bắt buộc trước khi xác nhận: "
            + ", ".join(missing),
            {"required_guardian": missing},
        )

    set_lead_confirmation(lead_doc.name, confirmed=True, guardian=parent_id)
    write_log(
        student=student_id,
        lead=lead_doc.name,
        guardian=parent_id,
        action=ACTION_NO_CHANGE,
        has_changes=False,
    )
    frappe.db.commit()

    return success_response(
        data={"student_id": student_id, "confirmation_status": STATUS_CONFIRMED},
        message="Đã xác nhận thông tin học sinh",
    )
