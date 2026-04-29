"""
CRM Issue API - Van de chung (tuyen sinh): module, SLA, duyet, PIC tu CRM Lead
"""

import frappe
from frappe.utils import now, add_to_date, get_datetime, getdate
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import ALLOWED_ROLES, check_crm_permission, get_request_data

# Role Care duoc tao issue truc tiep (khong qua hang cho)
DIRECT_ISSUE_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
    }
)

# Team Care duoc duyet & tu choi (dong bo frontend IssueDetail)
APPROVER_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
    }
)

# User co the duoc gan lam PIC; tach khoi DIRECT_ISSUE_ROLES de Sales van co the xu ly issue.
PIC_ELIGIBLE_ROLES = frozenset(
    {
        "SIS Sales",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)

CARE_ADMIN_ROLES = frozenset({"SIS Sales Care Admin"})
VALID_ISSUE_RESULTS = frozenset({"Hai long", "Chua hai long"})

# Role duoc ghi / xu ly van de (dong bo frontend canWriteIssue; SM tuong duong Sales Admin trong module)
ISSUE_WRITE_ROLES = frozenset(
    {
        "SIS Sales",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
        "SIS BOD",
        "System Manager",
    }
)

# Chi nhom Sales doi trang thai / ket qua xu ly (sidebar Issue Detail — dong bo frontend)
ISSUE_STATUS_SALES_ROLES = frozenset(
    {
        "SIS Sales",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)

# Doi PIC: System Manager + hai Admin Sales (dong bo mobile PIC_CHANGE_ROLES)
PIC_CHANGE_ROLES = frozenset(
    {
        "System Manager",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)

# Role bo sung cho API get_issues (dong bo mobile hasCrmAccess — Campus + extra)
CRM_ISSUE_LIST_EXTRA_ROLES = frozenset(
    {
        "SIS Teacher",
        "SIS Marcom",
        "SIS Administrative",
        "SIS IT",
        "SIS User",
        "SIS Library",
        "SIS AI Manager",
        "SIS Supervisory",
        "SIS Supervisory Admin",
    }
)

# Viền log (sales): khong gom SIS BOD — user vua BOD vua Sales hoac vua phong ban luon dung accent bod
LOG_ACCENT_SALES_ROLES = frozenset(
    {
        "SIS Sales",
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
        "System Manager",
    }
)

# Con lai <= 20% thoi gian SLA -> Warning (dong bo scheduler + UI)
WARNING_THRESHOLD = 0.2
# San canh bao toi thieu (giay): SLA ngan + cron thua tranh bo lo Warning (dong bo scheduler)
MIN_WARNING_SECONDS = 30 * 60


def _warning_seconds_before_deadline(total_seconds: float) -> float:
    """Thoi luong truoc deadline ma coi la Warning: max(20% cua cua so, san toi thieu, khong qua 50% cua so)."""
    if total_seconds <= 0:
        return MIN_WARNING_SECONDS
    ratio_part = total_seconds * WARNING_THRESHOLD
    capped_floor = min(MIN_WARNING_SECONDS, total_seconds * 0.5)
    return max(ratio_part, capped_floor)


def _compute_sla_status_from_values(sla_started_at, sla_deadline, first_response_at):
    """
    Passed / On track / Warning / Breached — logic thuan (dung scheduler + _recompute_sla_state).
    """
    if first_response_at:
        return "Passed"
    if not sla_deadline or not sla_started_at:
        return "On track"
    try:
        total = (get_datetime(sla_deadline) - get_datetime(sla_started_at)).total_seconds()
        remaining = (get_datetime(sla_deadline) - get_datetime(now())).total_seconds()
    except Exception:
        return "On track"
    if remaining <= 0:
        return "Breached"
    if total > 0:
        w_before = _warning_seconds_before_deadline(total)
        if remaining <= w_before:
            return "Warning"
    return "On track"


def _recompute_sla_state(doc):
    """Xac dinh sla_status dua tren first_response_at, sla_deadline, now."""
    st = _compute_sla_status_from_values(
        getattr(doc, "sla_started_at", None),
        getattr(doc, "sla_deadline", None),
        getattr(doc, "first_response_at", None),
    )
    doc.sla_status = st
    return st


def _first_pic_log_timestamp(doc):
    """Thoi diem logged_at som nhat trong cac dong log do PIC ghi (logged_by == pic)."""
    pic = (getattr(doc, "pic", None) or "").strip()
    if not pic:
        return None
    logs = getattr(doc, "process_logs", None) or []
    if not logs:
        return None
    candidates = []
    for row in logs:
        lb = (getattr(row, "logged_by", None) or "").strip()
        if lb != pic:
            continue
        la = getattr(row, "logged_at", None)
        if la:
            try:
                candidates.append(get_datetime(la))
            except Exception:
                continue
    if not candidates:
        return None
    return min(candidates)


def _mark_first_response_if_eligible(doc):
    """Pass SLA: trang thai 'Dang xu ly' + it nhat mot log do PIC ghi (logged_by == pic)."""
    if getattr(doc, "first_response_at", None):
        return
    if (getattr(doc, "status", None) or "").strip() != "Dang xu ly":
        return
    ts = _first_pic_log_timestamp(doc)
    if not ts:
        return
    doc.first_response_at = ts
    doc.sla_status = "Passed"


def _can_write_issue_ops(user: str, issue_doc) -> bool:
    """User duoc chinh sua van de (sau check_crm_permission): role ISSUE_WRITE_ROLES hoac thanh vien mot phong ban lien quan."""
    if not user or user == "Guest":
        return False
    roles = set(frappe.get_roles(user))
    if ISSUE_WRITE_ROLES & roles:
        return True
    for dn in _issue_department_docnames(issue_doc):
        if dn and user in _department_member_emails(dn):
            return True
    return False


def _can_change_issue_status_sales(user: str) -> bool:
    """Chi role Sales (4 role) moi doi status/result xu ly — khong BOD/SM/phong ban."""
    if not user or user == "Guest":
        return False
    return bool(ISSUE_STATUS_SALES_ROLES & set(frappe.get_roles(user)))


def _can_care_admin(user: str = None) -> bool:
    """Care Admin xac nhan dong issue hoac tra lai PIC xu ly tiep."""
    u = user or frappe.session.user
    if not u or u == "Guest":
        return False
    roles = _session_roles_current() if u == frappe.session.user else set(frappe.get_roles(u))
    return bool(CARE_ADMIN_ROLES & roles or "System Manager" in roles or u == "Administrator")


def _is_issue_pic(user: str, issue_doc) -> bool:
    """PIC hien tai cua issue."""
    return bool(user and user != "Guest" and (getattr(issue_doc, "pic", "") or "").strip() == user)


def _normalize_issue_date(value):
    """Nhan date/datetime/string va tra YYYY-MM-DD cho field Date."""
    if not value:
        return str(getdate(now()))
    try:
        return str(getdate(value))
    except Exception:
        return str(value)[:10]


def _get_user_crm_issue_department_names(user: str):
    """Docname CRM Issue Department ma user la thanh vien."""
    if not user or user == "Guest":
        return []
    rows = frappe.db.sql(
        """
        SELECT DISTINCT parent FROM `tabCRM Issue Dept Member`
        WHERE user = %(u)s
        """,
        {"u": user},
    )
    return [r[0] for r in rows] if rows else []


def _can_access_crm_issue_list() -> bool:
    """Mo rong hon check_crm_permission: Campus *, CRM core, extra roles (dong bo mobile hasCrmAccess)."""
    u = frappe.session.user
    if not u or u == "Guest":
        return False
    roles = set(frappe.get_roles(u))
    if any(x.startswith("Campus ") for x in roles):
        return True
    if any(role in roles for role in ALLOWED_ROLES):
        return True
    if CRM_ISSUE_LIST_EXTRA_ROLES & roles:
        return True
    return False


def _compute_log_accent(logged_by: str, issue_doc) -> str:
    """Mau viền log: luon uu tien SIS BOD neu co (ke ca dong thoi Sales hoac thanh vien phong ban), roi sales/SM, roi dept."""
    if not logged_by:
        return "neutral"
    roles = set(frappe.get_roles(logged_by))
    if "SIS BOD" in roles:
        return "bod"
    if LOG_ACCENT_SALES_ROLES & roles:
        return "sales"
    for dn in _issue_department_docnames(issue_doc):
        if dn and logged_by in _department_member_emails(dn):
            return "dept"
    return "neutral"


def _compute_log_source_label(logged_by: str, issue_doc) -> str:
    """
    Nhan hien thi canh ten nguoi ghi log (tab Qua trinh xu ly).
    Uu tien: SIS BOD -> Ban lanh dao; Sales/SM -> Phong tuyen sinh; thanh vien phong ban issue -> department_name.
    """
    if not logged_by:
        return ""
    roles = set(frappe.get_roles(logged_by))
    if "SIS BOD" in roles:
        return "Ban lãnh đạo"
    if LOG_ACCENT_SALES_ROLES & roles:
        return "Phòng tuyển sinh"
    for dn in _issue_department_docnames(issue_doc):
        if dn and logged_by in _department_member_emails(dn):
            dn_name = frappe.db.get_value("CRM Issue Department", dn, "department_name")
            return ((dn_name or "").strip() or dn)
    return ""


def _enrich_process_logs_accent(data: dict, issue_doc):
    """Gan log_accent + log_source_label cho moi dong process_logs (API get_issue / update)."""
    if not isinstance(data, dict):
        return
    logs = data.get("process_logs") or []
    for row in logs:
        if not isinstance(row, dict):
            continue
        lb = (row.get("logged_by") or "").strip()
        row["log_accent"] = _compute_log_accent(lb, issue_doc)
        row["log_source_label"] = _compute_log_source_label(lb, issue_doc)


def _finalize_issue_api_dict(doc):
    """as_dict + enrich user + issue_students + log_accent (tra ve client)."""
    data = doc.as_dict()
    _enrich_user_info([data])
    _enrich_issue_students_display(data)
    _enrich_process_logs_accent(data, doc)
    # Quyen theo session thuc te (tranh lech JWT/Has Role o frontend)
    u = frappe.session.user
    if u and u != "Guest":
        ap = (getattr(doc, "approval_status", None) or "").strip()
        st = (getattr(doc, "status", None) or "").strip()
        src_fb = (getattr(doc, "source_feedback", None) or "").strip()
        data["can_approve_reject"] = bool(_can_approve())
        data["can_write_issue"] = bool(_can_write_issue_ops(u, doc))
        data["can_edit_sales_status"] = bool(
            ap == "Da duyet"
            and st != "Dong"
            and (_is_issue_pic(u, doc) or _can_care_admin(u) or _can_change_issue_status_sales(u))
        )
        roles = _session_roles_current()
        can_pic_role = bool(PIC_CHANGE_ROLES & roles)
        data["can_change_pic"] = bool(can_pic_role and ap == "Da duyet")
        data["can_change_department"] = bool(_can_write_issue_ops(u, doc) and ap == "Da duyet")
        data["can_add_process_log"] = bool(
            (_is_issue_pic(u, doc) or _can_write_issue_ops(u, doc)) and ap == "Da duyet" and st == "Dang xu ly"
        )
        data["can_edit_process_log"] = bool(_can_care_admin(u) and ap == "Da duyet" and st != "Dong")
        data["can_reply_parent"] = bool(
            _can_change_issue_status_sales(u)
            and bool(src_fb)
            and ap == "Da duyet"
            and st not in ("Hoan thanh", "Dong")
        )
    else:
        data["can_approve_reject"] = False
        data["can_write_issue"] = False
        data["can_edit_sales_status"] = False
        data["can_change_pic"] = False
        data["can_change_department"] = False
        data["can_add_process_log"] = False
        data["can_edit_process_log"] = False
        data["can_reply_parent"] = False
    return data


def _notify_crm_issue_mobile(users, title, body, issue_doc, notif_type, exclude_user=None):
    """
    Push Expo + ERP Notification (trung tam thong bao mobile / notification_center).
    Dong bo payload voi workspace-mobile (issueId / issue_id, type crm_issue_*).
    """
    try:
        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification_persisted
    except Exception as e:
        frappe.logger().warning(f"CRM Issue: khong import send_mobile_notification_persisted: {e}")
        return

    payload = {
        "type": notif_type,
        "issueId": issue_doc.name,
        "issue_id": issue_doc.name,
        "issueCode": (issue_doc.issue_code or ""),
    }

    seen = set()
    for email in users or []:
        if not email or email in ("Guest",) or email == exclude_user:
            continue
        if email in seen:
            continue
        seen.add(email)
        try:
            send_mobile_notification_persisted(
                user_email=email,
                title=title,
                body=body,
                data=payload,
                erp_notification_type="system",
                reference_doctype="CRM Issue",
                reference_name=issue_doc.name,
            )
        except Exception as ex:
            frappe.logger().error(f"CRM Issue push notify failed for {email}: {ex}")


def _approver_emails():
    """User co role duyet van de, chi user enabled."""
    roles = list(APPROVER_ROLES)
    rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", roles], "parenttype": "User"},
        pluck="parent",
    )
    if not rows:
        return []
    enabled = frappe.get_all(
        "User",
        filters={"name": ["in", list(set(rows))], "enabled": 1},
        pluck="name",
    )
    return list(set(enabled or []))


def _care_admin_emails():
    """User Care Admin nhan thong bao can xac nhan issue hoan thanh."""
    rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", list(CARE_ADMIN_ROLES)], "parenttype": "User"},
        pluck="parent",
    )
    if not rows:
        return []
    enabled = frappe.get_all(
        "User",
        filters={"name": ["in", list(set(rows))], "enabled": 1},
        pluck="name",
    )
    return list(set(enabled or []))


def _department_member_emails(department_name):
    """Email thanh vien phong ban CRM Issue."""
    if not department_name or not frappe.db.exists("CRM Issue Department", department_name):
        return []
    dept = frappe.get_doc("CRM Issue Department", department_name)
    return [m.user for m in (dept.members or [])]


def _department_manager_emails(department_name):
    """Email manager cua phong ban CRM Issue."""
    if not department_name or not frappe.db.exists("CRM Issue Department", department_name):
        return []
    dept = frappe.get_doc("CRM Issue Department", department_name)
    return [m.user for m in (dept.members or []) if getattr(m, "is_manager", 0)]


def _issue_department_docnames(issue_doc):
    """Docname CRM Issue Department: uu tien bang issue_departments, fallback cot department."""
    names = []
    rows = getattr(issue_doc, "issue_departments", None) or []
    for row in rows:
        d = (getattr(row, "department", None) or "").strip()
        if d and d not in names:
            names.append(d)
    if not names:
        dept = (getattr(issue_doc, "department", None) or "").strip()
        if dept:
            names.append(dept)
    return names


def _all_department_member_emails_for_issue(issue_doc):
    """Union email thanh vien cua tat ca phong ban lien quan (dedupe)."""
    seen = set()
    out = []
    for dn in _issue_department_docnames(issue_doc):
        for e in _department_member_emails(dn):
            if e and e not in seen:
                seen.add(e)
                out.append(e)
    return out


def _all_department_manager_emails_for_issue(issue_doc):
    """Union email manager cua tat ca phong ban lien quan."""
    seen = set()
    out = []
    for dn in _issue_department_docnames(issue_doc):
        for e in _department_manager_emails(dn):
            if e and e not in seen:
                seen.add(e)
                out.append(e)
    return out


def _issue_names_matching_department(dept_name):
    """CRM Issue co department=dept_name hoac co dong child trung dept_name."""
    if not dept_name:
        return []
    n1 = frappe.get_all("CRM Issue", filters={"department": dept_name}, pluck="name")
    n2 = frappe.get_all(
        "CRM Issue Related Department",
        filters={"department": dept_name, "parenttype": "CRM Issue"},
        pluck="parent",
    )
    return list(set(n1 or []) | set(n2 or []))


def _issue_names_visible_to_department_members(dept_docnames):
    """Issue ma user (thuoc mot trong cac phong ban dept_docnames) co lien quan."""
    if not dept_docnames:
        return []
    n1 = frappe.get_all("CRM Issue", filters={"department": ["in", list(dept_docnames)]}, pluck="name")
    n2 = frappe.get_all(
        "CRM Issue Related Department",
        filters={"department": ["in", list(dept_docnames)], "parenttype": "CRM Issue"},
        pluck="parent",
    )
    return list(set(n1 or []) | set(n2 or []))


def _sync_issue_departments(doc, data):
    """
    Dong bo bang con issue_departments + cot department (phan tu dau).
    Payload: departments: list docname CRM Issue Department.
    """
    if "departments" not in data:
        return
    ids = []
    for x in data.get("departments") or []:
        sid = (x or "").strip() if isinstance(x, str) else ""
        if sid and frappe.db.exists("CRM Issue Department", sid) and sid not in ids:
            ids.append(sid)
    doc.issue_departments = []
    for sid in ids:
        doc.append("issue_departments", {"department": sid})
    doc.department = ids[0] if ids else ""


def _enrich_issue_list_departments(issues):
    """Gan departments: [docname,...] cho danh sach issue (list API)."""
    if not issues:
        return
    names = [r.get("name") for r in issues if r.get("name")]
    if not names:
        return
    rows = frappe.get_all(
        "CRM Issue Related Department",
        filters={"parent": ["in", names], "parenttype": "CRM Issue"},
        fields=["parent", "department", "idx"],
    )
    rows = sorted(rows or [], key=lambda r: ((r.parent or ""), r.idx or 0))
    by_parent = {}
    for r in rows or []:
        p = r.parent
        d = (r.department or "").strip()
        if not d:
            continue
        if p not in by_parent:
            by_parent[p] = []
        if d not in by_parent[p]:
            by_parent[p].append(d)
    for r in issues:
        depts = by_parent.get(r.get("name")) or []
        if not depts and r.get("department"):
            depts = [r["department"]]
        r["departments"] = depts


def _user_roles():
    return set(frappe.get_roles(frappe.session.user))


def _session_roles_current():
    """
    Role cua user hien tai sau khi xoa cache Redis (frappe.permissions.get_roles cache theo key 'roles').
    Neu chi gan SIS Sales Admin trong Frappe ma chua dang nhap lai, cache cu co the thieu role -> duyet that bai.
    Cong them role tu Role Profile (neu User co role_profile_name nhung chua Save de dong bo Has Role).
    """
    u = frappe.session.user
    if not u or u == "Guest":
        return set()
    try:
        frappe.cache.hdel("roles", u)
    except Exception:
        pass
    r = set(frappe.get_roles(u))
    rp_name = frappe.db.get_value("User", u, "role_profile_name")
    if rp_name and frappe.db.exists("Role Profile", rp_name):
        try:
            rp_doc = frappe.get_doc("Role Profile", rp_name)
            for row in rp_doc.roles or []:
                role = getattr(row, "role", None)
                if role:
                    r.add(role)
        except Exception:
            pass
    return r


def _can_create_directly():
    return bool(DIRECT_ISSUE_ROLES & _user_roles())


def _is_valid_pic_user(pic_email: str) -> bool:
    """PIC hop le: user ton tai va co it nhat mot role xu ly (dong bo get_issue_pic_candidates)."""
    if not pic_email or not frappe.db.exists("User", pic_email):
        return False
    return bool(PIC_ELIGIBLE_ROLES & set(frappe.get_roles(pic_email)))


def _can_approve():
    """Duyet/tu choi: APPROVER_ROLES + System Manager / Administrator (van hanh Frappe)."""
    r = _session_roles_current()
    if APPROVER_ROLES & r:
        return True
    if "System Manager" in r or "Administrator" in r:
        return True
    return False


def _generate_issue_code(prefix: str) -> str:
    """Sinh ma PREFIX-00001 theo prefix module (VD: KL)."""
    p = (prefix or "X").strip().upper()
    rows = frappe.db.sql(
        """
        SELECT issue_code FROM `tabCRM Issue`
        WHERE issue_code LIKE %(pat)s
        """,
        {"pat": f"{p}-%"},
        as_dict=True,
    )
    max_n = 0
    for row in rows or []:
        c = (row.get("issue_code") or "").strip()
        parts = c.split("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            max_n = max(max_n, int(parts[1]))
    return f"{p}-{max_n + 1:05d}"


def _pic_from_student(student_id: str):
    """Lay PIC tu CRM Lead co linked_student = student."""
    if not student_id:
        return None
    pic = frappe.db.get_value("CRM Lead", {"linked_student": student_id}, "pic")
    return pic or None


def _pic_from_department(dept_name: str):
    """Lay user dau tien trong phong ban lam PIC mac dinh."""
    if not dept_name or not frappe.db.exists("CRM Issue Department", dept_name):
        return None
    doc = frappe.get_doc("CRM Issue Department", dept_name)
    if doc.members and len(doc.members) > 0:
        return doc.members[0].user
    return None


def _pic_from_module(module_name: str):
    """Lay user dau tien trong bang thanh vien CRM Issue Module (uu tien PIC tu loai van de)."""
    if not module_name or not frappe.db.exists("CRM Issue Module", module_name):
        return None
    doc = frappe.get_doc("CRM Issue Module", module_name)
    if doc.members and len(doc.members) > 0:
        return doc.members[0].user
    return None


def _assign_pic_from_issue_context(doc):
    """
    Gan PIC theo Loai van de -> Lead hoc sinh -> phong ban (dong bo create_issue).
    Goi sau khi issue_module / hoc sinh / phong ban da dong bo len doc.
    """
    module_name = (getattr(doc, "issue_module", None) or "").strip()
    if not module_name:
        return
    pic = _pic_from_module(module_name) or ""
    if not pic and getattr(doc, "student", None):
        pic = _pic_from_student(doc.student) or ""
    if not pic:
        for dn in _issue_department_docnames(doc):
            pic = _pic_from_department(dn) or ""
            if pic:
                break
    doc.pic = pic


def _sync_issue_students(doc, data):
    """
    Dong bo bang con issue_students + truong student (hoc sinh dau tien, tuong thich PIC/legacy).
    - Neu co khoa students (list): dung lam nguon that.
    - Neu khong: dung student (mot hoc sinh) nhu truoc.
    """
    if "students" in data:
        ids = []
        for x in data.get("students") or []:
            sid = (x or "").strip() if isinstance(x, str) else ""
            if sid and frappe.db.exists("CRM Student", sid) and sid not in ids:
                ids.append(sid)
        doc.issue_students = []
        for sid in ids:
            doc.append("issue_students", {"student": sid})
        doc.student = ids[0] if ids else ""
        return
    st = (data.get("student") or "").strip()
    doc.issue_students = []
    if st and frappe.db.exists("CRM Student", st):
        doc.append("issue_students", {"student": st})
    doc.student = st


def _normalize_vn_name(full_name):
    """Tra ve full_name nguyen ban tu User (Frappe da luu dung thu tu, khong reorder)."""
    if not full_name:
        return ""
    return (full_name or "").strip()


def _enrich_user_info(issues):
    """Them pic_full_name, pic_user_image, created_by_name, approved_by_name, rejected_by_name vao danh sach issues"""
    emails = set()
    for r in issues:
        _get = r.get if isinstance(r, dict) else lambda k, d=None: getattr(r, k, d)
        if _get("pic"):
            emails.add(_get("pic"))
        # created_by_user co the trong (ban ghi cu); owner la nguoi tao chuan Frappe
        creator_id = (_get("created_by_user") or _get("owner") or "").strip()
        if creator_id:
            emails.add(creator_id)
        ab = (_get("approved_by_user") or "").strip()
        if ab:
            emails.add(ab)
        rb = (_get("rejected_by_user") or "").strip()
        if rb:
            emails.add(rb)
    if not emails:
        return
    users = {
        u.name: u
        for u in frappe.get_all(
            "User",
            filters={"name": ["in", list(emails)]},
            fields=["name", "full_name", "user_image", "job_title"],
        )
    }
    for r in issues:
        is_dict = isinstance(r, dict)
        _get = r.get if is_dict else lambda k, d=None: getattr(r, k, d)

        pic_u = users.get(_get("pic") or "")
        pic_name = _normalize_vn_name(pic_u.full_name) if pic_u else ""
        creator_key = (_get("created_by_user") or _get("owner") or "").strip()
        creator_u = users.get(creator_key) if creator_key else None
        creator_name = _normalize_vn_name(creator_u.full_name) if creator_u else ""
        creator_img = (creator_u.user_image if creator_u else "") or ""
        creator_title = (creator_u.job_title if creator_u else "") or ""
        # Batch get_all doi khi khong khop — tra truc tiep User
        if creator_key and not creator_name:
            row_u = frappe.db.get_value(
                "User",
                creator_key,
                ["full_name", "user_image", "job_title"],
                as_dict=True,
            )
            if row_u:
                creator_name = _normalize_vn_name((row_u.get("full_name") or "").strip())
                creator_img = (row_u.get("user_image") or "").strip()
                creator_title = (row_u.get("job_title") or "").strip()

        ab_key = (_get("approved_by_user") or "").strip()
        ab_u = users.get(ab_key) if ab_key else None
        ab_name = _normalize_vn_name(ab_u.full_name) if ab_u else ""
        if ab_key and not ab_name:
            row_ab = frappe.db.get_value(
                "User",
                ab_key,
                ["full_name", "user_image"],
                as_dict=True,
            )
            if row_ab:
                ab_name = _normalize_vn_name((row_ab.get("full_name") or "").strip())

        rb_key = (_get("rejected_by_user") or "").strip()
        rb_u = users.get(rb_key) if rb_key else None
        rb_name = _normalize_vn_name(rb_u.full_name) if rb_u else ""
        if rb_key and not rb_name:
            row_rb = frappe.db.get_value(
                "User",
                rb_key,
                ["full_name", "user_image"],
                as_dict=True,
            )
            if row_rb:
                rb_name = _normalize_vn_name((row_rb.get("full_name") or "").strip())

        if is_dict:
            r["pic_full_name"] = pic_name
            r["pic_user_image"] = pic_u.user_image if pic_u else ""
            r["created_by_name"] = creator_name
            r["created_by_image"] = creator_img
            r["created_by_title"] = creator_title
            r["approved_by_name"] = ab_name
            r["rejected_by_name"] = rb_name
        else:
            r.pic_full_name = pic_name
            r.pic_user_image = pic_u.user_image if pic_u else ""
            r.created_by_name = creator_name
            r.created_by_image = creator_img
            r.created_by_title = creator_title
            r.approved_by_name = ab_name
            r.rejected_by_name = rb_name


def _enrich_issue_students_display(data):
    """Gắn student_display_name, student_class_title cho issue_students — mobile hiển thị Tên (Lớp)."""
    if not isinstance(data, dict):
        return
    try:
        rows = data.get("issue_students") or []
        ids = []
        for r in rows:
            sid = (r.get("student") or "").strip()
            if sid and sid not in ids:
                ids.append(sid)
        single = (data.get("student") or "").strip()
        if single and single not in ids:
            ids.append(single)
        if not ids:
            return
        stud_rows = frappe.get_all(
            "CRM Student",
            filters={"name": ["in", ids]},
            fields=["name", "student_name"],
        )
        name_to_display = {s["name"]: (s.get("student_name") or "").strip() for s in (stud_rows or [])}
        class_by_student = {}
        current_sy = frappe.db.get_value(
            "SIS School Year", {"is_enable": 1}, "name", order_by="start_date desc"
        )
        if current_sy:
            class_rows = frappe.db.sql(
                """
                SELECT cs.student_id, c.title AS class_title
                FROM `tabSIS Class Student` cs
                INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                WHERE cs.student_id IN %(ids)s
                  AND cs.school_year_id = %(year)s
                  AND c.school_year_id = %(year)s
                """,
                {"ids": tuple(ids), "year": current_sy},
                as_dict=True,
            )
            for cr in class_rows or []:
                sid = cr.get("student_id")
                if sid and sid not in class_by_student:
                    class_by_student[sid] = (cr.get("class_title") or "").strip()
        for r in rows:
            sid = (r.get("student") or "").strip()
            r["student_display_name"] = name_to_display.get(sid) or sid
            r["student_class_title"] = class_by_student.get(sid, "")
        if single:
            data["student_display_name"] = name_to_display.get(single) or single
            data["student_class_title"] = class_by_student.get(single, "")
    except Exception as e:
        frappe.logger().error(f"_enrich_issue_students_display: {e}")


def _compute_sla_deadline(occurred_at, sla_hours):
    """occurred_at: string/datetime, sla_hours: float"""
    if not occurred_at or sla_hours is None:
        return None
    try:
        dt = get_datetime(occurred_at)
        hrs = float(sla_hours) if sla_hours else 0
        return add_to_date(dt, hours=hrs)
    except Exception:
        return None


@frappe.whitelist()
def whoami_crm_issue():
    """Debug: tra ve user + roles ma server dang thay (doi chieu voi can_approve_reject)."""
    u = frappe.session.user
    current_roles = sorted(_session_roles_current())
    is_approver = bool(APPROVER_ROLES & set(current_roles)) or (
        "System Manager" in current_roles or "Administrator" in current_roles
    )
    return success_response(
        data={
            "user": u,
            "current_roles": current_roles,
            "approver_roles_config": sorted(APPROVER_ROLES),
            "can_approve": is_approver,
            "can_access_list": bool(_can_access_crm_issue_list()),
            "jwt_authenticated": bool(getattr(frappe.local, "jwt_authenticated", False)),
        }
    )


@frappe.whitelist()
def get_issue_pic_candidates():
    """Tra ve danh sach user co role PIC hop le (Sales/Care)."""
    # Khong dung check_crm_permission: moi user dang nhap can tai dropdown PIC khi tao/sua issue

    pic_roles = list(PIC_ELIGIBLE_ROLES)
    user_emails = frappe.get_all(
        "Has Role",
        filters={"role": ["in", pic_roles], "parenttype": "User"},
        fields=["parent"],
        pluck="parent",
    )
    unique_emails = list(set(user_emails))
    if not unique_emails:
        return success_response([])

    users = frappe.get_all(
        "User",
        filters={"name": ["in", unique_emails], "enabled": 1},
        fields=["name as user_id", "full_name", "email", "user_image", "job_title"],
    )
    return success_response(users)


@frappe.whitelist()
def get_issues():
    """Lay danh sach van de — day du cho moi user co quyen CRM (khong loc theo phong ban/owner). Chi loc khi client gui department / only_my_departments."""
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen truy cap danh sach van de CRM", frappe.PermissionError)

    user = frappe.session.user
    is_department_member = bool(_get_user_crm_issue_department_names(user))
    # UI: danh sach chung day du — luon 'all' (phan quyen nut o get_issue / can_*)
    list_pending_scope_hint = "all"

    student_id = frappe.request.args.get("student_id")
    lead_name = frappe.request.args.get("lead_name")
    status = frappe.request.args.get("status")
    issue_module = frappe.request.args.get("issue_module")
    approval_status = frappe.request.args.get("approval_status")
    department = frappe.request.args.get("department")
    pic = (frappe.request.args.get("pic") or "").strip()
    only_my_departments = frappe.request.args.get("only_my_departments")
    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 20))

    filters = {}
    if student_id:
        filters["student"] = student_id
    if lead_name:
        filters["lead"] = lead_name
    if status:
        filters["status"] = status
    if issue_module:
        filters["issue_module"] = issue_module
    if approval_status:
        filters["approval_status"] = approval_status
    if pic:
        filters["pic"] = pic

    name_constraint_sets = []

    if department:
        dept_names = _issue_names_matching_department(department)
        if not dept_names:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        name_constraint_sets.append(set(dept_names))
    if only_my_departments and str(only_my_departments).lower() in ("1", "true", "yes"):
        my_depts = _get_user_crm_issue_department_names(user)
        if not my_depts:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        visible = _issue_names_visible_to_department_members(my_depts)
        if not visible:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        name_constraint_sets.append(set(visible))
    if name_constraint_sets:
        inter = set.intersection(*name_constraint_sets)
        names_list = list(inter)
        if not names_list:
            out = paginated_response([], page, 0, per_page)
            out["can_see_pending_queue_scope"] = list_pending_scope_hint
            out["is_department_member"] = is_department_member
            return out
        filters["name"] = ["in", names_list]

    total = frappe.db.count("CRM Issue", filters=filters)
    offset = (page - 1) * per_page

    issues = frappe.get_all(
        "CRM Issue",
        filters=filters,
        fields=[
            "name",
            "issue_code",
            "title",
            "issue_module",
            "status",
            "result",
            "priority",
            "pic",
            "created_by_user",
            "owner",
            "occurred_at",
            "lead",
            "student",
            "modified",
            "creation",
            "approval_status",
            "sla_deadline",
            "sla_status",
            "department",
        ],
        order_by="creation desc",
        start=offset,
        page_length=per_page,
    )

    _enrich_user_info(issues)
    _enrich_issue_list_departments(issues)
    out = paginated_response(issues, page, total, per_page)
    out["can_see_pending_queue_scope"] = list_pending_scope_hint
    out["is_department_member"] = is_department_member
    return out


