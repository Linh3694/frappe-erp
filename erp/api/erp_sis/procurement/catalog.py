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
    "approver_type", "approver_role", "approver_user",
    "assignee_principal_type", "assignee_ref", "assignee_relation", "assignee_unit_type", "assignee_position",
    "is_optional", "parallel_group",
    "condition_match", "conditions", "condition_field", "condition_op", "condition_value",
    "principals",
    "deadline_hours", "escalation", "escalation_after_hours",
]

EDGE_FIELDS = [
    "from_node", "to_node", "edge_kind", "is_default", "label",
    "condition_match", "conditions", "condition_field", "condition_op", "condition_value",
    "source_handle", "target_handle", "waypoints",
]

PRINCIPAL_FIELDS = ["slot", "principal_type", "ref", "relation", "unit_type", "position", "label"]

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


def _row(src, fields):
    """Lấy dict theo fields; field JSON (conditions/waypoints) parse -> list cho FE."""
    d = {f: src.get(f) for f in fields}
    for jf in ("conditions", "waypoints", "principals"):
        if jf in d:
            d[jf] = _parse_list(d.get(jf))
    return d


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
        "steps": [_row(s, STEP_FIELDS) for s in sorted(doc.steps, key=lambda x: (x.step_order or 0))],
        "edges": [_row(e, EDGE_FIELDS) for e in (doc.edges or [])],
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


def seed_default_template(target_doctype):
    """Di trú một lần: tạo 1 ERP Approval Template active từ _default_graph nếu doctype chưa có template nào.
    Dùng cho PR/PO để giữ chạy y như cũ sau khi bỏ luồng mặc định cứng."""
    if frappe.db.exists(TEMPLATE_DT, {"target_doctype": target_doctype}):
        return
    g = _default_graph(target_doctype)
    doc = frappe.new_doc(TEMPLATE_DT)
    doc.title = f"Luồng mặc định — {target_doctype}"
    doc.target_doctype = target_doctype
    doc.is_active = 1
    for s in g["steps"]:
        row = {k: s.get(k) for k in STEP_FIELDS if k in s}
        row["conditions"] = json.dumps(s.get("conditions") or [])
        row["principals"] = json.dumps(s.get("principals") or [])
        doc.append("steps", row)
    for e in g["edges"]:
        doc.append("edges", {"from_node": e["from_node"], "to_node": e["to_node"], "edge_kind": "forward"})
    doc.insert(ignore_permissions=True)


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
            "assignee_principal_type": s.get("assignee_principal_type"),
            "assignee_ref": s.get("assignee_ref"),
            "assignee_relation": s.get("assignee_relation"),
            "assignee_unit_type": s.get("assignee_unit_type"),
            "assignee_position": s.get("assignee_position"),
            "principals": json.dumps(s.get("principals") or []),
            "is_optional": 1 if s.get("is_optional") else 0,
            "parallel_group": s.get("parallel_group"),
            "condition_match": s.get("condition_match") or "all",
            "conditions": json.dumps(s.get("conditions") or []),
            "condition_field": s.get("condition_field"),
            "condition_op": s.get("condition_op"),
            "condition_value": s.get("condition_value"),
            "deadline_hours": s.get("deadline_hours") or 0,
            "escalation": s.get("escalation") or "notify",
            "escalation_after_hours": s.get("escalation_after_hours") or 0,
        })
    doc.set("edges", [])
    for e in _parse_list(data.get("edges")):
        if not (e.get("from_node") and e.get("to_node")):
            continue
        doc.append("edges", {
            "from_node": e.get("from_node"),
            "to_node": e.get("to_node"),
            "edge_kind": e.get("edge_kind") or "forward",
            "is_default": 1 if e.get("is_default") else 0,
            "label": e.get("label"),
            "condition_match": e.get("condition_match") or "all",
            "conditions": json.dumps(e.get("conditions") or []),
            "condition_field": e.get("condition_field"),
            "condition_op": e.get("condition_op"),
            "condition_value": e.get("condition_value"),
            "source_handle": e.get("source_handle"),
            "target_handle": e.get("target_handle"),
            "waypoints": json.dumps(e.get("waypoints") or []),
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
    """KHÔNG còn luồng mặc định cứng (quyết định #5): builder mở canvas trống (FE tự thêm Người tạo + Kết thúc)."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    return single_item_response({"steps": [], "edges": []})


@frappe.whitelist()
def list_workflow_doctypes():
    """Doctype đã bật workflow (cho builder chọn loại luồng) — từ sổ đăng ký ERP Workflow Doctype."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    rows = frappe.get_all(
        "ERP Workflow Doctype", filters={"is_enabled": 1}, fields=["target_doctype", "label"], order_by="label asc"
    )
    return list_response([{"value": r.target_doctype, "label": r.label or r.target_doctype} for r in rows])


@frappe.whitelist()
def get_condition_fields(target_doctype=None):
    """Trường điều kiện hợp lệ của target_doctype (generic, lọc theo kiểu trường an toàn)."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    from ..approval import fields as wf_fields

    return list_response(wf_fields.allowed_condition_fields(target_doctype))


@frappe.whitelist()
def get_doc_fields(target_doctype=None):
    """Mọi field của doctype (cho picker Principal 'tương đối' chọn field Link đơn vị/User/bảng con)."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    from ..approval import fields as wf_fields

    return list_response(wf_fields.all_fields(target_doctype))


@frappe.whitelist()
def search_org_units(term=None, limit=20):
    """Search đơn vị (cho picker Principal trưởng/thành viên/chức danh đơn vị)."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    term = (term or "").strip()
    or_filters = None
    if term:
        like = f"%{term}%"
        or_filters = {"unit_name_vn": ["like", like], "unit_code": ["like", like], "name": ["like", like]}
    rows = frappe.get_all(
        "ERP Organization Unit",
        filters={"is_active": 1},
        or_filters=or_filters,
        fields=["name", "unit_name_vn"],
        limit_page_length=int(limit or 20),
        order_by="unit_name_vn asc",
    )
    return list_response(rows)


@frappe.whitelist()
def list_roles():
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    rows = frappe.get_all("Role", filters={"disabled": 0}, pluck="name", order_by="name asc")
    skip = {"Guest", "All", "Administrator", "Desk User"}
    return list_response([r for r in rows if r not in skip])


@frappe.whitelist()
def list_campuses():
    """Danh sách campus (cho dropdown giá trị điều kiện field campus_id)."""
    if not _is_manager():
        return forbidden_response("Không có quyền cấu hình")
    rows = frappe.get_all("SIS Campus", fields=["name", "title_vn"], order_by="title_vn asc")
    return list_response(rows)


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
