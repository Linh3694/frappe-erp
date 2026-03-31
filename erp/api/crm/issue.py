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

# Role duyet / tu choi
APPROVER_ROLES = frozenset(
    {
        "System Manager",
        "SIS BOD",
        "SIS Sales Care Admin",
        "SIS Sales Admin",
    }
)


def _notify_crm_issue_mobile(users, title, body, issue_doc, notif_type, exclude_user=None):
    """Gui push notification Expo cho user (workspace-mobile)."""
    try:
        from erp.api.erp_sis.mobile_push_notification import send_mobile_notification
    except Exception as e:
        frappe.logger().warning(f"CRM Issue: khong import send_mobile_notification: {e}")
        return
    seen = set()
    for email in users or []:
        if not email or email in ("Guest",) or email == exclude_user:
            continue
        if email in seen:
            continue
        seen.add(email)
        try:
            send_mobile_notification(
                user_email=email,
                title=title,
                body=body,
                data={
                    "type": notif_type,
                    "issueId": issue_doc.name,
                    "issueCode": (issue_doc.issue_code or ""),
                },
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


def _user_roles():
    return set(frappe.get_roles(frappe.session.user))


def _can_create_directly():
    return bool(DIRECT_ISSUE_ROLES & _user_roles())


def _can_approve():
    return bool(APPROVER_ROLES & _user_roles())


def _can_edit_issue(doc) -> bool:
    """Chi SIS Sales Care Admin, PIC, hoac nguoi tao (created_by_user) duoc sua van de."""
    user = frappe.session.user
    if not user or user == "Guest":
        return False
    if "SIS Sales Care Admin" in frappe.get_roles(user):
        return True
    if getattr(doc, "pic", None) and doc.pic == user:
        return True
    if getattr(doc, "created_by_user", None) and doc.created_by_user == user:
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
    """Them pic_full_name, pic_user_image, created_by_name vao danh sach issues"""
    emails = set()
    for r in issues:
        _get = r.get if isinstance(r, dict) else lambda k, d=None: getattr(r, k, d)
        if _get("pic"):
            emails.add(_get("pic"))
        # created_by_user co the trong (ban ghi cu); owner la nguoi tao chuan Frappe
        creator_id = (_get("created_by_user") or _get("owner") or "").strip()
        if creator_id:
            emails.add(creator_id)
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

        if is_dict:
            r["pic_full_name"] = pic_name
            r["pic_user_image"] = pic_u.user_image if pic_u else ""
            r["created_by_name"] = creator_name
            r["created_by_image"] = creator_img
        else:
            r.pic_full_name = pic_name
            r.pic_user_image = pic_u.user_image if pic_u else ""
            r.created_by_name = creator_name
            r.created_by_image = creator_img


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
    check_crm_permission()

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
    check_crm_permission()

    student_id = frappe.request.args.get("student_id")
    lead_name = frappe.request.args.get("lead_name")
    status = frappe.request.args.get("status")
    issue_module = frappe.request.args.get("issue_module")
    approval_status = frappe.request.args.get("approval_status")
    department = frappe.request.args.get("department")
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
    if department:
        filters["department"] = department

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
    return paginated_response(issues, page, total, per_page)


@frappe.whitelist()
def get_pending_issues():
    """Danh sach van de cho duyet (admin)"""
    check_crm_permission()
    if not _can_approve():
        frappe.throw("Khong co quyen xem hang cho duyet", frappe.PermissionError)

    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 50))
    filters = {"approval_status": "Cho duyet"}
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
    return paginated_response(issues, page, total, per_page)


@frappe.whitelist()
def get_issue():
    """Chi tiet van de"""
    check_crm_permission()

    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")

    doc = frappe.get_doc("CRM Issue", name)
    data = doc.as_dict()
    _enrich_user_info([data])
    _enrich_issue_students_display(data)
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
    check_crm_permission()

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


@frappe.whitelist(methods=["POST"])
def create_issue():
    """Tao van de moi"""
    check_crm_permission()
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
        doc.department = data.get("department") or ""
        doc.attachment = data.get("attachment") or ""

        sla_h = float(mod.sla_hours or 0)
        doc.sla_hours = sla_h
        doc.sla_deadline = _compute_sla_deadline(now(), sla_h)

        # PIC: payload > student lead > department first member
        pic = data.get("pic") or ""
        if not pic and doc.student:
            pic = _pic_from_student(doc.student) or ""
        if not pic and doc.department:
            pic = _pic_from_department(doc.department) or ""
        doc.pic = pic

        user = frappe.session.user
        doc.created_by_user = user

        if _can_create_directly():
            doc.approval_status = "Da duyet"
            doc.status = "Tiep nhan"
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

        return single_item_response(doc.as_dict(), "Tao van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao van de: {str(e)}")


