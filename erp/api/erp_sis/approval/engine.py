"""
Engine duyệt GENERIC (dùng chung mọi doctype có child `approval_steps` = ERP Approval Step).

3 lớp: RESOLVE (module nghiệp vụ cung cấp resolved-steps) -> SNAPSHOT (materialize)
-> ADVANCE (approve/return/reject). Gate: role HOẶC leader của scope_unit (LIVE).
KHÔNG đóng băng email — chỉ đóng băng cấu trúc (role + scope_unit).
"""

import json

import frappe
from frappe.utils import now

APPROVAL_STEP_DT = "ERP Approval Step"
APPROVAL_TEMPLATE_DT = "ERP Approval Template"
ORG_DT = "ERP Organization Unit"
ORG_LEADER_DT = "ERP Organization Unit Leader"
PROC_HISTORY_DT = "ERP Procurement History"

# Role org-wide: duyệt/thấy được mọi bước scoped (đường thoát)
ORG_WIDE_ROLES = ("System Manager", "SIS BOD")

# Field header được phép dùng trong điều kiện bước (whitelist)
CONDITION_WHITELIST = {
    "total_estimated",
    "total_qty",
    "request_group",
    "campus_id",
    "budget_in_out",
    "has_substitution",
    "is_urgent",
}


# ---------------------------------------------------------------------------
# Org gating helpers
# ---------------------------------------------------------------------------

def units_led_by(email):
    rows = frappe.get_all(
        ORG_LEADER_DT, filters={"user": email, "parenttype": ORG_DT}, pluck="parent"
    )
    return list({r for r in rows if r})


def is_leader_of(unit, email):
    if not unit:
        return False
    return bool(
        frappe.db.exists(
            ORG_LEADER_DT, {"parent": unit, "parenttype": ORG_DT, "user": email}
        )
    )


def first_leader_of(unit):
    if not unit:
        return None
    rows = frappe.get_all(
        ORG_LEADER_DT,
        filters={"parent": unit, "parenttype": ORG_DT},
        fields=["user", "full_name"],
        order_by="sort_order asc, idx asc",
        limit=1,
    )
    if not rows:
        return None
    return {"user": rows[0].user, "full_name": rows[0].full_name or rows[0].user}


def unit_has_leader(unit):
    return bool(first_leader_of(unit))


# ---------------------------------------------------------------------------
# Điều kiện bước (field – toán tử – giá trị)
# ---------------------------------------------------------------------------

def _to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _apply_op(op, actual, value):
    if op in (">", "<", ">=", "<="):
        a, b = _to_num(actual), _to_num(value)
        if a is None or b is None:
            return False
        return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
    if op == "in":
        choices = {c.strip() for c in str(value or "").replace("\n", ",").split(",") if c.strip()}
        return str(actual) in choices
    # "=" / "!=" : so chuỗi (hỗ trợ số)
    an, bn = _to_num(actual), _to_num(value)
    if an is not None and bn is not None:
        eq = an == bn
    else:
        eq = str(actual or "") == str(value or "")
    return eq if op == "=" else (not eq)


def step_enabled(step, doc):
    """Bước có vào luồng theo điều kiện dữ liệu phiếu không."""
    field = step.get("condition_field")
    if not field:
        return True
    if field not in CONDITION_WHITELIST:
        return True  # field lạ -> không chặn (an toàn)
    return _apply_op(step.get("condition_op"), doc.get(field), step.get("condition_value"))


def edge_passes(edge, doc):
    """Cạnh DAG có điều kiện rẽ nhánh không; rỗng = luôn đi."""
    field = edge.get("condition_field")
    if not field:
        return True
    if field not in CONDITION_WHITELIST:
        return True
    return _apply_op(edge.get("condition_op"), doc.get(field), edge.get("condition_value"))


# ---------------------------------------------------------------------------
# Template active (config) -> step dicts; None nếu chưa cấu hình (dùng DEFAULT)
# ---------------------------------------------------------------------------

