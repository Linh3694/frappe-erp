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
    """RESOLVE: chọn template active (hoặc DEFAULT) -> resolved step dicts."""
    steps, tpl = engine.get_active_template(doc.doctype)
    if steps is None:
        steps = DEFAULT_PR_STEPS if doc.doctype == PR_DT else DEFAULT_PO_STEPS
    doc.applied_template = tpl
    resolved = []
    for step in steps:
        if not engine.step_enabled(step, doc):
            continue
        resolved.extend(_resolve_one(step, doc))
    return resolved
