"""API Phiếu Mua sắm (Purchase Order) + state machine duyệt (qua engine generic)."""

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

PO_DT = u.PO_DT
PR_DT = u.PR_DT


def _parse(value, default=None):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _po_to_dict(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "source_prs": [r.purchase_request for r in (doc.source_prs or [])],
        "procurement_unit": doc.procurement_unit,
        "buyer": doc.buyer,
        "campus_id": doc.campus_id,
        "selected_supplier_idx": doc.selected_supplier_idx,
        "selection_reason": doc.selection_reason,
        "has_substitution": bool(doc.has_substitution),
        "workflow_state": doc.workflow_state,
        "current_seq": doc.current_seq,
        "applied_template": doc.applied_template,
        "return_reason": doc.return_reason,
        "total_estimated": doc.total_estimated,
        "saving_vs_pr": doc.saving_vs_pr,
        "submitted_by": doc.submitted_by,
        "submitted_at": str(doc.submitted_at) if doc.submitted_at else None,
        "approved_by": doc.approved_by,
        "approved_at": str(doc.approved_at) if doc.approved_at else None,
        "approval_steps": engine.serialize_steps(doc),
        "suppliers": [
            {
                "supplier_name": s.supplier_name, "address": s.address,
                "contact_person": s.contact_person, "phone": s.phone, "email": s.email,
                "leadtime": s.leadtime, "logistic": s.logistic,
                "payment_terms": s.payment_terms, "invoice_status": s.invoice_status,
                "total_amount": s.total_amount,
            }
            for s in (doc.suppliers or [])
        ],
        "quotes": [
            {"item": q.item, "supplier": q.supplier, "unit_price_vat": q.unit_price_vat, "amount": q.amount}
            for q in (doc.quotes or [])
        ],
        "lines": [
            {
                "name": l.name, "pr_line": l.pr_line, "pr": l.pr, "item": l.item,
                "item_name": l.item_name, "spec": l.spec, "uom": l.uom, "qty": l.qty,
                "price_history": l.price_history, "selected_unit_price": l.selected_unit_price,
                "amount": l.amount, "line_action": l.line_action,
                "substitute_item": l.substitute_item, "substitute_reason": l.substitute_reason,
            }
            for l in (doc.lines or [])
        ],
    }


@frappe.whitelist()
def get_my_orders():
    me = u.session_email()
    rows = frappe.get_all(
        PO_DT,
        filters={"buyer": me},
        fields=["name", "title", "workflow_state", "total_estimated", "saving_vs_pr"],
        order_by="modified desc",
    )
    return list_response(rows)


@frappe.whitelist()
def get_order(name=None):
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(PO_DT, name):
        return not_found_response("Không tìm thấy PO")
    doc = frappe.get_doc(PO_DT, name)
    if not engine.can_view_doc(doc, u.session_email()):
        return forbidden_response("Không có quyền xem PO này")
    return single_item_response(_po_to_dict(doc))


@frappe.whitelist()
def fetch_pr_lines_for_po(pr_ids=None):
    """Lấy dòng PR còn tồn (Open/Partial) của các PR đã chọn, loại dòng đã mua hết."""
    pr_ids = _parse(pr_ids, pr_ids)
    if isinstance(pr_ids, str):
        pr_ids = [pr_ids]
    pr_ids = [p for p in (pr_ids or []) if p]
    # chỉ PR đã duyệt
    approved = frappe.get_all(
        PR_DT, filters={"name": ("in", pr_ids), "workflow_state": "Approved"}, pluck="name"
    ) if pr_ids else []
    return list_response(u.outstanding_pr_lines(approved))


def _affected_prs(doc):
    prs = set()
    for l in (doc.lines or []):
        if l.pr_line:
            pr = frappe.db.get_value("ERP Purchase Request Line", l.pr_line, "parent")
            if pr:
                prs.add(pr)
    return prs