def get_active_template(target_doctype):
    """Trả (steps, edges, name); (None, None, None) nếu chưa cấu hình -> dùng DEFAULT."""
    name = frappe.db.get_value(
        APPROVAL_TEMPLATE_DT,
        {"target_doctype": target_doctype, "is_active": 1},
        "name",
    )
    if not name:
        return None, None, None
    tpl = frappe.get_doc(APPROVAL_TEMPLATE_DT, name)
    steps = []
    for s in sorted(tpl.steps, key=lambda x: (x.step_order or 0)):
        steps.append(
            {
                "node_id": s.node_id,
                "kind": s.kind,
                "label": s.label,
                "approver_type": s.approver_type,
                "approver_role": s.approver_role,
                "approver_user": s.approver_user,
                "is_optional": s.is_optional,
                "parallel_group": s.parallel_group,
                "return_roles": s.return_roles,
                "return_users": s.return_users,
                "view_roles": s.view_roles,
                "view_users": s.view_users,
                "edit_roles": s.edit_roles,
                "edit_users": s.edit_users,
                "delete_roles": s.delete_roles,
                "delete_users": s.delete_users,
                "condition_field": s.condition_field,
                "condition_op": s.condition_op,
                "condition_value": s.condition_value,
            }
        )
    edges = [
        {
            "from_node": e.from_node,
            "to_node": e.to_node,
            "condition_field": e.condition_field,
            "condition_op": e.condition_op,
            "condition_value": e.condition_value,
        }
        for e in (tpl.edges or [])
    ]
    return steps, edges, name


# ---------------------------------------------------------------------------
# SNAPSHOT - materialize resolved steps vào doc.approval_steps
# ---------------------------------------------------------------------------

def materialize(doc, resolved):
    """resolved: list dict {kind,label,approver_role,scope_unit,parallel_group,return_roles}.
    Gán seq (cùng parallel_group -> cùng seq), dedupe (approver_role, scope_unit) liền kề."""
    # dedupe liền kề
    cleaned = []
    for r in resolved:
        key = (r.get("approver_role") or "", r.get("scope_unit") or "")
        if cleaned:
            prev = cleaned[-1]
            if (prev.get("approver_role") or "", prev.get("scope_unit") or "") == key:
                continue
        cleaned.append(r)

    # gán seq
    seq = 0
    last_group = None
    sentinel = 0
    rows = []
    for r in cleaned:
        grp = r.get("parallel_group")
        if grp and grp == last_group:
            pass  # cùng nấc
        else:
            seq += 1
            if grp:
                last_group = grp
            else:
                sentinel += 1
                last_group = ("__solo__", sentinel)
        rows.append({**r, "seq": seq})

    doc.set("approval_steps", [])
    for r in rows:
        doc.append(
            "approval_steps",
            {
                "seq": r["seq"],
                "kind": r.get("kind"),
                "label": r.get("label"),
                "approver_role": r.get("approver_role"),
                "scope_unit": r.get("scope_unit"),
                "parallel_group": r.get("parallel_group"),
                "return_roles": r.get("return_roles"),
                "status": "Pending",
                "is_active": 1 if r["seq"] == 1 else 0,
            },
        )
    doc.current_seq = 1 if rows else 0
    return bool(rows)


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

def can_act_step(row, email):
    roles = set(frappe.get_roles(email))
    if row.scope_unit:
        return is_leader_of(row.scope_unit, email) or bool(roles & set(ORG_WIDE_ROLES))
    if row.approver_role:
        return row.approver_role in roles
    return False


def can_return_step(row, email):
    roles = set(frappe.get_roles(email))
    rr = (row.return_roles or "").replace("\n", ",")
    allowed = {r.strip() for r in rr.split(",") if r.strip()}
    if allowed and (roles & allowed):
        return True
    return can_act_step(row, email)


def _active_rows(doc):
    return [r for r in (doc.approval_steps or []) if r.is_active and r.status == "Pending"]


def _seq_rows(doc, seq):
    return [r for r in (doc.approval_steps or []) if r.seq == seq]


# ---------------------------------------------------------------------------
# ADVANCE
# ---------------------------------------------------------------------------

def act_approve(doc, email, comment=None):
    """Duyệt các bước trong nấc hiện tại mà user có quyền. Trả về dict {final}."""
    if doc.get("approval_edges"):
        return _act_approve_dag(doc, email, comment)
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    if doc.submitted_by and doc.submitted_by == email:
        frappe.throw("Người nộp không được tự duyệt (4-mắt).")

    actionable = [r for r in _active_rows(doc) if can_act_step(r, email)]
    if not actionable:
        frappe.throw("Bạn không có quyền duyệt bước hiện tại.")

    ts = now()
    for r in actionable:
        r.status = "Approved"
        r.acted_by = email
        r.acted_at = ts
        if comment:
            r.comment = comment

    # nấc hiện tại đã đủ chưa?
    seq = doc.current_seq
    seq_rows = _seq_rows(doc, seq)
    if not all(r.status in ("Approved", "Skipped") for r in seq_rows):
        return {"final": False, "advanced": False}

    # đẩy nấc
    return _advance_to_next_seq(doc, seq)