@frappe.whitelist()
def get_pending_issues():
    """Hang cho duyet — day du cho moi user co quyen CRM. Duyet/tu choi van theo can_* tren chi tiet."""
    user = frappe.session.user
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen truy cap hang cho duyet CRM", frappe.PermissionError)

    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 50))
    filters = {"approval_status": "Cho duyet"}
    scope_meta = "all"
    dept_flag = bool(_get_user_crm_issue_department_names(user))
    total = frappe.db.count("CRM Issue", filters=filters)
    offset = (page - 1) * per_page

    issues = frappe.get_all(
        "CRM Issue",
        filters=filters,
        fields=[
            "name",
            "issue_code",
            "title",
            "issue_module",
            "status",
            "result",
            "priority",
            "pic",
            "created_by_user",
            "owner",
            "occurred_at",
            "lead",
            "student",
            "modified",
            "creation",
            "approval_status",
            "sla_deadline",
            "sla_status",
            "department",
        ],
        order_by="creation asc",
        start=offset,
        page_length=per_page,
    )
    _enrich_user_info(issues)
    _enrich_issue_list_departments(issues)
    out = paginated_response(issues, page, total, per_page)
    out["can_see_pending_queue_scope"] = scope_meta
    out["is_department_member"] = dept_flag
    return out


