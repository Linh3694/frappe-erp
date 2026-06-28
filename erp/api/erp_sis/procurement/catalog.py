"""API cấu hình mua sắm: Sản phẩm, Nhóm yêu cầu, Luồng duyệt (Template) — chỉ manager."""

import json

import frappe

from erp.utils.api_response import (
    list_response,
    single_item_response,
    success_response,
    forbidden_response,
    not_found_response,
)

from . import utils as u

PRODUCT_DT = "ERP Product"
GROUP_DT = "ERP Procurement Request Group"
TEMPLATE_DT = "ERP Approval Template"

STEP_FIELDS = [
    "node_id", "step_order", "pos_x", "pos_y", "kind", "label",
    "approver_type", "approver_role", "approver_user", "is_optional", "parallel_group",
    "return_roles", "return_users", "view_roles", "view_users",
    "edit_roles", "edit_users", "delete_roles", "delete_users",
    "condition_field", "condition_op", "condition_value",
]

EDGE_FIELDS = ["from_node", "to_node", "label", "condition_field", "condition_op", "condition_value"]

_ROLE_KINDS = ("council_finance", "council_coo", "council_ceo", "role")


def _parse_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _is_manager():
    return u.is_system_manager() or "SIS Finance" in frappe.get_roles(frappe.session.user)


# ---------------------------------------------------------------------------
# Sản phẩm
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_products(term=None, limit=50, offset=0):
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    term = (term or "").strip()
    or_filters = None
    if term:
        like = f"%{term}%"
        or_filters = {"product_code": ["like", like], "product_name": ["like", like]}
    rows = frappe.get_all(
        PRODUCT_DT,
        or_filters=or_filters,
        fields=["name", "product_code", "product_name", "uom", "standard_rate", "category", "is_active"],
        limit_page_length=int(limit or 50),
        limit_start=int(offset or 0),
        order_by="product_name asc",
    )
    return list_response(rows)


@frappe.whitelist()
def upsert_product():
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    data = u.get_request_data()
    name = data.get("name")
    if name and frappe.db.exists(PRODUCT_DT, name):
        doc = frappe.get_doc(PRODUCT_DT, name)
        # product_code = autoname; không đổi khi sửa
        for f in ("product_name", "uom", "standard_rate", "category"):
            if f in data:
                doc.set(f, data.get(f))
    else:
        doc = frappe.new_doc(PRODUCT_DT)
        for f in ("product_code", "product_name", "uom", "standard_rate", "category"):
            doc.set(f, data.get(f))
    if "is_active" in data:
        doc.is_active = 1 if data.get("is_active") else 0
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response({"name": doc.name})


