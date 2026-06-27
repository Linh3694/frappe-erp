"""Helper dùng chung cho API mua sắm (PR/PO)."""

import frappe

ORG_DT = "ERP Organization Unit"
ORG_LEADER_DT = "ERP Organization Unit Leader"
ORG_MEMBER_DT = "ERP Organization Unit Member"
ORG_ASSOC_DT = "ERP Organization Unit Associate"

PR_DT = "ERP Purchase Request"
PO_DT = "ERP Purchase Order"
PR_LINE_DT = "ERP Purchase Request Line"
PO_LINE_DT = "ERP Purchase Order Line"
PROC_SETTINGS_DT = "ERP Procurement Settings"


def get_request_data():
    if frappe.request and frappe.request.is_json:
        return frappe.request.json or {}
    return dict(frappe.form_dict or {})


def session_email():
    return frappe.session.user


def is_system_manager(email=None):
    return "System Manager" in frappe.get_roles(email or frappe.session.user)


def _in_child(child_dt, unit, email):
    return bool(frappe.db.exists(child_dt, {"parent": unit, "parenttype": ORG_DT, "user": email}))


def can_set_routing_unit(unit, email=None):
    """Quyền đặt routing_unit = phòng khác: member/leader/associate (liên kết) của phòng đó, hoặc SM."""
    email = email or frappe.session.user
    if is_system_manager(email):
        return True
    if not unit:
        return False
    return (
        _in_child(ORG_LEADER_DT, unit, email)
        or _in_child(ORG_MEMBER_DT, unit, email)
        or _in_child(ORG_ASSOC_DT, unit, email)
    )


def user_home_unit(email=None):
    """Phòng gốc của user (member hoặc leader đầu tiên)."""
    email = email or frappe.session.user
    rows = frappe.db.sql(
        """
        SELECT parent FROM `tabERP Organization Unit Member`
        WHERE user = %(u)s AND parenttype = %(dt)s
        UNION
        SELECT parent FROM `tabERP Organization Unit Leader`
        WHERE user = %(u)s AND parenttype = %(dt)s
        LIMIT 1
        """,
        {"u": email, "dt": ORG_DT},
        as_dict=True,
    )
    return rows[0].parent if rows else None


def resolve_campus(unit):
    if not unit:
        return None
    return frappe.db.get_value(ORG_DT, unit, "campus_id")


def default_procurement_unit():
    try:
        return frappe.db.get_single_value(PROC_SETTINGS_DT, "procurement_unit")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fulfillment (D10): cập nhật qty_ordered / line_status của PR khi PO đổi trạng thái
# ---------------------------------------------------------------------------

def _ordered_qty_for(pr_line_name):
    rows = frappe.db.sql(
        """
        SELECT COALESCE(SUM(pol.qty), 0) AS q
        FROM `tabERP Purchase Order Line` pol
        INNER JOIN `tabERP Purchase Order` po ON pol.parent = po.name
        WHERE pol.pr_line = %(pl)s
          AND po.workflow_state NOT IN ('Cancelled', 'Rejected', 'Draft')
        """,
        {"pl": pr_line_name},
        as_dict=True,
    )
    return (rows[0].q or 0) if rows else 0


def recompute_pr_fulfillment(pr_name):
    """Cập nhật qty_ordered/line_status mọi dòng PR + rollup fulfillment_status."""
    if not pr_name:
        return
    pr = frappe.get_doc(PR_DT, pr_name)
    for l in pr.lines or []:
        ordered = _ordered_qty_for(l.name)
        l.qty_ordered = ordered
        target = l.qty_to_buy or 0
        if ordered <= 0:
            l.line_status = "Open"
        elif ordered < target:
            l.line_status = "Partial"
        else:
            l.line_status = "Closed"
    statuses = [l.line_status for l in (pr.lines or [])]
    if statuses and all(s == "Closed" for s in statuses):
        pr.fulfillment_status = "Closed"
    elif any(s in ("Partial", "Closed") for s in statuses):
        pr.fulfillment_status = "Partial"
    else:
        pr.fulfillment_status = "Open"
    pr.save(ignore_permissions=True)


def outstanding_pr_lines(pr_names):
    """Các dòng PR còn tồn (qty_to_buy > qty_ordered) của các PR đã Approved."""
    if not pr_names:
        return []
    lines = frappe.get_all(
        PR_LINE_DT,
        filters={"parent": ("in", list(pr_names))},
        fields=[
            "name", "parent", "item", "item_name", "spec", "uom",
            "qty_to_buy", "qty_ordered", "unit_price", "line_status",
        ],
        order_by="parent asc, idx asc",
    )
    out = []
    for l in lines:
        remaining = (l.qty_to_buy or 0) - (l.qty_ordered or 0)
        if remaining > 0:
            out.append({**l, "remaining_qty": remaining})
    return out