@frappe.whitelist()
def get_issue():
    """Chi tiet van de — doc day du neu co quyen CRM (phan quyen thao tac: can_*)."""
    if not _can_access_crm_issue_list():
        frappe.throw("Khong co quyen xem chi tiet van de CRM", frappe.PermissionError)

    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    data = _finalize_issue_api_dict(doc)
    return single_item_response(data)


def _feedback_replies_and_guardian_for_crm(feedback_name):
    """
    Tra ve replies (co enrich ten) + guardian_info toi gian cho man CRM Issue.
    Logic dong bo voi erp.api.erp_sis.feedback.admin_get (phan replies).
    """
    feedback = frappe.get_doc("Feedback", feedback_name)
    replies_data = []
    if feedback.replies:
        for reply in feedback.replies:
            reply_data = {
                "content": reply.content,
                "reply_by": reply.reply_by,
                "reply_by_type": reply.reply_by_type,
                "reply_date": reply.reply_date,
                "is_internal": reply.is_internal,
                "reply_by_full_name": None,
            }
            if reply.reply_by_type == "Staff" and reply.reply_by:
                try:
                    reply_user = frappe.get_doc("User", reply.reply_by)
                    reply_data["reply_by_full_name"] = reply_user.full_name
                except frappe.DoesNotExistError:
                    reply_data["reply_by_full_name"] = reply.reply_by
            elif reply.reply_by_type == "Guardian" and feedback.guardian:
                try:
                    guardian_doc = frappe.get_doc("CRM Guardian", feedback.guardian)
                    reply_data["reply_by_full_name"] = guardian_doc.guardian_name
                except frappe.DoesNotExistError:
                    reply_data["reply_by_full_name"] = "Phụ huynh"
            replies_data.append(reply_data)

    guardian_info = None
    if feedback.guardian:
        try:
            guardian = frappe.get_doc("CRM Guardian", feedback.guardian)
            guardian_info = {
                "name": guardian.guardian_name,
                "phone_number": guardian.phone_number,
                "email": guardian.email,
            }
        except frappe.DoesNotExistError:
            guardian_info = {
                "name": feedback.guardian_name or feedback.guardian,
                "phone_number": None,
                "email": None,
            }

    return {
        "source_feedback": feedback.name,
        "replies": replies_data,
        "guardian_info": guardian_info,
    }


