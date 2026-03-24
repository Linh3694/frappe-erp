# Copyright (c) 2026, Wellspring International School and contributors
"""
Workflow phê duyệt phiếu khám SK định kỳ (L1 → L2 Medical Admin → L3 GVCN).
Thông báo email: tạm override qua health_checkup_notify_override_email hoặc mặc định test.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime
from erp.utils.api_response import success_response, error_response
from erp.utils.email_service import send_email_via_service

import json

ROLE_SIS_MEDICAL = "SIS Medical"
ROLE_SIS_MEDICAL_ADMIN = "SIS Medical Admin"
# Email test QA — bỏ override trong site_config khi gửi user thật
_DEFAULT_NOTIFY_OVERRIDE = "linh.nguyenhai@wellspring.edu.vn"


def _get_request_data():
    data = {}
    if hasattr(frappe, "request") and hasattr(frappe.request, "args") and frappe.request.args:
        data.update(dict(frappe.request.args))
    if frappe.local.form_dict:
        data.update(dict(frappe.local.form_dict))
    if hasattr(frappe.request, "is_json") and frappe.request.is_json:
        json_data = frappe.request.json or {}
        data.update(json_data)
    else:
        try:
            if hasattr(frappe.request, "data") and frappe.request.data:
                raw = frappe.request.data
                body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                if body and body.strip():
                    json_data = json.loads(body)
                    if isinstance(json_data, dict):
                        data.update(json_data)
        except (json.JSONDecodeError, ValueError):
            pass
    return data


def _normalize_checkup_phase(phase):
    if phase is None or str(phase).strip() == "":
        return "beginning"
    p = str(phase).strip().lower()
    if p in ("beginning", "end"):
        return p
    return None


def _has_role(role: str) -> bool:
    return role in frappe.get_roles()


def _has_approval_column():
    """Tên DocType không có prefix tab (has_column tự nối tab). Bọc try khi bảng chưa migrate."""
    try:
        return frappe.db.has_column("SIS Student Health Checkup", "approval_status")
    except Exception:
        return False


def _notify_workflow(recipient_emails, subject: str, body_html: str):
    """
    Gửi email thông báo workflow. Override: site_config health_checkup_notify_override_email
    hoặc mặc định email test (chỉ 1 người nhận khi đang test).
    """
    override = frappe.conf.get("health_checkup_notify_override_email")
    if override is None or str(override).strip() == "":
        override = _DEFAULT_NOTIFY_OVERRIDE
    to_list = [override] if override else [e for e in (recipient_emails or []) if e]
    if not to_list:
        return
    try:
        send_email_via_service(to_list, subject, f"<p>{body_html}</p>")
    except Exception as e:
        frappe.log_error(f"health_checkup notify: {str(e)}")


def _user_emails_with_role(role: str):
    rows = frappe.db.sql(
        """
        SELECT DISTINCT u.name, u.email
        FROM `tabUser` u
        INNER JOIN `tabHas Role` hr ON hr.parent = u.name AND hr.parenttype = 'User'
        WHERE hr.role = %(role)s AND IFNULL(u.enabled, 0) = 1
        """,
        {"role": role},
        as_dict=True,
    )
    return [r.email for r in rows if r.get("email")]


def _email_for_user(user_name):
    if not user_name:
        return None
    return frappe.db.get_value("User", user_name, "email")


def _teacher_id_from_session_user():
    uid = frappe.session.user
    if uid in ("Guest", "Administrator"):
        return None
    return frappe.db.get_value("SIS Teacher", {"user_id": uid}, "name")


def _get_regular_class_row(student_id, school_year_id):
    return frappe.db.sql(
        """
        SELECT c.name as class_id, c.homeroom_teacher, c.vice_homeroom_teacher
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
        WHERE cs.student_id = %(sid)s AND cs.school_year_id = %(sy)s AND c.class_type = 'regular'
        LIMIT 1
        """,
        {"sid": student_id, "sy": school_year_id},
        as_dict=True,
    )


def _homeroom_emails_for_student(student_id, school_year_id):
    rows = _get_regular_class_row(student_id, school_year_id)
    if not rows:
        return []
    row = rows[0]
    emails = []
    for tid in (row.get("homeroom_teacher"), row.get("vice_homeroom_teacher")):
        if not tid:
            continue
        uid = frappe.db.get_value("SIS Teacher", tid, "user_id")
        em = _email_for_user(uid)
        if em and em not in emails:
            emails.append(em)
    return emails


def _is_homeroom_for_student(student_id, school_year_id) -> bool:
    tid = _teacher_id_from_session_user()
    if not tid:
        return False
    rows = _get_regular_class_row(student_id, school_year_id)
    if not rows:
        return False
    row = rows[0]
    return tid in (row.get("homeroom_teacher"), row.get("vice_homeroom_teacher"))


@frappe.whitelist(allow_guest=False)
def submit_student_health_checkup(checkup_name=None, student_id=None, school_year_id=None):
    """L1 gửi duyệt: draft → pending_l2."""
    try:
        data = _get_request_data()
        checkup_name = checkup_name or data.get("checkup_name")
        student_id = student_id or data.get("student_id")
        school_year_id = school_year_id or data.get("school_year_id")
        phase = _normalize_checkup_phase(data.get("checkup_phase"))
        if phase is None:
            return error_response(message="checkup_phase không hợp lệ", code="VALIDATION_ERROR")

        if not _has_approval_column():
            return error_response(message="Chưa migrate DocType phê duyệt", code="MIGRATE_REQUIRED")

        if not _has_role(ROLE_SIS_MEDICAL) and "System Manager" not in frappe.get_roles():
            return error_response(message="Chỉ SIS Medical được gửi duyệt", code="FORBIDDEN")

        if not checkup_name:
            if not student_id or not school_year_id:
                return error_response(
                    message="Thiếu checkup_name hoặc (student_id + school_year_id)",
                    code="VALIDATION_ERROR",
                )
            checkup_name = frappe.db.get_value(
                "SIS Student Health Checkup",
                {"student_id": student_id, "school_year_id": school_year_id, "checkup_phase": phase},
                "name",
            )
        if not checkup_name:
            return error_response(message="Không tìm thấy phiếu khám", code="NOT_FOUND")

        doc = frappe.get_doc("SIS Student Health Checkup", checkup_name)
        if doc.approval_status != "draft":
            return error_response(message="Chỉ gửi duyệt khi đang nháp", code="INVALID_STATE")

        doc.approval_status = "pending_l2"
        doc.submitted_at = now_datetime()
        doc.submitted_by = frappe.session.user
        doc.returned_from_level = None
        doc.last_rejection_comment = None
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Thông báo L2
        recipients = _user_emails_with_role(ROLE_SIS_MEDICAL_ADMIN)
        subj = f"[Khám SK] Phiếu chờ duyệt L2 — {doc.student_name or doc.student_id}"
        body = f"Học sinh: {doc.student_name} ({doc.student_code}). Đợt: {doc.checkup_phase}. Mã phiếu: {doc.name}."
        _notify_workflow(recipients, subj, body)

        return success_response(data=doc.as_dict(), message="Đã gửi duyệt")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"submit_student_health_checkup: {str(e)}")
        return error_response(message=str(e), code="SUBMIT_ERROR")


def _load_checkup_names(data):
    names = data.get("checkup_names") or data.get("names")
    if isinstance(names, str):
        names = json.loads(names)
    if not names and data.get("checkup_name"):
        names = [data.get("checkup_name")]
    return names or []


@frappe.whitelist(allow_guest=False)
def approve_health_checkup_l2(checkup_name=None):
    """L2 duyệt: pending_l2 → pending_l3."""
    try:
        data = _get_request_data()
        names = _load_checkup_names(data)
        if checkup_name:
            names = [checkup_name]
        if not names:
            return error_response(message="Thiếu checkup_name / checkup_names", code="VALIDATION_ERROR")

        if not _has_approval_column():
            return error_response(message="Chưa migrate DocType phê duyệt", code="MIGRATE_REQUIRED")

        if not _has_role(ROLE_SIS_MEDICAL_ADMIN) and "System Manager" not in frappe.get_roles():
            return error_response(message="Chỉ SIS Medical Admin được duyệt L2", code="FORBIDDEN")

        done = []
        for name in names:
            doc = frappe.get_doc("SIS Student Health Checkup", name)
            if doc.approval_status != "pending_l2":
                continue
            doc.approval_status = "pending_l3"
            doc.l2_action_at = now_datetime()
            doc.l2_action_by = frappe.session.user
            doc.save(ignore_permissions=True)
            done.append(name)

            emails = _homeroom_emails_for_student(doc.student_id, doc.school_year_id)
            subj = f"[Khám SK] Phiếu chờ GVCN — {doc.student_name or doc.student_id}"
            body = f"Học sinh: {doc.student_name}. Đợt: {doc.checkup_phase}. Phiếu: {doc.name}."
            _notify_workflow(emails, subj, body)

        frappe.db.commit()
        return success_response(data={"approved": done}, message=f"Đã duyệt {len(done)} phiếu")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"approve_health_checkup_l2: {str(e)}")
        return error_response(message=str(e), code="L2_APPROVE_ERROR")


@frappe.whitelist(allow_guest=False)
def reject_health_checkup_l2(checkup_name=None, comment=None):
    """L2 trả: pending_l2 → draft."""
    try:
        data = _get_request_data()
        names = _load_checkup_names(data)
        if checkup_name:
            names = [checkup_name]
        comment = (comment or data.get("comment") or data.get("rejection_comment") or "").strip()
        if not comment:
            return error_response(message="Vui lòng nhập lý do trả phiếu", code="VALIDATION_ERROR")

        if not names:
            return error_response(message="Thiếu phiếu", code="VALIDATION_ERROR")

        if not _has_approval_column():
            return error_response(message="Chưa migrate DocType phê duyệt", code="MIGRATE_REQUIRED")

        if not _has_role(ROLE_SIS_MEDICAL_ADMIN) and "System Manager" not in frappe.get_roles():
            return error_response(message="Chỉ SIS Medical Admin được trả L2", code="FORBIDDEN")

        done = []
        for name in names:
            doc = frappe.get_doc("SIS Student Health Checkup", name)
            if doc.approval_status != "pending_l2":
                continue
            doc.approval_status = "draft"
            doc.returned_from_level = "l2"
            doc.last_rejection_comment = comment[:500]
            doc.l2_action_at = now_datetime()
            doc.l2_action_by = frappe.session.user
            doc.save(ignore_permissions=True)
            done.append(name)

            target = _email_for_user(doc.submitted_by) or _email_for_user(doc.owner)
            subj = f"[Khám SK] Phiếu bị trả L2 — {doc.student_name or doc.student_id}"
            body = f"Phiếu {doc.name}. Lý do: {comment}."
            _notify_workflow([target] if target else [], subj, body)

        frappe.db.commit()
        return success_response(data={"rejected": done}, message=f"Đã trả {len(done)} phiếu")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"reject_health_checkup_l2: {str(e)}")
        return error_response(message=str(e), code="L2_REJECT_ERROR")


@frappe.whitelist(allow_guest=False)
def approve_health_checkup_l3(checkup_name=None):
    """L3 duyệt: pending_l3 → published."""
    try:
        data = _get_request_data()
        names = _load_checkup_names(data)
        if checkup_name:
            names = [checkup_name]
        if not names:
            return error_response(message="Thiếu phiếu", code="VALIDATION_ERROR")

        if not _has_approval_column():
            return error_response(message="Chưa migrate DocType phê duyệt", code="MIGRATE_REQUIRED")

        tid = _teacher_id_from_session_user()
        if not tid and "System Manager" not in frappe.get_roles():
            return error_response(message="Không xác định giáo viên chủ nhiệm", code="FORBIDDEN")

        done = []
        for name in names:
            doc = frappe.get_doc("SIS Student Health Checkup", name)
            if doc.approval_status != "pending_l3":
                continue
            if "System Manager" not in frappe.get_roles():
                if not _is_homeroom_for_student(doc.student_id, doc.school_year_id):
                    continue
            doc.approval_status = "published"
            doc.l3_action_at = now_datetime()
            doc.l3_action_by = frappe.session.user
            doc.save(ignore_permissions=True)
            done.append(name)

        frappe.db.commit()
        return success_response(data={"approved": done}, message=f"Đã công bố {len(done)} phiếu")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"approve_health_checkup_l3: {str(e)}")
        return error_response(message=str(e), code="L3_APPROVE_ERROR")


@frappe.whitelist(allow_guest=False)
def reject_health_checkup_l3(checkup_name=None, comment=None):
    """L3 trả: pending_l3 → draft."""
    try:
        data = _get_request_data()
        names = _load_checkup_names(data)
        if checkup_name:
            names = [checkup_name]
        comment = comment or data.get("comment") or data.get("rejection_comment") or ""

        if not names:
            return error_response(message="Thiếu phiếu", code="VALIDATION_ERROR")

        if not _has_approval_column():
            return error_response(message="Chưa migrate DocType phê duyệt", code="MIGRATE_REQUIRED")

        if "System Manager" not in frappe.get_roles():
            if not _teacher_id_from_session_user():
                return error_response(message="Không xác định giáo viên", code="FORBIDDEN")

        done = []
        for name in names:
            doc = frappe.get_doc("SIS Student Health Checkup", name)
            if doc.approval_status != "pending_l3":
                continue
            if "System Manager" not in frappe.get_roles():
                if not _is_homeroom_for_student(doc.student_id, doc.school_year_id):
                    continue
            doc.approval_status = "draft"
            doc.returned_from_level = "l3"
            doc.last_rejection_comment = (comment or "")[:500]
            doc.l3_action_at = now_datetime()
            doc.l3_action_by = frappe.session.user
            doc.save(ignore_permissions=True)
            done.append(name)

            target = _email_for_user(doc.submitted_by) or _email_for_user(doc.owner)
            subj = f"[Khám SK] Phiếu bị trả L3 — {doc.student_name or doc.student_id}"
            body = f"Phiếu {doc.name}. Lý do: {comment or '(không có)'}."
            _notify_workflow([target] if target else [], subj, body)

        frappe.db.commit()
        return success_response(data={"rejected": done}, message=f"Đã trả {len(done)} phiếu")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"reject_health_checkup_l3: {str(e)}")
        return error_response(message=str(e), code="L3_REJECT_ERROR")


def _health_checkup_l2_list_filters():
    """Các bước duyệt: Y tế (draft) → Trưởng phòng (pending_l2) → GVCN (pending_l3) → published."""
    return frozenset(("draft", "pending_l2", "pending_l3", "published"))


@frappe.whitelist(allow_guest=False)
def get_health_checkup_approval_queue_l2(school_year_id=None, checkup_phase=None, list_filter=None):
    """Màn L2: tổng hợp counts theo bước duyệt + danh sách theo list_filter (mặc định pending_l2)."""
    try:
        data = _get_request_data()
        school_year_id = school_year_id or data.get("school_year_id")
        checkup_phase = _normalize_checkup_phase(checkup_phase or data.get("checkup_phase"))
        list_filter = (list_filter or data.get("list_filter") or "pending_l2").strip()
        if not school_year_id:
            return error_response(message="school_year_id là bắt buộc", code="VALIDATION_ERROR")
        if checkup_phase is None:
            return error_response(message="checkup_phase không hợp lệ", code="VALIDATION_ERROR")
        if list_filter not in _health_checkup_l2_list_filters():
            return error_response(message="list_filter không hợp lệ", code="VALIDATION_ERROR")

        if not _has_role(ROLE_SIS_MEDICAL_ADMIN) and "System Manager" not in frappe.get_roles():
            return error_response(message="Không có quyền xem hàng đợi L2", code="FORBIDDEN")

        from erp.utils.campus_utils import get_current_campus_from_context

        campus_id = get_current_campus_from_context()
        campus_filter = "AND shc.campus_id = %(campus_id)s" if campus_id else ""

        if not _has_approval_column():
            return success_response(
                data={
                    "counts": {"draft": 0, "pending_l2": 0, "pending_l3": 0, "published": 0},
                    "items": [],
                    "list_filter": list_filter,
                },
                message="OK",
            )

        # Một phiếu khám = một dòng; không JOIN Class Student trực tiếp (một HS có thể có nhiều
        # bản ghi lớp/năm → gây duplicate). Lấy tên lớp regular qua subquery LIMIT 1.
        select_cols = """
                shc.name,
                shc.student_id,
                shc.student_name,
                shc.student_code,
                shc.school_year_id,
                shc.checkup_phase,
                shc.approval_status,
                shc.submitted_at,
                shc.returned_from_level,
                shc.last_rejection_comment,
                (
                    SELECT c.title
                    FROM `tabSIS Class Student` cs2
                    INNER JOIN `tabSIS Class` c ON c.name = cs2.class_id
                        AND IFNULL(c.class_type, '') = 'regular'
                    WHERE cs2.student_id = shc.student_id
                        AND cs2.school_year_id = shc.school_year_id
                    ORDER BY c.title ASC
                    LIMIT 1
                ) AS class_name
        """
        params = {"sy": school_year_id, "ph": checkup_phase}
        if campus_id:
            params["campus_id"] = campus_id

        sql_counts = f"""
            SELECT shc.approval_status, COUNT(*) AS cnt
            FROM `tabSIS Student Health Checkup` shc
            WHERE shc.school_year_id = %(sy)s
                AND shc.checkup_phase = %(ph)s
                {campus_filter}
            GROUP BY shc.approval_status
        """
        count_rows = frappe.db.sql(sql_counts, params, as_dict=True)
        counts = {"draft": 0, "pending_l2": 0, "pending_l3": 0, "published": 0}
        for r in count_rows:
            st = r.get("approval_status")
            if st in counts:
                counts[st] = int(r.get("cnt") or 0)

        order_by = {
            "draft": "shc.modified DESC, shc.name ASC",
            "pending_l2": "shc.submitted_at IS NULL, shc.submitted_at ASC, shc.name ASC",
            "pending_l3": "shc.submitted_at IS NULL, shc.submitted_at ASC, shc.name ASC",
            "published": "shc.modified DESC, shc.name ASC",
        }[list_filter]
        # Giới hạn tải — published thường nhiều nhất nên 500; các bước khác 2000
        limit_sql = " LIMIT 500" if list_filter == "published" else " LIMIT 2000"

        sql_items = f"""
            SELECT
                {select_cols}
            FROM `tabSIS Student Health Checkup` shc
            WHERE shc.school_year_id = %(sy)s
                AND shc.checkup_phase = %(ph)s
                AND shc.approval_status = %(lf)s
                {campus_filter}
            ORDER BY {order_by}
            {limit_sql}
        """
        params_items = {**params, "lf": list_filter}
        items = frappe.db.sql(sql_items, params_items, as_dict=True)

        return success_response(
            data={"counts": counts, "items": items, "list_filter": list_filter},
            message="OK",
        )
    except Exception as e:
        frappe.log_error(f"get_health_checkup_approval_queue_l2: {str(e)}")
        return error_response(message=str(e), code="QUEUE_L2_ERROR")


@frappe.whitelist(allow_guest=False)
def get_class_periodic_health_checkups(class_id=None, school_year_id=None, checkup_phase=None):
    """Danh sách học sinh lớp + phiếu khám định kỳ (cho GVCN)."""
    try:
        data = _get_request_data()
        class_id = class_id or data.get("class_id")
        school_year_id = school_year_id or data.get("school_year_id")
        checkup_phase = _normalize_checkup_phase(checkup_phase or data.get("checkup_phase"))
        if not class_id or not school_year_id:
            return error_response(message="class_id và school_year_id là bắt buộc", code="VALIDATION_ERROR")
        if checkup_phase is None:
            return error_response(message="checkup_phase không hợp lệ", code="VALIDATION_ERROR")

        if "System Manager" not in frappe.get_roles():
            tid = _teacher_id_from_session_user()
            if not tid:
                return error_response(message="Không xác định giáo viên", code="FORBIDDEN")
            cls = frappe.db.get_value(
                "SIS Class",
                class_id,
                ["homeroom_teacher", "vice_homeroom_teacher", "school_year_id"],
                as_dict=True,
            )
            if not cls or cls.school_year_id != school_year_id:
                return error_response(message="Lớp không hợp lệ", code="VALIDATION_ERROR")
            if tid not in (cls.homeroom_teacher, cls.vice_homeroom_teacher):
                return error_response(message="Không phải GVCN lớp này", code="FORBIDDEN")

        students = frappe.db.sql(
            """
            SELECT s.name as student_id, s.student_name, s.student_code, s.gender,
                shc.name as checkup_id,
                IFNULL(shc.approval_status, 'published') as approval_status
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabCRM Student` s ON s.name = cs.student_id
            LEFT JOIN `tabSIS Student Health Checkup` shc
                ON shc.student_id = cs.student_id
                AND shc.school_year_id = cs.school_year_id
                AND shc.checkup_phase = %(ph)s
            WHERE cs.class_id = %(cid)s AND cs.school_year_id = %(sy)s
            ORDER BY s.student_name
            """,
            {"cid": class_id, "sy": school_year_id, "ph": checkup_phase},
            as_dict=True,
        )

        return success_response(data={"students": students}, message="OK")
    except Exception as e:
        frappe.log_error(f"get_class_periodic_health_checkups: {str(e)}")
        return error_response(message=str(e), code="CLASS_CHECKUP_ERROR")
