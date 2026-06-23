"""
Budget API - Helper dùng chung (không export ra ngoài).

Bao gồm:
- Phân quyền (SIS Finance / BOD / System Manager)
- Cơ chế "trưởng phòng" lấy từ Sơ đồ tổ chức ERP Organization Unit (D6)
- Ghi lịch sử (_append_history) mirror erp_administrative_ticket
- Luồng duyệt CỐ ĐỊNH: Phòng ban -> TC (CFO) -> COO -> CEO (PLAN_STEPS)
"""

import json

import frappe
from frappe import _

# --- Doctype constants ---
CODE_DT = "ERP Budget Code"
CODE_DEPT_DT = "ERP Budget Code Department"
PERIOD_DT = "ERP Budget Period"
PLAN_DT = "ERP Budget Plan"
PLAN_LINE_DT = "ERP Budget Plan Line"
PLAN_HISTORY_DT = "ERP Budget Plan History"
SETTLEMENT_DT = "ERP Budget Settlement"

ORG_UNIT_DT = "ERP Organization Unit"
ORG_UNIT_TYPE_DT = "ERP Organization Unit Type"
ORG_UNIT_LEADER_DT = "ERP Organization Unit Leader"
ORG_UNIT_MEMBER_DT = "ERP Organization Unit Member"
SCHOOL_YEAR_DT = "SIS School Year"

# Tên loại đơn vị được phép nộp ngân sách (cấp "Phòng")
DEPARTMENT_TYPE_TITLE_VN = "Phòng"

FINANCE_ROLES = ("System Manager", "SIS Finance")
BOD_ROLES = ("System Manager", "SIS BOD")

# Vai trò duyệt ngân sách (BOD): CFO (bước Phòng TC), COO, CEO.
BUDGET_APPROVER_ROLES = ("CFO", "COO", "CEO")

# Nhãn trạng thái workflow — dùng cho lịch sử "từ giá trị nào sang giá trị nào".
STATE_LABELS = {
    "Draft": "Nháp",
    "Returned": "Bị trả lại",
    "Pending": "Chờ duyệt",
    "Approved": "Đã duyệt",
    "Active": "Đang hiệu lực",
    "Closed": "Đã đóng",
    "Superseded": "Đã thay thế",
}


def _state_label(state):
    return STATE_LABELS.get(state, state or "")


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


def _is_plan_approver_role(email=None):
    """User có ít nhất một vai trò duyệt ngân sách (CFO/COO/CEO)."""
    user_roles = set(frappe.get_roles(email or frappe.session.user))
    return any(r in user_roles for r in BUDGET_APPROVER_ROLES)


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
        ORG_UNIT_TYPE_DT, {"title_vn": ["like", "%Phòng%"]}, "name"
    )
    if name:
        return name
    name = frappe.db.get_value(
        ORG_UNIT_TYPE_DT, {"title_en": ["like", "Department%"]}, "name"
    )
    if name:
        return name
    # Sơ đồ tổ chức: type_order 3 = Phòng (1=tổ chức, 2=khối, 3=phòng, 4=nhóm)
    return frappe.db.get_value(
        ORG_UNIT_TYPE_DT, {"type_order": 3, "is_active": 1}, "name"
    )


def list_budget_departments(campus_id=None):
    """Danh sách phòng ban (cấp Phòng) từ Sơ đồ tổ chức.

    Mã ngân sách dùng chung toàn trường — không lọc campus (campus_id bị bỏ qua).
    """
    _ = campus_id  # legacy param; frontend axios có thể inject campus_id
    dept_type = _department_unit_type()
    if not dept_type:
        return []
    units = frappe.get_all(
        ORG_UNIT_DT,
        filters={"unit_type": dept_type, "is_active": 1},
        fields=["name", "unit_name_vn", "campus_id"],
        order_by="unit_name_vn asc",
    )
    return [
        {"department": u.name, "department_name": u.unit_name_vn, "campus_id": u.campus_id}
        for u in units
    ]


