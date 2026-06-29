"""
Engine duyệt GENERIC (dùng chung mọi doctype có child `approval_steps` = ERP Approval Step).

3 lớp: RESOLVE (module nghiệp vụ cung cấp resolved-steps) -> SNAPSHOT (materialize)
-> ADVANCE (approve/return/reject). Gate: role HOẶC leader của scope_unit (LIVE).
KHÔNG đóng băng email — chỉ đóng băng cấu trúc (role + scope_unit).
"""

import json

import frappe
from frappe.utils import add_to_date, now

from . import fields as cond_fields

APPROVAL_STEP_DT = "ERP Approval Step"
APPROVAL_TEMPLATE_DT = "ERP Approval Template"
ORG_DT = "ERP Organization Unit"
ORG_LEADER_DT = "ERP Organization Unit Leader"
PROC_HISTORY_DT = "ERP Procurement History"

# Role org-wide: duyệt/thấy được mọi bước scoped (đường thoát)
ORG_WIDE_ROLES = ("System Manager", "SIS BOD")


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


def _clauses_of(obj):
    """(clauses, match) từ node/edge: ưu tiên list 'conditions', fallback điều kiện đơn."""
    raw = obj.get("conditions")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    if isinstance(raw, list) and raw:
        return raw, (obj.get("condition_match") or "all")
    if obj.get("condition_field"):
        return [
            {"field": obj.get("condition_field"), "op": obj.get("condition_op"), "value": obj.get("condition_value")}
        ], "all"
    return [], "all"


def eval_conditions(obj, doc):
    """True nếu node/edge thoả điều kiện ghép (AND='all' / OR='any'); field ngoài whitelist -> bỏ qua."""
    clauses, match = _clauses_of(obj)
    checks = []
    for c in clauses:
        f = c.get("field")
        if not f or not cond_fields.field_allowed(getattr(doc, "doctype", None), f):
            continue
        checks.append(_apply_op(c.get("op"), doc.get(f), c.get("value")))
    if not checks:
        return True
    return all(checks) if (match or "all") == "all" else any(checks)


def step_enabled(step, doc):
    """Node có vào luồng theo điều kiện dữ liệu phiếu không (hỗ trợ ghép AND/OR)."""
    return eval_conditions(step, doc)


def edge_passes(edge, doc):
    """Cạnh có thoả điều kiện không (rỗng = luôn đi); hỗ trợ ghép AND/OR."""
    return eval_conditions(edge, doc)


# ---------------------------------------------------------------------------
# Template active (config) -> step dicts; None nếu chưa cấu hình (dùng DEFAULT)
# ---------------------------------------------------------------------------

