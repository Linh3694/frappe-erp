"""
CRM Issue API - Van de chung (tuyen sinh): module, SLA, duyet, PIC tu CRM Lead
"""

import frappe
from frappe.utils import now, add_to_date, get_datetime
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
)
from erp.api.crm.utils import check_crm_permission, get_request_data

# Role duoc tao ticket truc tiep (khong qua hang cho)
DIRECT_ISSUE_ROLES = frozenset(
    {
        "SIS Sales Care",
        "SIS Sales Care Admin",
        "SIS Sales",
        "SIS Sales Admin",
    }
)

# Chi SIS Sales Admin / SIS Sales Care Admin duoc duyet & tu choi (dong bo frontend IssueDetail)
APPROVER_ROLES = frozenset(
    {
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)

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


def _can_see_pending_issues_queue(user: str) -> bool:
    """Xem hang cho duyet: co role ghi hoac thuoc it nhat mot phong ban."""
    if ISSUE_WRITE_ROLES & set(frappe.get_roles(user)):
        return True
    return bool(_get_user_crm_issue_department_names(user))


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
        data["can_approve_reject"] = bool(_can_approve())
        data["can_write_issue"] = bool(_can_write_issue_ops(u, doc))
        data["can_edit_sales_status"] = bool(_can_change_issue_status_sales(u))
    else:
        data["can_approve_reject"] = False
        data["can_write_issue"] = False
        data["can_edit_sales_status"] = False
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
    """User co role duyet van de."""
    roles = list(APPROVER_ROLES)
    rows = frappe.get_all(
        "Has Role",
        filters={"role": ["in", roles], "parenttype": "User"},
        pluck="parent",
    )
    return list(set(rows or []))


def _department_member_emails(department_name):
    """Email thanh vien phong ban CRM Issue."""
    if not department_name or not frappe.db.exists("CRM Issue Department", department_name):
        return []
    dept = frappe.get_doc("CRM Issue Department", department_name)
    return [m.user for m in (dept.members or [])]


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


def _can_create_directly():
    return bool(DIRECT_ISSUE_ROLES & _user_roles())


def _is_valid_pic_user(pic_email: str) -> bool:
    """PIC hop le: user ton tai va co it nhat mot role trong DIRECT_ISSUE_ROLES (dong bo get_issue_pic_candidates)."""
    if not pic_email or not frappe.db.exists("User", pic_email):
        return False
    return bool(DIRECT_ISSUE_ROLES & set(frappe.get_roles(pic_email)))


def _can_approve():
    """Duyet/tu choi: APPROVER_ROLES + System Manager / Administrator (van hanh Frappe)."""
    r = _user_roles()
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
        for u in frappe.get_all("User", filters={"name": ["in", list(emails)]}, fields=["name", "full_name", "user_image"])
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
        # Batch get_all doi khi khong khop — tra truc tiep User
        if creator_key and not creator_name:
            row_u = frappe.db.get_value(
                "User",
                creator_key,
                ["full_name", "user_image"],
                as_dict=True,
            )
            if row_u:
                creator_name = _normalize_vn_name((row_u.get("full_name") or "").strip())
                creator_img = (row_u.get("user_image") or "").strip()

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
            r["approved_by_name"] = ab_name
            r["rejected_by_name"] = rb_name
        else:
            r.pic_full_name = pic_name
            r.pic_user_image = pic_u.user_image if pic_u else ""
            r.created_by_name = creator_name
            r.created_by_image = creator_img
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
def get_issue_pic_candidates():
    """Tra ve danh sach user co role PIC hop le (SIS Sales, Sales Admin, Sales Care, Sales Care Admin)"""
    # Khong dung check_crm_permission: moi user dang nhap can tai dropdown PIC khi tao/sua issue

    pic_roles = list(DIRECT_ISSUE_ROLES)
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
        fields=["name as user_id", "full_name", "email", "user_image"],
    )
    return success_response(users)


@frappe.whitelist()
def get_issues():
    """Lay danh sach van de"""
    # Khong dung check_crm_permission: doc danh sach cho moi user dang nhap

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
            return paginated_response([], page, 0, per_page)
        name_constraint_sets.append(set(dept_names))
    if only_my_departments and str(only_my_departments).lower() in ("1", "true", "yes"):
        user = frappe.session.user
        my_depts = _get_user_crm_issue_department_names(user)
        if not my_depts:
            return paginated_response([], page, 0, per_page)
        visible = _issue_names_visible_to_department_members(my_depts)
        if not visible:
            return paginated_response([], page, 0, per_page)
        name_constraint_sets.append(set(visible))
    if name_constraint_sets:
        inter = set.intersection(*name_constraint_sets)
        names_list = list(inter)
        if not names_list:
            return paginated_response([], page, 0, per_page)
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
            "department",
        ],
        order_by="creation desc",
        start=offset,
        page_length=per_page,
    )

    _enrich_user_info(issues)
    _enrich_issue_list_departments(issues)
    return paginated_response(issues, page, total, per_page)


