"""
Chat Scope API cho social-service khi caller là GIÁO VIÊN.

Endpoint song song với `parent_portal.journal.get_class_chat_scope` (cho PH),
nhưng xác thực GV thuộc lớp (homeroom / vice / subject teacher) thay vì
kiểm tra phụ huynh có liên kết HS trong lớp.

Mục tiêu: Tránh phụ thuộc Resource permission (SIS Class / SIS Subject Assignment / ...)
khi GV bộ môn không có quyền đọc trực tiếp DocType qua /api/resource.
"""

import json

import frappe
from frappe import _

from erp.api.erp_sis.family import build_guardians_by_student_ids
from erp.api.parent_portal.journal import _teacher_snapshot_for_chat
from erp.utils.api_response import success_response, error_response


def _parse_chat_scope_payload():
    """Gộp form_dict + JSON body (cho POST từ social-service)."""
    d = dict(frappe.form_dict or {})
    if getattr(frappe, "request", None) and frappe.request.data:
        try:
            raw = (
                frappe.request.data.decode("utf-8")
                if isinstance(frappe.request.data, bytes)
                else frappe.request.data
            )
            body = json.loads(raw)
            if isinstance(body, dict):
                d.update(body)
        except Exception:
            pass
    return d


def _resolve_teacher_id_for_user(user_email):
    """Tìm SIS Teacher theo email Frappe User.

    Trả về (teacher_id, user_name). Nếu không tìm được, trả về (None, None).
    """
    if not user_email:
        return None, None

    user_name = frappe.db.get_value("User", {"email": user_email}, "name") or user_email

    teacher = frappe.db.get_value(
        "SIS Teacher",
        {"user_id": user_name},
        ["name"],
    )
    if teacher:
        return teacher, user_name

    teacher = frappe.db.get_value(
        "SIS Teacher",
        {"user_id": user_email},
        ["name"],
    )
    if teacher:
        return teacher, user_name

    return None, user_name


def _resolve_subject_titles(subject_ids):
    if not subject_ids:
        return {}
    rows = frappe.db.get_values(
        "SIS Actual Subject",
        {"name": ["in", list(subject_ids)]},
        ["name", "title_vn", "title_en"],
    ) or []
    return {sid: (title_vn or title_en or sid) for sid, title_vn, title_en in rows}


