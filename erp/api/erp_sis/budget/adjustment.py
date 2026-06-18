"""
Budget Adjustment APIs - điều chỉnh giữa năm (delta/event - D4).

Ngân sách hiệu lực = approved_amount (bản gốc is_current) + Σ delta_amount các adjustment Approved.
Định tuyến duyệt theo loại + ngưỡng (D3).
"""

import frappe
from frappe import _

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
    ADJUSTMENT_DT,
    PERIOD_DT,
    PLAN_DT,
    _get_request_data,
    _parse,
    _session_email,
    _is_finance,
    _resolve_campus_from_unit,
    _adjustment_steps,
    _can_approve_step,
)
from . import notification as notify


def _adjustment_to_dict(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "period": doc.period,
        "type": doc.type,
        "department": doc.department,
        "campus_id": doc.campus_id,
        "workflow_state": doc.workflow_state,
        "current_step": doc.current_step,
        "total_delta": doc.total_delta,
        "return_reason": doc.return_reason,
        "reason": doc.reason,
        "attachment": doc.attachment,
        "lines": [
            {
                "plan": l.plan,
                "budget_code": l.budget_code,
                "delta_amount": l.delta_amount,
                "note": l.note,
            }
            for l in (doc.lines or [])
        ],
    }


def _total_abs_delta(doc):
    return sum(abs(l.delta_amount or 0) for l in (doc.lines or []))


@frappe.whitelist(allow_guest=False)
def list_adjustments(period=None, workflow_state=None):
    filters = {}
    if period:
        filters["period"] = period
    if workflow_state:
        filters["workflow_state"] = workflow_state
    names = frappe.get_all(ADJUSTMENT_DT, filters=filters, pluck="name", order_by="creation desc")
    data = [_adjustment_to_dict(frappe.get_doc(ADJUSTMENT_DT, n)) for n in names]
    return list_response(data)


@frappe.whitelist(allow_guest=False)
def get_adjustment(name=None):
    name = name or _get_request_data().get("name")
    if not name or not frappe.db.exists(ADJUSTMENT_DT, name):
        return not_found_response(f"Không tìm thấy điều chỉnh: {name}")
    return single_item_response(_adjustment_to_dict(frappe.get_doc(ADJUSTMENT_DT, name)))


def _apply_lines(doc, lines):
    doc.set("lines", [])
    for l in lines or []:
        if not isinstance(l, dict) or not l.get("plan") or not l.get("budget_code"):
            continue
        doc.append(
            "lines",
            {
                "plan": l.get("plan"),
                "budget_code": l.get("budget_code"),
                "delta_amount": l.get("delta_amount") or 0,
                "note": l.get("note"),
            },
        )


@frappe.whitelist(allow_guest=False)
def create_adjustment():
    if not _is_finance():
        return forbidden_response("Chỉ Phòng TC được tạo điều chỉnh")
    data = _get_request_data()
    if not data.get("period"):
        return validation_error_response("Thiếu period", {"period": ["Bắt buộc"]})
    adj_type = data.get("type") or "Transfer"
    try:
        doc = frappe.new_doc(ADJUSTMENT_DT)
        doc.period = data["period"]
        doc.type = adj_type
        doc.department = data.get("department")
        doc.campus_id = data.get("campus_id") or _resolve_campus_from_unit(data.get("department"))
        doc.reason = data.get("reason")
        doc.attachment = data.get("attachment")
        doc.title = data.get("title") or f"Điều chỉnh {adj_type}"
        doc.workflow_state = "Draft"
        _apply_lines(doc, _parse(data.get("lines")))
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_adjustment_to_dict(doc), message="Tạo điều chỉnh thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e))
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Create Adjustment Error")
        return error_response(f"Lỗi khi tạo điều chỉnh: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_adjustment():
    if not _is_finance():
        return forbidden_response("Chỉ Phòng TC được sửa điều chỉnh")
    data = _get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists(ADJUSTMENT_DT, name):
        return not_found_response(f"Không tìm thấy điều chỉnh: {name}")
    doc = frappe.get_doc(ADJUSTMENT_DT, name)
    if doc.workflow_state not in ("Draft", "Returned"):
        return error_response("Chỉ sửa được khi ở Nháp hoặc Bị trả lại")
    try:
        for f in ("type", "department", "reason", "attachment", "title"):
            if f in data:
                setattr(doc, f, data.get(f))
        if "lines" in data:
            _apply_lines(doc, _parse(data.get("lines")))
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_adjustment_to_dict(doc), message="Cập nhật thành công")
    except frappe.ValidationError as e:
        frappe.db.rollback()
        return error_response(str(e))
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi cập nhật: {str(e)}")


