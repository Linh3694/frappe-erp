"""
API workflow GENERIC theo (doctype, name) — dùng cho MỌI doctype đã đăng ký `ERP Workflow Doctype`.
Thay cho boilerplate request.py/order.py. Engine + resolve_graph + registry; gate theo Principal/org chart.
"""

import frappe
from frappe.utils import now

from erp.utils.api_response import (
    list_response,
    single_item_response,
    error_response,
    not_found_response,
    forbidden_response,
)
from erp.common.doctype.erp_workflow_doctype.erp_workflow_doctype import get_registry, enabled_doctypes

from . import engine


def _u():
    from ..procurement import utils as u  # tái dùng get_request_data/session_email (lazy, tránh cycle)

    return u


def _resolve(doc):
    from ..procurement import resolvers  # lazy

    return resolvers.resolve_graph(doc)


def _load(doctype, name):
    if not (doctype and name) or not frappe.db.exists(doctype, name):
        return None
    return frappe.get_doc(doctype, name)


def _serialize(doc, reg):
    title_field = (reg or {}).get("title_field") or "title"
    return {
        "doctype": doc.doctype,
        "name": doc.name,
        "title": doc.get(title_field) or doc.name,
        "workflow_state": doc.get("workflow_state"),
        "submitted_by": doc.get("submitted_by"),
        "submitted_at": str(doc.get("submitted_at")) if doc.get("submitted_at") else None,
        "approved_by": doc.get("approved_by"),
        "approved_at": str(doc.get("approved_at")) if doc.get("approved_at") else None,
        "return_reason": doc.get("return_reason"),
        "applied_template": doc.get("applied_template"),
        "approval_steps": engine.serialize_steps(doc),
        "approval_edges": engine.serialize_edges(doc),
    }


@frappe.whitelist()
def submit(doctype=None, name=None):
    u = _u()
    data = u.get_request_data()
    doctype = doctype or data.get("doctype")
    name = name or data.get("name")
    reg = get_registry(doctype)
    if not reg:
        return forbidden_response("Doctype chưa bật workflow")
    doc = _load(doctype, name)
    if not doc:
        return not_found_response("Không tìm thấy phiếu")
    me = u.session_email()
    if doc.get("workflow_state") not in ("Draft", "Returned"):
        return error_response("Phiếu không ở trạng thái nộp được")
    req_field = reg.get("requester_field")
    if req_field and doc.get(req_field) != me and not u.is_system_manager(me):
        return forbidden_response("Không có quyền nộp phiếu này")
    nodes, edges = _resolve(doc)
    if not engine.materialize_graph(doc, nodes, edges):
        return error_response("Chưa cấu hình luồng duyệt cho loại phiếu này")
    doc.workflow_state = "Pending"
    doc.submitted_by = me
    doc.submitted_at = now()
    doc.save(ignore_permissions=True)
    engine.append_history(doctype, doc.name, "Nộp duyệt")
    frappe.db.commit()
    return single_item_response(_serialize(doc, reg))


def _act(doctype, name, action_fn, history, arg=None):
    u = _u()
    data = u.get_request_data()
    doctype = doctype or data.get("doctype")
    name = name or data.get("name")
    reg = get_registry(doctype)
    if not reg:
        return forbidden_response("Doctype chưa bật workflow")
    doc = _load(doctype, name)
    if not doc:
        return not_found_response("Không tìm thấy phiếu")
    result = action_fn(doc, u.session_email(), arg)
    doc.save(ignore_permissions=True)
    suffix = " (hoàn tất)" if isinstance(result, dict) and result.get("final") else ""
    engine.append_history(doctype, doc.name, history + suffix)
    frappe.db.commit()
    return single_item_response(_serialize(doc, reg))


@frappe.whitelist()
def approve(doctype=None, name=None, comment=None):
    comment = comment or _u().get_request_data().get("comment")
    return _act(doctype, name, engine.act_approve, "Duyệt", comment)


@frappe.whitelist()
def return_doc(doctype=None, name=None, reason=None):
    reason = reason or _u().get_request_data().get("reason")
    return _act(doctype, name, engine.act_return, "Trả lại", reason)


@frappe.whitelist()
def reject(doctype=None, name=None, reason=None):
    reason = reason or _u().get_request_data().get("reason")
    return _act(doctype, name, engine.act_reject, "Từ chối", reason)


@frappe.whitelist()
def get(doctype=None, name=None):
    u = _u()
    data = u.get_request_data()
    doctype = doctype or data.get("doctype")
    name = name or data.get("name")
    reg = get_registry(doctype)
    if not reg:
        return forbidden_response("Doctype chưa bật workflow")
    doc = _load(doctype, name)
    if not doc:
        return not_found_response("Không tìm thấy phiếu")
    if not engine.can_view_doc(doc, u.session_email()):
        return forbidden_response("Không có quyền xem phiếu này")
    return single_item_response(_serialize(doc, reg))


@frappe.whitelist()
def queue():
    """Hàng chờ duyệt của tôi, gộp mọi doctype đã bật workflow (4-mắt: ẩn phiếu mình nộp)."""
    u = _u()
    me = u.session_email()
    dts = enabled_doctypes()
    if not dts:
        return list_response([])
    rows = engine.pending_parent_names(me, tuple(dts))
    out = []
    for r in rows:
        reg = get_registry(r.parenttype) or {}
        title_field = reg.get("title_field") or "title"
        submitted_by, state = frappe.db.get_value(r.parenttype, r.name, ["submitted_by", "workflow_state"]) or (None, None)
        if submitted_by == me:
            continue
        try:
            title = frappe.db.get_value(r.parenttype, r.name, title_field)
        except Exception:
            title = None
        out.append(
            {
                "doctype": r.parenttype,
                "name": r.name,
                "title": title or r.name,
                "workflow_state": state,
                "module": reg.get("module"),
                "label": reg.get("label"),
            }
        )
    return list_response(out)