@frappe.whitelist()
def get_linked_feedback_replies():
    """
    Lay lich su trao doi Feedback gan voi CRM Issue (khi co source_feedback).
    Dung cho workspace-mobile tab Qua trinh xu ly.
    """

    issue_name = frappe.request.args.get("issue_name") or frappe.request.args.get("name")
    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    issue_doc = frappe.get_doc("CRM Issue", issue_name)
    sf = getattr(issue_doc, "source_feedback", None) or ""
    if not (sf and str(sf).strip()):
        return success_response(
            data={
                "source_feedback": None,
                "replies": [],
                "guardian_info": None,
            }
        )

    if not frappe.db.exists("Feedback", sf):
        return success_response(
            data={
                "source_feedback": sf,
                "replies": [],
                "guardian_info": None,
            }
        )

    try:
        payload = _feedback_replies_and_guardian_for_crm(sf)
        return success_response(data=payload)
    except frappe.DoesNotExistError:
        return not_found_response(f"Khong tim thay feedback {sf}")
    except Exception as e:
        frappe.logger().error(f"get_linked_feedback_replies: {e}")
        return error_response(f"Loi lay feedback lien ket: {str(e)}")


@frappe.whitelist()
def get_linked_issue():
    """
    Lay CRM Issue co source_feedback = feedback_name (thuong tu dong tao khi phu huynh gui Gop y).
    Dung cho man chi tiet Feedback (web/mobile) de dieu huong sang Issue.
    """

    feedback_name = frappe.request.args.get("feedback_name") or frappe.request.args.get("name")
    if not feedback_name:
        return validation_error_response("Thieu feedback_name", {"feedback_name": ["Bat buoc"]})

    if not frappe.db.exists("Feedback", feedback_name):
        return not_found_response(f"Khong tim thay feedback {feedback_name}")

    rows = frappe.get_all(
        "CRM Issue",
        filters={"source_feedback": feedback_name},
        fields=[
            "name",
            "issue_code",
            "title",
            "status",
            "approval_status",
            "source_feedback",
        ],
        limit=1,
    )
    if not rows:
        return success_response(data=None, message="Khong co van de lien ket")

    return success_response(data=rows[0])


