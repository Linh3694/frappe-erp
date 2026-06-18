"""
Budget API - Helper dùng chung (không export ra ngoài).

Bao gồm:
- Phân quyền (SIS Finance / BOD / System Manager)
- Cơ chế "trưởng phòng" lấy từ Sơ đồ tổ chức ERP Organization Unit (D6)
- Ghi lịch sử (_append_history) mirror erp_administrative_ticket
- Luồng duyệt CỐ ĐỊNH: TC -> CFO -> CEO -> COO (PLAN_STEPS)
"""

import json

import frappe
from frappe import _

# --- Doctype constants ---
CODE_DT = "ERP Budget Code"
PERIOD_DT = "ERP Budget Period"
PLAN_DT = "ERP Budget Plan"
PLAN_LINE_DT = "ERP Budget Plan Line"
PLAN_HISTORY_DT = "ERP Budget Plan History"

ORG_UNIT_DT = "ERP Organization Unit"
ORG_UNIT_TYPE_DT = "ERP Organization Unit Type"
ORG_UNIT_LEADER_DT = "ERP Organization Unit Leader"

# Tên loại đơn vị được phép nộp ngân sách (cấp "Phòng")
DEPARTMENT_TYPE_TITLE_VN = "Phòng"

FINANCE_ROLES = ("System Manager", "SIS Finance")
BOD_ROLES = ("System Manager", "SIS BOD")


# ---------------------------------------------------------------------------
# Request / session helpers
# ---------------------------------------------------------------------------

def _get_request_data():
    """Lấy dữ liệu request, hỗ trợ JSON và form data."""
    if frappe.request and frappe.request.is_json:
        return frappe.request.json or {}
    return dict(frappe.form_dict or {})


def _parse(value):
    """Parse JSON string hoặc trả về nguyên dạng list/dict."""
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def _session_email():
    return frappe.session.user


def _has_any_role(roles):
    user_roles = set(frappe.get_roles(frappe.session.user))
    return any(r in user_roles for r in roles)


def _is_finance():
    """SIS Finance (Phòng TC) hoặc System Manager."""
    return _has_any_role(FINANCE_ROLES)


def _is_bod():
    return _has_any_role(BOD_ROLES)


# ---------------------------------------------------------------------------
# Cơ chế "trưởng phòng" - lấy từ Sơ đồ tổ chức (D6)
# ---------------------------------------------------------------------------

def _department_unit_type():
    """Trả về name loại đơn vị cấp Phòng — fallback nếu title_vn không khớp chính xác."""
    name = frappe.db.get_value(
        ORG_UNIT_TYPE_DT, {"title_vn": DEPARTMENT_TYPE_TITLE_VN}, "name"
    )
    if name:
        return name
    name = frappe.db.get_value(
        ORG_UNIT_TYPE_DT, {"title_en": ["like", "Department%"]}, "name"
    )
    if name:
        return name
    return frappe.db.get_value(
        ORG_UNIT_TYPE_DT, {"type_order": 2, "is_active": 1}, "name"
    )


def list_budget_departments(campus_id=None):
    """Danh sách phòng ban (cấp Phòng) từ Sơ đồ tổ chức — dùng chung API budget."""
    dept_type = _department_unit_type()
    if not dept_type:
        return []
    filters = {"unit_type": dept_type, "is_active": 1}
    if campus_id:
        filters["campus_id"] = campus_id
    units = frappe.get_all(
        ORG_UNIT_DT,
        filters=filters,
        fields=["name", "unit_name_vn", "campus_id"],
        order_by="unit_name_vn asc",
    )
    return [
        {"department": u.name, "department_name": u.unit_name_vn, "campus_id": u.campus_id}
        for u in units
    ]


def _user_led_unit(email=None):
    """
    Trả về ERP Organization Unit (cấp Phòng) mà user là trưởng phòng (∈ leaders).
    1 user chỉ leader 1 unit -> trả về 1 name (hoặc None).
    """
    email = email or _session_email()
    dept_type = _department_unit_type()
    if not dept_type:
        return None

    # Query child table leaders join unit cấp Phòng
    rows = frappe.db.sql(
        """
        SELECT u.name
        FROM `tabERP Organization Unit Leader` l
        INNER JOIN `tabERP Organization Unit` u ON l.parent = u.name
        WHERE l.user = %(user)s
          AND u.unit_type = %(dept_type)s
          AND u.is_active = 1
        LIMIT 1
        """,
        {"user": email, "dept_type": dept_type},
        as_dict=True,
    )
    return rows[0].name if rows else None


def _is_head_of(department, email=None):
    """Kiểm tra user có phải trưởng phòng của department không."""
    if not department:
        return False
    return _user_led_unit(email) == department


def _unit_name(unit):
    if not unit:
        return None
    return frappe.db.get_value(ORG_UNIT_DT, unit, "unit_name_vn")


def _resolve_campus_from_unit(unit):
    if not unit:
        return None
    return frappe.db.get_value(ORG_UNIT_DT, unit, "campus_id")


# ---------------------------------------------------------------------------
# Lịch sử - mirror administrative_ticket._append_history
# ---------------------------------------------------------------------------

def _append_history(plan_id, action, detail=None, user=None):
    """Ghi 1 dòng lịch sử cho 1 budget plan."""
    user = user or frappe.session.user
    ufn = frappe.db.get_value("User", user, "full_name") or user
    uav = frappe.db.get_value("User", user, "user_image") or ""
    detail_clean = (detail or "").strip()
    row = frappe.get_doc(
        {
            "doctype": PLAN_HISTORY_DT,
            "plan": plan_id,
            "action": action,
            "detail": detail_clean or None,
            "user_email": user,
            "user_fullname": ufn,
            "user_avatar": uav,
        }
    )
    row.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Luồng duyệt CỐ ĐỊNH (không cấu hình): TC -> CFO -> CEO -> COO
# ---------------------------------------------------------------------------

PLAN_STEPS = [
    {"step_order": 1, "approver_role": "SIS Finance", "label": "Phòng Tài chính"},
    {"step_order": 2, "approver_role": "CFO", "label": "CFO"},
    {"step_order": 3, "approver_role": "CEO", "label": "CEO"},
    {"step_order": 4, "approver_role": "COO", "label": "COO"},
]


def _plan_steps():
    """Luồng duyệt cố định TC -> CFO -> CEO -> COO."""
    return PLAN_STEPS


def _can_approve_step(steps, current_step, email=None):
    """Kiểm tra user hiện tại có quyền duyệt bước current_step không."""
    email = email or _session_email()
    if current_step < 1 or current_step > len(steps):
        return False
    step = steps[current_step - 1]
    role = step.get("approver_role")
    if not role:
        return True
    return role in frappe.get_roles(email)
