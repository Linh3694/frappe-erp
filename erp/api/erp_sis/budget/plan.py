"""
Budget Plan APIs - form ngân sách phòng ban + state machine duyệt.

State machine (mục 1.1):
Draft --submit--> Pending(step1: TC) --approve--> Pending(step2: BOD) --approve--> Approved --> Active --> Closed
Returned (khi return); Superseded (khi TC unsubmit -> versioning).
"""

import frappe
from frappe import _
from frappe.utils import now

from erp.utils.api_response import (
    list_response,
    single_item_response,
    success_response,
    error_response,
    not_found_response,
    forbidden_response,
    validation_error_response,
)

from .utils import (
    PLAN_DT,
    PLAN_HISTORY_DT,
    PERIOD_DT,
    CODE_DT,
    _get_request_data,
    _parse,
    _session_email,
    _is_finance,
    _user_led_unit,
    _is_head_of,
    _unit_name,
    _resolve_campus_from_unit,
    _append_history,
    _plan_steps,
    _can_approve_step,
)
from . import notification as notify


# ---------------------------------------------------------------------------
# Serialize
# ---------------------------------------------------------------------------

def _plan_to_dict(doc, with_lines=True):
    data = {
        "name": doc.name,
        "title": doc.title,
        "period": doc.period,
        "department": doc.department,
        "department_name": doc.department_name,
        "campus_id": doc.campus_id,
        "workflow_state": doc.workflow_state,
        "current_step": doc.current_step,
        "version": doc.version,
        "is_current": doc.is_current,
        "amends": doc.amends,
        "return_reason": doc.return_reason,
        "total_planned": doc.total_planned,
        "total_approved": doc.total_approved,
        "submitted_by": doc.submitted_by,
        "submitted_at": str(doc.submitted_at) if doc.submitted_at else None,
        "approved_by": doc.approved_by,
        "approved_at": str(doc.approved_at) if doc.approved_at else None,
    }
    if with_lines:
        data["lines"] = [
            {
                "budget_code": l.budget_code,
                "account_item": l.account_item,
                "planned_amount": l.planned_amount,
                "approved_amount": l.approved_amount,
                "note": l.note,
                "attachment": l.attachment,
            }
            for l in (doc.lines or [])
        ]
    return data


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def get_my_department():
    """Trả về phòng ban (cấp Phòng) mà user hiện tại làm trưởng phòng."""
    unit = _user_led_unit()
    if not unit:
        return single_item_response(None, message="Bạn không phải trưởng phòng nào")
    return single_item_response(
        {"department": unit, "department_name": _unit_name(unit), "campus_id": _resolve_campus_from_unit(unit)}
    )


@frappe.whitelist(allow_guest=False)
def get_my_plans(period=None):
    """Plan của phòng ban mà user làm trưởng phòng (scope theo _user_led_unit)."""
    unit = _user_led_unit()
    if not unit:
        return list_response([])
    filters = {"department": unit, "is_current": 1}
    if period:
        filters["period"] = period
    names = frappe.get_all(PLAN_DT, filters=filters, pluck="name", order_by="creation desc")
    data = [_plan_to_dict(frappe.get_doc(PLAN_DT, n)) for n in names]
    return list_response(data)


@frappe.whitelist(allow_guest=False)
def get_all_plans(period=None, workflow_state=None, include_superseded=None):
    """Toàn bộ plan (TC/BOD/System Manager). Mặc định chỉ bản hiện hành."""
    if not (_is_finance() or "SIS BOD" in frappe.get_roles()):
        return forbidden_response("Bạn không có quyền xem toàn bộ ngân sách")
    filters = {}
    if not (include_superseded in (1, "1", True, "true")):
        filters["is_current"] = 1
    if period:
        filters["period"] = period
    if workflow_state:
        filters["workflow_state"] = workflow_state
    names = frappe.get_all(PLAN_DT, filters=filters, pluck="name", order_by="creation desc")
    data = [_plan_to_dict(frappe.get_doc(PLAN_DT, n)) for n in names]
    return list_response(data)


