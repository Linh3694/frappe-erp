"""
Resolver luồng duyệt cho PR/PO (phần NGHIỆP VỤ — adapter của engine generic).

DEFAULT_PR_STEPS / DEFAULT_PO_STEPS: CHỈ để catalog.seed_default_template di trú PR/PO 1 lần thành template.
resolve_graph(doc): template nodes+edges -> (runtime_nodes, runtime_edges) cho engine.materialize_graph().
"""

import frappe

from ..approval import engine
from ..approval import principals

ORG_DT = "ERP Organization Unit"
ORG_TYPE_DT = "ERP Organization Unit Type"
PR_DT = "ERP Purchase Request"
PO_DT = "ERP Purchase Order"

# Node "Người tạo" (gốc luồng) — marker UI, không sinh bước duyệt; đích trả-về = người tạo
START_KIND = "requester"
# Node "Kết thúc" — marker terminal; tới đây = phiếu Approved (splice khỏi forward)
END_KIND = "end"

def _return_principals(*role_refs):
    return [{"slot": "return", "principal_type": "role", "ref": r} for r in role_refs]


# Luồng PR: (Trưởng nhóm tự bỏ) -> Trưởng phòng -> Phòng liên quan (song song) -> CFO -> COO -> CEO
DEFAULT_PR_STEPS = [
    {"kind": "team_lead", "label": "Trưởng nhóm", "is_optional": 1},
    {"kind": "department_head", "label": "Trưởng phòng"},
    {"kind": "related_department", "label": "Phòng liên quan", "parallel_group": "related"},
    {"kind": "council_finance", "label": "Phòng Tài chính", "approver_role": "CFO", "principals": _return_principals("SIS Finance", "CFO")},
    {"kind": "council_coo", "label": "COO", "approver_role": "COO", "principals": _return_principals("COO")},
    {"kind": "council_ceo", "label": "CEO", "approver_role": "CEO", "principals": _return_principals("CEO")},
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
    {"kind": "council_finance", "label": "Phòng Tài chính", "approver_role": "CFO", "principals": _return_principals("SIS Finance", "CFO")},
    {"kind": "council_coo", "label": "COO", "approver_role": "COO", "principals": _return_principals("COO")},
    {"kind": "council_ceo", "label": "CEO", "approver_role": "CEO", "principals": _return_principals("CEO")},
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


def _perm_principals(tnode):
    """Lấy principal cho các ô quyền (view/edit/delete/return) từ bảng con template."""
    out = []
    for p in (tnode.get("principals") or []):
        if p.get("slot") in ("view", "edit", "delete", "return"):
            out.append({k: p.get(k) for k in ("slot", "principal_type", "ref", "relation", "unit_type", "position")})
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
        "assignee_principal_type": None,
        "assignee_ref": None,
        "assignee_position": None,
        "perm_principals": _perm_principals(tnode),
        "parallel_group": tnode.get("parallel_group"),
        "deadline_hours": tnode.get("deadline_hours"),
        "escalation": tnode.get("escalation"),
        "escalation_after_hours": tnode.get("escalation_after_hours"),
        "_cond_skip": not engine.step_enabled(tnode, doc),
    }
    d.update(over)
    return d


def _resolve_node(tnode, doc):
    """1 template node -> 0+ runtime node dict (expand dynamic)."""
    kind = tnode.get("kind")
    # Node "Kết thúc" (end): marker terminal -> splice khỏi forward (tới đây = phiếu Approved)
    if kind == END_KIND:
        return []
    # Node "Người tạo" (start): gắn người tạo phiếu, sẽ tự-duyệt khi nộp
    if kind == "requester":
        creator = getattr(doc, "requested_by", None) or getattr(doc, "buyer", None)
        return [_rnode(tnode, doc, approver_type="user", approver_user=creator)]
    # Người duyệt theo PRINCIPAL (neo Sơ đồ tổ chức) — ưu tiên nếu cấu hình; có thể fan-out nhiều node
    if tnode.get("assignee_principal_type"):
        p = {
            "principal_type": tnode.get("assignee_principal_type"),
            "ref": tnode.get("assignee_ref"),
            "relation": tnode.get("assignee_relation"),
            "unit_type": tnode.get("assignee_unit_type"),
            "position": tnode.get("assignee_position"),
        }
        targets = principals.resolve_principal(p, doc)
        if not targets and not tnode.get("is_optional"):
            # giữ semantics cũ: thiếu người resolve -> node rỗng (splice) nếu optional, else vẫn rỗng (an toàn)
            return []
        return [
            _rnode(
                tnode,
                doc,
                assignee_principal_type=t["principal_type"],
                scope_unit=t.get("scope_unit"),
                approver_role=t.get("approver_role"),
                approver_user=t.get("approver_user"),
                assignee_position=t.get("position"),
            )
            for t in targets
        ]
    at = tnode.get("approver_type")
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
        # Quyết định #5: KHÔNG còn luồng mặc định cứng — chưa cấu hình template => rỗng (chặn nộp)
        return [], []
    doc.applied_template = tpl

    # 1) gán node_id
    tnodes = []
    for i, s in enumerate(steps):
        tnodes.append({**s, "node_id": s.get("node_id") or f"n{i + 1}"})

    # start node id(s) — đích trả-về tới đây = người tạo
    start_ids = {tn["node_id"] for tn in tnodes if tn.get("kind") == START_KIND}

    # 2) cạnh template: tách FORWARD (tiến) vs RETURN (trả về)
    return_tpl = []
    if edges:
        fwd = [
            e for e in edges
            if e.get("from_node") and e.get("to_node") and (e.get("edge_kind") or "forward") != "return"
        ]
        # live của cạnh thường (non-default) theo điều kiện
        live = [False if e.get("is_default") else engine.edge_passes(e, doc) for e in fwd]
        # nguồn có cạnh non-default nào thoả?
        src_has_live = {}
        for e, lv in zip(fwd, live):
            if not e.get("is_default"):
                src_has_live[e["from_node"]] = src_has_live.get(e["from_node"], False) or lv
        # cạnh mặc định: live khi cùng nguồn không cạnh thường nào thoả
        tedges = []
        for e, lv in zip(fwd, live):
            if e.get("is_default"):
                lv = not src_has_live.get(e["from_node"], False)
            tedges.append({"from": e["from_node"], "to": e["to_node"], "live": lv})
        return_tpl = [e for e in edges if e.get("from_node") and e.get("to_node") and e.get("edge_kind") == "return"]
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

    # 4) bypass node rỗng khỏi forward
    empty = {nid for nid, rids in expansion.items() if not rids}
    if empty:
        tedges = _splice_out(tedges, empty)

    # 5) FORWARD runtime edges
    runtime_edges = []
    for e in tedges:
        for rf in expansion.get(e["from"], []):
            for rt in expansion.get(e["to"], []):
                runtime_edges.append({"from": rf, "to": rt, "live": e["live"], "kind": "forward"})

    # 6) RETURN runtime edges (đích là start -> "__creator__" = trả về người tạo)
    for e in return_tpl:
        targets = ["__creator__"] if e["to_node"] in start_ids else expansion.get(e["to_node"], [])
        for rf in expansion.get(e["from_node"], []):
            for rt in targets:
                runtime_edges.append({
                    "from": rf,
                    "to": rt,
                    "kind": "return",
                    "is_default": e.get("is_default"),
                    "condition_field": e.get("condition_field"),
                    "condition_op": e.get("condition_op"),
                    "condition_value": e.get("condition_value"),
                    "conditions": e.get("conditions"),
                    "condition_match": e.get("condition_match"),
                })

    return runtime_nodes, runtime_edges
