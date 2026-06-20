"""
Budget Plan APIs - form ngân sách phòng ban + state machine duyệt.

State machine:
Draft --submit--> Pending(step1: TC -> CEO -> COO) --approve--> Approved --> Active --> Closed
Returned (khi return); Superseded (khi TC unsubmit -> versioning).
Ngân sách duyệt 1 lần/năm học, không điều chỉnh giữa năm.
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
    MONTH_FIELDS,
    PLAN_DT,
    PLAN_HISTORY_DT,
    PERIOD_DT,
    CODE_DT,
    _get_request_data,
    _parse,
    _session_email,
    _is_finance,
    _is_bod,
    _is_plan_approver_role,
    _user_budget_unit,
    _user_managed_units,
    _can_edit_plan_dept,
    _is_first_leader,
    _unit_name,
    _first_department_leader,
    _resolve_campus_from_unit,
    _append_history,
    _plan_steps,
    _parse_line_attachments,
    _serialize_line_attachments,
    _line_attachments_from_payload,
    _can_approve_step,
    _can_return_step,
    _can_read_plan,
    _actionable_steps_for_user,
    _plan_line_snapshot,
    _diff_line_snapshots,
    _state_label,
    _period_school_year_id,
    _school_year_title,
    _plan_display_title,
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
    leader = _first_department_leader(doc.department)
    if leader:
        data["department_leader"] = leader
    sy_id = _period_school_year_id(doc.period)
    data["school_year_id"] = sy_id
    data["school_year_title"] = _school_year_title(sy_id) if sy_id else None
    data["display_title"] = _plan_display_title(doc)

    # Quyền của user hiện tại với bước đang chờ (cho FE hiện nút Duyệt / Trả lại)
    can_approve = can_return = False
    current_step_label = None
    if doc.workflow_state == "Pending":
        steps = _plan_steps()
        email = _session_email()
        can_approve = _can_approve_step(steps, doc.current_step, email)
        # 4-mắt: người nộp không tự duyệt
        if can_approve and doc.submitted_by and doc.submitted_by == email:
            can_approve = False
        can_return = _can_return_step(steps, doc.current_step, email)
        if 1 <= (doc.current_step or 0) <= len(steps):
            current_step_label = steps[doc.current_step - 1].get("label")
    data["can_approve_current"] = can_approve
    data["can_return_current"] = can_return
    data["current_step_label"] = current_step_label

    if with_lines:
        # Sau khi duyệt xong (final): ẩn hẳn dòng đã gạch khỏi file ngân sách.
        # Trước đó (Draft/Returned/Pending): vẫn trả kèm cờ is_removed để FE gạch ngang.
        hide_removed = doc.workflow_state in ("Approved", "Active", "Closed")
        data["lines"] = []
        for l in (doc.lines or []):
            is_removed = 1 if l.get("is_removed") else 0
            if is_removed and hide_removed:
                continue
            attachments = _parse_line_attachments(l.attachment)
            data["lines"].append(
                {
                    "budget_code": l.budget_code,
                    "account_item": l.account_item,
                    "is_removed": is_removed,
                    "planned_amount": l.planned_amount,
                    "approved_amount": l.approved_amount,
                    "note": l.note,
                    "explanation": l.explanation,
                    "attachment": attachments[0] if attachments else None,
                    "attachments": attachments,
                    **{m: (l.get(m) or 0) for m in MONTH_FIELDS},
                }
            )
    return data


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def get_my_department():
    """Phòng (cấp Phòng) mà user được lập ngân sách: leader/member phòng hoặc leader nhóm trực thuộc."""
    unit = _user_budget_unit()
    if not unit:
        return single_item_response(None, message="Bạn không thuộc phòng nào để lập ngân sách")
    payload = {
        "department": unit,
        "department_name": _unit_name(unit),
        "campus_id": _resolve_campus_from_unit(unit),
    }
    leader = _first_department_leader(unit)
    if leader:
        payload["department_leader"] = leader
    return single_item_response(payload)


@frappe.whitelist(allow_guest=False)
def get_my_plans(period=None):
    """Plan của phòng mà user thuộc về (leader/member phòng hoặc leader nhóm trực thuộc)."""
    unit = _user_budget_unit()
    if not unit:
        return list_response([])
    base = {"department": unit}
    if period:
        base["period"] = period
    # Bản hiện hành + bản điều chỉnh (v+1) đang xử lý (is_current=0, chưa duyệt xong)
    names = frappe.get_all(
        PLAN_DT, filters={**base, "is_current": 1}, pluck="name", order_by="creation desc"
    )
    amend = frappe.get_all(
        PLAN_DT,
        filters={**base, "is_current": 0, "workflow_state": ("in", ["Draft", "Returned", "Pending"]), "amends": ("is", "set")},
        pluck="name",
        order_by="creation desc",
    )
    seen = list(dict.fromkeys(names + amend))
    data = [_plan_to_dict(frappe.get_doc(PLAN_DT, n)) for n in seen]
    return list_response(data)


@frappe.whitelist(allow_guest=False)
def get_pending_plans(period=None):
    """Ngân sách Pending ở bước user xử lý được (duyệt HOẶC trả về: CFO/COO/CEO + SIS Finance)."""
    my_steps = _actionable_steps_for_user()
    if not my_steps:
        return list_response([])
    # Bỏ ràng buộc is_current: bản điều chỉnh (v2) lúc Pending là is_current=0 nhưng vẫn cần duyệt.
    filters = {"workflow_state": "Pending", "current_step": ["in", my_steps]}
    if period:
        filters["period"] = period
    names = frappe.get_all(PLAN_DT, filters=filters, pluck="name", order_by="creation desc")
    data = [_plan_to_dict(frappe.get_doc(PLAN_DT, n)) for n in names]
    return list_response(data)


@frappe.whitelist(allow_guest=False)
def get_reviewable_plans(period=None):
    """Mọi ngân sách ĐÃ TỪNG NỘP (workflow_state != Draft, bản hiện hành) cho người SAU bước
    phòng ban: Phòng TC, CFO/COO/CEO, BOD, System Manager.

    KHÔNG gồm nháp chưa từng submit (đó là status lưu nháp riêng của phòng, tách khỏi luồng).
    """
    is_reviewer = (
        "System Manager" in frappe.get_roles()
        or _is_finance()
        or _is_bod()
        or _is_plan_approver_role()
    )
    if not is_reviewer:
        return list_response([])
    period_filter = {"period": period} if period else {}
    # Bản hiện hành đã từng nộp + bản điều chỉnh (v2) đang xử lý (is_current=0, đã nộp)
    names = frappe.get_all(
        PLAN_DT,
        filters={**period_filter, "is_current": 1, "workflow_state": ["!=", "Draft"]},
        pluck="name",
        order_by="creation desc",
    )
    amend = frappe.get_all(
        PLAN_DT,
        filters={**period_filter, "is_current": 0, "amends": ("is", "set"), "workflow_state": ("in", ["Pending", "Returned"])},
        pluck="name",
        order_by="creation desc",
    )
    seen = list(dict.fromkeys(names + amend))
    data = [_plan_to_dict(frappe.get_doc(PLAN_DT, n)) for n in seen]
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
    if not _can_read_plan(doc):
        return forbidden_response("Bạn không có quyền xem ngân sách này")
    return single_item_response(_plan_to_dict(doc))


# ---------------------------------------------------------------------------
# Validate budget_code: chỉ cần tồn tại + là mã lá (không có mã con).
# KHÔNG ràng buộc theo phòng ban — phòng có thể lập ngân sách cho mã bất kỳ.
# ---------------------------------------------------------------------------

def _validate_codes_for_department(lines, department=None):
    for l in lines or []:
        code = l.get("budget_code") if isinstance(l, dict) else None
        if not code:
            continue
        if not frappe.db.exists(CODE_DT, code):
            frappe.throw(_("Mã ngân sách không tồn tại: {0}").format(code))
        has_child = frappe.db.exists(CODE_DT, {"parent_budget_code": code})
        if has_child:
            frappe.throw(
                _("Mã ngân sách {0} là mã nhóm (có mã con) — chỉ lập cho mã chi tiết").format(code)
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
        old_snapshot = {}
        if name and frappe.db.exists(PLAN_DT, name):
            doc = frappe.get_doc(PLAN_DT, name)
            if not _can_edit_plan_dept(doc.department, email):
                return forbidden_response("Bạn không có quyền sửa ngân sách của phòng này")
            if doc.workflow_state not in ("Draft", "Returned"):
                return error_response("Chỉ sửa được khi ở trạng thái Nháp hoặc Bị trả lại")
            department = doc.department
            old_snapshot = _plan_line_snapshot(doc)
        else:
            # Tạo mới -> department = phòng user thuộc về (leader/member/leader nhóm)
            department = data.get("department") or _user_budget_unit(email)
            if not department:
                return forbidden_response("Bạn không thuộc phòng nào để lập ngân sách")
            if not _can_edit_plan_dept(department, email):
                return forbidden_response("Bạn không có quyền lập ngân sách cho phòng này")
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
            doc.title = _plan_display_title(doc)

        lines = _parse(data.get("lines"))
        if lines is not None:
            _validate_codes_for_department(lines, department)
            doc.set("lines", [])
            for l in lines:
                if not isinstance(l, dict) or not l.get("budget_code"):
                    continue
                row = {
                    "budget_code": l.get("budget_code"),
                    "note": l.get("note"),
                    "explanation": l.get("explanation"),
                    "is_removed": 1 if l.get("is_removed") else 0,
                    "attachment": _serialize_line_attachments(_line_attachments_from_payload(l)),
                }
                # planned_amount tự tính từ 12 tháng trong controller
                for m in MONTH_FIELDS:
                    row[m] = l.get(m) or 0
                doc.append("lines", row)

        is_new = not doc.name
        new_snapshot = _plan_line_snapshot(doc)
        doc.save(ignore_permissions=True)
        # Lịch sử: diff từng dòng (tháng X->Y, ghi chú/diễn giải, thêm/bớt mã)
        diff_detail = _diff_line_snapshots(old_snapshot, new_snapshot)
        _append_history(
            doc.name,
            "Lưu nháp (tạo mới)" if is_new else "Cập nhật nháp",
            detail=diff_detail or None,
            user=email,
        )
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
    if not _is_first_leader(doc.department, email):
        return forbidden_response("Chỉ trưởng phòng đứng đầu (vị trí thứ nhất) được nộp ngân sách")
    if doc.workflow_state not in ("Draft", "Returned"):
        return error_response("Chỉ nộp được khi ở trạng thái Nháp hoặc Bị trả lại")
    if not [l for l in (doc.lines or []) if not l.get("is_removed")]:
        return error_response("Ngân sách phải có ít nhất 1 dòng (chưa bị gạch bỏ)")

    try:
        steps = _plan_steps()
        prev_state = doc.workflow_state
        doc.workflow_state = "Pending"
        doc.current_step = 1
        doc.return_reason = None
        doc.submitted_by = email
        doc.submitted_at = now()
        doc.save(ignore_permissions=True)
        _append_history(
            doc.name,
            "Nộp duyệt",
            detail=(
                f"Trạng thái: {_state_label(prev_state)} → {_state_label('Pending')} · "
                f"Bước 1 ({steps[0].get('label')} – CFO duyệt)"
            ),
            user=email,
        )
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

        steps = _plan_steps()
        if not _can_approve_step(steps, doc.current_step, email):
            return forbidden_response("Bạn không có quyền duyệt bước này")

        # 4-mắt: người nộp không được tự duyệt
        if doc.submitted_by and doc.submitted_by == email:
            return forbidden_response("Người nộp không được tự duyệt")

        cur_label = steps[doc.current_step - 1].get("label")
        is_last = doc.current_step >= len(steps)
        if is_last:
            doc.workflow_state = "Approved"
            doc.approved_by = email
            doc.approved_at = now()
            # D1: approved_amount = planned_amount, khoá. Dòng đã gạch -> 0 (không vào file).
            for l in doc.lines:
                l.approved_amount = 0 if l.get("is_removed") else (l.planned_amount or 0)

            # Bản điều chỉnh (v+1): đóng băng bản cũ TRƯỚC rồi mới kích hoạt bản này,
            # tránh vi phạm ràng buộc "1 bản hiện hành / phòng / kì".
            superseded_old = None
            if doc.amends and frappe.db.exists(PLAN_DT, doc.amends):
                old = frappe.get_doc(PLAN_DT, doc.amends)
                if old.is_current:
                    old.is_current = 0
                    old.workflow_state = "Superseded"
                    old.save(ignore_permissions=True)
                    superseded_old = old
                    _append_history(
                        old.name,
                        "Đóng băng (thay bằng bản điều chỉnh)",
                        detail=f"Thay bằng {doc.name} (v{doc.version})",
                        user=email,
                    )
            if doc.amends:
                doc.is_current = 1

            doc.save(ignore_permissions=True)
            applied_note = (
                f" · Áp dụng bản v{doc.version}, đóng băng {superseded_old.name}"
                if superseded_old
                else ""
            )
            _append_history(
                doc.name,
                "Duyệt - hoàn tất",
                detail=(
                    f"Bước {cur_label} duyệt · Trạng thái: {_state_label('Pending')} → "
                    f"{_state_label('Approved')}{applied_note}"
                ),
                user=email,
            )
            frappe.db.commit()
            try:
                notify.notify_plan_approved(doc, doc.submitted_by)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Notify Approve Plan Error")
        else:
            next_label = steps[doc.current_step].get("label")
            doc.current_step += 1
            doc.save(ignore_permissions=True)
            _append_history(
                doc.name,
                f"Duyệt - chuyển {next_label}",
                detail=f"Bước {cur_label} duyệt · Chuyển bước {doc.current_step} ({next_label})",
                user=email,
            )
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
        steps = _plan_steps()
        if not _can_return_step(steps, doc.current_step, email):
            return forbidden_response("Bạn không có quyền trả lại ở bước này")

        cur_label = steps[doc.current_step - 1].get("label")
        # Trả GIẬT về từng cấp: lùi đúng 1 bước.
        # - Còn cấp duyệt thấp hơn (>=1): vẫn Pending, cấp dưới xem lại.
        # - Đã ở bước 1 (TC): về phòng ban (Returned) để trưởng phòng sửa & nộp lại.
        prev_step = doc.current_step - 1
        doc.return_reason = reason
        if prev_step >= 1:
            doc.current_step = prev_step
            doc.workflow_state = "Pending"
            target_step = steps[prev_step - 1]
            target_role = target_step.get("approver_role")
            doc.save(ignore_permissions=True)
            _append_history(
                doc.name,
                f"Trả lại bước {prev_step} ({target_step.get('label')})",
                detail=f"Từ {cur_label} → {target_step.get('label')} · Lý do: {reason}",
                user=email,
            )
            frappe.db.commit()
            try:
                notify.notify_plan_returned_to_step(doc, target_role, reason)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Notify Return Plan Error")
            msg = f"Đã trả lại cấp duyệt {prev_step}"
        else:
            doc.current_step = 0
            doc.workflow_state = "Returned"
            doc.save(ignore_permissions=True)
            _append_history(
                doc.name,
                "Trả lại phòng ban",
                detail=f"Từ {cur_label} → Phòng ban ({_state_label('Returned')}) · Lý do: {reason}",
                user=email,
            )
            frappe.db.commit()
            try:
                notify.notify_plan_returned(doc, doc.submitted_by, reason)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Notify Return Plan Error")
            msg = "Đã trả lại phòng ban"
        return single_item_response(_plan_to_dict(doc), message=msg)
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
            row = {
                "budget_code": l.budget_code,
                "note": l.note,
                "explanation": l.explanation,
                "is_removed": 1 if l.get("is_removed") else 0,
                "attachment": l.attachment,
            }
            for m in MONTH_FIELDS:
                row[m] = l.get(m) or 0
            new_doc.append("lines", row)
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
# Lập ngân sách (1 phòng / kì chỉ 1 ngân sách):
# - Chưa có bản nào trong kì  -> tạo MỚI (v1, is_current=1).
# - Đã có bản ĐÃ DUYỆT         -> tạo bản tiếp theo (v+1, clone số, is_current=0;
#                                 bản cũ vẫn hiệu lực tới khi bản mới duyệt xong).
# - Đang có bản chưa duyệt     -> KHÔNG cho tạo (phải xử lý xong bản đang dở).
# ---------------------------------------------------------------------------

def _target_open_period():
    """Kì ngân sách đang mở gần nhất (giả định mỗi thời điểm 1 kì Open)."""
    rows = frappe.get_all(
        PERIOD_DT, filters={"status": "Open"}, pluck="name", order_by="creation desc", limit=1
    )
    return rows[0] if rows else None


def _inprogress_plan_in_period(department, period):
    """Bản chưa duyệt (Draft/Pending/Returned) của phòng trong kì — chặn tạo bản mới."""
    return frappe.db.get_value(
        PLAN_DT,
        {
            "department": department,
            "period": period,
            "workflow_state": ("in", ["Draft", "Pending", "Returned"]),
        },
        "name",
    )


def _approved_current_plan_in_period(department, period):
    """Bản hiện hành đã duyệt của phòng trong kì (nguồn để tạo bản tiếp theo)."""
    return frappe.db.get_value(
        PLAN_DT,
        {
            "department": department,
            "period": period,
            "is_current": 1,
            "workflow_state": ("in", ["Approved", "Active"]),
        },
        "name",
    )


def _next_version_in_period(department, period):
    versions = frappe.get_all(
        PLAN_DT, filters={"department": department, "period": period}, pluck="version"
    )
    return (max([v or 1 for v in versions]) + 1) if versions else 1


def _make_amendment_doc(src, period, email):
    """Tạo bản tiếp theo (v+1) clone số từ src; is_current=0 (bản cũ còn hiệu lực)."""
    new_doc = frappe.new_doc(PLAN_DT)
    new_doc.period = src.period
    new_doc.department = src.department
    new_doc.department_name = src.department_name
    new_doc.campus_id = src.campus_id
    new_doc.title = src.title
    new_doc.workflow_state = "Draft"
    new_doc.current_step = 0
    new_doc.version = _next_version_in_period(src.department, src.period)
    new_doc.is_current = 0
    new_doc.amends = src.name
    for l in src.lines:
        if l.get("is_removed"):
            continue
        row = {
            "budget_code": l.budget_code,
            "note": l.note,
            "explanation": l.explanation,
            "is_removed": 0,
            "attachment": l.attachment,
        }
        for m in MONTH_FIELDS:
            row[m] = l.get(m) or 0
        new_doc.append("lines", row)
    new_doc.insert(ignore_permissions=True)
    _append_history(
        new_doc.name,
        f"Tạo bản điều chỉnh v{new_doc.version}",
        detail=f"Sao chép số liệu từ {src.name} (v{src.version}); bản cũ vẫn hiệu lực tới khi duyệt xong",
        user=email,
    )
    return new_doc


def _make_new_plan_doc(department, period, email):
    """Tạo bản ngân sách mới (v1) cho phòng trong kì."""
    new_doc = frappe.new_doc(PLAN_DT)
    new_doc.period = period
    new_doc.department = department
    new_doc.department_name = _unit_name(department)
    new_doc.campus_id = _resolve_campus_from_unit(department)
    new_doc.workflow_state = "Draft"
    new_doc.current_step = 0
    new_doc.version = _next_version_in_period(department, period)
    new_doc.is_current = 1
    new_doc.title = _plan_display_title(new_doc)
    new_doc.insert(ignore_permissions=True)
    _append_history(new_doc.name, "Tạo mới ngân sách", user=email)
    return new_doc


@frappe.whitelist(allow_guest=False)
def get_creatable_departments():
    """Danh sách phòng user quản lý ĐỦ ĐIỀU KIỆN lập ngân sách trong kì đang mở.
    Đủ điều kiện = chưa có bản nào ĐANG DỞ (Draft/Pending/Returned) trong kì.
    mode = 'next' nếu đã có bản duyệt (tạo bản tiếp theo), 'new' nếu chưa có."""
    period = _target_open_period()
    units = _user_managed_units()
    items = []
    if period:
        for unit in units:
            if _inprogress_plan_in_period(unit, period):
                continue  # đang có bản dở -> không cho tạo
            approved = _approved_current_plan_in_period(unit, period)
            items.append(
                {
                    "department": unit,
                    "department_name": _unit_name(unit),
                    "mode": "next" if approved else "new",
                }
            )
    return list_response(items)


@frappe.whitelist(allow_guest=False)
def start_plan():
    """Lập ngân sách cho 1 phòng: tạo mới hoặc tạo bản tiếp theo (tự quyết định)."""
    data = _get_request_data()
    department = data.get("department")
    email = _session_email()
    if not department:
        return validation_error_response("Thiếu phòng ban", {"department": ["Bắt buộc"]})
    if not _can_edit_plan_dept(department, email):
        return forbidden_response("Bạn không có quyền lập ngân sách cho phòng này")

    period = _target_open_period()
    if not period:
        return error_response("Chưa có kì ngân sách nào đang mở")
    if _inprogress_plan_in_period(department, period):
        return error_response("Phòng đang có bản ngân sách chưa duyệt xong — xử lý xong rồi mới lập bản mới")

    try:
        approved_name = _approved_current_plan_in_period(department, period)
        if approved_name:
            src = frappe.get_doc(PLAN_DT, approved_name)
            new_doc = _make_amendment_doc(src, period, email)
            msg = f"Đã tạo bản điều chỉnh v{new_doc.version}"
        else:
            new_doc = _make_new_plan_doc(department, period, email)
            msg = "Đã tạo ngân sách mới"
        frappe.db.commit()
        return single_item_response(_plan_to_dict(new_doc), message=msg)
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e))
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Start Budget Plan Error")
        return error_response(f"Lỗi khi lập ngân sách: {str(e)}")


# ---------------------------------------------------------------------------
# Delete (chỉ bản Nháp - phòng ban). Xoá kèm lịch sử + bình luận.
# ---------------------------------------------------------------------------

@frappe.whitelist(allow_guest=False)
def delete_plan():
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")

    doc = frappe.get_doc(PLAN_DT, name)
    if not _can_edit_plan_dept(doc.department, email):
        return forbidden_response("Bạn không có quyền xoá ngân sách của phòng này")
    if doc.workflow_state != "Draft":
        return error_response("Chỉ xoá được ngân sách ở trạng thái Nháp")

    try:
        # Dọn dữ liệu liên quan (lịch sử + bình luận) rồi xoá plan
        frappe.db.delete(PLAN_HISTORY_DT, {"plan": name})
        frappe.db.delete("ERP Budget Plan Comment", {"plan": name})
        frappe.delete_doc(PLAN_DT, name, ignore_permissions=True, force=True)
        frappe.db.commit()
        return success_response(message="Đã xoá ngân sách nháp")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Delete Budget Plan Error")
        return error_response(f"Lỗi khi xoá ngân sách: {str(e)}")


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


@frappe.whitelist(allow_guest=False)
def get_plan_versions(name=None):
    """Các phiên bản (v1, v2…) của cùng phòng + kì với plan đã cho — để xem lịch sử theo version."""
    name = name or _get_request_data().get("name")
    if not name or not frappe.db.exists(PLAN_DT, name):
        return not_found_response(f"Không tìm thấy ngân sách: {name}")
    doc = frappe.get_doc(PLAN_DT, name)
    if not _can_read_plan(doc):
        return forbidden_response("Bạn không có quyền xem ngân sách này")
    rows = frappe.get_all(
        PLAN_DT,
        filters={"department": doc.department, "period": doc.period},
        fields=["name", "version", "workflow_state", "is_current"],
        order_by="version asc, creation asc",
    )
    return list_response(rows)
