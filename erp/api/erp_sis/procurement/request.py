"""API Phiếu Yêu cầu (Purchase Request) + state machine duyệt (qua engine generic)."""

import json

import frappe
from frappe.utils import now

from erp.utils.api_response import (
    list_response,
    single_item_response,
    error_response,
    not_found_response,
    forbidden_response,
)

from ..approval import engine
from . import resolvers
from . import utils as u

PR_DT = u.PR_DT
PO_DT = u.PO_DT


def _parse(value, default=None):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Serialize
# ---------------------------------------------------------------------------

def _pr_to_dict(doc):
    data = {
        "name": doc.name,
        "title": doc.title,
        "requested_by": doc.requested_by,
        "requesting_department": doc.requesting_department,
        "routing_unit": doc.routing_unit,
        "request_group": doc.request_group,
        "request_date": str(doc.request_date) if doc.request_date else None,
        "lead_time_days": doc.lead_time_days,
        "leadtime_date": str(doc.leadtime_date) if doc.leadtime_date else None,
        "budget_in_out": doc.budget_in_out,
        "campus_id": doc.campus_id,
        "workflow_state": doc.workflow_state,
        "current_seq": doc.current_seq,
        "applied_template": doc.applied_template,
        "fulfillment_status": doc.fulfillment_status,
        "return_reason": doc.return_reason,
        "note": doc.note,
        "total_estimated": doc.total_estimated,
        "submitted_by": doc.submitted_by,
        "submitted_at": str(doc.submitted_at) if doc.submitted_at else None,
        "approved_by": doc.approved_by,
        "approved_at": str(doc.approved_at) if doc.approved_at else None,
        "approval_steps": engine.serialize_steps(doc),
        "lines": [
            {
                "name": l.name,
                "item": l.item,
                "item_name": l.item_name,
                "spec": l.spec,
                "uom": l.uom,
                "qty_total": l.qty_total,
                "qty_available": l.qty_available,
                "qty_to_buy": l.qty_to_buy,
                "unit_price": l.unit_price,
                "amount": l.amount,
                "reason": l.reason,
                "line_budget_code": l.line_budget_code,
                "in_budget": bool(l.in_budget),
                "qty_ordered": l.qty_ordered,
                "line_status": l.line_status,
            }
            for l in (doc.lines or [])
        ],
        "related_departments": [
            {
                "department": r.department,
                "department_name": r.department_name,
                "relation_reason": r.relation_reason,
            }
            for r in (doc.related_departments or [])
        ],
    }
    return data


# ---------------------------------------------------------------------------
# Catalog / master
# ---------------------------------------------------------------------------

@frappe.whitelist()
def search_products(term=None, limit=20):
    """Search-as-you-type sản phẩm (KHÔNG load all)."""
    term = (term or "").strip()
    if len(term) < 2:
        return list_response([])
    like = f"%{term}%"
    rows = frappe.db.get_all(
        "ERP Product",
        or_filters={"product_code": ["like", like], "product_name": ["like", like]},
        filters={"is_active": 1},
        fields=["name", "product_name", "standard_rate", "uom"],
        limit_page_length=int(limit or 20),
        order_by="product_name asc",
    )
    return list_response(rows)


@frappe.whitelist()
def get_request_groups():
    rows = frappe.get_all(
        "ERP Procurement Request Group",
        filters={"is_active": 1},
        fields=["name", "group_name", "default_leadtime_days"],
        order_by="group_name asc",
    )
    return list_response(rows)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_my_requests():
    me = u.session_email()
    rows = frappe.get_all(
        PR_DT,
        filters={"requested_by": me},
        fields=["name", "title", "workflow_state", "request_date", "total_estimated", "fulfillment_status"],
        order_by="modified desc",
    )
    return list_response(rows)


@frappe.whitelist()
def get_request(name=None):
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(PR_DT, name):
        return not_found_response("Không tìm thấy PR")
    doc = frappe.get_doc(PR_DT, name)
    if not engine.can_view_doc(doc, u.session_email()):
        return forbidden_response("Không có quyền xem PR này")
    return single_item_response(_pr_to_dict(doc))


# ---------------------------------------------------------------------------
# Create / update (Draft / Returned)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def upsert_request():
    data = u.get_request_data()
    me = u.session_email()
    name = data.get("name")

    if name:
        if not frappe.db.exists(PR_DT, name):
            return not_found_response("Không tìm thấy PR")
        doc = frappe.get_doc(PR_DT, name)
        if doc.workflow_state in ("Approved", "Rejected", "Cancelled"):
            return error_response("Phiếu đã chốt, không sửa được")
        if not engine.can_edit_doc(doc, me):
            return forbidden_response("Bạn không có quyền sửa PR này ở bước hiện tại")
    else:
        doc = frappe.new_doc(PR_DT)
        doc.requested_by = me
        doc.requesting_department = u.user_home_unit(me)
        doc.workflow_state = "Draft"

    routing_unit = data.get("routing_unit") or doc.requesting_department
    if routing_unit and routing_unit != doc.requesting_department:
        if not u.can_set_routing_unit(routing_unit, me):
            return forbidden_response("Không có quyền lập PR cho phòng ban này")
    doc.routing_unit = routing_unit
    doc.campus_id = u.resolve_campus(routing_unit)

    for f in ("title", "request_group", "request_date", "lead_time_days", "note"):
        if f in data:
            doc.set(f, data.get(f))

    if "lines" in data:
        doc.set("lines", [])
        for l in _parse(data.get("lines"), []) or []:
            doc.append("lines", {
                "item": l.get("item"),
                "spec": l.get("spec"),
                "qty_total": l.get("qty_total") or 0,
                "qty_available": l.get("qty_available") or 0,
                "qty_to_buy": l.get("qty_to_buy") or 0,
                "unit_price": l.get("unit_price") or 0,
                "reason": l.get("reason"),
                "line_budget_code": l.get("line_budget_code"),
            })

    if "related_departments" in data:
        doc.set("related_departments", [])
        for r in _parse(data.get("related_departments"), []) or []:
            doc.append("related_departments", {
                "department": r.get("department"),
                "relation_reason": r.get("relation_reason"),
            })

    if not doc.title:
        doc.title = f"PR {doc.request_group or ''} - {doc.requesting_department or ''}".strip()

    doc.save(ignore_permissions=True)
    if not name:
        engine.append_history(PR_DT, doc.name, "Tạo nháp")
    frappe.db.commit()
    return single_item_response(_pr_to_dict(doc))


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

