"""
Resolver luồng duyệt cho PR/PO (phần NGHIỆP VỤ — adapter của engine generic).

DEFAULT_PR_STEPS / DEFAULT_PO_STEPS: luồng mặc định khi chưa cấu hình template.
resolve_steps(doc): trả list resolved-step dict cho engine.materialize().
"""

import frappe

from ..approval import engine

ORG_DT = "ERP Organization Unit"
ORG_TYPE_DT = "ERP Organization Unit Type"
PR_DT = "ERP Purchase Request"
PO_DT = "ERP Purchase Order"

# Luồng PR: (Trưởng nhóm tự bỏ) -> Trưởng phòng -> Phòng liên quan (song song) -> CFO -> COO -> CEO
DEFAULT_PR_STEPS = [
    {"kind": "team_lead", "label": "Trưởng nhóm", "is_optional": 1},
    {"kind": "department_head", "label": "Trưởng phòng"},
    {"kind": "related_department", "label": "Phòng liên quan", "parallel_group": "related"},
    {"kind": "council_finance", "label": "Phòng Tài chính", "approver_role": "CFO", "return_roles": "SIS Finance,CFO"},
    {"kind": "council_coo", "label": "COO", "approver_role": "COO", "return_roles": "COO"},
    {"kind": "council_ceo", "label": "CEO", "approver_role": "CEO", "return_roles": "CEO"},
]

# Luồng PO: Trưởng phòng mua hàng -> (Trưởng phòng order nếu có thay thế) -> CFO -> COO -> CEO
DEFAULT_PO_STEPS = [
    {"kind": "department_head", "label": "Trưởng phòng mua hàng"},
    {
        "kind": "order_dept_head",
        "label": "Trưởng phòng order (thay thế)",
        "parallel_group": "order",
        "condition_field": "has_substitution",
        "condition_op": "=",
        "condition_value": "1",
    },
    {"kind": "council_finance", "label": "Phòng Tài chính", "approver_role": "CFO", "return_roles": "SIS Finance,CFO"},
    {"kind": "council_coo", "label": "COO", "approver_role": "COO", "return_roles": "COO"},
    {"kind": "council_ceo", "label": "CEO", "approver_role": "CEO", "return_roles": "CEO"},
]


def _unit_type_by_order(order):
    return frappe.db.get_value(
        ORG_TYPE_DT, {"type_order": order, "is_active": 1}, "name"
    ) or frappe.db.get_value(ORG_TYPE_DT, {"type_order": order}, "name")


