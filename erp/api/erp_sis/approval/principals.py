"""
Mô hình "Đối tượng được chỉ định" (Principal) neo trên Sơ đồ tổ chức.
Dùng chung cho NGƯỜI DUYỆT (assignee) và từng Ô QUYỀN (view/edit/delete/return).

- resolve_principal(p, doc) -> list target {principal_type, scope_unit, approver_role, approver_user, position}
  (assignee có thể fan-out nhiều node, vd "trưởng các đơn vị trong bảng con").
- node_assignee_grants(step, email) -> bool : gate người-duyệt theo principal đã snapshot trên runtime step.
- principal_grants(p, email, doc) -> bool : gate Ô QUYỀN, phân giải LIVE theo org chart hiện thời.

Thuần BỔ SUNG: chỉ chạy khi node có assignee_principal_type / ô quyền có principal; nếu không, engine
giữ nguyên đường legacy (kind/approver_role/scope_unit + CSV) → PR/PO không đổi hành vi.
"""

import frappe

from . import engine

ORG_DT = "ERP Organization Unit"
ORG_TYPE_DT = "ERP Organization Unit Type"
MEMBER_DT = "ERP Organization Unit Member"
ASSOCIATE_DT = "ERP Organization Unit Associate"
LEADER_DT = "ERP Organization Unit Leader"

DEPARTMENT_TYPE_ORDER = 3
TEAM_TYPE_ORDER = 4


# ---------------------------------------------------------------------------
# Helper org chart (bổ sung cho engine.is_leader_of/units_led_by)
# ---------------------------------------------------------------------------

def is_member_of(unit, email):
    if not (unit and email):
        return False
    return bool(frappe.db.exists(MEMBER_DT, {"parent": unit, "parenttype": ORG_DT, "user": email}))


def is_associate_of(unit, email):
    if not (unit and email):
        return False
    return bool(frappe.db.exists(ASSOCIATE_DT, {"parent": unit, "parenttype": ORG_DT, "user": email}))


def has_position(unit, position, email):
    """Người có chức danh = position (trong unit nếu có, không thì xuyên đơn vị) — dùng GĐ5."""
    if not (position and email):
        return False
    for dt in (LEADER_DT, MEMBER_DT):
        flt = {"parenttype": ORG_DT, "user": email, "position": position}
        if unit:
            flt["parent"] = unit
        if frappe.db.exists(dt, flt):
            return True
    return False


def _unit_type_name(type_order):
    return frappe.db.get_value(ORG_TYPE_DT, {"type_order": type_order, "is_active": 1}, "name") or frappe.db.get_value(
        ORG_TYPE_DT, {"type_order": type_order}, "name"
    )


def _walk_to_department(unit):
    """Đi lên cây tới đơn vị type_order=3 (Phòng); trả về chính nó nếu đã là Phòng."""
    cur = unit
    seen = 0
    while cur and seen < 12:
        seen += 1
        row = frappe.db.get_value(ORG_DT, cur, ["parent_organization_unit", "unit_type"], as_dict=True)
        if not row:
            return None
        torder = frappe.db.get_value(ORG_TYPE_DT, row.unit_type, "type_order") if row.unit_type else None
        if torder == DEPARTMENT_TYPE_ORDER:
            return cur
        cur = row.parent_organization_unit
    return None


