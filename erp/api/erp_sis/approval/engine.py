"""
Engine duyệt GENERIC (dùng chung mọi doctype có child `approval_steps` = ERP Approval Step).

3 lớp: RESOLVE (module nghiệp vụ cung cấp resolved-steps) -> SNAPSHOT (materialize)
-> ADVANCE (approve/return/reject). Gate: role HOẶC leader của scope_unit (LIVE).
KHÔNG đóng băng email — chỉ đóng băng cấu trúc (role + scope_unit).
"""

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


# ---------------------------------------------------------------------------
# Template active (config) -> step dicts; None nếu chưa cấu hình (dùng DEFAULT)
# ---------------------------------------------------------------------------

def get_active_template(target_doctype):
    name = frappe.db.get_value(
        APPROVAL_TEMPLATE_DT,
        {"target_doctype": target_doctype, "is_active": 1},
        "name",
    )
    if not name:
        return None, None
    tpl = frappe.get_doc(APPROVAL_TEMPLATE_DT, name)
    steps = []
    for s in sorted(tpl.steps, key=lambda x: (x.step_order or 0)):
        steps.append(
            {
                "kind": s.kind,
                "label": s.label,
                "approver_role": s.approver_role,
                "is_optional": s.is_optional,
                "parallel_group": s.parallel_group,
                "return_roles": s.return_roles,
                "condition_field": s.condition_field,
                "condition_op": s.condition_op,
                "condition_value": s.condition_value,
            }
        )
    return steps, name


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
        can_approve = (
            doc.workflow_state == "Pending"
            and r.is_active
            and r.status == "Pending"
            and can_act_step(r, email)
            and doc.submitted_by != email
        )
        leader = first_leader_of(r.scope_unit) if r.scope_unit else None
        out.append(
            {
                "seq": r.seq,
                "kind": r.kind,
                "label": r.label,
                "approver_role": r.approver_role,
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
