"""
Resolver luồng duyệt GENERIC (KissFlow DAG) — template nodes+edges -> runtime nodes+edges.

Mọi node người-duyệt khai báo bằng "Đối tượng" (Principal) neo Sơ đồ tổ chức; chỉ còn 2 marker
cấu trúc: Người tạo (requester) + Kết thúc (end). Không còn luồng mặc định cứng / dispatch theo kind.
resolve_graph(doc) -> (runtime_nodes, runtime_edges) cho engine.materialize_graph().
"""

import frappe

from ..approval import engine
from ..approval import principals

# Node "Người tạo" (gốc luồng) — marker UI, không sinh bước duyệt; đích trả-về = người tạo
START_KIND = "requester"
# Node "Kết thúc" — marker terminal; tới đây = phiếu Approved (splice khỏi forward)
END_KIND = "end"


# ===========================================================================
# DAG RESOLVE (KissFlow) — template nodes+edges -> runtime nodes + edges
# ===========================================================================


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
    d = {
        "node_id": tnode.get("node_id"),
        "kind": tnode.get("kind"),
        "label": tnode.get("label"),
        "approver_type": tnode.get("approver_type") or "dynamic",
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


def _assignee_incomplete(tnode):
    """Người duyệt khai báo CHƯA đủ để phân giải (lỗi cấu hình luồng) — khác với 'resolve ra 0 người' lúc chạy."""
    pt = tnode.get("assignee_principal_type")
    if not pt:
        return True
    if pt == "position":
        return not tnode.get("assignee_position")
    if pt == "relative":
        # mọi quan hệ hiện có đều trỏ tới 1 field trên phiếu
        return not (tnode.get("assignee_relation") and tnode.get("assignee_ref"))
    # user / role / unit_leader / unit_members / unit_associate: cần ref
    return not tnode.get("assignee_ref")


def _resolve_node(tnode, doc):
    """1 template node -> 0+ runtime node. Chỉ còn marker requester/end + người duyệt theo Principal."""
    kind = tnode.get("kind")
    # Node "Kết thúc" (end): marker terminal -> splice khỏi forward (tới đây = phiếu Approved)
    if kind == END_KIND:
        return []
    # Node "Người tạo" (start): gắn người tạo phiếu, sẽ tự-duyệt khi nộp
    if kind == START_KIND:
        creator = getattr(doc, "requested_by", None) or getattr(doc, "buyer", None) or getattr(doc, "owner", None)
        return [_rnode(tnode, doc, approver_type="user", approver_user=creator)]
    # Node duyệt phải khai báo người duyệt ĐẦY ĐỦ; thiếu mà KHÔNG đánh dấu tuỳ chọn -> chặn nộp
    # (tránh node bắt buộc bị splice âm thầm -> auto-bypass). Tuỳ chọn -> bỏ qua êm.
    if _assignee_incomplete(tnode):
        if tnode.get("is_optional"):
            return []
        frappe.throw(
            f"Bước '{tnode.get('label') or tnode.get('node_id')}' chưa chỉ định người duyệt — "
            "hoàn tất cấu hình luồng duyệt trước khi nộp."
        )
    # Người duyệt theo PRINCIPAL (neo Sơ đồ tổ chức) — có thể fan-out nhiều node
    p = {
        "principal_type": tnode.get("assignee_principal_type"),
        "ref": tnode.get("assignee_ref"),
        "relation": tnode.get("assignee_relation"),
        "unit_type": tnode.get("assignee_unit_type"),
        "position": tnode.get("assignee_position"),
    }
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
        for t in principals.resolve_principal(p, doc)
    ]


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