def _user_led_unit(email=None):
    """
    Trả về một ERP Organization Unit (cấp Phòng) mà user là trưởng phòng (∈ leaders).
    User có thể lãnh đạo nhiều phòng — hàm này chỉ trả về phòng đầu tiên (dùng làm mặc định).
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


def _user_budget_unit(email=None):
    """Phòng (cấp Phòng) mà user được lập ngân sách:
    - leader của Phòng, hoặc
    - member của Phòng, hoặc
    - leader của Nhóm trực thuộc một Phòng (lấy Phòng cha).
    Trả về name Phòng đầu tiên khớp (mặc định)."""
    email = email or _session_email()
    # 1) Leader của Phòng (giữ tương thích _user_led_unit)
    led = _user_led_unit(email)
    if led:
        return led
    dept_type = _department_unit_type()
    if not dept_type:
        return None
    # 2) Member của Phòng
    rows = frappe.db.sql(
        """
        SELECT u.name
        FROM `tabERP Organization Unit Member` m
        INNER JOIN `tabERP Organization Unit` u ON m.parent = u.name
        WHERE m.user = %(user)s AND u.unit_type = %(dept_type)s AND u.is_active = 1
        LIMIT 1
        """,
        {"user": email, "dept_type": dept_type},
        as_dict=True,
    )
    if rows:
        return rows[0].name
    # 3) Leader của Nhóm trực thuộc -> Phòng cha
    rows = frappe.db.sql(
        """
        SELECT p.name
        FROM `tabERP Organization Unit Leader` l
        INNER JOIN `tabERP Organization Unit` u ON l.parent = u.name
        INNER JOIN `tabERP Organization Unit` p ON u.parent_organization_unit = p.name
        WHERE l.user = %(user)s AND p.unit_type = %(dept_type)s AND p.is_active = 1
        LIMIT 1
        """,
        {"user": email, "dept_type": dept_type},
        as_dict=True,
    )
    return rows[0].name if rows else None


def _user_managed_units(email=None):
    """Tất cả Phòng (cấp Phòng) mà user được lập ngân sách:
    leader/member của Phòng, hoặc leader của Nhóm trực thuộc Phòng.
    Trả về danh sách name Phòng (không trùng), giữ thứ tự xuất hiện."""
    email = email or _session_email()
    dept_type = _department_unit_type()
    if not dept_type:
        return []
    rows = frappe.db.sql(
        """
        SELECT u.name FROM `tabERP Organization Unit Leader` l
        INNER JOIN `tabERP Organization Unit` u ON l.parent = u.name
        WHERE l.user = %(user)s AND u.unit_type = %(dept_type)s AND u.is_active = 1
        UNION
        SELECT u.name FROM `tabERP Organization Unit Member` m
        INNER JOIN `tabERP Organization Unit` u ON m.parent = u.name
        WHERE m.user = %(user)s AND u.unit_type = %(dept_type)s AND u.is_active = 1
        UNION
        SELECT p.name FROM `tabERP Organization Unit Leader` l
        INNER JOIN `tabERP Organization Unit` u ON l.parent = u.name
        INNER JOIN `tabERP Organization Unit` p ON u.parent_organization_unit = p.name
        WHERE l.user = %(user)s AND p.unit_type = %(dept_type)s AND p.is_active = 1
        """,
        {"user": email, "dept_type": dept_type},
        as_dict=True,
    )
    seen = []
    for r in rows:
        if r.name not in seen:
            seen.append(r.name)
    return seen


def _is_head_of(department, email=None):
    """Kiểm tra user có phải lãnh đạo của department cụ thể không."""
    if not department:
        return False
    email = email or _session_email()
    return bool(
        frappe.db.exists(
            ORG_UNIT_LEADER_DT,
            {"parent": department, "parenttype": ORG_UNIT_DT, "user": email},
        )
    )


def _is_member_or_leader_of(department, email=None):
    """User là leader HOẶC member (child table) của đơn vị department."""
    if not department:
        return False
    email = email or _session_email()
    if frappe.db.exists(
        ORG_UNIT_LEADER_DT,
        {"parent": department, "parenttype": ORG_UNIT_DT, "user": email},
    ):
        return True
    return bool(
        frappe.db.exists(
            ORG_UNIT_MEMBER_DT,
            {"parent": department, "parenttype": ORG_UNIT_DT, "user": email},
        )
    )


def _is_subgroup_leader_of(department, email=None):
    """User là leader của một đơn vị con (Nhóm) trực thuộc department."""
    if not department:
        return False
    email = email or _session_email()
    rows = frappe.db.sql(
        """
        SELECT 1
        FROM `tabERP Organization Unit Leader` l
        INNER JOIN `tabERP Organization Unit` u ON l.parent = u.name
        WHERE l.user = %(user)s
          AND u.parent_organization_unit = %(dept)s
          AND u.is_active = 1
        LIMIT 1
        """,
        {"user": email, "dept": department},
        as_dict=True,
    )
    return bool(rows)


def _can_edit_plan_dept(department, email=None):
    """Quyền TẠO/SỬA nháp ngân sách của phòng:
    leader/member của phòng + leader nhóm trực thuộc (+ System Manager).
    SIS Finance KHÔNG được sửa (chỉ xem + trả về)."""
    email = email or _session_email()
    if "System Manager" in frappe.get_roles(email):
        return True
    return _is_member_or_leader_of(department, email) or _is_subgroup_leader_of(department, email)


def _is_first_leader(department, email=None):
    """User là lãnh đạo ĐỨNG ĐẦU (sort_order nhỏ nhất) của phòng — người duy nhất được nộp."""
    if not department:
        return False
    email = email or _session_email()
    first = _first_department_leader(department)
    return bool(first and first.get("user") == email)


def _unit_name(unit):
    if not unit:
        return None
    return frappe.db.get_value(ORG_UNIT_DT, unit, "unit_name_vn")


def _first_department_leader(department):
    """Lãnh đạo đầu tiên (sort_order) của phòng ban — dùng hiển thị bước phòng ban."""
    if not department:
        return None
    rows = frappe.get_all(
        ORG_UNIT_LEADER_DT,
        filters={"parent": department, "parenttype": ORG_UNIT_DT},
        fields=["user", "full_name", "sort_order"],
        order_by="sort_order asc, idx asc",
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "user": row.user,
        "full_name": row.full_name or row.user,
    }


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


# 12 tháng ngân sách theo năm tài chính: T7 năm nay -> T6 năm sau (thứ tự hiển thị)
MONTH_FIELDS = ["m7", "m8", "m9", "m10", "m11", "m12", "m1", "m2", "m3", "m4", "m5", "m6"]

# Nhãn tháng cho lịch sử thay đổi (m7 -> "T7")
MONTH_LABELS = {m: f"T{m[1:]}" for m in MONTH_FIELDS}


# ---------------------------------------------------------------------------
# Luồng duyệt CỐ ĐỊNH (không cấu hình): Phòng ban -> TC (CFO) -> COO -> CEO
#
# Mỗi bước:
#   - approver_role: vai trò DUYỆT (tiến bước).
#   - return_roles : vai trò được XEM + TRẢ VỀ (rộng hơn approve).
# Bước Phòng Tài chính: CHỈ CFO duyệt; SIS Finance được xem + trả về.
# ---------------------------------------------------------------------------

PLAN_STEPS = [
    {
        "step_order": 1,
        "approver_role": "CFO",
        "return_roles": ("SIS Finance", "CFO"),
        "label": "Phòng Tài chính",
    },
    {"step_order": 2, "approver_role": "COO", "return_roles": ("COO",), "label": "COO"},
    {"step_order": 3, "approver_role": "CEO", "return_roles": ("CEO",), "label": "CEO"},
]


def _plan_steps():
    """Luồng duyệt cố định Phòng ban -> TC (CFO) -> COO -> CEO."""
    return PLAN_STEPS


def _parse_line_attachments(value):
    """Parse danh sách URL đính kèm — hỗ trợ JSON array hoặc 1 URL legacy (Attach cũ)."""
    if not value:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [v for v in parsed if isinstance(v, str) and v.strip()]
            except (ValueError, TypeError):
                pass
        return [raw]
    return []


def _serialize_line_attachments(urls):
    """Lưu danh sách URL đính kèm vào field attachment (Long Text JSON)."""
    cleaned = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
    return json.dumps(cleaned) if cleaned else None


def _line_attachments_from_payload(line):
    """Lấy attachments từ payload API — ưu tiên mảng attachments, fallback attachment đơn."""
    if not isinstance(line, dict):
        return []
    if line.get("attachments") is not None:
        return _parse_line_attachments(line.get("attachments"))
    if line.get("attachment") is not None:
        return _parse_line_attachments(line.get("attachment"))
    return []


# ---------------------------------------------------------------------------
# Lịch sử thay đổi dòng — diff "từ giá trị nào sang giá trị nào"
# ---------------------------------------------------------------------------

def _fmt_amount(value):
    """Định dạng số tiền kiểu vi-VN (dấu . ngăn ngàn) cho lịch sử."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0
    if n == int(n):
        return f"{int(n):,}".replace(",", ".")
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _plan_line_snapshot(doc):
    """Ảnh chụp các dòng để so sánh: {budget_code: {m7..m6, note, explanation}}."""
    snap = {}
    for l in (doc.lines or []):
        if not l.budget_code:
            continue
        snap[l.budget_code] = {
            **{m: float(l.get(m) or 0) for m in MONTH_FIELDS},
            "note": (l.note or "").strip(),
            "overrun_explanation": (l.overrun_explanation or "").strip(),
            "explanation": (l.explanation or "").strip(),
        }
    return snap