@frappe.whitelist(allow_guest=False)
def submit_adjustment():
    if not _is_finance():
        return forbidden_response("Chỉ Phòng TC được nộp điều chỉnh")
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(ADJUSTMENT_DT, name):
        return not_found_response(f"Không tìm thấy điều chỉnh: {name}")
    doc = frappe.get_doc(ADJUSTMENT_DT, name)
    if doc.workflow_state not in ("Draft", "Returned"):
        return error_response("Chỉ nộp được khi ở Nháp hoặc Bị trả lại")
    if not doc.lines:
        return error_response("Điều chỉnh phải có ít nhất 1 dòng")
    try:
        steps = _adjustment_steps(doc.period, doc.type, _total_abs_delta(doc))
        doc.workflow_state = "Pending"
        doc.current_step = 1
        doc.return_reason = None
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        try:
            notify.notify_adjustment_event(doc, steps[0].get("approver_role"), "Điều chỉnh chờ duyệt")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Notify Submit Adjustment Error")
        return single_item_response(_adjustment_to_dict(doc), message="Đã nộp điều chỉnh")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi nộp điều chỉnh: {str(e)}")


@frappe.whitelist(allow_guest=False)
def approve_adjustment():
    data = _get_request_data()
    name = data.get("name")
    email = _session_email()
    if not name or not frappe.db.exists(ADJUSTMENT_DT, name):
        return not_found_response(f"Không tìm thấy điều chỉnh: {name}")
    try:
        doc = frappe.get_doc(ADJUSTMENT_DT, name, for_update=True)
        if doc.workflow_state != "Pending":
            return error_response("Chỉ duyệt được điều chỉnh đang chờ duyệt")
        steps = _adjustment_steps(doc.period, doc.type, _total_abs_delta(doc))
        if not _can_approve_step(steps, doc.current_step, email):
            return forbidden_response("Bạn không có quyền duyệt bước này")

        is_last = doc.current_step >= len(steps)
        if is_last:
            doc.workflow_state = "Approved"
            doc.save(ignore_permissions=True)
            frappe.db.commit()
        else:
            doc.current_step += 1
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            try:
                next_role = steps[doc.current_step - 1].get("approver_role")
                notify.notify_adjustment_event(doc, next_role, "Điều chỉnh chờ duyệt bước kế")
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Notify Advance Adjustment Error")
        return single_item_response(_adjustment_to_dict(doc), message="Đã duyệt điều chỉnh")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(frappe.get_traceback(), "Approve Adjustment Error")
        return error_response(f"Lỗi khi duyệt điều chỉnh: {str(e)}")


@frappe.whitelist(allow_guest=False)
def return_adjustment():
    data = _get_request_data()
    name = data.get("name")
    reason = data.get("return_reason") or data.get("reason")
    email = _session_email()
    if not name or not frappe.db.exists(ADJUSTMENT_DT, name):
        return not_found_response(f"Không tìm thấy điều chỉnh: {name}")
    if not reason:
        return validation_error_response("Thiếu lý do trả lại", {"return_reason": ["Bắt buộc"]})
    try:
        doc = frappe.get_doc(ADJUSTMENT_DT, name, for_update=True)
        if doc.workflow_state != "Pending":
            return error_response("Chỉ trả lại được điều chỉnh đang chờ duyệt")
        steps = _adjustment_steps(doc.period, doc.type, _total_abs_delta(doc))
        if not _can_approve_step(steps, doc.current_step, email):
            return forbidden_response("Bạn không có quyền trả lại ở bước này")
        doc.workflow_state = "Returned"
        doc.current_step = 0
        doc.return_reason = reason
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_adjustment_to_dict(doc), message="Đã trả lại điều chỉnh")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Lỗi khi trả lại: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_effective_budget(period=None, department=None):
    """
    Ngân sách hiệu lực theo (plan, budget_code):
    approved_amount (bản is_current) + Σ delta_amount các adjustment Approved.
    """
    if not (_is_finance() or "SIS BOD" in frappe.get_roles()):
        return forbidden_response("Bạn không có quyền xem báo cáo ngân sách")

    filters = {"is_current": 1, "workflow_state": ("in", ["Approved", "Active", "Closed"])}
    if period:
        filters["period"] = period
    if department:
        filters["department"] = department
    plan_names = frappe.get_all(PLAN_DT, filters=filters, pluck="name")

    # Map (plan, budget_code) -> số liệu
    result = {}
    for pn in plan_names:
        plan = frappe.get_doc(PLAN_DT, pn)
        for l in plan.lines:
            key = (pn, l.budget_code)
            result[key] = {
                "plan": pn,
                "department": plan.department,
                "department_name": plan.department_name,
                "budget_code": l.budget_code,
                "account_item": l.account_item,
                "approved_amount": l.approved_amount or 0,
                "delta_total": 0,
                "effective_amount": l.approved_amount or 0,
            }

    # Cộng dồn delta từ adjustment Approved
    adj_filters = {"workflow_state": "Approved"}
    if period:
        adj_filters["period"] = period
    adj_names = frappe.get_all(ADJUSTMENT_DT, filters=adj_filters, pluck="name")
    for an in adj_names:
        adj = frappe.get_doc(ADJUSTMENT_DT, an)
        for l in adj.lines:
            key = (l.plan, l.budget_code)
            if key in result:
                result[key]["delta_total"] += (l.delta_amount or 0)
                result[key]["effective_amount"] = (
                    result[key]["approved_amount"] + result[key]["delta_total"]
                )

    return list_response(list(result.values()))
