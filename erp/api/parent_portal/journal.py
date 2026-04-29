"""
Parent Portal Journal API
Trả về phạm vi lớp/năm học mà phụ huynh được phép xem Nhật ký.
"""

import frappe
from frappe import _
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


@frappe.whitelist(allow_guest=False)
def get_student_class_scopes(student_id=None):
    """
    Lấy toàn bộ lớp/năm học học sinh từng học để social-service lọc bài Nhật ký.
    Endpoint này tự kiểm tra học sinh thuộc phụ huynh, sau đó đọc SIS bằng ignore_permissions.
    """
    try:
        student_id = student_id or frappe.form_dict.get("student_id")
        if not student_id:
            return error_response(message="Thiếu student_id", code="MISSING_STUDENT")

        allowed_students = _get_parent_student_ids(frappe.session.user)
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

            class_doc = frappe.db.get_value(
                "SIS Class",
                class_id,
                ["title", "short_title", "school_year_id", "campus_id", "class_type"],
                as_dict=True,
            ) or {}
            school_year_id = row.get("school_year_id") or class_doc.get("school_year_id")
            school_year = {}
            if school_year_id:
                school_year = frappe.db.get_value(
                    "SIS School Year",
                    school_year_id,
                    ["title_vn", "title_en"],
                    as_dict=True,
                ) or {}

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