def _line_total(row):
    return sum(row.get(m, 0) for m in MONTH_FIELDS)


def _diff_line_snapshots(old, new):
    """So sánh 2 snapshot -> chuỗi mô tả thay đổi (mỗi thay đổi 1 dòng)."""
    old = old or {}
    new = new or {}
    changes = []
    for code in old:
        if code not in new:
            changes.append(f"• Bỏ mã {code} (tổng cũ {_fmt_amount(_line_total(old[code]))})")
    for code, new_row in new.items():
        if code not in old:
            changes.append(f"• Thêm mã {code} (tổng {_fmt_amount(_line_total(new_row))})")
            continue
        old_row = old[code]
        parts = []
        for m in MONTH_FIELDS:
            ov, nv = old_row.get(m, 0), new_row.get(m, 0)
            if ov != nv:
                parts.append(f"{MONTH_LABELS[m]}: {_fmt_amount(ov)}→{_fmt_amount(nv)}")
        if old_row.get("note", "") != new_row.get("note", ""):
            parts.append("sửa ghi chú")
        if old_row.get("overrun_explanation", "") != new_row.get("overrun_explanation", ""):
            parts.append("sửa giải trình vượt KH")
        if old_row.get("explanation", "") != new_row.get("explanation", ""):
            parts.append("sửa diễn giải")
        if parts:
            changes.append(f"• {code}: " + "; ".join(parts))
    return "\n".join(changes)