@frappe.whitelist()
def upsert_order():
    data = u.get_request_data()
    me = u.session_email()
    name = data.get("name")

    if name:
        if not frappe.db.exists(PO_DT, name):
            return not_found_response("Không tìm thấy PO")
        doc = frappe.get_doc(PO_DT, name)
        if doc.workflow_state in ("Approved", "Rejected", "Cancelled"):
            return error_response("Phiếu đã chốt, không sửa được")
        if not engine.can_edit_doc(doc, me):
            return forbidden_response("Bạn không có quyền sửa PO này ở bước hiện tại")
    else:
        doc = frappe.new_doc(PO_DT)
        doc.buyer = me
        doc.workflow_state = "Draft"

    doc.procurement_unit = data.get("procurement_unit") or doc.procurement_unit or u.default_procurement_unit()
    doc.campus_id = u.resolve_campus(doc.procurement_unit)
    for f in ("title", "selection_reason"):
        if f in data:
            doc.set(f, data.get(f))
    if "selected_supplier_idx" in data:
        doc.selected_supplier_idx = data.get("selected_supplier_idx") or 0

    if "source_prs" in data:
        doc.set("source_prs", [])
        for p in _parse(data.get("source_prs"), []) or []:
            doc.append("source_prs", {"purchase_request": p})

    if "suppliers" in data:
        doc.set("suppliers", [])
        for s in _parse(data.get("suppliers"), []) or []:
            doc.append("suppliers", {
                "supplier_name": s.get("supplier_name"), "address": s.get("address"),
                "contact_person": s.get("contact_person"), "phone": s.get("phone"),
                "email": s.get("email"), "leadtime": s.get("leadtime"),
                "logistic": s.get("logistic"), "payment_terms": s.get("payment_terms"),
                "invoice_status": s.get("invoice_status"),
            })

    if "quotes" in data:
        doc.set("quotes", [])
        for q in _parse(data.get("quotes"), []) or []:
            doc.append("quotes", {
                "item": q.get("item"), "supplier": q.get("supplier"),
                "unit_price_vat": q.get("unit_price_vat") or 0,
            })

    if "lines" in data:
        doc.set("lines", [])
        for l in _parse(data.get("lines"), []) or []:
            pr_line = l.get("pr_line")
            pr = None
            if pr_line:
                pr = frappe.db.get_value("ERP Purchase Request Line", pr_line, "parent")
            doc.append("lines", {
                "pr_line": pr_line, "pr": pr, "item": l.get("item"), "spec": l.get("spec"),
                "qty": l.get("qty") or 0, "price_history": l.get("price_history"),
                "line_action": l.get("line_action") or "buy",
                "substitute_item": l.get("substitute_item"),
                "substitute_reason": l.get("substitute_reason"),
            })

    doc.save(ignore_permissions=True)
    if not name:
        engine.append_history(PO_DT, doc.name, "Tạo nháp PO")
    frappe.db.commit()
    return single_item_response(_po_to_dict(doc))


@frappe.whitelist()
def submit_order(name=None):
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(PO_DT, name):
        return not_found_response("Không tìm thấy PO")
    me = u.session_email()
    doc = frappe.get_doc(PO_DT, name)
    if doc.workflow_state not in ("Draft", "Returned"):
        return error_response("PO không ở trạng thái nộp được")
    if not doc.lines:
        return error_response("PO chưa có dòng hàng")
    if not doc.selected_supplier_idx:
        return error_response("Chưa chọn NCC (KẾT LUẬN)")
    _validate_qty(doc)

    nodes, edges = resolvers.resolve_graph(doc)
    if not engine.materialize_graph(doc, nodes, edges):
        return error_response("Không resolve được luồng duyệt")
    doc.workflow_state = "Pending"
    doc.submitted_by = me
    doc.submitted_at = now()
    doc.save(ignore_permissions=True)
    engine.append_history(PO_DT, doc.name, "Nộp duyệt PO")
    for pr in _affected_prs(doc):
        u.recompute_pr_fulfillment(pr)
    frappe.db.commit()
    return single_item_response(_po_to_dict(doc))


def _validate_qty(doc):
    """qty mỗi dòng <= tồn của pr_line."""
    for l in (doc.lines or []):
        if not l.pr_line:
            continue
        info = frappe.db.get_value(
            "ERP Purchase Request Line", l.pr_line, ["qty_to_buy", "qty_ordered"], as_dict=True
        )
        if not info:
            continue
        remaining = (info.qty_to_buy or 0) - (info.qty_ordered or 0)
        if (l.qty or 0) > remaining:
            frappe.throw(f"Dòng {l.item}: số lượng {l.qty} vượt tồn còn lại {remaining} của PR")


@frappe.whitelist()
def approve_order_step(name=None, comment=None):
    data = u.get_request_data()
    name = name or data.get("name")
    if not name or not frappe.db.exists(PO_DT, name):
        return not_found_response("Không tìm thấy PO")
    doc = frappe.get_doc(PO_DT, name)
    result = engine.act_approve(doc, u.session_email(), comment or data.get("comment"))
    doc.save(ignore_permissions=True)
    engine.append_history(PO_DT, doc.name, "Duyệt PO" + (" (hoàn tất)" if result.get("final") else ""))
    frappe.db.commit()
    return single_item_response(_po_to_dict(doc))


@frappe.whitelist()
def return_order(name=None, reason=None):
    data = u.get_request_data()
    name = name or data.get("name")
    if not name or not frappe.db.exists(PO_DT, name):
        return not_found_response("Không tìm thấy PO")
    doc = frappe.get_doc(PO_DT, name)
    engine.act_return(doc, u.session_email(), reason or data.get("reason"))
    doc.save(ignore_permissions=True)
    engine.append_history(PO_DT, doc.name, "Trả lại PO", reason)
    for pr in _affected_prs(doc):
        u.recompute_pr_fulfillment(pr)
    frappe.db.commit()
    return single_item_response(_po_to_dict(doc))


@frappe.whitelist()
def reject_order(name=None, reason=None):
    data = u.get_request_data()
    name = name or data.get("name")
    if not name or not frappe.db.exists(PO_DT, name):
        return not_found_response("Không tìm thấy PO")
    doc = frappe.get_doc(PO_DT, name)
    engine.act_reject(doc, u.session_email(), reason or data.get("reason"))
    doc.save(ignore_permissions=True)
    engine.append_history(PO_DT, doc.name, "Từ chối PO", reason)
    for pr in _affected_prs(doc):
        u.recompute_pr_fulfillment(pr)
    frappe.db.commit()
    return single_item_response(_po_to_dict(doc))
