"""
Parent Portal Journal API
Trả về phạm vi lớp/năm học mà phụ huynh được phép xem Nhật ký.
"""

import json

import frappe
from frappe import _

from erp.api.erp_sis.family import build_guardians_by_student_ids
from erp.api.parent_portal.otp_auth import get_parent_portal_user_from_request
from erp.utils.api_response import success_response, error_response


def _get_parent_student_ids(parent_email):
    """Lấy danh sách học sinh thuộc phụ huynh đang đăng nhập."""
    guardian_id = parent_email.split("@")[0]
    guardians = frappe.get_all(
        "CRM Guardian",
        filters={"guardian_id": guardian_id},
        fields=["name"],
        limit=1,
        ignore_permissions=True,
    )

    if not guardians:
        return []

    return frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": guardians[0].name},
        fields=["student"],
        pluck="student",
        ignore_permissions=True,
    )


@frappe.whitelist(allow_guest=True)
def get_student_class_scopes(student_id=None):
    """
    Lấy toàn bộ lớp/năm học học sinh từng học để social-service lọc bài Nhật ký.
    Endpoint này tự kiểm tra học sinh thuộc phụ huynh, sau đó đọc SIS bằng ignore_permissions.
    """
    try:
        student_id = student_id or frappe.form_dict.get("student_id")
        if not student_id:
            return error_response(message="Thiếu student_id", code="MISSING_STUDENT")

        parent_email = get_parent_portal_user_from_request()
        if not parent_email:
            return error_response(message="Vui lòng đăng nhập", code="NOT_AUTHENTICATED")

        allowed_students = _get_parent_student_ids(parent_email)
        if student_id not in allowed_students:
            return error_response(
                message="Bạn không có quyền xem Nhật ký của học sinh này",
                code="ACCESS_DENIED",
            )

        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"student_id": student_id},
            fields=["class_id", "school_year_id", "class_type", "docstatus"],
            order_by="modified desc",
            ignore_permissions=True,
            or_filters={"docstatus": ["in", [0, 1]]},
            limit_page_length=1000,
        )

        # Batch class + school year — tránh get_value trong vòng lặp
        class_ids = list({r.get("class_id") for r in class_students if r.get("class_id")})
        class_map = {}
        if class_ids:
            for c in frappe.get_all(
                "SIS Class",
                filters={"name": ["in", class_ids]},
                fields=["name", "title", "short_title", "school_year_id", "campus_id", "class_type"],
                ignore_permissions=True,
                limit_page_length=1000,
            ):
                class_map[c.name] = c

        year_ids = set()
        for row in class_students:
            cid = row.get("class_id")
            sy = row.get("school_year_id") or (class_map.get(cid) or {}).get("school_year_id")
            if sy:
                year_ids.add(sy)
        year_map = {}
        if year_ids:
            for y in frappe.get_all(
                "SIS School Year",
                filters={"name": ["in", list(year_ids)]},
                fields=["name", "title_vn", "title_en"],
                ignore_permissions=True,
                limit_page_length=500,
            ):
                year_map[y.name] = y

        scopes = []
        seen = set()
        for row in class_students:
            class_id = row.get("class_id")
            if not class_id:
                continue
            key = f"{class_id}:{row.get('school_year_id') or ''}"
            if key in seen:
                continue
            seen.add(key)

            class_doc = class_map.get(class_id) or {}
            school_year_id = row.get("school_year_id") or class_doc.get("school_year_id")
            school_year = year_map.get(school_year_id) or {}

            scopes.append({
                "classId": class_id,
                "schoolYearId": school_year_id,
                "classType": row.get("class_type") or class_doc.get("class_type"),
                "classTitle": class_doc.get("title") or class_doc.get("short_title") or class_id,
                "schoolYearTitle": school_year.get("title_vn") or school_year.get("title_en") or school_year_id,
                "campusId": class_doc.get("campus_id"),
            })

        return success_response(data={"scopes": scopes})
    except Exception as e:
        frappe.logger().error(f"[Parent Portal Journal] get_student_class_scopes error: {str(e)}")
        return error_response(message=_("Không thể lấy lịch sử lớp của học sinh"), code="JOURNAL_SCOPE_ERROR")


