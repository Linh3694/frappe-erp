# -*- coding: utf-8 -*-
"""
Report Card Template APIs
=========================

CRUD APIs cho Report Card Template.
"""

import frappe
from frappe import _
import json
from typing import Optional

from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

from .utils import get_request_payload, get_current_campus_id
from .serializers import (
    doc_to_template_dict,
    apply_scores,
    apply_homeroom_titles,
    apply_subjects,
    save_test_point_titles_manually,
)


@frappe.whitelist(allow_guest=False)
def get_all_templates(
    page: int = 1, 
    limit: int = 20, 
    include_all_campuses: int = 0, 
    school_year: Optional[str] = None,
    curriculum: Optional[str] = None, 
    education_stage: Optional[str] = None,
    education_grade: Optional[str] = None, 
    is_published: Optional[int] = None
):
    """
    Lấy danh sách templates với pagination và filters.
    
    Args:
        page: Số trang (mặc định 1)
        limit: Số items mỗi trang (mặc định 20)
        include_all_campuses: Bao gồm tất cả campuses của user (0/1)
        school_year: Filter theo năm học
        curriculum: Filter theo chương trình
        education_stage: Filter theo cấp học
        education_grade: Filter theo khối
        is_published: Filter theo trạng thái published (0/1)
    
    Returns:
        Paginated response với danh sách templates
    """
    try:
        page = int(page or 1)
        limit = int(limit or 20)
        include_all_campuses = int(include_all_campuses or 0)
        offset = (page - 1) * limit

        # Build filters
        if include_all_campuses:
            from erp.utils.campus_utils import get_campus_filter_for_all_user_campuses
            filters = get_campus_filter_for_all_user_campuses()
        else:
            filters = {"campus_id": get_current_campus_id()}

        # Optional filters
        if school_year:
            filters["school_year"] = school_year
        if curriculum:
            filters["curriculum"] = curriculum
        if education_stage:
            filters["education_stage"] = education_stage
        if education_grade:
            filters["education_grade"] = education_grade
        if is_published is not None and str(is_published) != "":
            filters["is_published"] = int(is_published)

        rows = frappe.get_all(
            "SIS Report Card Template",
            fields=[
                "name", "title", "campus_id", "curriculum", "education_stage",
                "education_grade", "school_year", "semester_part", "is_published",
                "creation", "modified", "owner",
            ],
            filters=filters,
            order_by="modified desc",
            limit_start=offset,
            limit_page_length=limit,
        )

        # Lấy full_name của owner từ bảng User
        owner_emails = list(set([r.get("owner") for r in rows if r.get("owner")]))
        owner_map = {}
        if owner_emails:
            users = frappe.get_all(
                "User",
                filters={"name": ["in", owner_emails]},
                fields=["name", "full_name"]
            )
            owner_map = {u["name"]: u.get("full_name") or u["name"] for u in users}
        
        # Thêm owner_full_name vào mỗi row
        for row in rows:
            row["owner_full_name"] = owner_map.get(row.get("owner"), row.get("owner"))

        total_count = frappe.db.count("SIS Report Card Template", filters=filters)
        return paginated_response(
            data=rows,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Templates fetched successfully",
        )
    except Exception as e:
        frappe.log_error(f"Error fetching report card templates: {str(e)}")
        return error_response("Error fetching report card templates")