@frappe.whitelist(allow_guest=False)
def get_plan(name=None):
    name = name or _get_request_data().get("name")
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")
    doc = frappe.get_doc(PLAN_DT, name)
    # Phân quyền đọc: TC/BOD/SM hoặc trưởng phòng sở hữu
    if not (_is_finance() or "SIS BOD" in frappe.get_roles() or _is_head_of(doc.department)):
        return forbidden_response("Bạn không có quyền xem ngân sách này")
    return single_item_response(_plan_to_dict(doc))


# ---------------------------------------------------------------------------
# Validate budget_code thuộc department
# ---------------------------------------------------------------------------

def _validate_codes_for_department(lines, department):
    for l in lines or []:
        code = l.get("budget_code") if isinstance(l, dict) else None
        if not code:
            continue
        if not frappe.db.exists(CODE_DT, code):
            frappe.throw(_("Mã ngân sách không tồn tại: {0}").format(code))
        ok = frappe.db.exists(
            "SIS Budget Code Department",
            {"parent": code, "parenttype": CODE_DT, "department": department},
        )
        if not ok:
            frappe.throw(
                _("Mã ngân sách {0} không áp dụng cho phòng ban này").format(code)
            )


# ---------------------------------------------------------------------------
# Upsert (Draft/Returned) - chỉ trưởng phòng
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def upsert_plan():
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()

    try:
        if name and frappe.db.exists(PLAN_DT, name):
            doc = frappe.get_doc(PLAN_DT, name)
            if not (_is_head_of(doc.department, email) or _is_finance()):
                return forbidden_response("Chỉ trưởng phòng được sửa ngân sách này")
            if doc.workflow_state not in ("Draft", "Returned"):
                return error_response("Chỉ sửa được khi ở trạng thái Nháp hoặc Bị trả lại")
            department = doc.department
        else:
            # Tạo mới -> department = phòng user làm trưởng phòng
            department = data.get("department") or _user_led_unit(email)
            if not department:
                return forbidden_response("Bạn không phải trưởng phòng nào, không thể tạo ngân sách")
            if not (_is_head_of(department, email) or _is_finance()):
                return forbidden_response("Chỉ trưởng phòng được tạo ngân sách cho phòng mình")
            period = data.get("period")
            if not period:
                return validation_error_response("Thiếu period", {"period": ["Bắt buộc"]})
            # Kì phải Open
            period_status = frappe.db.get_value(PERIOD_DT, period, "status")
            if period_status not in ("Open",):
                return error_response("Kì ngân sách chưa mở để nộp (status != Open)")
            doc = frappe.new_doc(PLAN_DT)
            doc.period = period
            doc.department = department
            doc.workflow_state = "Draft"
            doc.version = 1
            doc.is_current = 1

        # Header fields
        doc.campus_id = _resolve_campus_from_unit(department)
        doc.department_name = _unit_name(department)
        if not doc.title:
            sy = frappe.db.get_value(PERIOD_DT, doc.period, "school_year_id")
            doc.title = f"Ngân sách {sy or ''} - {doc.department_name}".strip()

        lines = _parse(data.get("lines"))
        if lines is not None:
            _validate_codes_for_department(lines, department)
            doc.set("lines", [])
            for l in lines:
                if not isinstance(l, dict) or not l.get("budget_code"):
                    continue
                doc.append(
                    "lines",
                    {
                        "budget_code": l.get("budget_code"),
                        "planned_amount": l.get("planned_amount") or 0,
                        "note": l.get("note"),
                        "attachment": l.get("attachment"),
                    },
                )

        is_new = not doc.name
        doc.save(ignore_permissions=True)
        _append_history(doc.name, "Lưu nháp" if is_new else "Cập nhật", user=email)
        frappe.db.commit()
        return single_item_response(_plan_to_dict(doc), message="Lưu ngân sách thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e))
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Upsert Budget Plan Error")
        return error_response(f"Lỗi khi lưu ngân sách: {str(e)}")


# ---------------------------------------------------------------------------
# Submit (Draft/Returned -> Pending step 1)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def submit_plan():
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")

    doc = frappe.get_doc(PLAN_DT, name)
    if not (_is_head_of(doc.department, email) or _is_finance()):
        return forbidden_response("Chỉ trưởng phòng được nộp ngân sách này")
    if doc.workflow_state not in ("Draft", "Returned"):
        return error_response("Chỉ nộp được khi ở trạng thái Nháp hoặc Bị trả lại")
    if not doc.lines:
        return error_response("Ngân sách phải có ít nhất 1 dòng")

    try:
        steps = _plan_steps(doc.period)
        doc.workflow_state = "Pending"
        doc.current_step = 1
        doc.return_reason = None
        doc.submitted_by = email
        doc.submitted_at = now()
        doc.save(ignore_permissions=True)
        _append_history(doc.name, "Nộp duyệt", user=email)
        frappe.db.commit()
        try:
            head_email = email
            notify.notify_plan_submitted(doc, steps[0].get("approver_role"), head_email)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Notify Submit Plan Error")
        return single_item_response(_plan_to_dict(doc), message="Đã nộp ngân sách chờ duyệt")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi nộp ngân sách: {str(e)}")


# ---------------------------------------------------------------------------
# Approve (tiến bước; bước cuối -> Approved, copy planned->approved, khoá)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def approve_plan():
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")

    try:
        # Lock doc tránh race khi duyệt song song
        doc = frappe.get_doc(PLAN_DT, name, for_update=True)
        if doc.workflow_state != "Pending":
            return error_response("Chỉ duyệt được ngân sách đang chờ duyệt (Pending)")

        steps = _plan_steps(doc.period)
        if not _can_approve_step(steps, doc.current_step, email):
            return forbidden_response("Bạn không có quyền duyệt bước này")

        # 4-mắt: người nộp không được tự duyệt
        if doc.submitted_by and doc.submitted_by == email and not _is_finance():
            return forbidden_response("Người nộp không được tự duyệt")

        is_last = doc.current_step >= len(steps)
        if is_last:
            doc.workflow_state = "Approved"
            doc.approved_by = email
            doc.approved_at = now()
            # D1: approved_amount = planned_amount, khoá
            for l in doc.lines:
                l.approved_amount = l.planned_amount or 0
            doc.save(ignore_permissions=True)
            _append_history(doc.name, "Duyệt - hoàn tất", user=email)
            frappe.db.commit()
            try:
                notify.notify_plan_approved(doc, doc.submitted_by)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Notify Approve Plan Error")
        else:
            doc.current_step += 1
            doc.save(ignore_permissions=True)
            _append_history(doc.name, f"Duyệt - chuyển bước {doc.current_step}", user=email)
            frappe.db.commit()
            try:
                next_role = steps[doc.current_step - 1].get("approver_role")
                notify.notify_plan_advanced(doc, next_role)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Notify Advance Plan Error")

        return single_item_response(_plan_to_dict(doc), message="Đã duyệt")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Approve Plan Error")
        return error_response(f"Lỗi khi duyệt: {str(e)}")


# ---------------------------------------------------------------------------
# Return (trả lại -> Returned)
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def return_plan():
    data = _get_request_data()
    name = data.get("name")
    reason = data.get("return_reason") or data.get("reason")
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")
    if not reason:
        return validation_error_response("Thiếu lý do trả lại", {"return_reason": ["Bắt buộc"]})

    try:
        doc = frappe.get_doc(PLAN_DT, name, for_update=True)
        if doc.workflow_state != "Pending":
            return error_response("Chỉ trả lại được ngân sách đang chờ duyệt")
        steps = _plan_steps(doc.period)
        if not _can_approve_step(steps, doc.current_step, email):
            return forbidden_response("Bạn không có quyền trả lại ở bước này")

        doc.workflow_state = "Returned"
        doc.current_step = 0
        doc.return_reason = reason
        doc.save(ignore_permissions=True)
        _append_history(doc.name, "Trả lại", detail=reason, user=email)
        frappe.db.commit()
        try:
            notify.notify_plan_returned(doc, doc.submitted_by, reason)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Notify Return Plan Error")
        return single_item_response(_plan_to_dict(doc), message="Đã trả lại ngân sách")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi trả lại: {str(e)}")


# ---------------------------------------------------------------------------
# Unsubmit (D7) - chỉ SIS Finance: Approved -> Superseded + clone version+1 Returned
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def unsubmit_plan():
    if not _is_finance():
        return forbidden_response("Chỉ Phòng TC được mở lại ngân sách đã duyệt")
    data = _get_request_data()
    name = data.get("name")
    reason = data.get("return_reason") or data.get("reason") or "Phòng TC mở lại để chỉnh sửa"
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")

    try:
        old = frappe.get_doc(PLAN_DT, name, for_update=True)
        if old.workflow_state not in ("Approved", "Active"):
            return error_response("Chỉ mở lại được ngân sách đã duyệt (Approved/Active)")

        # Đóng băng bản cũ
        old.workflow_state = "Superseded"
        old.is_current = 0
        old.save(ignore_permissions=True)
        _append_history(old.name, "Đóng băng (Superseded)", detail=reason, user=email)

        # Clone bản mới version+1, Returned, is_current=1
        new_doc = frappe.new_doc(PLAN_DT)
        new_doc.period = old.period
        new_doc.department = old.department
        new_doc.department_name = old.department_name
        new_doc.campus_id = old.campus_id
        new_doc.title = old.title
        new_doc.workflow_state = "Returned"
        new_doc.current_step = 0
        new_doc.version = (old.version or 1) + 1
        new_doc.is_current = 1
        new_doc.amends = old.name
        new_doc.return_reason = reason
        for l in old.lines:
            new_doc.append(
                "lines",
                {
                    "budget_code": l.budget_code,
                    "planned_amount": l.planned_amount,
                    "note": l.note,
                    "attachment": l.attachment,
                },
            )
        new_doc.insert(ignore_permissions=True)
        _append_history(new_doc.name, f"Tạo bản v{new_doc.version} (mở lại)", detail=reason, user=email)
        frappe.db.commit()
        try:
            notify.notify_plan_returned(new_doc, new_doc.submitted_by, reason)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Notify Unsubmit Plan Error")
        return single_item_response(
            _plan_to_dict(new_doc), message=f"Đã mở lại, tạo bản v{new_doc.version}"
        )
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Unsubmit Plan Error")
        return error_response(f"Lỗi khi mở lại: {str(e)}")


# ---------------------------------------------------------------------------
# Lifecycle: activate / close
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def activate_plan():
    if not _is_finance():
        return forbidden_response("Bạn không có quyền kích hoạt ngân sách")
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")
    doc = frappe.get_doc(PLAN_DT, name)
    if doc.workflow_state != "Approved":
        return error_response("Chỉ kích hoạt được ngân sách đã duyệt")
    doc.workflow_state = "Active"
    doc.save(ignore_permissions=True)
    _append_history(doc.name, "Kích hoạt", user=email)
    frappe.db.commit()
    return single_item_response(_plan_to_dict(doc), message="Đã kích hoạt")


@frappe.whitelist(allow_guest=False)
def close_plan():
    if not _is_finance():
        return forbidden_response("Bạn không có quyền đóng ngân sách")
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")
    doc = frappe.get_doc(PLAN_DT, name)
    if doc.workflow_state not in ("Approved", "Active"):
        return error_response("Chỉ đóng được ngân sách đã duyệt/đang hoạt động")
    doc.workflow_state = "Closed"
    doc.save(ignore_permissions=True)
    _append_history(doc.name, "Đóng", user=email)
    frappe.db.commit()
    return single_item_response(_plan_to_dict(doc), message="Đã đóng ngân sách")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def get_plan_history(name=None):
    name = name or _get_request_data().get("name")
    if not name:
        return validation_error_response("Thiếu name", {"name": ["Bắt buộc"]})
    rows = frappe.get_all(
        PLAN_HISTORY_DT,
        filters={"plan": name},
        fields=["action", "detail", "user_email", "user_fullname", "user_avatar", "creation"],
        order_by="creation asc",
    )
    for r in rows:
        r["creation"] = str(r["creation"]) if r.get("creation") else None
    return list_response(rows)