def _find_team_unit(routing_unit, user):
    """Nhóm (type_order=4) trực thuộc routing_unit mà user là member."""
    if not (routing_unit and user):
        return None
    grp_type = _unit_type_by_order(4)
    if not grp_type:
        return None
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabERP Organization Unit Member` m
        INNER JOIN `tabERP Organization Unit` u ON m.parent = u.name
        WHERE m.user = %(user)s AND u.unit_type = %(gt)s
          AND u.parent_organization_unit = %(ru)s AND u.is_active = 1
        LIMIT 1
        """,
        {"user": user, "gt": grp_type, "ru": routing_unit},
        as_dict=True,
    )
    return rows[0].name if rows else None


def _substituted_requesting_depts(doc):
    depts = []
    for l in (doc.lines or []):
        if l.line_action == "substitute" and l.pr_line:
            pr = frappe.db.get_value("ERP Purchase Request Line", l.pr_line, "parent")
            if not pr:
                continue
            rd = frappe.db.get_value(PR_DT, pr, "requesting_department") or frappe.db.get_value(
                PR_DT, pr, "routing_unit"
            )
            if rd and rd not in depts:
                depts.append(rd)
    return depts


def _rs(step, **over):
    d = {
        "kind": step.get("kind"),
        "label": step.get("label"),
        "approver_role": step.get("approver_role"),
        "scope_unit": None,
        "parallel_group": step.get("parallel_group"),
        "return_roles": step.get("return_roles"),
    }
    d.update(over)
    return d


def _resolve_one(step, doc):
    kind = step.get("kind")
    if kind == "team_lead":
        nhom = _find_team_unit(getattr(doc, "routing_unit", None), getattr(doc, "requested_by", None))
        if nhom and engine.unit_has_leader(nhom):
            return [_rs(step, scope_unit=nhom)]
        return []
    if kind == "department_head":
        unit = doc.routing_unit if doc.doctype == PR_DT else getattr(doc, "procurement_unit", None)
        if not unit:
            if step.get("is_optional"):
                return []
            frappe.throw("Chưa xác định phòng chủ quản để duyệt.")
        if not engine.unit_has_leader(unit):
            if step.get("is_optional"):
                return []
            frappe.throw("Đơn vị chủ quản chưa gán trưởng — không thể nộp phiếu.")
        return [_rs(step, scope_unit=unit)]
    if kind == "related_department":
        rds = getattr(doc, "related_departments", None) or []
        grp = step.get("parallel_group") or "related"
        return [_rs(step, scope_unit=rd.department, parallel_group=grp) for rd in rds if rd.department]
    if kind == "order_dept_head":
        depts = _substituted_requesting_depts(doc)
        grp = step.get("parallel_group") or "order"
        return [_rs(step, scope_unit=d, parallel_group=grp) for d in depts]
    # council_* / role: gate theo role
    return [_rs(step, scope_unit=None)]


def resolve_steps(doc):
    """LEGACY linear RESOLVE (giữ tham chiếu; submit mới dùng resolve_graph)."""
    steps, _edges, tpl = engine.get_active_template(doc.doctype)
    if steps is None:
        steps = DEFAULT_PR_STEPS if doc.doctype == PR_DT else DEFAULT_PO_STEPS
    doc.applied_template = tpl
    resolved = []
    for step in steps:
        if not engine.step_enabled(step, doc):
            continue
        resolved.extend(_resolve_one(step, doc))
    return resolved


# ===========================================================================
# DAG RESOLVE (KissFlow) — template nodes+edges -> runtime nodes + edges
# ===========================================================================

_COUNCIL_ROLE = {"council_finance": "CFO", "council_coo": "COO", "council_ceo": "CEO"}


def _assign_seq(nodes):
    """Gom node liền kề cùng parallel_group vào 1 nấc (cho linear khi không có cạnh)."""
    seq = 0
    last = None
    sentinel = 0
    out = []
    for i, n in enumerate(nodes):
        grp = n.get("parallel_group")
        if grp and grp == last:
            pass
        else:
            seq += 1
            if grp:
                last = grp
            else:
                sentinel += 1
                last = ("__solo__", sentinel)
        out.append(seq)
    return out


def _rnode(tnode, doc, **over):
    at = tnode.get("approver_type")
    kind = tnode.get("kind")
    if not at:
        at = "role" if kind in ("council_finance", "council_coo", "council_ceo", "role") else "dynamic"
    d = {
        "node_id": tnode.get("node_id"),
        "kind": kind,
        "label": tnode.get("label"),
        "approver_type": at,
        "approver_role": tnode.get("approver_role"),
        "approver_user": tnode.get("approver_user"),
        "scope_unit": None,
        "parallel_group": tnode.get("parallel_group"),
        "return_roles": tnode.get("return_roles"),
        "return_users": tnode.get("return_users"),
        "view_roles": tnode.get("view_roles"),
        "view_users": tnode.get("view_users"),
        "edit_roles": tnode.get("edit_roles"),
        "edit_users": tnode.get("edit_users"),
        "delete_roles": tnode.get("delete_roles"),
        "delete_users": tnode.get("delete_users"),
        "_cond_skip": not engine.step_enabled(tnode, doc),
    }
    d.update(over)
    return d


def _resolve_node(tnode, doc):
    """1 template node -> 0+ runtime node dict (expand dynamic)."""
    at = tnode.get("approver_type")
    kind = tnode.get("kind")
    if not at:
        at = "role" if kind in ("council_finance", "council_coo", "council_ceo", "role") else "dynamic"
    if at == "user":
        return [_rnode(tnode, doc)]
    if at == "role":
        role = tnode.get("approver_role") or _COUNCIL_ROLE.get(kind)
        return [_rnode(tnode, doc, approver_role=role)]
    # dynamic
    if kind == "team_lead":
        nhom = _find_team_unit(getattr(doc, "routing_unit", None), getattr(doc, "requested_by", None))
        if nhom and engine.unit_has_leader(nhom):
            return [_rnode(tnode, doc, scope_unit=nhom)]
        return []
    if kind == "department_head":
        unit = doc.routing_unit if doc.doctype == PR_DT else getattr(doc, "procurement_unit", None)
        if not unit:
            if tnode.get("is_optional"):
                return []
            frappe.throw("Chưa xác định phòng chủ quản để duyệt.")
        if not engine.unit_has_leader(unit):
            if tnode.get("is_optional"):
                return []
            frappe.throw("Đơn vị chủ quản chưa gán trưởng — không thể nộp phiếu.")
        return [_rnode(tnode, doc, scope_unit=unit)]
    if kind == "related_department":
        rds = getattr(doc, "related_departments", None) or []
        return [_rnode(tnode, doc, scope_unit=rd.department) for rd in rds if rd.department]
    if kind == "order_dept_head":
        return [_rnode(tnode, doc, scope_unit=d) for d in _substituted_requesting_depts(doc)]
    # dynamic lạ -> gate theo approver_role nếu có
    return [_rnode(tnode, doc)]


def _splice_out(tedges, empty):
    """Bỏ template node có expansion rỗng: nối thẳng pred -> succ (bypass)."""
    edges = list(tedges)
    for nid in empty:
        preds = [e for e in edges if e["to"] == nid]
        succs = [e for e in edges if e["from"] == nid]
        edges = [e for e in edges if e["from"] != nid and e["to"] != nid]
        for p in preds:
            for s in succs:
                edges.append({"from": p["from"], "to": s["to"], "live": p["live"] and s["live"]})
    # dedupe (from,to) — live = OR các đường
    out = []
    index = {}
    for e in edges:
        if e["from"] == e["to"]:
            continue
        k = (e["from"], e["to"])
        if k in index:
            out[index[k]]["live"] = out[index[k]]["live"] or e["live"]
        else:
            index[k] = len(out)
            out.append(dict(e))
    return out


def resolve_graph(doc):
    """RESOLVE DAG: template (hoặc DEFAULT linear) -> (runtime_nodes, runtime_edges)."""
    steps, edges, tpl = engine.get_active_template(doc.doctype)
    if steps is None:
        steps = DEFAULT_PR_STEPS if doc.doctype == PR_DT else DEFAULT_PO_STEPS
        edges = None
    doc.applied_template = tpl

    # 1) gán node_id
    tnodes = []
    for i, s in enumerate(steps):
        tnodes.append({**s, "node_id": s.get("node_id") or f"n{i + 1}"})

    # 2) cạnh ở mức template
    if edges:
        tedges = [
            {
                "from": e.get("from_node"),
                "to": e.get("to_node"),
                "live": engine.edge_passes(e, doc),
            }
            for e in edges
            if e.get("from_node") and e.get("to_node")
        ]
    else:
        seqs = _assign_seq(tnodes)
        by_seq = {}
        for i, sq in enumerate(seqs):
            by_seq.setdefault(sq, []).append(tnodes[i]["node_id"])
        order = [by_seq[k] for k in sorted(by_seq)]
        tedges = []
        for k in range(len(order) - 1):
            for f in order[k]:
                for t in order[k + 1]:
                    tedges.append({"from": f, "to": t, "live": True})

    # 3) resolve node -> expansion map
    runtime_nodes = []
    expansion = {}
    for tn in tnodes:
        resolved = _resolve_node(tn, doc)
        rids = []
        for j, rn in enumerate(resolved):
            rid = tn["node_id"] if len(resolved) == 1 else f"{tn['node_id']}__{j + 1}"
            rn["node_id"] = rid
            runtime_nodes.append(rn)
            rids.append(rid)
        expansion[tn["node_id"]] = rids

    # 4) bypass node rỗng
    empty = {nid for nid, rids in expansion.items() if not rids}
    if empty:
        tedges = _splice_out(tedges, empty)

    # 5) expand cạnh template -> cạnh runtime (cartesian theo expansion)
    runtime_edges = []
    for e in tedges:
        for rf in expansion.get(e["from"], []):
            for rt in expansion.get(e["to"], []):
                runtime_edges.append({"from": rf, "to": rt, "live": e["live"]})

    return runtime_nodes, runtime_edges