@frappe.whitelist()
def delete_product(name=None):
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(PRODUCT_DT, name):
        return not_found_response("Không tìm thấy sản phẩm")
    frappe.delete_doc(PRODUCT_DT, name, ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Đã xoá")


# ---------------------------------------------------------------------------
# Nhóm yêu cầu
# ---------------------------------------------------------------------------

@frappe.whitelist()
def list_request_groups_all():
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    rows = frappe.get_all(
        GROUP_DT,
        fields=["name", "group_name", "default_leadtime_days", "is_active"],
        order_by="group_name asc",
    )
    return list_response(rows)


@frappe.whitelist()
def upsert_request_group():
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    data = u.get_request_data()
    name = data.get("name")
    if name and frappe.db.exists(GROUP_DT, name):
        doc = frappe.get_doc(GROUP_DT, name)
        if "default_leadtime_days" in data:
            doc.default_leadtime_days = data.get("default_leadtime_days") or 0
    else:
        doc = frappe.new_doc(GROUP_DT)
        doc.group_name = data.get("group_name")
        doc.default_leadtime_days = data.get("default_leadtime_days") or 0
    if "is_active" in data:
        doc.is_active = 1 if data.get("is_active") else 0
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response({"name": doc.name})


@frappe.whitelist()
def delete_request_group(name=None):
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(GROUP_DT, name):
        return not_found_response("Không tìm thấy nhóm")
    frappe.delete_doc(GROUP_DT, name, ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Đã xoá")


# ---------------------------------------------------------------------------
# Luồng duyệt (ERP Approval Template) — flow builder kiểu KissFlow
# ---------------------------------------------------------------------------

def _template_dict(doc):
    return {
        "name": doc.name,
        "title": doc.title,
        "target_doctype": doc.target_doctype,
        "is_active": doc.is_active,
        "steps": [
            {f: s.get(f) for f in STEP_FIELDS}
            for s in sorted(doc.steps, key=lambda x: (x.step_order or 0))
        ],
        "edges": [{f: e.get(f) for f in EDGE_FIELDS} for e in (doc.edges or [])],
    }


def _default_graph(target_doctype):
    """Dựng graph mặc định (node_id + edges tuyến tính theo nấc) từ DEFAULT_*_STEPS."""
    from .resolvers import DEFAULT_PR_STEPS, DEFAULT_PO_STEPS, _assign_seq

    base = DEFAULT_PR_STEPS if target_doctype == "ERP Purchase Request" else DEFAULT_PO_STEPS
    steps = []
    for i, s in enumerate(base):
        node = {k: s.get(k) for k in STEP_FIELDS if k in s}
        node["node_id"] = f"n{i + 1}"
        node["step_order"] = i + 1
        node["pos_x"] = 0
        node["pos_y"] = i * 140
        node["approver_type"] = "role" if s.get("kind") in _ROLE_KINDS else "dynamic"
        steps.append(node)

    seqs = _assign_seq([{"parallel_group": s.get("parallel_group")} for s in base])
    by_seq = {}
    for i, sq in enumerate(seqs):
        by_seq.setdefault(sq, []).append(f"n{i + 1}")
    order = [by_seq[k] for k in sorted(by_seq)]
    edges = []
    for k in range(len(order) - 1):
        for fr in order[k]:
            for to in order[k + 1]:
                edges.append({"from_node": fr, "to_node": to})
    return {"steps": steps, "edges": edges}


@frappe.whitelist()
def list_templates(target_doctype=None):
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    filters = {}
    if target_doctype:
        filters["target_doctype"] = target_doctype
    rows = frappe.get_all(
        TEMPLATE_DT, filters=filters,
        fields=["name", "title", "target_doctype", "is_active"],
        order_by="modified desc",
    )
    return list_response(rows)


@frappe.whitelist()
def get_template(name=None):
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(TEMPLATE_DT, name):
        return not_found_response("Không tìm thấy luồng")
    return single_item_response(_template_dict(frappe.get_doc(TEMPLATE_DT, name)))


@frappe.whitelist()
def upsert_template():
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    data = u.get_request_data()
    name = data.get("name")
    if name and frappe.db.exists(TEMPLATE_DT, name):
        doc = frappe.get_doc(TEMPLATE_DT, name)
    else:
        doc = frappe.new_doc(TEMPLATE_DT)
    doc.title = data.get("title") or "Luồng duyệt"
    doc.target_doctype = data.get("target_doctype")
    doc.is_active = 1 if data.get("is_active") else 0

    # Giữ ≤1 luồng active / target_doctype: tự tắt luồng active khác (tránh controller throw)
    if doc.is_active and doc.target_doctype:
        others = frappe.get_all(
            TEMPLATE_DT,
            filters={"target_doctype": doc.target_doctype, "is_active": 1, "name": ["!=", doc.name or ""]},
            pluck="name",
        )
        for o in others:
            frappe.db.set_value(TEMPLATE_DT, o, "is_active", 0)

    doc.set("steps", [])
    for i, s in enumerate(_parse_list(data.get("steps"))):
        doc.append("steps", {
            "node_id": s.get("node_id") or f"n{i + 1}",
            "step_order": s.get("step_order") or (i + 1),
            "pos_x": s.get("pos_x") or 0,
            "pos_y": s.get("pos_y") or 0,
            "kind": s.get("kind"),
            "label": s.get("label"),
            "approver_type": s.get("approver_type") or "dynamic",
            "approver_role": s.get("approver_role"),
            "approver_user": s.get("approver_user"),
            "is_optional": 1 if s.get("is_optional") else 0,
            "parallel_group": s.get("parallel_group"),
            "return_roles": s.get("return_roles"),
            "return_users": s.get("return_users"),
            "view_roles": s.get("view_roles"),
            "view_users": s.get("view_users"),
            "edit_roles": s.get("edit_roles"),
            "edit_users": s.get("edit_users"),
            "delete_roles": s.get("delete_roles"),
            "delete_users": s.get("delete_users"),
            "condition_field": s.get("condition_field"),
            "condition_op": s.get("condition_op"),
            "condition_value": s.get("condition_value"),
        })
    doc.set("edges", [])
    for e in _parse_list(data.get("edges")):
        if not (e.get("from_node") and e.get("to_node")):
            continue
        doc.append("edges", {
            "from_node": e.get("from_node"),
            "to_node": e.get("to_node"),
            "label": e.get("label"),
            "condition_field": e.get("condition_field"),
            "condition_op": e.get("condition_op"),
            "condition_value": e.get("condition_value"),
        })
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return single_item_response(_template_dict(doc))


@frappe.whitelist()
def delete_template(name=None):
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    name = name or u.get_request_data().get("name")
    if not name or not frappe.db.exists(TEMPLATE_DT, name):
        return not_found_response("Không tìm thấy luồng")
    frappe.delete_doc(TEMPLATE_DT, name, ignore_permissions=True)
    frappe.db.commit()
    return success_response(message="Đã xoá")


@frappe.whitelist()
def get_default_steps(target_doctype=None):
    """Graph mặc định (steps + edges) để khởi tạo builder."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    return single_item_response(_default_graph(target_doctype))


@frappe.whitelist()
def list_roles():
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    rows = frappe.get_all("Role", filters={"disabled": 0}, pluck="name", order_by="name asc")
    skip = {"Guest", "All", "Administrator", "Desk User"}
    return list_response([r for r in rows if r not in skip])


@frappe.whitelist()
def search_users(term=None, limit=20):
    """Search người dùng (cho approver_user + ma trận quyền)."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    term = (term or "").strip()
    or_filters = None
    if term:
        like = f"%{term}%"
        or_filters = {"full_name": ["like", like], "name": ["like", like]}
    rows = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        or_filters=or_filters,
        fields=["name", "full_name"],
        limit_page_length=int(limit or 20),
        order_by="full_name asc",
    )
    return list_response(rows)