@frappe.whitelist(methods=["POST"])
def create_issue():
    """Tao van de moi"""
    data = get_request_data()

    required = ["content", "issue_module", "priority"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    dept_payload = data.get("departments") or ([data.get("department")] if data.get("department") else [])
    if not dept_payload:
        errors["departments"] = ["Bat buoc"]
    if data.get("priority") and data.get("priority") not in ("Cao", "Trung binh", "Thap"):
        errors["priority"] = ["Gia tri khong hop le"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)

    module_name = data["issue_module"]
    if not frappe.db.exists("CRM Issue Module", module_name):
        return validation_error_response("Module khong hop le", {"issue_module": ["Khong ton tai"]})

    mod = frappe.get_doc("CRM Issue Module", module_name)
    if not mod.is_active:
        return error_response("Module khong con hoat dong")

    try:
        doc = frappe.new_doc("CRM Issue")
        doc.content = data["content"]
        doc.issue_module = module_name
        doc.issue_code = _generate_issue_code(mod.code)
        doc.title = (data.get("title") or doc.issue_code or mod.module_name or module_name).strip()
        doc.priority = data.get("priority")

        occurred_at = _normalize_issue_date(data.get("occurred_at"))
        doc.occurred_at = occurred_at
        doc.lead = data.get("lead") or ""
        _sync_issue_students(doc, data)
        if "departments" in data:
            _sync_issue_departments(doc, data)
        else:
            doc.department = (data.get("department") or "").strip()
            doc.issue_departments = []
            d0 = doc.department
            if d0 and frappe.db.exists("CRM Issue Department", d0):
                doc.append("issue_departments", {"department": d0})
        doc.attachment = data.get("attachment") or ""

        sla_h = float(mod.sla_hours or 0)
        doc.sla_hours = sla_h
        # SLA chi bat dau khi tao truc tiep (Da duyet); hang cho: approve_issue se gan moc
        if _can_create_directly():
            doc.sla_started_at = now()
            doc.sla_deadline = _compute_sla_deadline(now(), sla_h)
            doc.sla_status = "On track"
        else:
            doc.sla_started_at = None
            doc.sla_deadline = None
            doc.first_response_at = None
            doc.sla_status = "On track"

        # PIC: tu dong — khong nhan tu client
        _assign_pic_from_issue_context(doc)

        user = frappe.session.user
        doc.created_by_user = user

        if _can_create_directly():
            doc.approval_status = "Da duyet"
            doc.status = "Tiep nhan"
            doc.approved_by_user = user
            doc.approved_at = now()
        else:
            doc.approval_status = "Cho duyet"
            doc.status = "Cho duyet"

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Push: co van de cho duyet -> thong bao nguoi duyet
        try:
            if doc.approval_status == "Cho duyet":
                _notify_crm_issue_mobile(
                    _approver_emails(),
                    "Vấn đề mới chờ duyệt",
                    f"{doc.issue_code}: {doc.title}",
                    doc,
                    "crm_issue_created",
                    exclude_user=frappe.session.user,
                )
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify create: {e}")

        return single_item_response(_finalize_issue_api_dict(doc), "Tao van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao van de: {str(e)}")


@frappe.whitelist(methods=["POST"])
def approve_issue():
    """Duyet van de trong hang cho"""
    # Khong dung check_crm_permission: chi can role duyet (APPROVER_ROLES) — tranh 403 khi JWT/session khac tap role CRM tong

    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    doc = frappe.get_doc("CRM Issue", name)
    if not _can_approve():
        # Log chi tiet de doi chieu voi can_approve_reject tra ve tu get_issue
        current_roles = sorted(_session_roles_current())
        frappe.logger().warning(
            f"CRM Issue approve blocked: user={frappe.session.user}, roles={current_roles}, "
            f"required_any={sorted(APPROVER_ROLES) + ['System Manager', 'Administrator']}, name={name}"
        )
        return error_response(
            "Khong co quyen duyet",
            code="PERMISSION_DENIED",
            debug_info={
                "user": frappe.session.user,
                "current_roles": current_roles,
                "approver_roles": sorted(APPROVER_ROLES),
                "issue_name": name,
            },
        )
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    if "departments" in data:
        dept_values = data.get("departments") or []
        if not dept_values:
            return validation_error_response("Phong ban lien quan la bat buoc", {"departments": ["Bat buoc"]})
        _sync_issue_departments(doc, data)
    elif "department" in data:
        dept_value = (data.get("department") or "").strip()
        if not dept_value:
            return validation_error_response("Phong ban lien quan la bat buoc", {"department": ["Bat buoc"]})
        doc.department = dept_value
        doc.issue_departments = []
        if frappe.db.exists("CRM Issue Department", dept_value):
            doc.append("issue_departments", {"department": dept_value})

    if "priority" in data:
        priority = (data.get("priority") or "").strip()
        if priority not in ("Cao", "Trung binh", "Thap"):
            return validation_error_response("Muc do khong hop le", {"priority": ["Khong hop le"]})
        doc.priority = priority

    if "pic" in data:
        new_pic = (data.get("pic") or "").strip()
        if new_pic and not _is_valid_pic_user(new_pic):
            return error_response("PIC khong hop le")
        doc.pic = new_pic

    if not (doc.pic or "").strip():
        _assign_pic_from_issue_context(doc)

    doc.approval_status = "Da duyet"
    doc.status = "Tiep nhan"
    doc.approved_by_user = frappe.session.user
    doc.approved_at = now()
    doc.rejected_by_user = ""
    doc.rejected_at = None
    # Moc SLA: luc duyet (khong phai luc tao neu qua hang cho)
    doc.sla_started_at = now()
    doc.sla_deadline = _compute_sla_deadline(now(), float(doc.sla_hours or 0))
    _recompute_sla_state(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        recipients = []
        if doc.pic:
            recipients.append(doc.pic)
        recipients.extend(_all_department_manager_emails_for_issue(doc))
        _notify_crm_issue_mobile(
            recipients,
            "Vấn đề đã được duyệt",
            f"{doc.issue_code}: {doc.title}",
            doc,
            "crm_issue_approved",
            exclude_user=frappe.session.user,
        )
    except Exception as e:
        frappe.logger().error(f"CRM Issue notify approve: {e}")

    return single_item_response(_finalize_issue_api_dict(doc), "Da duyet van de")


@frappe.whitelist(methods=["POST"])
def reject_issue():
    """Tu choi van de trong hang cho"""
    # Chi kiem tra _can_approve — dong ly do approve_issue

    data = get_request_data()
    name = data.get("name")
    reason = data.get("reason") or ""
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    doc = frappe.get_doc("CRM Issue", name)
    if not _can_approve():
        current_roles = sorted(_session_roles_current())
        frappe.logger().warning(
            f"CRM Issue reject blocked: user={frappe.session.user}, roles={current_roles}, "
            f"required_any={sorted(APPROVER_ROLES) + ['System Manager', 'Administrator']}, name={name}"
        )
        return error_response(
            "Khong co quyen tu choi",
            code="PERMISSION_DENIED",
            debug_info={
                "user": frappe.session.user,
                "current_roles": current_roles,
                "approver_roles": sorted(APPROVER_ROLES),
                "issue_name": name,
            },
        )
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    doc.approval_status = "Tu choi"
    doc.rejection_reason = reason
    doc.status = "Hoan thanh"
    doc.rejected_by_user = frappe.session.user
    doc.rejected_at = now()
    doc.approved_by_user = ""
    doc.approved_at = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        if doc.created_by_user:
            _notify_crm_issue_mobile(
                [doc.created_by_user],
                "Vấn đề bị từ chối",
                f"{doc.issue_code}: {doc.title}",
                doc,
                "crm_issue_rejected",
                exclude_user=frappe.session.user,
            )
    except Exception as e:
        frappe.logger().error(f"CRM Issue notify reject: {e}")

    return single_item_response(_finalize_issue_api_dict(doc), "Da tu choi")


@frappe.whitelist(methods=["POST"])
def update_issue():
    """Cap nhat van de"""
    check_crm_permission()
    data = get_request_data()

    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    try:
        doc = frappe.get_doc("CRM Issue", name)
        if not _can_write_issue_ops(frappe.session.user, doc):
            return error_response("Khong co quyen sua van de nay")

        old_pic = doc.pic

        updatable = [
            "title",
            "content",
            "pic",
            "attachment",
            "lead",
            "priority",
        ]
        for field in updatable:
            if field in data:
                doc.set(field, data[field])

        if "occurred_at" in data:
            doc.occurred_at = _normalize_issue_date(data.get("occurred_at"))

        if "priority" in data and (data.get("priority") or "").strip() not in ("Cao", "Trung binh", "Thap"):
            return validation_error_response("Muc do khong hop le", {"priority": ["Khong hop le"]})

        # PIC chi gan user co role Sales (dong bo get_issue_pic_candidates)
        if "pic" in data:
            new_pic = (data.get("pic") or "").strip()
            old_pic_s = (old_pic or "").strip()
            if new_pic != old_pic_s:
                if not (PIC_CHANGE_ROLES & _session_roles_current()):
                    return error_response("Khong co quyen doi PIC")
                if new_pic and not _is_valid_pic_user(new_pic):
                    return error_response(
                        "PIC khong hop le: chi user co role xu ly van de (dong bo danh sach PIC)"
                    )

        if "departments" in data:
            _sync_issue_departments(doc, data)
        elif "department" in data:
            doc.department = (data.get("department") or "").strip()
            doc.issue_departments = []
            d0 = doc.department
            if d0 and frappe.db.exists("CRM Issue Department", d0):
                doc.append("issue_departments", {"department": d0})

        if "students" in data or "student" in data:
            _sync_issue_students(doc, data)

        if "issue_module" in data and data["issue_module"]:
            if frappe.db.exists("CRM Issue Module", data["issue_module"]):
                doc.issue_module = data["issue_module"]
                mod = frappe.get_doc("CRM Issue Module", doc.issue_module)
                doc.sla_hours = float(mod.sla_hours or 0)
                if getattr(doc, "sla_started_at", None):
                    doc.sla_deadline = _compute_sla_deadline(doc.sla_started_at, doc.sla_hours)
                else:
                    doc.sla_deadline = _compute_sla_deadline(doc.creation, doc.sla_hours)
                _recompute_sla_state(doc)
                doc.issue_code = doc.issue_code or _generate_issue_code(mod.code)

        # PIC: client khong gui (mobile/web form) -> gan lai theo module/hoc sinh/phong ban
        if "pic" not in data:
            _assign_pic_from_issue_context(doc)

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        try:
            new_pic = (doc.pic or "").strip()
            old_pic_s = (old_pic or "").strip()
            if new_pic and new_pic != old_pic_s:
                _notify_crm_issue_mobile(
                    [new_pic],
                    "Bạn được giao vấn đề mới",
                    f"{doc.issue_code}: {doc.title}",
                    doc,
                    "crm_issue_pic_changed",
                    exclude_user=frappe.session.user,
                )
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify pic change: {e}")

        return single_item_response(_finalize_issue_api_dict(doc), "Cap nhat van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")


@frappe.whitelist(methods=["POST"])
def change_issue_status():
    """Chuyen trang thai van de"""
    check_crm_permission()
    data = get_request_data()

    name = data.get("name")
    status = data.get("status")
    result = data.get("result", "")

    if not name or not status:
        return validation_error_response(
            "Thieu tham so",
            {"name": ["Bat buoc"] if not name else [], "status": ["Bat buoc"] if not status else []},
        )

    valid_statuses = ["Cho duyet", "Tiep nhan", "Dang xu ly", "Hoan thanh", "Dong"]
    if status not in valid_statuses:
        return error_response(f"Trang thai khong hop le: {', '.join(valid_statuses)}")

    if status in ("Cho duyet", "Tiep nhan"):
        return error_response("Khong duoc chuyen thu cong sang Cho duyet hoac Tiep nhan")

    if result and result not in VALID_ISSUE_RESULTS:
        return validation_error_response("Ket qua khong hop le", {"result": ["Khong hop le"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    current_user = frappe.session.user
    old_status = (getattr(doc, "status", None) or "").strip()
    if doc.approval_status != "Da duyet":
        return error_response("Van de chua duoc duyet, khong doi trang thai xu ly")

    is_pic = _is_issue_pic(current_user, doc)
    is_care_admin = _can_care_admin(current_user)
    is_status_role = _can_change_issue_status_sales(current_user)

    if status == "Dang xu ly":
        if old_status == "Hoan thanh":
            if not is_care_admin:
                return error_response("Chi Care Admin duoc tra van de ve Dang xu ly")
        elif old_status != "Tiep nhan":
            return error_response("Chi duoc chuyen sang Dang xu ly tu Tiep nhan hoac Hoan thanh")
        elif not (is_pic or is_status_role or is_care_admin):
            return error_response("Khong co quyen tiep tuc xu ly van de")
    elif status == "Hoan thanh":
        if old_status != "Dang xu ly":
            return error_response("Chi duoc hoan thanh van de tu trang thai Dang xu ly")
        if not is_pic:
            return error_response("Chi PIC duoc chuyen van de sang Hoan thanh")
        if not result:
            return validation_error_response("Can co ket qua khi hoan thanh", {"result": ["Bat buoc"]})
    elif status == "Dong":
        if old_status != "Hoan thanh":
            return error_response("Chi duoc dong van de sau khi PIC hoan thanh")
        if not is_care_admin:
            return error_response("Chi Care Admin duoc dong van de")

    doc.status = status
    if status == "Hoan thanh":
        doc.result = result or ""
    elif old_status == "Hoan thanh" and status == "Dang xu ly":
        doc.result = ""
    _mark_first_response_if_eligible(doc)
    _recompute_sla_state(doc)
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        recipients = []
        title = "Cập nhật trạng thái vấn đề"
        body = f"{doc.issue_code}: {status}"
        if status == "Hoan thanh":
            recipients.extend(_care_admin_emails())
            title = "Vấn đề đã hoàn thành"
            body = f"{doc.issue_code}: PIC đã hoàn thành, cần xác nhận"
        elif status == "Dong":
            if doc.pic:
                recipients.append(doc.pic)
            title = "Vấn đề đã đóng"
            body = f"{doc.issue_code}: Care Admin đã xác nhận đóng"
        elif old_status == "Hoan thanh" and status == "Dang xu ly":
            if doc.pic:
                recipients.append(doc.pic)
            title = "Vấn đề cần tiếp tục xử lý"
            body = f"{doc.issue_code}: Care Admin yêu cầu tiếp tục xử lý"
        else:
            if doc.pic:
                recipients.append(doc.pic)
            if doc.created_by_user:
                recipients.append(doc.created_by_user)
            recipients.extend(_all_department_manager_emails_for_issue(doc))
        _notify_crm_issue_mobile(
            recipients,
            title,
            body,
            doc,
            "crm_issue_status_changed",
            exclude_user=frappe.session.user,
        )
    except Exception as e:
        frappe.logger().error(f"CRM Issue notify status: {e}")

    return single_item_response(_finalize_issue_api_dict(doc), f"Da chuyen trang thai sang {status}")


@frappe.whitelist(methods=["POST"])
def add_process_log():
    """Them log qua trinh xu ly"""
    check_crm_permission()
    data = get_request_data()

    issue_name = data.get("issue_name")
    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    required = ["content"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)

    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
        current_user = frappe.session.user
        if doc.approval_status != "Da duyet":
            return error_response("Van de chua duoc duyet, khong them log")
        if (getattr(doc, "status", None) or "").strip() != "Dang xu ly":
            return error_response("Chi them log khi van de dang xu ly")
        if not (_is_issue_pic(current_user, doc) or _can_write_issue_ops(current_user, doc)):
            return error_response("Khong co quyen them log")
        user_full_name = frappe.db.get_value("User", current_user, "full_name") or current_user
        doc.append(
            "process_logs",
            {
                "title": data.get("title") or "Nhật ký xử lý",
                "content": data["content"],
                "logged_at": data.get("logged_at", now()),
                "logged_by": current_user,
                "logged_by_name": user_full_name,
                "assignees": data.get("assignees", ""),
                "attachment": data.get("attachment", ""),
            },
        )
        _mark_first_response_if_eligible(doc)
        _recompute_sla_state(doc)
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        try:
            recipients = []
            if doc.pic:
                recipients.append(doc.pic)
            if doc.created_by_user:
                recipients.append(doc.created_by_user)
            recipients.extend(_all_department_member_emails_for_issue(doc))
            _notify_crm_issue_mobile(
                recipients,
                "Log xử lý vấn đề mới",
                f"{doc.issue_code}: Có cập nhật xử lý mới",
                doc,
                "crm_issue_log_added",
                exclude_user=frappe.session.user,
            )
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify log: {e}")

        return single_item_response(_finalize_issue_api_dict(doc), "Them log xu ly thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi them log: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_process_log():
    """Cap nhat log xu ly"""
    check_crm_permission()
    data = get_request_data()

    issue_name = data.get("issue_name")
    log_name = (data.get("log_name") or "").strip()
    log_idx = data.get("log_idx")

    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
        if doc.approval_status != "Da duyet":
            return error_response("Van de chua duoc duyet, khong sua log")
        if (getattr(doc, "status", None) or "").strip() == "Dong":
            return error_response("Van de da dong, khong sua log")
        if not _can_care_admin(frappe.session.user):
            return error_response("Chi Care Admin duoc sua log")

        idx = None
        if log_name:
            for i, row in enumerate(doc.process_logs):
                if row.name == log_name:
                    idx = i
                    break
            if idx is None:
                return error_response("Khong tim thay log")
        else:
            if log_idx is None:
                return validation_error_response(
                    "Thieu log_name hoac log_idx",
                    {"log_name": ["Bat buoc"], "log_idx": ["Bat buoc"]},
                )
            idx = int(log_idx)
            if not (0 <= idx < len(doc.process_logs)):
                return error_response("Khong tim thay log voi index da cho")

        log = doc.process_logs[idx]
        for field in ["title", "content", "assignees", "attachment"]:
            if field in data:
                setattr(log, field, data[field])

        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return single_item_response(_finalize_issue_api_dict(doc), "Cap nhat log thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat log: {str(e)}")