def _advance_to_next_seq(doc, seq):
    for r in _seq_rows(doc, seq):
        r.is_active = 0
    next_seq = seq + 1
    next_rows = _seq_rows(doc, next_seq)
    if next_rows:
        for r in next_rows:
            r.is_active = 1
        doc.current_seq = next_seq
        return {"final": False, "advanced": True}
    # hết nấc -> Approved
    doc.workflow_state = "Approved"
    doc.approved_by = frappe.session.user
    doc.approved_at = now()
    return {"final": True, "advanced": True}


def act_return(doc, email, reason=None):
    if doc.get("approval_edges"):
        return _act_return_dag(doc, email, reason)
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    seq = doc.current_seq
    active = _seq_rows(doc, seq)
    if not any(can_return_step(r, email) for r in active):
        frappe.throw("Bạn không có quyền trả lại bước hiện tại.")
    for r in active:
        r.is_active = 0
        r.status = "Pending"
    prev = seq - 1
    if prev >= 1:
        for r in _seq_rows(doc, prev):
            r.status = "Pending"
            r.is_active = 1
        doc.current_seq = prev
    else:
        doc.current_seq = 0
        doc.workflow_state = "Returned"
    doc.return_reason = reason


def act_reject(doc, email, reason=None):
    if doc.get("approval_edges"):
        return _act_reject_dag(doc, email, reason)
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    active = _seq_rows(doc, doc.current_seq)
    if not any(can_return_step(r, email) for r in active):
        frappe.throw("Bạn không có quyền từ chối phiếu này.")
    for r in active:
        if r.status == "Pending":
            r.status = "Rejected"
            r.is_active = 0
    doc.workflow_state = "Rejected"
    doc.return_reason = reason


# ---------------------------------------------------------------------------
# Hàng chờ - query SQL trên tabERP Approval Step
# ---------------------------------------------------------------------------

def pending_parent_names(email, parenttypes):
    units = units_led_by(email)
    roles = frappe.get_roles(email)
    org_wide = bool(set(roles) & set(ORG_WIDE_ROLES))

    pts = tuple(parenttypes) if isinstance(parenttypes, (list, tuple)) else (parenttypes,)
    params = {"pts": pts}
    where = ["s.is_active = 1", "s.status = 'Pending'", "s.parenttype IN %(pts)s"]

    if not org_wide:
        clauses = []
        # bước council/role (scope_unit rỗng) -> theo role
        params["roles"] = tuple(roles) if roles else ("__none__",)
        clauses.append("(s.scope_unit IS NULL AND s.approver_role IN %(roles)s)")
        # bước scoped -> theo đơn vị mình lãnh đạo
        params["units"] = tuple(units) if units else ("__none__",)
        clauses.append("s.scope_unit IN %(units)s")
        # bước người-cụ-thể (approver_type=user)
        params["me"] = email
        clauses.append("s.approver_user = %(me)s")
        where.append("(" + " OR ".join(clauses) + ")")

    rows = frappe.db.sql(
        "SELECT DISTINCT s.parent AS name, s.parenttype AS parenttype "
        "FROM `tabERP Approval Step` s WHERE " + " AND ".join(where),
        params,
        as_dict=True,
    )
    return rows


# ---------------------------------------------------------------------------
# Lịch sử (polymorphic)
# ---------------------------------------------------------------------------

def append_history(ref_doctype, ref_name, action, detail=None, user=None):
    user = user or frappe.session.user
    ufn = frappe.db.get_value("User", user, "full_name") or user
    uav = frappe.db.get_value("User", user, "user_image") or ""
    frappe.get_doc(
        {
            "doctype": PROC_HISTORY_DT,
            "reference_doctype": ref_doctype,
            "reference_name": ref_name,
            "action": action,
            "detail": (detail or "").strip() or None,
            "user_email": user,
            "user_fullname": ufn,
            "user_avatar": uav,
        }
    ).insert(ignore_permissions=True)


def get_history(ref_doctype, ref_name):
    return frappe.get_all(
        PROC_HISTORY_DT,
        filters={"reference_doctype": ref_doctype, "reference_name": ref_name},
        fields=["action", "detail", "user_email", "user_fullname", "user_avatar", "creation"],
        order_by="creation desc",
    )


# ---------------------------------------------------------------------------
# Serialize bước duyệt cho FE (tracker)
# ---------------------------------------------------------------------------