@frappe.whitelist(methods=["POST"])
def approve_issue():
    """Duyet van de trong hang cho"""
    check_crm_permission()
    if not _can_approve():
        frappe.throw("Khong co quyen duyet", frappe.PermissionError)

    data = get_request_data()
    name = data.get("name")
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    doc = frappe.get_doc("CRM Issue", name)
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    doc.approval_status = "Da duyet"
    doc.status = "Tiep nhan"
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

    return single_item_response(doc.as_dict(), "Da duyet van de")


@frappe.whitelist(methods=["POST"])
def reject_issue():
    """Tu choi van de trong hang cho"""
    check_crm_permission()
    if not _can_approve():
        frappe.throw("Khong co quyen tu choi", frappe.PermissionError)

    data = get_request_data()
    name = data.get("name")
    reason = data.get("reason") or ""
    if not name or not frappe.db.exists("CRM Issue", name):
        return not_found_response("Khong tim thay van de")

    doc = frappe.get_doc("CRM Issue", name)
    if doc.approval_status != "Cho duyet":
        return error_response("Van de khong o trang thai cho duyet")

    doc.approval_status = "Tu choi"
    doc.rejection_reason = reason
    doc.status = "Hoan thanh"
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

    return single_item_response(doc.as_dict(), "Da tu choi")


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
        if not _can_edit_issue(doc):
            return error_response("Khong co quyen sua van de nay")

        old_pic = doc.pic

        updatable = [
            "title",
            "content",
            "occurred_at",
            "pic",
            "attachment",
            "lead",
            "department",
        ]
        for field in updatable:
            if field in data:
                doc.set(field, data[field])

        if "students" in data or "student" in data:
            _sync_issue_students(doc, data)

        if "issue_module" in data and data["issue_module"]:
            if frappe.db.exists("CRM Issue Module", data["issue_module"]):
                doc.issue_module = data["issue_module"]
                mod = frappe.get_doc("CRM Issue Module", doc.issue_module)
                doc.sla_hours = float(mod.sla_hours or 0)
                doc.sla_deadline = _compute_sla_deadline(doc.creation, doc.sla_hours)
                doc.issue_code = doc.issue_code or _generate_issue_code(mod.code)

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        try:
            new_pic = (doc.pic or "").strip()
            old_pic_s = (old_pic or "").strip()
            if new_pic and new_pic != old_pic_s:
                _notify_crm_issue_mobile(
                    [new_pic],
                    "Bạn được giao PIC vấn đề",
                    f"{doc.issue_code}: {doc.title}",
                    doc,
                    "crm_issue_pic_changed",
                    exclude_user=frappe.session.user,
                )
        except Exception as e:
            frappe.logger().error(f"CRM Issue notify pic change: {e}")

        return single_item_response(doc.as_dict(), "Cap nhat van de thanh cong")
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
        recipients.extend(_department_member_emails(doc.department))
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

    return single_item_response(doc.as_dict(), f"Da chuyen trang thai sang {status}")


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
            recipients.extend(_department_member_emails(doc.department))
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

        return single_item_response(doc.as_dict(), "Them log xu ly thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi them log: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_process_log():
    """Cap nhat log xu ly"""
    check_crm_permission()
    data = get_request_data()

    issue_name = data.get("issue_name")
    log_idx = data.get("log_idx")

    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})

    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")

    try:
        doc = frappe.get_doc("CRM Issue", issue_name)

        if log_idx is not None and 0 <= int(log_idx) < len(doc.process_logs):
            log = doc.process_logs[int(log_idx)]
            for field in ["title", "content", "assignees", "attachment"]:
                if field in data:
                    setattr(log, field, data[field])

            doc.save(ignore_permissions=True)
            frappe.db.commit()
            return single_item_response(doc.as_dict(), "Cap nhat log thanh cong")

        return error_response("Khong tim thay log voi index da cho")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat log: {str(e)}")