def _can_approve_step(steps, current_step, email=None):
    """User có quyền DUYỆT (tiến bước) current_step không — theo approver_role."""
    email = email or _session_email()
    if current_step < 1 or current_step > len(steps):
        return False
    step = steps[current_step - 1]
    role = step.get("approver_role")
    if not role:
        return True
    return role in frappe.get_roles(email)


def _can_return_step(steps, current_step, email=None):
    """User có quyền TRẢ VỀ current_step không — theo return_roles (rộng hơn approve).
    Vd bước Phòng TC: cả SIS Finance lẫn CFO được trả về."""
    email = email or _session_email()
    if current_step < 1 or current_step > len(steps):
        return False
    step = steps[current_step - 1]
    roles = step.get("return_roles")
    if not roles:
        role = step.get("approver_role")
        roles = (role,) if role else ()
    if not roles:
        return True
    user_roles = set(frappe.get_roles(email))
    return any(r in user_roles for r in roles)


def _approver_steps_for_user(email=None):
    """Các bước mà user được DUYỆT."""
    email = email or _session_email()
    steps = _plan_steps()
    return [s["step_order"] for s in steps if _can_approve_step(steps, s["step_order"], email)]


def _actionable_steps_for_user(email=None):
    """Các bước user có thể XỬ LÝ (duyệt HOẶC trả về) — dùng cho hàng chờ."""
    email = email or _session_email()
    steps = _plan_steps()
    return [
        s["step_order"]
        for s in steps
        if _can_approve_step(steps, s["step_order"], email)
        or _can_return_step(steps, s["step_order"], email)
    ]