@frappe.whitelist()
def get_pending_issues():
    """Danh sach van de cho duyet (admin)"""
    user = frappe.session.user
    if not _can_see_pending_issues_queue(user):
        frappe.throw("Khong co quyen xem hang cho duyet", frappe.PermissionError)

    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 50))
    filters = {"approval_status": "Cho duyet"}
    if not (ISSUE_WRITE_ROLES & set(frappe.get_roles(user))):
        depts = _get_user_crm_issue_department_names(user)
        if not depts:
            return paginated_response([], page, 0, per_page)
        visible = _issue_names_visible_to_department_members(depts)
        if not visible:
            return paginated_response([], page, 0, per_page)
        filters["name"] = ["in", visible]
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
            "department",
        ],
        order_by="creation asc",
        start=offset,
        page_length=per_page,
    )
    _enrich_user_info(issues)
    _enrich_issue_list_departments(issues)
    return paginated_response(issues, page, total, per_page)


@frappe.whitelist()
def get_issue():
    """Chi tiet van de"""
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

    required = ["title", "content", "issue_module"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
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
        doc.title = data["title"]
        doc.content = data["content"]
        doc.issue_module = module_name
        doc.issue_code = _generate_issue_code(mod.code)

        occurred_at = data.get("occurred_at") or now()
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
        doc.sla_deadline = _compute_sla_deadline(now(), sla_h)

        # PIC: tu dong — uu tien thanh vien dau tien cua Loai van de > Lead hoc sinh > phong ban (khong nhan pic tu client)
        pic = _pic_from_module(module_name) or ""
        if not pic and doc.student:
            pic = _pic_from_student(doc.student) or ""
        if not pic:
            for dn in _issue_department_docnames(doc):
                pic = _pic_from_department(dn) or ""
                if pic:
                    break
        doc.pic = pic

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
        frappe.throw("Khong co quyen duyet", frappe.PermissionError)
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    doc.approval_status = "Da duyet"
    doc.status = "Tiep nhan"
    doc.approved_by_user = frappe.session.user
    doc.approved_at = now()
    doc.rejected_by_user = ""
    doc.rejected_at = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    try:
        recipients = []
        if doc.pic:
            recipients.append(doc.pic)
        if doc.created_by_user:
            recipients.append(doc.created_by_user)
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
        frappe.throw("Khong co quyen tu choi", frappe.PermissionError)
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
        prev_module = (doc.issue_module or "").strip()

        updatable = [
            "title",
            "content",
            "occurred_at",
            "pic",
            "attachment",
            "lead",
        ]
        for field in updatable:
            if field in data:
                doc.set(field, data[field])

        # PIC chi gan user co role Sales (dong bo get_issue_pic_candidates)
        if "pic" in data:
            new_pic = (data.get("pic") or "").strip()
            old_pic_s = (old_pic or "").strip()
            if new_pic != old_pic_s and new_pic and not _is_valid_pic_user(new_pic):
                return error_response("PIC khong hop le: chi user co role Sales tuyen sinh (dong bo danh sach PIC)")

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
                doc.sla_deadline = _compute_sla_deadline(doc.creation, doc.sla_hours)
                doc.issue_code = doc.issue_code or _generate_issue_code(mod.code)

        # Doi Loai van de -> gan lai PIC theo module (giong create); fallback hoc sinh / phong ban
        new_mod = (doc.issue_module or "").strip()
        if new_mod and new_mod != prev_module:
            pic = _pic_from_module(new_mod) or ""
            if not pic and doc.student:
                pic = _pic_from_student(doc.student) or ""
            if not pic:
                for dn in _issue_department_docnames(doc):
                    pic = _pic_from_department(dn) or ""
                    if pic:
                        break
            doc.pic = pic

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

    valid_statuses = ["Cho duyet", "Tiep nhan", "Dang xu ly", "Hoan thanh"]
    if status not in valid_statuses:
        return error_response(f"Trang thai khong hop le: {', '.join(valid_statuses)}")

    if status == "Hoan thanh" and not result:
        return validation_error_response("Can co ket qua khi hoan thanh", {"result": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    if not _can_change_issue_status_sales(frappe.session.user):
        return error_response("Khong co quyen cap nhat trang thai van de")
    if doc.approval_status != "Da duyet" and status != "Cho duyet":
        return error_response("Van de chua duoc duyet, khong doi trang thai xu ly")

    doc.status = status
    if "result" in data:
        doc.result = result or ""
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
            "Cập nhật trạng thái vấn đề",
            f"{doc.issue_code}: {status}",
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

    required = ["title", "content"]
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
        if not _can_write_issue_ops(current_user, doc):
            return error_response("Khong co quyen them log")
        user_full_name = frappe.db.get_value("User", current_user, "full_name") or current_user
        doc.append(
            "process_logs",
            {
                "title": data["title"],
                "content": data["content"],
                "logged_at": data.get("logged_at", now()),
                "logged_by": current_user,
                "logged_by_name": user_full_name,
                "assignees": data.get("assignees", ""),
                "attachment": data.get("attachment", ""),
            },
        )
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
                f"{doc.issue_code}: {data.get('title', '')}",
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
        if not _can_write_issue_ops(frappe.session.user, doc):
            return error_response("Khong co quyen sua log")

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