def serialize_steps(doc, email=None):
    email = email or frappe.session.user
    dag = bool(doc.get("approval_edges"))
    out = []
    for r in (doc.approval_steps or []):
        gate = can_act_node(r, email) if dag else can_act_step(r, email)
        can_approve = (
            doc.workflow_state == "Pending"
            and r.is_active
            and r.status == "Pending"
            and gate
            and doc.submitted_by != email
        )
        leader = first_leader_of(r.scope_unit) if r.scope_unit else None
        out.append(
            {
                "node_id": r.node_id,
                "seq": r.seq,
                "kind": r.kind,
                "label": r.label,
                "approver_type": r.approver_type,
                "approver_role": r.approver_role,
                "approver_user": r.approver_user,
                "scope_unit": r.scope_unit,
                "scope_leader": leader,
                "status": r.status,
                "is_active": bool(r.is_active),
                "acted_by": r.acted_by,
                "acted_at": str(r.acted_at) if r.acted_at else None,
                "comment": r.comment,
                "can_approve": bool(can_approve),
            }
        )
    return out


def serialize_edges(doc):
    """Cạnh đã resolve trên phiếu (để FE vẽ graph runtime nếu cần)."""
    try:
        return json.loads(doc.get("approval_edges") or "[]")
    except (ValueError, TypeError):
        return []


# ===========================================================================
# DAG ENGINE (KissFlow) — node + edge; dead-path elimination + AND-join
# ===========================================================================

def _csv(v):
    return [x.strip() for x in (v or "").replace("\n", ",").split(",") if x.strip()]


def _node_grants(step, perm, email, roles):
    """perm in ('view','edit','delete','return'): user/role có trong danh sách quyền của node."""
    rl = _csv(getattr(step, f"{perm}_roles", None))
    ul = _csv(getattr(step, f"{perm}_users", None))
    return (email in ul) or bool(set(rl) & set(roles))


def can_act_node(step, email):
    """Ai DUYỆT được node: theo approver_type (dynamic scope/role | role | user) + org-wide."""
    roles = set(frappe.get_roles(email))
    if roles & set(ORG_WIDE_ROLES):
        return True
    at = step.approver_type or "dynamic"
    if at == "user":
        return bool(step.approver_user) and step.approver_user == email
    if step.scope_unit:
        return is_leader_of(step.scope_unit, email)
    if step.approver_role:
        return step.approver_role in roles
    return False


def can_return_node(step, email):
    roles = set(frappe.get_roles(email))
    if _node_grants(step, "return", email, roles):
        return True
    return can_act_node(step, email)


def active_nodes(doc):
    return [s for s in (doc.approval_steps or []) if s.status == "Pending"]


# ---- materialize + propagate ----------------------------------------------

def materialize_graph(doc, nodes, edges):
    """nodes: list dict đã resolve; edges: list dict {from,to,live}. Đóng băng + propagate."""
    doc.set("approval_steps", [])
    for n in nodes:
        doc.append(
            "approval_steps",
            {
                "node_id": n.get("node_id"),
                "kind": n.get("kind"),
                "label": n.get("label"),
                "approver_type": n.get("approver_type") or "dynamic",
                "approver_role": n.get("approver_role"),
                "approver_user": n.get("approver_user"),
                "scope_unit": n.get("scope_unit"),
                "parallel_group": n.get("parallel_group"),
                "return_roles": n.get("return_roles"),
                "return_users": n.get("return_users"),
                "view_roles": n.get("view_roles"),
                "view_users": n.get("view_users"),
                "edit_roles": n.get("edit_roles"),
                "edit_users": n.get("edit_users"),
                "delete_roles": n.get("delete_roles"),
                "delete_users": n.get("delete_users"),
                "status": "Skipped" if n.get("_cond_skip") else "Waiting",
                "is_active": 0,
            },
        )
    doc.approval_edges = json.dumps(
        [
            {"from": e["from"], "to": e["to"], "live": 1 if e.get("live", True) else 0}
            for e in edges
        ]
    )
    doc.current_seq = 0
    _propagate(doc)
    return bool(nodes)