def _build_class_chat_scope(cls, class_id, school_year_id):
    """Dựng scope roster đầy đủ cho một lớp + năm học (không kèm ACL/caller).

    Dùng chung cho `get_class_chat_scope_for_teacher` (sau khi đã check GV thuộc lớp)
    và `get_class_chat_scope_for_sync` (service account của social-service).
    """
    sy_title = (
        frappe.db.get_value(
            "SIS School Year",
            school_year_id,
            ["title_vn", "title_en"],
            as_dict=True,
        )
        or {}
    )
    school_year_name = sy_title.get("title_vn") or sy_title.get("title_en") or school_year_id

    class_student_rows = frappe.get_all(
        "SIS Class Student",
        filters={"class_id": class_id, "school_year_id": school_year_id},
        fields=["student_id"],
        ignore_permissions=True,
        limit_page_length=10000,
    )
    student_ids = [r.student_id for r in class_student_rows if r.get("student_id")]

    students_out = []
    for sid in student_ids:
        row = (
            frappe.db.get_value(
                "CRM Student",
                sid,
                ["student_name", "student_code", "family_code"],
                as_dict=True,
            )
            or {}
        )
        students_out.append(
            {
                "student_id": sid,
                "student_name": row.get("student_name"),
                "student_code": row.get("student_code"),
                "family_code": row.get("family_code"),
            }
        )

    guardians = build_guardians_by_student_ids(student_ids)

    teachers = []
    for tid in [cls.get("homeroom_teacher"), cls.get("vice_homeroom_teacher")]:
        snap = _teacher_snapshot_for_chat(tid)
        if snap:
            teachers.append(snap)

    # GV bộ môn + môn dạy (gắn `subjects: [{id,title}]`).
    subject_rows = frappe.get_all(
        "SIS Subject Assignment",
        filters={"class_id": class_id, "school_year_id": school_year_id},
        fields=["teacher_id", "actual_subject_id"],
        ignore_permissions=True,
        limit_page_length=2000,
    )
    subj_ids = {r.get("actual_subject_id") for r in subject_rows if r.get("actual_subject_id")}
    subj_title_map = _resolve_subject_titles(subj_ids)

    teacher_subject_map = {}
    for row in subject_rows:
        tid = row.get("teacher_id")
        sid = row.get("actual_subject_id")
        if not tid or not sid:
            continue
        entry = {"id": sid, "title": subj_title_map.get(sid, sid)}
        bucket = teacher_subject_map.setdefault(tid, [])
        if not any(item.get("id") == sid for item in bucket):
            bucket.append(entry)

    homeroom_ids = {cls.get("homeroom_teacher"), cls.get("vice_homeroom_teacher")}
    seen_subj_teacher = {t.get("teacherId") for t in teachers if t.get("teacherId")}
    subject_teachers = []
    for tid in teacher_subject_map.keys():
        if not tid or tid in homeroom_ids or tid in seen_subj_teacher:
            continue
        snap = _teacher_snapshot_for_chat(tid, subjects=teacher_subject_map.get(tid, []))
        if snap:
            subject_teachers.append(snap)
            seen_subj_teacher.add(tid)

    class_year_on_doc = cls.get("school_year_id")
    is_active = (not class_year_on_doc) or (str(class_year_on_doc) == str(school_year_id))

    return {
        "classId": cls.get("name") or class_id,
        "className": cls.get("title") or cls.get("short_title") or class_id,
        "schoolYearId": school_year_id,
        "schoolYearName": school_year_name,
        "classType": cls.get("class_type"),
        "isActive": is_active,
        "students": students_out,
        "guardians": guardians,
        "teachers": teachers,
        "subject_teachers": subject_teachers,
    }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_class_chat_scope_for_teacher(class_id=None, school_year_id=None):
    """
    Scope lớp cho social-service khi caller là GV.

    Trả schema cùng dạng với `parent_portal.journal.get_class_chat_scope`:
      - homeroom_teacher / vice_homeroom_teacher / teachers / subject_teachers (kèm `subjects`).
      - students, guardians (đầy đủ key_person, is_key_person_any).
    """
    try:
        payload = _parse_chat_scope_payload()
        class_id = class_id or payload.get("class_id")
        school_year_id = school_year_id or payload.get("school_year_id")

        if not class_id:
            return error_response(message="Thiếu class_id", code="MISSING_CLASS")
        if not school_year_id:
            return error_response(message="Thiếu school_year_id", code="MISSING_SCHOOL_YEAR")

        user_email = frappe.session.user
        if not user_email or user_email == "Guest":
            return error_response(message="Vui lòng đăng nhập", code="NOT_AUTHENTICATED")

        cls = frappe.db.get_value(
            "SIS Class",
            class_id,
            [
                "name",
                "title",
                "short_title",
                "school_year_id",
                "class_type",
                "homeroom_teacher",
                "vice_homeroom_teacher",
            ],
            as_dict=True,
        )
        if not cls:
            return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

        # Kiểm tra GV có thuộc lớp này không (homeroom / vice / subject teacher).
        teacher_id, user_name = _resolve_teacher_id_for_user(user_email)
        is_homeroom = bool(teacher_id) and teacher_id in {
            cls.get("homeroom_teacher"),
            cls.get("vice_homeroom_teacher"),
        }
        is_subject_teacher = False
        if teacher_id and not is_homeroom:
            is_subject_teacher = bool(
                frappe.db.exists(
                    "SIS Subject Assignment",
                    {
                        "class_id": class_id,
                        "teacher_id": teacher_id,
                        "school_year_id": school_year_id,
                    },
                )
            )
        if not (is_homeroom or is_subject_teacher):
            return error_response(
                message="Bạn không thuộc lớp này",
                code="ACCESS_DENIED",
            )

        scope = _build_class_chat_scope(cls, class_id, school_year_id)
        scope["callerTeacherId"] = teacher_id or ""
        scope["callerUserName"] = user_name or ""

        return success_response(data=scope, message="OK")
    except Exception as e:
        frappe.logger().error(
            f"[Chat Scope] get_class_chat_scope_for_teacher error: {str(e)}"
        )
        return error_response(
            message=_("Không thể tải scope chat lớp"),
            code="CLASS_CHAT_SCOPE_ERROR",
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def list_class_chat_sync_targets():
    """
    Danh sách (classId, schoolYearId) cho job sync membership của social-service.

    Chỉ trả lớp CHÍNH QUY (`class_type = regular`) thuộc năm học đang bật
    (`SIS School Year.is_enable = 1`) — job dùng danh sách này để TẠO nhóm chat còn thiếu
    (lớp chưa từng có ai mở chat) và merge roster, thay vì chỉ quét các nhóm đã tồn tại
    trong Mongo. Lớp mixed/club không auto-tạo nhóm (khớp isRegularScope ở read-path).
    """
    try:
        frappe.only_for(("System Manager",))

        enabled_years = frappe.get_all(
            "SIS School Year",
            filters={"is_enable": 1},
            pluck="name",
        )
        if not enabled_years:
            return success_response(data={"targets": []}, message="OK")

        rows = frappe.get_all(
            "SIS Class",
            filters={
                "school_year_id": ["in", enabled_years],
                "class_type": "regular",
            },
            fields=["name", "school_year_id"],
            ignore_permissions=True,
            limit_page_length=0,
        )
        targets = [
            {"classId": r.get("name"), "schoolYearId": r.get("school_year_id")}
            for r in rows
            if r.get("name") and r.get("school_year_id")
        ]
        return success_response(data={"targets": targets}, message="OK")
    except frappe.PermissionError:
        return error_response(message="Chỉ dành cho service account", code="ACCESS_DENIED")
    except Exception as e:
        frappe.logger().error(
            f"[Chat Scope] list_class_chat_sync_targets error: {str(e)}"
        )
        return error_response(
            message=_("Không thể liệt kê lớp cho sync chat"),
            code="CLASS_CHAT_SYNC_TARGETS_ERROR",
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def get_class_chat_scope_for_sync(class_id=None, school_year_id=None):
    """
    Scope ĐẦY ĐỦ cho job sync membership của social-service.

    Chỉ dành cho service account (API key admin / System Manager) — KHÔNG dùng cho
    request user-context. Marker `scopeComplete=True` là điều kiện bắt buộc để
    social-service được phép REVOKE participant (tránh lặp bug scope thiếu teachers
    từ request PH làm GV mất quyền).
    """
    try:
        frappe.only_for(("System Manager",))

        payload = _parse_chat_scope_payload()
        class_id = class_id or payload.get("class_id")
        school_year_id = school_year_id or payload.get("school_year_id")

        if not class_id:
            return error_response(message="Thiếu class_id", code="MISSING_CLASS")
        if not school_year_id:
            return error_response(message="Thiếu school_year_id", code="MISSING_SCHOOL_YEAR")

        cls = frappe.db.get_value(
            "SIS Class",
            class_id,
            [
                "name",
                "title",
                "short_title",
                "school_year_id",
                "class_type",
                "homeroom_teacher",
                "vice_homeroom_teacher",
            ],
            as_dict=True,
        )
        if not cls:
            return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

        scope = _build_class_chat_scope(cls, class_id, school_year_id)
        scope["scopeComplete"] = True

        return success_response(data=scope, message="OK")
    except frappe.PermissionError:
        return error_response(message="Chỉ dành cho service account", code="ACCESS_DENIED")
    except Exception as e:
        frappe.logger().error(
            f"[Chat Scope] get_class_chat_scope_for_sync error: {str(e)}"
        )
        return error_response(
            message=_("Không thể tải scope chat lớp (sync)"),
            code="CLASS_CHAT_SCOPE_SYNC_ERROR",
        )