def _json_list(v):
    """Parse Long Text JSON -> list (an toàn)."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        try:
            out = json.loads(v)
            return out if isinstance(out, list) else []
        except (ValueError, TypeError):
            return []
    return []


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
                "assignee_principal_type": s.get("assignee_principal_type"),
                "assignee_ref": s.get("assignee_ref"),
                "assignee_relation": s.get("assignee_relation"),
                "assignee_unit_type": s.get("assignee_unit_type"),
                "assignee_position": s.get("assignee_position"),
                "principals": _json_list(s.get("principals")),
                "deadline_hours": s.get("deadline_hours"),
                "escalation": s.get("escalation"),
                "escalation_after_hours": s.get("escalation_after_hours"),
                "is_optional": s.is_optional,
                "parallel_group": s.parallel_group,
                "condition_field": s.condition_field,
                "condition_op": s.condition_op,
                "condition_value": s.condition_value,
                "conditions": s.conditions,
                "condition_match": s.condition_match,
            }
        )
    edges = [
        {
            "from_node": e.from_node,
            "to_node": e.to_node,
            "edge_kind": e.edge_kind or "forward",
            "is_default": e.is_default,
            "condition_field": e.condition_field,
            "condition_op": e.condition_op,
            "condition_value": e.condition_value,
            "conditions": e.conditions,
            "condition_match": e.condition_match,
        }
        for e in (tpl.edges or [])
    ]
    return steps, edges, name


# ---------------------------------------------------------------------------
# ADVANCE (DAG — engine duy nhất; nhánh linear cũ đã gỡ)
# ---------------------------------------------------------------------------

def act_approve(doc, email, comment=None):
    return _act_approve_dag(doc, email, comment)


def act_return(doc, email, reason=None):
    return _act_return_dag(doc, email, reason)


def act_reject(doc, email, reason=None):
    return _act_reject_dag(doc, email, reason)


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
    out = []
    for r in (doc.approval_steps or []):
        gate = can_act_node(r, email)
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

def _node_grants(step, perm, email, doc=None):
    """perm in ('view','edit','delete','return'): Principal (neo org chart, LIVE) — perm_principals JSON."""
    raw = step.get("perm_principals") if hasattr(step, "get") else None
    if not raw or doc is None:
        return False
    try:
        plist = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return False
    rows = [p for p in (plist or []) if p.get("slot") == perm]
    if not rows:
        return False
    from . import principals
    return any(principals.principal_grants(p, email, doc) for p in rows)


def can_act_node(step, email):
    """Ai DUYỆT node: org-wide; Principal (neo org chart); hoặc node 'Người tạo' (approver_type=user)."""
    roles = set(frappe.get_roles(email))
    if roles & set(ORG_WIDE_ROLES):
        return True
    if step.get("assignee_principal_type"):
        from . import principals
        return principals.node_assignee_grants(step, email)
    if (step.approver_type or "dynamic") == "user":
        return bool(step.approver_user) and step.approver_user == email
    return False


def can_return_node(step, email, doc=None):
    if _node_grants(step, "return", email, doc):
        return True
    return can_act_node(step, email)


def active_nodes(doc):
    return [s for s in (doc.approval_steps or []) if s.status == "Pending"]


# ---- materialize + propagate ----------------------------------------------

def materialize_graph(doc, nodes, edges):
    """nodes: list dict đã resolve; edges: list dict {from,to,live}. Đóng băng + propagate."""
    doc.set("approval_steps", [])
    ts = now()
    for n in nodes:
        # Node "Người tạo" (start) tự-duyệt ngay khi nộp — chính việc nộp là hành động của họ
        is_start = n.get("kind") == "requester"
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
                "assignee_principal_type": n.get("assignee_principal_type"),
                "assignee_ref": n.get("assignee_ref"),
                "assignee_position": n.get("assignee_position"),
                "perm_principals": json.dumps(n.get("perm_principals") or []),
                "deadline_hours": n.get("deadline_hours"),
                "escalation": n.get("escalation"),
                "escalation_after_hours": n.get("escalation_after_hours"),
                "status": "Approved" if is_start else ("Skipped" if n.get("_cond_skip") else "Waiting"),
                "is_active": 0,
                "acted_by": n.get("approver_user") if is_start else None,
                "acted_at": ts if is_start else None,
            },
        )
    doc.approval_edges = json.dumps(
        [
            {
                "from": e["from"],
                "to": e["to"],
                "live": 1 if e.get("live", True) else 0,
                "kind": e.get("kind", "forward"),
                "is_default": 1 if e.get("is_default") else 0,
                "cf": e.get("condition_field"),
                "co": e.get("condition_op"),
                "cv": e.get("condition_value"),
                "conds": e.get("conditions"),
                "match": e.get("condition_match"),
            }
            for e in edges
        ]
    )
    doc.current_seq = 0
    # node "Người tạo" (start) tự duyệt ngay — đại diện hành vi nộp; mở khoá các bước kế
    for s in (doc.approval_steps or []):
        if s.kind == "requester":
            s.status = "Approved"
            s.is_active = 0
            s.acted_by = s.approver_user or None
    _propagate(doc)
    return bool(nodes)


def _activate(s):
    """Đưa node vào Pending + đóng dấu SLA (activated_at, deadline_at) lần đầu kích hoạt."""
    s.status = "Pending"
    s.is_active = 1
    if not s.get("activated_at"):
        s.activated_at = now()
        try:
            h = int(s.get("deadline_hours") or 0)
        except (TypeError, ValueError):
            h = 0
        if h > 0:
            s.deadline_at = add_to_date(s.activated_at, hours=h)


def _propagate(doc):
    """Kích hoạt node theo reachability: node ready khi MỌI cạnh-live tới đã xong (AND-join);
    không cạnh-live nào tới (mà có incoming) -> Skipped (dead-path)."""
    edges = [e for e in json.loads(doc.get("approval_edges") or "[]") if e.get("kind", "forward") != "return"]
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
                _activate(s)
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
                    _activate(s)
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
    elif steps:
        # còn lại đều Approved/Skipped -> không còn bước chặn -> DUYỆT
        # (gồm cả trường hợp mọi bước sau Người tạo đều bị Skipped: tránh kẹt Pending vĩnh viễn)
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


CREATOR_TARGET = "__creator__"


def _stored_edge_passes(e, doc):
    """Điều kiện trên cạnh đã đóng băng (conds ghép, fallback cf/co/cv)."""
    return eval_conditions(
        {
            "conditions": e.get("conds"),
            "condition_match": e.get("match"),
            "condition_field": e.get("cf"),
            "condition_op": e.get("co"),
            "condition_value": e.get("cv"),
        },
        doc,
    )


def _forward_descendants(start_id, edges):
    """Tập node tới được từ start_id qua cạnh FORWARD (gồm chính start_id)."""
    fwd = {}
    for e in edges:
        if e.get("kind", "forward") == "return":
            continue
        fwd.setdefault(e.get("from"), []).append(e.get("to"))
    seen, stack = set(), [start_id]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for nxt in fwd.get(n, []):
            if nxt not in seen:
                stack.append(nxt)
    return seen


def _return_to_creator(doc, reason):
    for s in (doc.approval_steps or []):
        s.is_active = 0
        if s.status in ("Pending", "Approved"):
            s.status = "Waiting"
    doc.workflow_state = "Returned"
    doc.return_reason = reason


def _act_return_dag(doc, email, reason=None):
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    actor_nodes = [s for s in active_nodes(doc) if can_return_node(s, email, doc)]
    if not actor_nodes:
        frappe.throw("Bạn không có quyền trả lại phiếu này.")
    src = actor_nodes[0]

    all_edges = json.loads(doc.get("approval_edges") or "[]")
    ret_edges = [e for e in all_edges if e.get("kind") == "return" and e.get("from") == src.node_id]
    # cạnh có điều kiện trước, cạnh mặc định sau (chỉ đi khi không cạnh nào khác thoả)
    ordered = [e for e in ret_edges if not e.get("is_default")] + [e for e in ret_edges if e.get("is_default")]
    target = None
    for e in ordered:
        if _stored_edge_passes(e, doc):
            target = e.get("to")
            break

    nodes = {s.node_id: s for s in (doc.approval_steps or [])}
    # Không có cạnh trả về khớp -> trả về người tạo (phiếu về Returned để sửa & nộp lại)
    if not target or target == CREATOR_TARGET or target not in nodes:
        _return_to_creator(doc, reason)
        return

    # Trả về node trung gian: reset nhánh-sau-đích (giữ Skipped), kích hoạt lại đích, phiếu vẫn Pending
    desc = _forward_descendants(target, all_edges)
    for s in (doc.approval_steps or []):
        if s.node_id in desc and s.status in ("Approved", "Pending"):
            s.status = "Waiting"
            s.is_active = 0
            s.acted_by = None
            s.acted_at = None
            s.comment = None
    _propagate(doc)
    doc.return_reason = reason


def _act_reject_dag(doc, email, reason=None):
    if doc.workflow_state != "Pending":
        frappe.throw("Phiếu không ở trạng thái chờ duyệt.")
    active = active_nodes(doc)
    if not any(can_return_node(s, email, doc) for s in active):
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
        if can_act_node(s, email) or can_return_node(s, email, doc) or _node_grants(s, "view", email, doc):
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
        return any(_node_grants(s, "edit", email, doc) for s in active_nodes(doc))
    return False


def can_delete_doc(doc, email):
    roles = set(frappe.get_roles(email))
    if roles & set(ORG_WIDE_ROLES):
        return True
    state = getattr(doc, "workflow_state", None)
    if state in ("Draft", "Returned", None):
        return _is_owner_editor(doc, email)
    if state == "Pending":
        return any(_node_grants(s, "delete", email, doc) for s in active_nodes(doc))
    return False