def _propagate(doc):
    """Kích hoạt node theo reachability: node ready khi MỌI cạnh-live tới đã xong (AND-join);
    không cạnh-live nào tới (mà có incoming) -> Skipped (dead-path)."""
    edges = json.loads(doc.get("approval_edges") or "[]")
    nodes = {s.node_id: s for s in (doc.approval_steps or []) if s.node_id}
    incoming = {nid: [] for nid in nodes}
    for e in edges:
        if e.get("to") in incoming:
            incoming[e["to"]].append(e)

    changed = True
    while changed:
        changed = False
        for nid, s in nodes.items():
            if s.status != "Waiting":
                continue
            inc = incoming.get(nid, [])
            if not inc:  # entry node
                s.status = "Pending"
                s.is_active = 1
                changed = True
                continue
            live_inc = [e for e in inc if e.get("live")]
            if not live_inc:  # mọi cạnh tới đều chết -> không thể tới
                s.status = "Skipped"
                changed = True
                continue
            preds = [nodes[e["from"]] for e in live_inc if e.get("from") in nodes]
            if preds and all(p.status in ("Approved", "Skipped") for p in preds):
                if any(p.status == "Approved" for p in preds):
                    s.status = "Pending"
                    s.is_active = 1
                else:
                    s.status = "Skipped"
                changed = True
    _finalize(doc)


def _finalize(doc):
    steps = doc.approval_steps or []
    if any(s.status == "Pending" for s in steps):
        doc.workflow_state = "Pending"
    elif any(s.status == "Rejected" for s in steps):
        doc.workflow_state = "Rejected"
    elif steps and any(s.status == "Approved" for s in steps):
        doc.workflow_state = "Approved"
        doc.approved_by = frappe.session.user
        doc.approved_at = now()


# ---- advance ---------------------------------------------------------------

def _act_approve_dag(doc, email, comment=None):
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    if doc.submitted_by and doc.submitted_by == email:
        frappe.throw("Người nộp không được tự duyệt (4-mắt).")
    actionable = [
        s
        for s in (doc.approval_steps or [])
        if s.is_active and s.status == "Pending" and can_act_node(s, email)
    ]
    if not actionable:
        frappe.throw("Bạn không có quyền duyệt bước hiện tại.")
    ts = now()
    for s in actionable:
        s.status = "Approved"
        s.is_active = 0
        s.acted_by = email
        s.acted_at = ts
        if comment:
            s.comment = comment
    _propagate(doc)
    return {"final": doc.workflow_state == "Approved", "advanced": True}


def _act_return_dag(doc, email, reason=None):
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    active = active_nodes(doc)
    if not any(can_return_node(s, email) for s in active):
        frappe.throw("Bạn không có quyền trả lại phiếu này.")
    for s in (doc.approval_steps or []):
        s.is_active = 0
        if s.status in ("Pending", "Approved"):
            s.status = "Waiting"
    doc.workflow_state = "Returned"
    doc.return_reason = reason


def _act_reject_dag(doc, email, reason=None):
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    active = active_nodes(doc)
    if not any(can_return_node(s, email) for s in active):
        frappe.throw("Bạn không có quyền từ chối phiếu này.")
    for s in active:
        s.status = "Rejected"
        s.is_active = 0
    doc.workflow_state = "Rejected"
    doc.return_reason = reason


# ---- enforce quyền per-step (view/edit/delete) -----------------------------

def _is_owner_editor(doc, email):
    return email in (
        getattr(doc, "requested_by", None),
        getattr(doc, "buyer", None),
        getattr(doc, "submitted_by", None),
    )


def can_view_doc(doc, email):
    """Xem được nếu: org-wide / người lập / đã từng xử lý / node-active cấp quyền xem hoặc mình duyệt được."""
    roles = set(frappe.get_roles(email))
    if roles & set(ORG_WIDE_ROLES):
        return True
    if _is_owner_editor(doc, email):
        return True
    if not doc.get("approval_edges"):
        return True  # phiếu legacy / chưa snapshot -> không siết
    steps = doc.approval_steps or []
    if any(s.acted_by == email for s in steps):
        return True
    for s in active_nodes(doc):
        if can_act_node(s, email) or can_return_node(s, email) or _node_grants(s, "view", email, roles):
            return True
    return False


def can_edit_doc(doc, email):
    """Sửa được nếu: org-wide / (Draft|Returned & người lập) / (Pending & node-active cấp quyền sửa)."""
    roles = set(frappe.get_roles(email))
    if roles & set(ORG_WIDE_ROLES):
        return True
    state = getattr(doc, "workflow_state", None)
    if state in ("Draft", "Returned", None):
        return _is_owner_editor(doc, email)
    if state == "Pending":
        return any(_node_grants(s, "edit", email, roles) for s in active_nodes(doc))
    return False


def can_delete_doc(doc, email):
    roles = set(frappe.get_roles(email))
    if roles & set(ORG_WIDE_ROLES):
        return True
    state = getattr(doc, "workflow_state", None)
    if state in ("Draft", "Returned", None):
        return _is_owner_editor(doc, email)
    if state == "Pending":
        return any(_node_grants(s, "delete", email, roles) for s in active_nodes(doc))
    return False