def _school_year_title(sy_id):
    """Tên hiển thị năm học — ưu tiên title_vn."""
    if not sy_id:
        return ""
    return (
        frappe.db.get_value(SCHOOL_YEAR_DT, sy_id, "title_vn")
        or frappe.db.get_value(SCHOOL_YEAR_DT, sy_id, "title_en")
        or sy_id
    )


def _period_school_year_id(period_name):
    if not period_name:
        return None
    return frappe.db.get_value(PERIOD_DT, period_name, "school_year_id")


def _previous_school_year_id(school_year_id):
    """Năm học liền trước — suy ra theo start_date (không cần field quan hệ)."""
    if not school_year_id:
        return None
    start_date = frappe.db.get_value(SCHOOL_YEAR_DT, school_year_id, "start_date")
    if not start_date:
        return None
    rows = frappe.get_all(
        SCHOOL_YEAR_DT,
        filters={"start_date": ("<", start_date)},
        pluck="name",
        order_by="start_date desc",
        limit=1,
    )
    return rows[0] if rows else None


def _settlement_amounts(school_year_id, department):
    """{budget_code: số tổng kết} của 1 năm học × phòng ban. Cộng dồn nếu trùng mã."""
    result = {}
    if not school_year_id or not department:
        return result
    rows = frappe.get_all(
        SETTLEMENT_DT,
        filters={"school_year_id": school_year_id, "department": department},
        fields=["budget_code", "settlement_amount"],
        ignore_permissions=True,
    )
    for r in rows:
        code = r.get("budget_code")
        if not code:
            continue
        result[code] = (result.get(code) or 0) + (r.get("settlement_amount") or 0)
    return result


def _applicable_leaf_codes(department):
    """Danh sách mã lá active áp dụng cho 1 phòng — dùng seed snapshot lúc tạo bản."""
    if not department:
        return []
    parents = frappe.get_all(CODE_DEPT_DT, filters={"department": department}, pluck="parent")
    if not parents:
        return []
    return frappe.get_all(
        CODE_DT,
        filters={"name": ("in", parents), "is_active": 1, "is_group": 0},
        pluck="name",
    )


def _plan_display_title(doc):
    """Tiêu đề hiển thị — dùng tên năm học, không dùng mã SIS School Year."""
    sy_id = _period_school_year_id(doc.period)
    sy_title = _school_year_title(sy_id)
    dept = doc.department_name or _unit_name(doc.department)
    if sy_title:
        return f"Ngân sách {sy_title} - {dept}".strip()
    return (doc.title or doc.name or "").strip()


def _can_read_plan(doc, email=None):
    """Quyền đọc chi tiết ngân sách.

    - System Manager: xem mọi thứ (kể cả nháp).
    - Phòng của plan (leader/member/leader nhóm): xem MỌI trạng thái của phòng mình,
      kể cả nháp chưa nộp (đó là bản nháp của chính họ).
    - Sau bước phòng ban (Phòng TC, CFO/COO/CEO, BOD): xem mọi ngân sách ĐÃ TỪNG NỘP
      (workflow_state != "Draft"). KHÔNG xem nháp chưa từng submit của phòng khác.
    """
    email = email or _session_email()
    if "System Manager" in frappe.get_roles(email):
        return True
    if _can_edit_plan_dept(doc.department, email):
        return True
    if _is_finance() or _is_bod() or _is_plan_approver_role(email):
        return doc.workflow_state != "Draft"
    return False