@frappe.whitelist()
def submit_request(name=None):
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(PR_DT, name):
        return not_found_response("Không tìm thấy PR")
    me = u.session_email()
    doc = frappe.get_doc(PR_DT, name)
    if doc.workflow_state not in ("Draft", "Returned"):
        return error_response("PR không ở trạng thái nộp được")
    if doc.requested_by != me and not u.is_system_manager(me):
        return forbidden_response("Không có quyền nộp PR này")
    if not doc.lines:
        return error_response("PR chưa có dòng hàng")

    nodes, edges = resolvers.resolve_graph(doc)
    if not engine.materialize_graph(doc, nodes, edges):
        return error_response("Không resolve được luồng duyệt")
    doc.workflow_state = "Pending"
    doc.submitted_by = me
    doc.submitted_at = now()
    doc.save(ignore_permissions=True)
    engine.append_history(PR_DT, doc.name, "Nộp duyệt")
    frappe.db.commit()
    return single_item_response(_pr_to_dict(doc))


@frappe.whitelist()
def approve_step(name=None, comment=None):
    data = u.get_request_data()
    name = name or data.get("name")
    comment = comment or data.get("comment")
    if not name or not frappe.db.exists(PR_DT, name):
        return not_found_response("Không tìm thấy PR")
    me = u.session_email()
    doc = frappe.get_doc(PR_DT, name)
    result = engine.act_approve(doc, me, comment)
    doc.save(ignore_permissions=True)
    engine.append_history(PR_DT, doc.name, "Duyệt" + (" (hoàn tất)" if result.get("final") else ""))
    frappe.db.commit()
    return single_item_response(_pr_to_dict(doc))


@frappe.whitelist()
def return_request(name=None, reason=None):
    data = u.get_request_data()
    name = name or data.get("name")
    reason = reason or data.get("reason")
    if not name or not frappe.db.exists(PR_DT, name):
        return not_found_response("Không tìm thấy PR")
    doc = frappe.get_doc(PR_DT, name)
    engine.act_return(doc, u.session_email(), reason)
    doc.save(ignore_permissions=True)
    engine.append_history(PR_DT, doc.name, "Trả lại", reason)
    frappe.db.commit()
    return single_item_response(_pr_to_dict(doc))


@frappe.whitelist()
def reject_request(name=None, reason=None):
    data = u.get_request_data()
    name = name or data.get("name")
    reason = reason or data.get("reason")
    if not name or not frappe.db.exists(PR_DT, name):
        return not_found_response("Không tìm thấy PR")
    doc = frappe.get_doc(PR_DT, name)
    engine.act_reject(doc, u.session_email(), reason)
    doc.save(ignore_permissions=True)
    engine.append_history(PR_DT, doc.name, "Từ chối", reason)
    frappe.db.commit()
    return single_item_response(_pr_to_dict(doc))


@frappe.whitelist()
def cancel_request(name=None):
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(PR_DT, name):
        return not_found_response("Không tìm thấy PR")
    me = u.session_email()
    doc = frappe.get_doc(PR_DT, name)
    if doc.workflow_state in ("Approved", "Rejected", "Cancelled"):
        return error_response("Phiếu đã chốt, không huỷ được")
    if not engine.can_delete_doc(doc, me):
        return forbidden_response("Bạn không có quyền huỷ PR này ở bước hiện tại")
    doc.workflow_state = "Cancelled"
    doc.save(ignore_permissions=True)
    engine.append_history(PR_DT, doc.name, "Huỷ")
    frappe.db.commit()
    return single_item_response(_pr_to_dict(doc))


# ---------------------------------------------------------------------------
# Hàng chờ (PR + PO) + lịch sử
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_pending_for_me():
    me = u.session_email()
    rows = engine.pending_parent_names(me, (PR_DT, PO_DT))
    out = []
    for r in rows:
        submitted_by, title, state = frappe.db.get_value(
            r.parenttype, r.name, ["submitted_by", "title", "workflow_state"]
        ) or (None, None, None)
        if submitted_by == me:
            continue  # 4-mắt: ẩn phiếu mình nộp
        out.append({
            "doctype": r.parenttype,
            "name": r.name,
            "title": title,
            "workflow_state": state,
        })
    return list_response(out)


@frappe.whitelist()
def get_history(doctype=None, name=None):
    data = u.get_request_data()
    doctype = doctype or data.get("doctype") or PR_DT
    name = name or data.get("name")
    if not name:
        return error_response("Thiếu name")
    return list_response(engine.get_history(doctype, name))
