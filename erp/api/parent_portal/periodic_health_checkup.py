# Copyright (c) 2026, Wellspring International School and contributors
"""
Phiếu khám sức khỏe định kỳ đã công bố — Parent Portal (chỉ approval_status = published).
"""

import json

import frappe

from erp.api.parent_portal.report_card import _get_parent_student_ids
from erp.api.erp_sis.health_checkup_images import get_health_checkup_image_urls_for_checkup
from erp.utils.api_response import error_response, success_response

# Không trả về client PH
_WORKFLOW_FIELDS = frozenset(
    {
        "approval_status",
        "returned_from_level",
        "last_rejection_comment",
        "submitted_at",
        "submitted_by",
        "l2_action_at",
        "l2_action_by",
        "l3_action_at",
        "l3_action_by",
        "health_checkup_images_folder",
        "revoked_at",
        "revoked_by",
    }
)


def _parse_request_student_id():
    student_id = frappe.form_dict.get("student_id") or frappe.request.args.get("student_id")
    if not student_id and frappe.request.data:
        try:
            raw = frappe.request.data
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            if body and body.strip():
                data = json.loads(body)
                if isinstance(data, dict):
                    student_id = data.get("student_id")
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return student_id


def _checkup_table_exists():
    try:
        return bool(frappe.db.sql("SHOW TABLES LIKE 'tabSIS Student Health Checkup'"))
    except Exception:
        return False


def _has_approval_column():
    try:
        return frappe.db.has_column("SIS Student Health Checkup", "approval_status")
    except Exception:
        return False


def _get_regular_class_for_year(student_id, school_year_id):
    rows = frappe.db.sql(
        """
        SELECT c.name AS class_id, c.title AS class_name
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
        WHERE cs.student_id = %(student_id)s
            AND cs.school_year_id = %(school_year_id)s
            AND IFNULL(c.class_type, 'regular') = 'regular'
        LIMIT 1
        """,
        {"student_id": student_id, "school_year_id": school_year_id},
        as_dict=True,
    )
    return rows[0] if rows else None


def _strip_workflow_fields(row):
    if not row:
        return row
    out = dict(row)
    for k in _WORKFLOW_FIELDS:
        out.pop(k, None)
    return out


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_parent_published_periodic_checkups():
    """
    Trả về các phiếu khám SK định kỳ đã công bố (published) của học sinh mà PH được quyền xem.

    Params: student_id (query hoặc JSON body).

    Response data.items: mỗi phần tử gồm checkup (đã bỏ field workflow nội bộ),
    school_year_title_vn, class_name (lớp regular trong năm đó),
    reference_checkup_data (chỉ khi đợt cuối năm và có phiếu đầu năm published).
    """
    try:
        student_id = _parse_request_student_id()
        if not student_id:
            return error_response(
                message="Thiếu student_id",
                code="MISSING_PARAMS",
                logs=["student_id is required"],
            )

        parent_email = frappe.session.user
        if student_id not in (_get_parent_student_ids(parent_email) or []):
            return error_response(
                message="Không có quyền xem dữ liệu học sinh này",
                code="PERMISSION_DENIED",
                logs=[f"Student {student_id} not linked to parent"],
            )

        if not _checkup_table_exists() or not _has_approval_column():
            return success_response(
                data={"items": []},
                message="Chưa cấu hình phiếu khám SK định kỳ",
            )

        rows = frappe.db.sql(
            """
            SELECT *
            FROM `tabSIS Student Health Checkup`
            WHERE student_id = %(student_id)s AND approval_status = 'published'
            ORDER BY school_year_id DESC,
                CASE WHEN checkup_phase = 'end' THEN 0 ELSE 1 END ASC,
                name DESC
            """,
            {"student_id": student_id},
            as_dict=True,
        )

        st = frappe.db.get_value(
            "CRM Student",
            student_id,
            ["student_name", "student_code", "gender", "dob"],
            as_dict=True,
        )

        items = []
        for row in rows:
            sy = row.get("school_year_id")
            sy_title = None
            if sy:
                sy_title = frappe.db.get_value("SIS School Year", sy, "title_vn") or sy

            cls = _get_regular_class_for_year(student_id, sy) if sy else None
            class_name = cls.get("class_name") if cls else None

            checkup = _strip_workflow_fields(row)

            ref = None
            if row.get("checkup_phase") == "end" and sy:
                ref_row = frappe.db.get_value(
                    "SIS Student Health Checkup",
                    {
                        "student_id": student_id,
                        "school_year_id": sy,
                        "checkup_phase": "beginning",
                        "approval_status": "published",
                    },
                    ["*"],
                    as_dict=True,
                )
                if ref_row:
                    ref = _strip_workflow_fields(ref_row)

            image_urls = get_health_checkup_image_urls_for_checkup(row.get("name"))
            items.append(
                {
                    "checkup": checkup,
                    "school_year_id": sy,
                    "school_year_title_vn": sy_title,
                    "class_name": class_name,
                    "student": st,
                    "reference_checkup_data": ref,
                    "has_images": len(image_urls) > 0,
                    "images_folder": row.get("health_checkup_images_folder"),
                    "image_urls": image_urls,
                }
            )

        return success_response(
            data={"items": items, "total": len(items)},
            message=f"Lấy {len(items)} phiếu khám định kỳ",
        )
    except Exception as e:
        frappe.log_error(f"get_parent_published_periodic_checkups: {str(e)}")
        return error_response(
            message="Không thể tải phiếu khám định kỳ",
            code="FETCH_PERIODIC_CHECKUP_ERROR",
        )


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def get_parent_health_checkup_images():
    """
    Danh sách URL ảnh phiếu khám định kỳ (chỉ khi published + PH được quyền xem HS).

    Params: student_id, checkup_name (query hoặc JSON body).
    """
    try:
        student_id = _parse_request_student_id()
        checkup_name = frappe.form_dict.get("checkup_name") or frappe.request.args.get("checkup_name")
        if not checkup_name and frappe.request.data:
            try:
                raw = frappe.request.data
                body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                if body and body.strip():
                    data = json.loads(body)
                    if isinstance(data, dict):
                        checkup_name = data.get("checkup_name")
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        if not student_id or not checkup_name:
            return error_response(
                message="Thiếu student_id hoặc checkup_name",
                code="MISSING_PARAMS",
            )

        parent_email = frappe.session.user
        if student_id not in (_get_parent_student_ids(parent_email) or []):
            return error_response(message="Không có quyền xem", code="PERMISSION_DENIED")

        stu = frappe.db.get_value(
            "SIS Student Health Checkup",
            checkup_name,
            ["student_id", "approval_status"],
            as_dict=True,
        )
        if not stu or stu.get("student_id") != student_id:
            return error_response(message="Phiếu không hợp lệ", code="NOT_FOUND")
        if stu.get("approval_status") != "published":
            return success_response(
                data={"checkup_name": checkup_name, "image_urls": [], "has_images": False},
                message="Phiếu chưa được công bố",
            )

        image_urls = get_health_checkup_image_urls_for_checkup(checkup_name)
        return success_response(
            data={
                "checkup_name": checkup_name,
                "image_urls": image_urls,
                "has_images": len(image_urls) > 0,
                "total_pages": len(image_urls),
            },
            message="OK",
        )
    except Exception as e:
        frappe.log_error(f"get_parent_health_checkup_images: {str(e)}")
        return error_response(message=str(e), code="FETCH_IMAGES_ERROR")