@frappe.whitelist(allow_guest=False)
def get_template_by_id(template_id: Optional[str] = None):
    """
    Lấy chi tiết một template theo ID.
    
    Args:
        template_id: ID của template
    
    Returns:
        Single item response với chi tiết template
    """
    try:
        # Resolve template_id từ nhiều nguồn
        if not template_id:
            form = frappe.local.form_dict or {}
            template_id = (
                form.get("template_id")
                or form.get("name")
                or (frappe.request.args.get("template_id") 
                    if getattr(frappe, "request", None) and getattr(frappe.request, "args", None) 
                    else None)
            )
        if not template_id:
            payload = get_request_payload()
            template_id = payload.get("template_id") or payload.get("name")

        if not template_id:
            return validation_error_response(
                message="Template ID is required", 
                errors={"template_id": ["Required"]}
            )

        campus_id = get_current_campus_id()
        try:
            doc = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")

        if doc.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        return single_item_response(doc_to_template_dict(doc), "Template fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error fetching report card template {template_id}: {str(e)}")
        return error_response("Error fetching report card template")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_template():
    """
    Tạo mới một Report Card Template.
    
    Request payload: Xem ReportCard.md documentation
    
    Returns:
        Single item response với template đã tạo
    """
    try:
        data = get_request_payload()

        # Required fields validation
        required = ["title", "school_year", "education_stage", "semester_part"]
        missing = [f for f in required if not (data.get(f) and str(data.get(f)).strip())]
        if missing:
            return validation_error_response(
                message="Missing required fields", 
                errors={k: ["Required"] for k in missing}
            )

        campus_id = get_current_campus_id()

        # Duplicate check
        class_ids = data.get("class_ids")
        
        if class_ids and isinstance(class_ids, list) and len(class_ids) > 0:
            # Template cho lớp cụ thể - check duplicate theo class_ids
            class_ids_json = json.dumps(sorted(class_ids))
            
            existing_templates = frappe.get_all(
                "SIS Report Card Template",
                filters={
                    "campus_id": campus_id,
                    "school_year": data.get("school_year"),
                    "semester_part": data.get("semester_part"),
                    "program_type": (data.get("program_type") or "vn"),
                },
                fields=["name", "title", "class_ids"]
            )
            
            for template in existing_templates:
                if template.get("class_ids"):
                    try:
                        existing_class_ids_json = json.dumps(sorted(json.loads(template.get("class_ids"))))
                        if existing_class_ids_json == class_ids_json:
                            program_type_label = "Chương trình Việt Nam" if (data.get("program_type") or "vn") == "vn" else "Chương trình Quốc tế"
                            return validation_error_response(
                                message=_("Template already exists for these specific classes"),
                                errors={"template": [f"Đã tồn tại template cho các lớp này: {program_type_label} - {data.get('semester_part')} - {data.get('school_year')}"]}
                            )
                    except (json.JSONDecodeError, TypeError):
                        continue
        else:
            # Template cho toàn khối - check duplicate theo title
            existing = frappe.db.exists(
                "SIS Report Card Template",
                {
                    "title": (data.get("title") or "").strip(),
                    "campus_id": campus_id,
                    "school_year": data.get("school_year"),
                    "semester_part": data.get("semester_part"),
                    "program_type": (data.get("program_type") or "vn"),
                },
            )
            if existing:
                program_type_label = "Chương trình Việt Nam" if (data.get("program_type") or "vn") == "vn" else "Chương trình Quốc tế"
                return validation_error_response(
                    message=_("Template already exists for this school year, semester and program type"),
                    errors={"template": [f"Đã tồn tại template cho {program_type_label} - {data.get('semester_part')} - {data.get('school_year')}"]}
                )

        # Create doc
        doc_data = {
            "doctype": "SIS Report Card Template",
            "title": (data.get("title") or "").strip(),
            "is_published": 1 if data.get("is_published") else 0,
            "program_type": (data.get("program_type") or "vn"),
            "form_id": data.get("form_id"),
            "curriculum": data.get("curriculum"),
            "education_stage": data.get("education_stage"),
            "school_year": data.get("school_year"),
            "education_grade": data.get("education_grade"),
            "semester_part": data.get("semester_part"),
            "campus_id": campus_id,
            "scores_enabled": 1 if data.get("scores_enabled") else 0,
            "academic_ranking": data.get("academic_ranking"),
            "academic_ranking_year": data.get("academic_ranking_year"),
            "student_achievement": data.get("student_achievement"),
            "homeroom_enabled": 1 if data.get("homeroom_enabled") else 0,
            "homeroom_conduct_enabled": 1 if data.get("homeroom_conduct_enabled") else 0,
            "homeroom_conduct_year_enabled": 1 if data.get("homeroom_conduct_year_enabled") else 0,
            "conduct_ranking": data.get("conduct_ranking"),
            "conduct_ranking_year": data.get("conduct_ranking_year"),
            # Homeroom Approvers
            "homeroom_reviewer_level_1": data.get("homeroom_reviewer_level_1") or None,
            "homeroom_reviewer_level_2": data.get("homeroom_reviewer_level_2") or None,
            "subject_eval_enabled": 1 if data.get("subject_eval_enabled") else 0,
        }
        
        # Save homeroom_comment_options snapshot
        if "homeroom_comment_options" in data and data.get("homeroom_comment_options") is not None:
            doc_data["homeroom_comment_options"] = json.dumps(data.get("homeroom_comment_options"))
        
        # Add class_ids
        if class_ids and isinstance(class_ids, list) and len(class_ids) > 0:
            doc_data["class_ids"] = json.dumps(class_ids)
        
        doc = frappe.get_doc(doc_data)

        # Apply child tables
        apply_scores(doc, data.get("scores") or [])
        apply_homeroom_titles(doc, data.get("homeroom_titles") or [])
        apply_subjects(doc, data.get("subjects") or [])

        doc.insert(ignore_permissions=True)
        
        # Manual save test_point_titles (nested child table)
        save_test_point_titles_manually(doc)
        
        frappe.db.commit()

        created = frappe.get_doc("SIS Report Card Template", doc.name)
        return single_item_response(doc_to_template_dict(created), "Template created successfully")
        
    except frappe.LinkValidationError as e:
        error_msg = str(e)
        frappe.logger().error(f"Link validation error creating template: {error_msg}")
        
        if "Tiêu đề nhận xét" in error_msg or "comment title" in error_msg.lower():
            return error_response(
                message="Không thể tạo mẫu báo cáo: Một hoặc nhiều tiêu đề nhận xét không tồn tại hoặc đã bị xóa.",
                code="COMMENT_TITLE_NOT_FOUND"
            )
        elif "Môn học" in error_msg or "actual subject" in error_msg.lower():
            return error_response(
                message="Không thể tạo mẫu báo cáo: Một hoặc nhiều môn học không tồn tại hoặc đã bị xóa.",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        else:
            return error_response(
                message=f"Lỗi liên kết dữ liệu: {error_msg}",
                code="LINK_VALIDATION_ERROR"
            )
    except frappe.CharacterLengthExceededError:
        return error_response(
            message="Tiêu đề quá dài. Vui lòng rút ngắn tiêu đề và thử lại.",
            code="TITLE_TOO_LONG"
        )
    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Unexpected error creating template: {error_msg}")
        return error_response(
            message=f"Lỗi hệ thống khi tạo mẫu báo cáo: {error_msg}",
            code="TEMPLATE_CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_template(template_id: Optional[str] = None):
    """
    Cập nhật một Report Card Template.
    
    Args:
        template_id: ID của template cần cập nhật
    
    Returns:
        Success response với template đã cập nhật
    """
    try:
        data = get_request_payload()
        template_id = template_id or data.get("template_id") or data.get("name")
        if not template_id:
            return validation_error_response(
                message="Template ID is required", 
                errors={"template_id": ["Required"]}
            )

        campus_id = get_current_campus_id()
        try:
            doc = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")

        if doc.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Update scalar fields
        scalar_fields = [
            "title", "is_published", "program_type", "form_id", "curriculum",
            "education_stage", "school_year", "education_grade", "semester_part",
            "scores_enabled", "academic_ranking", "academic_ranking_year",
            "student_achievement", "homeroom_enabled", "homeroom_conduct_enabled",
            "homeroom_conduct_year_enabled", "conduct_ranking", "conduct_ranking_year",
            # Homeroom Approvers
            "homeroom_reviewer_level_1", "homeroom_reviewer_level_2",
            "subject_eval_enabled", "intl_overall_mark_enabled", "intl_overall_grade_enabled",
            "intl_comment_enabled", "intl_scoreboard_enabled",
        ]
        
        boolean_fields = [
            "is_published", "scores_enabled", "homeroom_enabled", "subject_eval_enabled",
            "intl_overall_mark_enabled", "intl_overall_grade_enabled", "intl_comment_enabled",
            "intl_scoreboard_enabled", "homeroom_conduct_enabled", "homeroom_conduct_year_enabled"
        ]
        
        for field in scalar_fields:
            if field in data:
                value = data.get(field)
                if field in boolean_fields:
                    value = 1 if value else 0
                if field == "program_type":
                    value = "intl" if str(value).lower() == "intl" else "vn"
                doc.set(field, value)

        # Auto-set intl_scoreboard_enabled based on program_type
        if "program_type" in data:
            program_type = data.get("program_type", "vn")
            if program_type == "intl":
                doc.set("intl_scoreboard_enabled", 1)
            elif program_type == "vn":
                doc.set("intl_scoreboard_enabled", 0)

        # Handle class_ids
        if "class_ids" in data:
            class_ids = data.get("class_ids")
            if class_ids and isinstance(class_ids, list) and len(class_ids) > 0:
                doc.set("class_ids", json.dumps(class_ids))
            else:
                doc.set("class_ids", None)

        # Handle homeroom_comment_options snapshot
        if "homeroom_comment_options" in data:
            if data.get("homeroom_comment_options") is not None:
                doc.set("homeroom_comment_options", json.dumps(data.get("homeroom_comment_options")))
            else:
                doc.set("homeroom_comment_options", None)

        # Replace child tables if provided
        if "scores" in data:
            apply_scores(doc, data.get("scores") or [])
        if "homeroom_titles" in data:
            apply_homeroom_titles(doc, data.get("homeroom_titles") or [])
        if "subjects" in data:
            apply_subjects(doc, data.get("subjects") or [])

        doc.save(ignore_permissions=True)
        
        # Manual save test_point_titles
        save_test_point_titles_manually(doc)
        
        frappe.db.commit()
        doc.reload()

        return success_response(data=doc_to_template_dict(doc), message="Template updated successfully")
        
    except frappe.LinkValidationError as e:
        error_msg = str(e)
        frappe.logger().error(f"Link validation error updating template {template_id}: {error_msg}")
        
        if "Tiêu đề nhận xét" in error_msg or "comment title" in error_msg.lower():
            return error_response(
                message="Không thể cập nhật mẫu báo cáo: Một hoặc nhiều tiêu đề nhận xét không tồn tại hoặc đã bị xóa.",
                code="COMMENT_TITLE_NOT_FOUND"
            )
        elif "Môn học" in error_msg or "actual subject" in error_msg.lower():
            return error_response(
                message="Không thể cập nhật mẫu báo cáo: Một hoặc nhiều môn học không tồn tại hoặc đã bị xóa.",
                code="ACTUAL_SUBJECT_NOT_FOUND"
            )
        else:
            return error_response(
                message=f"Lỗi liên kết dữ liệu: {error_msg}",
                code="LINK_VALIDATION_ERROR"
            )
    except frappe.CharacterLengthExceededError:
        return error_response(
            message="Tiêu đề quá dài. Vui lòng rút ngắn tiêu đề và thử lại.",
            code="TITLE_TOO_LONG"
        )
    except Exception as e:
        error_msg = str(e)
        frappe.logger().error(f"Unexpected error updating template {template_id}: {error_msg}")
        return error_response(
            message=f"Lỗi hệ thống khi cập nhật mẫu báo cáo: {error_msg}",
            code="TEMPLATE_UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_template(template_id: Optional[str] = None):
    """
    Xóa một Report Card Template (cascade delete linked reports).
    
    Args:
        template_id: ID của template cần xóa
    
    Returns:
        Success response hoặc confirmation request nếu có linked reports
    """
    try:
        # Resolve template_id
        if not template_id:
            form = frappe.local.form_dict or {}
            template_id = form.get("template_id") or form.get("name")
        if not template_id:
            payload = get_request_payload()
            template_id = payload.get("template_id") or payload.get("name")
        if not template_id:
            return validation_error_response(
                message="Template ID is required", 
                errors={"template_id": ["Required"]}
            )

        campus_id = get_current_campus_id()
        try:
            doc = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")

        if doc.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Check force_delete parameter
        payload = get_request_payload()
        force_delete = payload.get("force_delete", False)

        # Check linked Student Report Cards
        linked_reports = frappe.get_all(
            "SIS Student Report Card",
            fields=["name", "title", "student_id"],
            filters={"template_id": template_id}
        )

        if linked_reports and not force_delete:
            return {
                "success": False,
                "requires_confirmation": True,
                "message": f"Template có {len(linked_reports)} báo cáo học sinh liên kết. Xác nhận xóa tất cả?",
                "data": {
                    "linked_reports_count": len(linked_reports),
                    "sample_reports": linked_reports[:5],
                    "template_title": doc.title
                }
            }

        # Cascade delete linked reports
        deleted_reports = []
        failed_reports = []
        
        if linked_reports:
            for report in linked_reports:
                try:
                    frappe.delete_doc("SIS Student Report Card", report["name"], ignore_permissions=True)
                    deleted_reports.append(report["name"])
                except Exception as report_error:
                    failed_reports.append({
                        "report_id": report["name"],
                        "error": str(report_error)[:100]
                    })
                    frappe.logger().error(f"Failed to delete student report {report['name']}: {str(report_error)}")

        # Delete template
        frappe.delete_doc("SIS Report Card Template", template_id, ignore_permissions=True)
        frappe.db.commit()
        
        result_message = f"Template deleted successfully"
        if deleted_reports:
            result_message += f". Đã xóa {len(deleted_reports)} báo cáo học sinh liên kết"
        if failed_reports:
            result_message += f". {len(failed_reports)} báo cáo không thể xóa"

        return success_response(
            message=result_message,
            data={
                "deleted_reports_count": len(deleted_reports),
                "failed_reports_count": len(failed_reports),
                "failed_reports": failed_reports if failed_reports else None
            }
        )

    except Exception as e:
        error_msg = str(e)[:80] + "..." if len(str(e)) > 80 else str(e)
        frappe.log_error(f"Delete template {template_id[:10] if template_id else 'unknown'}...: {error_msg}")
        return error_response("Error deleting report card template")