def _find_team_unit(parent_unit, user):
    """Nhóm (type_order=4) trực thuộc parent_unit mà user là thành viên."""
    if not (parent_unit and user):
        return None
    grp_type = _unit_type_name(TEAM_TYPE_ORDER)
    if not grp_type:
        return None
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabERP Organization Unit Member` m
        INNER JOIN `tabERP Organization Unit` u ON m.parent = u.name
        WHERE m.user = %(user)s AND u.unit_type = %(gt)s
          AND u.parent_organization_unit = %(pu)s AND u.is_active = 1
        LIMIT 1
        """,
        {"user": user, "gt": grp_type, "pu": parent_unit},
        as_dict=True,
    )
    return rows[0].name if rows else None


def _units_in_table_field(doc, field):
    """field dạng 'tablefield.subfield' -> list giá trị (đơn vị) trong bảng con."""
    if not field or "." not in field:
        return []
    table, sub = field.split(".", 1)
    rows = doc.get(table) or []
    out = []
    for r in rows:
        v = r.get(sub) if hasattr(r, "get") else getattr(r, sub, None)
        if v:
            out.append(v)
    return out


def _requester(doc):
    return doc.get("requested_by") or doc.get("buyer") or getattr(doc, "owner", None)


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------

def _t(principal_type, scope_unit=None, approver_role=None, approver_user=None, position=None):
    return {
        "principal_type": principal_type,
        "scope_unit": scope_unit,
        "approver_role": approver_role,
        "approver_user": approver_user,
        "position": position,
    }


def _resolve_relative(p, doc):
    rel = p.get("relation")
    field = p.get("ref")
    val = doc.get(field) if field else None
    if rel == "self":
        return [_t("user", approver_user=val)] if val else []
    if rel == "leader_of_unit_in_field":
        return [_t("unit_leader", scope_unit=val)] if val else []
    if rel == "members_of_unit_in_field":
        return [_t("unit_members", scope_unit=val)] if val else []
    if rel == "parent_department_head":
        dept = _walk_to_department(val)
        return [_t("unit_leader", scope_unit=dept)] if dept else []
    if rel == "team_lead":
        team = _find_team_unit(val, _requester(doc))
        return [_t("unit_leader", scope_unit=team)] if team else []
    if rel == "leaders_of_units_in_table_field":
        return [_t("unit_leader", scope_unit=u) for u in _units_in_table_field(doc, field)]
    return []


def resolve_principal(p, doc):
    """1 principal -> list target (assignee có thể fan-out)."""
    ptype = p.get("principal_type")
    if ptype == "user":
        return [_t("user", approver_user=p.get("ref"))] if p.get("ref") else []
    if ptype == "role":
        return [_t("role", approver_role=p.get("ref"))] if p.get("ref") else []
    if ptype == "unit_leader":
        return [_t("unit_leader", scope_unit=p.get("ref"))] if p.get("ref") else []
    if ptype == "unit_members":
        return [_t("unit_members", scope_unit=p.get("ref"))] if p.get("ref") else []
    if ptype == "unit_associate":
        return [_t("unit_associate", scope_unit=p.get("ref"))] if p.get("ref") else []
    if ptype == "position":
        return [_t("position", scope_unit=p.get("ref") or None, position=p.get("position"))]
    if ptype == "relative":
        return _resolve_relative(p, doc)
    return []


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

def _target_has(t, email, roles):
    pt = t.get("principal_type")
    if pt == "user":
        return bool(t.get("approver_user")) and t["approver_user"] == email
    if pt == "role":
        return t.get("approver_role") in roles
    if pt == "unit_leader":
        return engine.is_leader_of(t.get("scope_unit"), email)
    if pt == "unit_members":
        return is_member_of(t.get("scope_unit"), email)
    if pt == "unit_associate":
        return is_associate_of(t.get("scope_unit"), email)
    if pt == "position":
        return has_position(t.get("scope_unit"), t.get("position"), email)
    return False


def node_assignee_grants(step, email):
    """Gate người-duyệt theo principal đã snapshot trên runtime step."""
    roles = set(frappe.get_roles(email))
    if roles & set(engine.ORG_WIDE_ROLES):
        return True
    t = _t(
        step.get("assignee_principal_type"),
        scope_unit=step.get("scope_unit"),
        approver_role=step.get("approver_role"),
        approver_user=step.get("approver_user"),
        position=step.get("assignee_position"),
    )
    return _target_has(t, email, roles)


def principal_grants(p, email, doc):
    """Gate Ô QUYỀN: phân giải LIVE principal theo org chart hiện thời rồi kiểm tra email."""
    roles = set(frappe.get_roles(email))
    if roles & set(engine.ORG_WIDE_ROLES):
        return True
    for t in resolve_principal(p, doc):
        if _target_has(t, email, roles):
            return True
    return False


# ---------------------------------------------------------------------------
# Liệt kê email (cho thông báo / SLA escalation)
# ---------------------------------------------------------------------------

def leaders_of(unit):
    return frappe.get_all(LEADER_DT, filters={"parent": unit, "parenttype": ORG_DT}, pluck="user") if unit else []


def members_of(unit):
    return frappe.get_all(MEMBER_DT, filters={"parent": unit, "parenttype": ORG_DT}, pluck="user") if unit else []


def associates_of(unit):
    return frappe.get_all(ASSOCIATE_DT, filters={"parent": unit, "parenttype": ORG_DT}, pluck="user") if unit else []


def role_users(role):
    return frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent") if role else []


def position_users(unit, position):
    if not position:
        return []
    out = set()
    for dt in (LEADER_DT, MEMBER_DT):
        flt = {"parenttype": ORG_DT, "position": position}
        if unit:
            flt["parent"] = unit
        out.update(frappe.get_all(dt, filters=flt, pluck="user"))
    return list(out)


def assignee_emails(step):
    """Danh sách email người-duyệt của 1 runtime step (dict hoặc doc, dùng .get)."""
    t = step.get("assignee_principal_type")
    su = step.get("scope_unit")
    if t == "user":
        return [step.get("approver_user")] if step.get("approver_user") else []
    if t == "role":
        return role_users(step.get("approver_role"))
    if t == "unit_leader":
        return leaders_of(su)
    if t == "unit_members":
        return members_of(su)
    if t == "unit_associate":
        return associates_of(su)
    if t == "position":
        return position_users(su, step.get("assignee_position"))
    # legacy
    if su:
        return leaders_of(su)
    if step.get("approver_role"):
        return role_users(step.get("approver_role"))
    if step.get("approver_user"):
        return [step.get("approver_user")]
    return []


def parent_unit_leader(unit):
    """Trưởng đơn vị CHA của unit (leo thang 1 cấp)."""
    if not unit:
        return []
    parent = frappe.db.get_value(ORG_DT, unit, "parent_organization_unit")
    return leaders_of(parent) if parent else []