def _parse_class_chat_scope_payload():
    """Gộp form_dict + JSON body (POST từ social-service)."""
    d = dict(frappe.form_dict or {})
    if getattr(frappe, "request", None) and frappe.request.data:
        try:
            raw = frappe.request.data.decode("utf-8") if isinstance(frappe.request.data, bytes) else frappe.request.data
            body = json.loads(raw)
            if isinstance(body, dict):
                d.update(body)
        except Exception:
            pass
    return d


def _teacher_snapshot_for_chat(teacher_id, subjects=None, homeroom_role=None):
    """Ảnh chụp GVCN/Phó GVCN/GV bộ môn cho payload chat (không qua Resource API).

    `homeroom_role` = 'homeroom' | 'vice_homeroom' (rỗng với GVBM). Bắt buộc phải TRUYỀN
    TƯỜNG MINH: trước đây vai trò chỉ nằm ở thứ tự [homeroom, vice] của mảng `teachers`,
    nên mọi client đều không phân biệt được CN với phó và cùng hiển thị nhãn "GVCN".
    Thứ tự mảng không đáng tin (nhánh fallback Resource-API của social-service dựng
    danh sách bằng Promise.all + push) ⇒ phải là field riêng.
    """
    if not teacher_id:
        return None
    t = frappe.db.get_value(
        "SIS Teacher",
        teacher_id,
        ["user_id", "name"],
        as_dict=True,
    )
    if not t:
        return {
            "teacherId": teacher_id,
            "name": teacher_id,
            "email": "",
            "avatarUrl": "",
            "userId": "",
            "userName": "",
            "phone_number": "",
            "homeroom_role": homeroom_role or "",
            "subjects": subjects or [],
        }
    user_id = t.get("user_id")
    user = None
    if user_id:
        user = frappe.db.get_value(
            "User",
            user_id,
            ["name", "email", "full_name", "user_image", "mobile_no"],
            as_dict=True,
        )
    return {
        "teacherId": teacher_id,
        "email": (user or {}).get("email") or user_id or "",
        "name": (user or {}).get("full_name") or user_id or teacher_id,
        "avatarUrl": (user or {}).get("user_image") or "",
        "userId": user_id or "",
        "userName": (user or {}).get("name") or user_id or "",
        # SĐT GV — panel thành viên chat hiển thị dưới tên (cùng dạng với PH).
        # CHỈ `mobile_no` (di động cá nhân). KHÔNG fallback `User.phone`: field đó do sync
        # Microsoft ghi từ `businessPhones` (xem microsoft_auth.py) nên GV không khai di động
        # trong AD sẽ hiện số tổng đài trường thay vì số của chính mình.
        "phone_number": (user or {}).get("mobile_no") or "",
        "homeroom_role": homeroom_role or "",
        "subjects": subjects or [],
    }


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def get_class_chat_scope(class_id=None, school_year_id=None):
    """
    Scope lớp + roster (học sinh, PHHS, GVCN) cho social-service khi Resource API trả 403.
    Chỉ trả dữ liệu nếu ít nhất một học sinh của PH đang học lớp+năm này.
    """
    try:
        payload = _parse_class_chat_scope_payload()
        class_id = class_id or payload.get("class_id")
        school_year_id = school_year_id or payload.get("school_year_id")

        if not class_id:
            return error_response(message="Thiếu class_id", code="MISSING_CLASS")
        if not school_year_id:
            return error_response(message="Thiếu school_year_id", code="MISSING_SCHOOL_YEAR")

        parent_email = get_parent_portal_user_from_request()
        if not parent_email:
            return error_response(message="Vui lòng đăng nhập", code="NOT_AUTHENTICATED")

        allowed_students = _get_parent_student_ids(parent_email)
        if not allowed_students:
            return error_response(message="Không tìm thấy học sinh liên kết", code="NO_STUDENTS")

        in_class = frappe.get_all(
            "SIS Class Student",
            filters={
                "class_id": class_id,
                "school_year_id": school_year_id,
                "student_id": ["in", allowed_students],
            },
            limit=1,
            ignore_permissions=True,
        )
        if not in_class:
            return error_response(
                message="Bạn không có quyền xem nhóm chat lớp này",
                code="ACCESS_DENIED",
            )

        cls = frappe.db.get_value(
            "SIS Class",
            class_id,
            ["name", "title", "short_title", "school_year_id", "class_type", "homeroom_teacher", "vice_homeroom_teacher"],
            as_dict=True,
        )
        if not cls:
            return error_response(message="Không tìm thấy lớp", code="CLASS_NOT_FOUND")

        sy_title = frappe.db.get_value(
            "SIS School Year",
            school_year_id,
            ["title_vn", "title_en"],
            as_dict=True,
        ) or {}
        school_year_name = sy_title.get("title_vn") or sy_title.get("title_en") or school_year_id

        class_student_rows = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id, "school_year_id": school_year_id},
            fields=["student_id"],
            ignore_permissions=True,
            limit_page_length=10000,
        )
        student_ids = [r.student_id for r in class_student_rows if r.get("student_id")]

        # Batch 1 query thay vì get_value từng HS (API nóng Parent Portal)
        student_map = {}
        if student_ids:
            for row in frappe.get_all(
                "CRM Student",
                filters={"name": ["in", student_ids]},
                fields=["name", "student_name", "student_code", "family_code"],
                ignore_permissions=True,
                limit_page_length=10000,
            ):
                student_map[row.name] = row

        students_out = []
        for sid in student_ids:
            row = student_map.get(sid) or {}
            students_out.append({
                "student_id": sid,
                "student_name": row.get("student_name"),
                "student_code": row.get("student_code"),
                "family_code": row.get("family_code"),
            })

        # access_only: cùng roster nhóm chat lớp với chat_scope._build_class_chat_scope nên
        # phải cùng bộ lọc cờ "Xem thông tin". Read-path này UNION membership, lỏng hơn là
        # add lại đúng những PH mà luồng sync vừa revoke.
        guardians = build_guardians_by_student_ids(student_ids, access_only=True)

        teachers = []
        for tid, hr_role in [
            (cls.get("homeroom_teacher"), "homeroom"),
            (cls.get("vice_homeroom_teacher"), "vice_homeroom"),
        ]:
            snap = _teacher_snapshot_for_chat(tid, homeroom_role=hr_role)
            if snap:
                teachers.append(snap)

        # Giáo viên bộ môn phân công vào lớp (dùng social-service / parent hiển thị avatar GV)
        sa_filters = {"class_id": class_id}
        if school_year_id:
            sa_filters["school_year_id"] = school_year_id
        subject_rows = frappe.get_all(
            "SIS Subject Assignment",
            filters=sa_filters,
            fields=["teacher_id", "actual_subject_id"],
            ignore_permissions=True,
            limit_page_length=2000,
        )
        # Map teacher_id -> [{id,title}] và resolve title môn 1 lần.
        subj_ids = {r.get("actual_subject_id") for r in subject_rows if r.get("actual_subject_id")}
        subj_title_map = {}
        if subj_ids:
            for sid, title_vn, title_en in frappe.db.get_values(
                "SIS Actual Subject",
                {"name": ["in", list(subj_ids)]},
                ["name", "title_vn", "title_en"],
            ) or []:
                subj_title_map[sid] = title_vn or title_en or sid
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

        scope = {
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

        return success_response(data=scope, message="OK")
    except Exception as e:
        frappe.logger().error(f"[Parent Portal Journal] get_class_chat_scope error: {str(e)}")
        return error_response(message=_("Không thể tải scope chat lớp"), code="CLASS_CHAT_SCOPE_ERROR")
