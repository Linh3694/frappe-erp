# -*- coding: utf-8 -*-
"""
Student Report Card APIs
========================

CRUD APIs cho Student Report Card (Học bạ học sinh).
"""

import frappe
import json
import copy
from typing import Any, Dict, List, Optional

from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

from .utils import (
    get_request_payload,
    get_current_campus_id,
    sanitize_float,
    resolve_actual_subject_title,
)
from .serializers import (
    normalize_intl_scores,
    initialize_report_data_from_template,
)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def sync_new_subjects_to_reports():
    """
    Sync subjects mới từ template vào các student report cards đã tạo.
    
    Use cases:
    1. Sau khi tạo reports: Thêm subjects mới cho tất cả học sinh
    2. Sau khi edit template: Thêm subjects mới vào reports hiện có
    
    Request payload:
        {
            "template_id": "TEMPLATE-XXX",
            "new_subject_ids": ["SIS_ACTUAL_SUBJECT-123"],  // Optional
            "class_ids": ["CLASS-A"],  // Optional
            "student_ids": ["STUDENT-1"],  // Optional
            "sections": ["scores", "subject_eval", "intl_scoreboard"],
            "dry_run": false
        }
    """
    try:
        data = get_request_payload()
        campus_id = get_current_campus_id()
        
        template_id = data.get("template_id")
        if not template_id:
            return validation_error_response(
                "Validation failed", 
                {"template_id": ["Template ID is required"]}
            )
        
        # Load template
        try:
            template = frappe.get_doc("SIS Report Card Template", template_id)
            if template.campus_id != campus_id:
                return forbidden_response("Template access denied")
        except frappe.DoesNotExistError:
            return not_found_response("Report card template not found")
        
        sections_to_sync = data.get("sections", ["scores", "subject_eval", "intl_scoreboard", "intl_scores"])
        dry_run = data.get("dry_run", False)
        
        # Get new_subject_ids
        new_subject_ids = data.get("new_subject_ids")
        if new_subject_ids and not isinstance(new_subject_ids, list):
            new_subject_ids = [new_subject_ids]
        
        # Build filters
        report_filters = {
            "template_id": template_id,
            "campus_id": campus_id,
            "status": ["!=", "published"]
        }
        
        if data.get("class_ids"):
            report_filters["class_id"] = ["in", data.get("class_ids")]
        if data.get("student_ids"):
            report_filters["student_id"] = ["in", data.get("student_ids")]
        
        # Get reports
        reports = frappe.get_all(
            "SIS Student Report Card",
            filters=report_filters,
            fields=["name", "student_id", "class_id", "data_json"]
        )
        
        if not reports:
            return success_response({
                "updated_reports": 0,
                "skipped_reports": 0,
                "message": "No reports found matching criteria"
            })
        
        # Determine subjects to sync
        if new_subject_ids:
            subjects_to_sync = set(new_subject_ids)
        else:
            subjects_to_sync = set()
            if hasattr(template, 'scores') and template.scores:
                for score_cfg in template.scores:
                    if score_cfg.subject_id:
                        subjects_to_sync.add(score_cfg.subject_id)
            
            if hasattr(template, 'subjects') and template.subjects:
                for subject_cfg in template.subjects:
                    if subject_cfg.subject_id:
                        subjects_to_sync.add(subject_cfg.subject_id)
        
        # Process reports
        updated_count = 0
        skipped_count = 0
        details = []
        all_new_subjects_added = set()
        
        for report in reports:
            try:
                data_json = json.loads(report.data_json or "{}")
                report_updated = False
                new_subjects_for_this_report = []
                
                # Sync scores section
                if "scores" in sections_to_sync and template.scores_enabled:
                    existing_scores = data_json.get("scores", {})
                    existing_subject_ids = set(existing_scores.keys())
                    new_subjects_in_scores = subjects_to_sync - existing_subject_ids
                    
                    if new_subjects_in_scores and hasattr(template, 'scores') and template.scores:
                        for score_cfg in template.scores:
                            subject_id = score_cfg.subject_id
                            
                            if subject_id in new_subjects_in_scores:
                                subject_title = (
                                    score_cfg.display_name
                                    or resolve_actual_subject_title(subject_id)
                                    or subject_id
                                )
                                
                                existing_scores[subject_id] = {
                                    "subject_title": subject_title,
                                    "display_name": subject_title,
                                    "subject_type": score_cfg.subject_type or "Môn tính điểm",
                                    "hs1_scores": [],
                                    "hs2_scores": [],
                                    "hs3_scores": [],
                                    "hs1_average": None,
                                    "hs2_average": None,
                                    "hs3_average": None,
                                    "final_average": None,
                                    "weight1_count": getattr(score_cfg, "weight1_count", 1) or 1,
                                    "weight2_count": getattr(score_cfg, "weight2_count", 1) or 1,
                                    "weight3_count": getattr(score_cfg, "weight3_count", 1) or 1
                                }
                                
                                report_updated = True
                                new_subjects_for_this_report.append(subject_id)
                                all_new_subjects_added.add(subject_id)
                        
                        data_json["scores"] = existing_scores
                
                # Sync subject_eval section
                if "subject_eval" in sections_to_sync and template.subject_eval_enabled:
                    existing_subject_eval = data_json.get("subject_eval", {})
                    existing_subject_ids = set(existing_subject_eval.keys())
                    new_subjects_in_eval = subjects_to_sync - existing_subject_ids
                    
                    if new_subjects_in_eval and hasattr(template, 'subjects') and template.subjects:
                        for subject_cfg in template.subjects:
                            subject_id = subject_cfg.subject_id
                            
                            if subject_id in new_subjects_in_eval:
                                subject_title = resolve_actual_subject_title(subject_id) or subject_id
                                
                                subject_data = {
                                    "subject_title": subject_title,
                                    "test_point_values": [],
                                    "criteria": {},
                                    "comments": {}
                                }
                                
                                existing_subject_eval[subject_id] = subject_data
                                report_updated = True
                                new_subjects_for_this_report.append(subject_id)
                                all_new_subjects_added.add(subject_id)
                        
                        data_json["subject_eval"] = existing_subject_eval
                
                # Sync intl_scoreboard/intl_scores section (handles both keys for consistency)
                # ✅ FIX: Accept both "intl_scoreboard" and "intl_scores" as valid section names
                should_sync_intl = ("intl_scoreboard" in sections_to_sync or "intl_scores" in sections_to_sync) and template.program_type == 'intl'
                if should_sync_intl:
                    # ✅ FIX: Sync vào cả intl_scoreboard (legacy) và intl_scores (current)
                    existing_intl_scoreboard = data_json.get("intl_scoreboard", {})
                    existing_intl_scores = data_json.get("intl_scores", {})
                    
                    # Check cả 2 để xác định subjects đã có
                    existing_subject_ids = set(existing_intl_scoreboard.keys()) | set(existing_intl_scores.keys())
                    new_subjects_in_intl = subjects_to_sync - existing_subject_ids
                    
                    if new_subjects_in_intl and hasattr(template, 'subjects') and template.subjects:
                        for subject_cfg in template.subjects:
                            subject_id = subject_cfg.subject_id
                            
                            if subject_id in new_subjects_in_intl:
                                subject_title = resolve_actual_subject_title(subject_id) or subject_id
                                subcurriculum_id = getattr(subject_cfg, 'subcurriculum_id', None) or 'none'
                                
                                scoreboard_data = {
                                    "subject_title": subject_title,
                                    "subcurriculum_id": subcurriculum_id,
                                    "subcurriculum_title_en": "General Program",
                                    "intl_comment": getattr(subject_cfg, 'intl_comment', None) or '',
                                    "main_scores": {}
                                }
                                
                                # ✅ FIX: Sync vào cả 2 keys để đảm bảo tương thích
                                existing_intl_scoreboard[subject_id] = scoreboard_data
                                existing_intl_scores[subject_id] = scoreboard_data.copy()
                                
                                report_updated = True
                                new_subjects_for_this_report.append(subject_id)
                                all_new_subjects_added.add(subject_id)
                        
                        data_json["intl_scoreboard"] = existing_intl_scoreboard
                        data_json["intl_scores"] = existing_intl_scores
                
                # Save if updated
                if report_updated:
                    if not dry_run:
                        frappe.db.set_value(
                            "SIS Student Report Card",
                            report.name,
                            "data_json",
                            json.dumps(data_json, ensure_ascii=False)
                        )
                    
                    updated_count += 1
                    details.append({
                        "report_id": report.name,
                        "student_id": report.student_id,
                        "class_id": report.class_id,
                        "new_subjects": new_subjects_for_this_report
                    })
                else:
                    skipped_count += 1
                
            except Exception as e:
                frappe.log_error(f"Error syncing report {report.name}: {str(e)}")
                skipped_count += 1
                details.append({
                    "report_id": report.name,
                    "error": str(e)
                })
        
        if not dry_run and updated_count > 0:
            frappe.db.commit()
        
        return success_response({
            "updated_reports": updated_count,
            "skipped_reports": skipped_count,
            "new_subjects_added": list(all_new_subjects_added),
            "total_reports": len(reports),
            "dry_run": dry_run,
            "details": details if dry_run else details[:10],
            "message": f"{'[DRY RUN] Would sync' if dry_run else 'Synced'} {updated_count} reports"
        })
        
    except Exception as e:
        frappe.log_error(f"Error in sync_new_subjects_to_reports: {str(e)}")
        return error_response(f"Failed to sync subjects: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def create_reports_for_class(template_id: Optional[str] = None, class_id: Optional[str] = None):
    """
    Tạo student report cards cho tất cả học sinh trong một lớp.
    
    Args:
        template_id: ID template
        class_id: ID lớp
    """
    try:
        data = get_request_payload()
        template_id = template_id or data.get("template_id")
        class_id = class_id or data.get("class_id")
        
        if not template_id or not class_id:
            errors = {}
            if not template_id:
                errors["template_id"] = ["Required"]
            if not class_id:
                errors["class_id"] = ["Required"]
            return validation_error_response(
                message="template_id and class_id are required", 
                errors=errors
            )

        campus_id = get_current_campus_id()
        template = frappe.get_doc("SIS Report Card Template", template_id)
        if template.campus_id != campus_id:
            return forbidden_response("Access denied: Template belongs to another campus")

        # Get students
        students = frappe.get_all(
            "SIS Class Student",
            fields=["name", "student_id"],
            filters={"class_id": class_id, "campus_id": campus_id}
        )

        created: List[str] = []
        failed_students: List[Dict[str, Any]] = []
        skipped_students: List[str] = []
        logs: List[str] = []
        
        for row in students:
            resolved_student_id = row.get("student_id")
            
            # Validate student exists
            exists_in_student = False
            try:
                if resolved_student_id:
                    exists_in_student = bool(frappe.db.exists("CRM Student", resolved_student_id))
            except Exception:
                exists_in_student = False

            if not exists_in_student:
                # Try mapping by student_code
                sid = row.get("student_id")
                if isinstance(sid, str) and sid:
                    try:
                        mapped = frappe.db.get_value("CRM Student", {"student_code": sid}, "name")
                        if mapped:
                            resolved_student_id = mapped
                            exists_in_student = True
                    except Exception:
                        pass

            # Check duplicate - Fixed: Batch query templates thay vì N+1
            existing_reports = frappe.get_all(
                "SIS Student Report Card",
                fields=["name", "template_id"],
                filters={
                    "student_id": resolved_student_id,
                    "school_year": template.school_year,
                    "semester_part": template.semester_part,
                    "campus_id": campus_id,
                }
            )
            
            program_type_conflict = False
            current_program_type = getattr(template, "program_type", "vn") or "vn"
            
            # FIX N+1: Batch fetch program_type của tất cả templates
            if existing_reports:
                existing_template_ids = [r.get("template_id") for r in existing_reports if r.get("template_id")]
                if existing_template_ids:
                    existing_templates = frappe.get_all(
                        "SIS Report Card Template",
                        filters={"name": ["in", existing_template_ids]},
                        fields=["name", "program_type"]
                    )
                    template_program_map = {t.name: (t.program_type or "vn") for t in existing_templates}
                    
                    for existing_report in existing_reports:
                        existing_program_type = template_program_map.get(existing_report.get("template_id"), "vn")
                        if existing_program_type == current_program_type:
                            program_type_conflict = True
                            break
            
            if program_type_conflict:
                program_type_label = "Chương trình Việt Nam" if current_program_type == "vn" else "Chương trình Quốc tế"
                skipped_students.append(resolved_student_id or row.get("student_id") or row.get("name"))
                logs.append(
                    f"Student {resolved_student_id} already has {program_type_label} report. Skipped."
                )
                continue

            # Initialize data from template
            try:
                from erp.api.erp_sis.student_subject import _initialize_report_data_from_template as init_with_student_filter
                initial_data = init_with_student_filter(template, resolved_student_id, class_id)
            except ImportError:
                initial_data = initialize_report_data_from_template(template, class_id)
            
            # Create report
            doc = frappe.get_doc({
                "doctype": "SIS Student Report Card",
                "title": template.title,
                "template_id": template.name,
                "form_id": template.form_id,
                "class_id": class_id,
                "student_id": resolved_student_id,
                "school_year": template.school_year,
                "semester_part": template.semester_part,
                "status": "draft",
                "campus_id": campus_id,
                "data_json": json.dumps(initial_data, ensure_ascii=False),
            })
            try:
                doc.insert(ignore_permissions=True)
                created.append(doc.name)
                logs.append(f"Created report {doc.name} for student {resolved_student_id}")
            except Exception as insert_err:
                frappe.log_error(f"Insert failed for {resolved_student_id}: {str(insert_err)}")
                failed_students.append({
                    "student_id": resolved_student_id,
                    "error": str(insert_err),
                })
                logs.append(f"Failed to create report for student {resolved_student_id}: {str(insert_err)}")

        frappe.db.commit()

        return success_response({
            "created": created,
            "failed": failed_students,
            "skipped": skipped_students,
            "total_students": len(students),
            "logs": logs
        })

    except Exception as e:
        frappe.log_error(f"create_reports_for_class error: {str(e)}")
        return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def get_reports_by_class():
    """Lấy danh sách student report cards của một lớp."""
    campus_id = get_current_campus_id()
    
    class_id = frappe.form_dict.get("class_id")
    if not class_id and hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
        class_id = frappe.request.args.get("class_id")
    
    if not class_id:
        return validation_error_response(
            message="class_id is required", 
            errors={"class_id": ["Required"]}
        )
    
    filters = {
        "campus_id": campus_id,
        "class_id": class_id
    }
    
    # Optional filters - ✅ FIX: Also check request.args for GET params
    template_id = frappe.form_dict.get("template_id")
    if not template_id and hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
        template_id = frappe.request.args.get("template_id")
    
    if template_id:
        filters["template_id"] = template_id
            
    school_year = frappe.form_dict.get("school_year")
    if school_year:
        filters["school_year"] = school_year
    
    semester_part = frappe.form_dict.get("semester_part")
    if semester_part:
        filters["semester_part"] = semester_part
    
    reports = frappe.get_all(
        "SIS Student Report Card",
        fields=[
            "name", "title", "template_id", "form_id", "class_id", "student_id",
            "school_year", "semester_part", "status", "creation", "modified", 
            "pdf_file", "is_approved", "approval_status",
            "rejection_reason", "rejected_by", "rejected_at",
            # ✅ Thêm rejected_section và rejected_from_level để highlight student bị reject
            "rejected_section", "rejected_from_level",
            # Thêm section-specific rejection info
            "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
            "scores_rejection_reason", "scores_rejected_by", "scores_rejected_at",
            # Thêm các fields approval status theo section
            "homeroom_approval_status", "homeroom_submitted_at", "homeroom_submitted_by",
            "scores_approval_status", "scores_submitted_at", "scores_submitted_by"
        ],
        filters=filters,
        order_by="modified desc"
    )
    
    page = int(frappe.form_dict.get("page", 1))
    # ✅ FIX: Accept both "limit" and "page_size" for compatibility
    page_size = int(frappe.form_dict.get("page_size") or frappe.form_dict.get("limit") or 200)
    total = len(reports)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = reports[start:end]
    
    # Load data_json riêng cho các reports trong page (vì frappe.get_all không trả về Long Text đầy đủ)
    if paginated:
        report_names = [r["name"] for r in paginated]
        data_json_records = frappe.db.sql("""
            SELECT name, data_json 
            FROM `tabSIS Student Report Card` 
            WHERE name IN %s
        """, [report_names], as_dict=True)
        
        data_json_map = {r["name"]: r["data_json"] for r in data_json_records}
        for report in paginated:
            report["data_json"] = data_json_map.get(report["name"])
    
    return paginated_response(paginated, total, page, page_size)


@frappe.whitelist(allow_guest=False, methods=["GET"])
def list_reports():
    """List student report cards với filters."""
    campus_id = get_current_campus_id()
    filters = {"campus_id": campus_id}

    # Optional filters
    for field in ["class_id", "template_id", "student_id", "status", "school_year", "semester_part"]:
        value = frappe.form_dict.get(field)
        if value:
            filters[field] = value

    reports = frappe.get_all(
        "SIS Student Report Card",
        fields=[
            "name", "title", "template_id", "form_id", "class_id", "student_id",
            "school_year", "semester_part", "status", "creation", "modified"
        ],
        filters=filters,
        order_by="modified desc"
    )

    page = int(frappe.form_dict.get("page", 1))
    page_size = int(frappe.form_dict.get("page_size", 20))
    total = len(reports)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = reports[start:end]

    return paginated_response(paginated, total, page, page_size)


@frappe.whitelist(allow_guest=False)
def get_report(report_id=None, **kwargs):
    """Lấy chi tiết một student report card."""
    if not report_id:
        report_id = frappe.form_dict.get("report_id")
    if not report_id:
        report_id = kwargs.get("report_id")
    if not report_id and hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
        report_id = frappe.request.args.get("report_id")
    
    if not report_id:
        return validation_error_response(
            message="report_id is required", 
            errors={"report_id": ["Required"]}
        )

    campus_id = get_current_campus_id()
    report = frappe.get_all(
        "SIS Student Report Card",
        fields=[
            "name", "title", "template_id", "form_id", "class_id", "student_id",
            "school_year", "semester_part", "status", "data_json", "creation", "modified",
            # Approval status fields
            "approval_status", "homeroom_approval_status", "scores_approval_status",
            # Rejection fields (chung)
            "rejection_reason", "rejected_by", "rejected_at", "rejected_section", "rejected_from_level",
            # Rejection fields (homeroom-specific)
            "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
            # Rejection fields (scores-specific)
            "scores_rejection_reason", "scores_rejected_by", "scores_rejected_at"
        ],
        filters={"name": report_id, "campus_id": campus_id}
    )

    if not report:
        return not_found_response("Report card not found")

    item = report[0]
    try:
        data_json = json.loads(item.get("data_json") or "{}")
    except Exception:
        data_json = {}
    
    item["data"] = data_json
    item["data_json"] = data_json

    return single_item_response(item)


@frappe.whitelist(allow_guest=False)
def get_report_by_id(**kwargs):
    """Alias cho get_report."""
    return get_report(**kwargs)


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_report_section():
    """
    Cập nhật một section cụ thể của student report card.
    
    Sections: scores, homeroom, subject_eval, intl_scores
    Sử dụng DEEP MERGE để tránh mất dữ liệu.
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        section = data.get("section")
        payload = data.get("payload") or {}
        
        if not report_id:
            return validation_error_response(
                message="report_id is required", 
                errors={"report_id": ["Required"]}
            )
        if not section:
            return validation_error_response(
                message="section is required", 
                errors={"section": ["Required"]}
            )
        
        campus_id = get_current_campus_id()
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != campus_id:
            return forbidden_response("Access denied")
        
        json_data = json.loads(doc.data_json or "{}")

        # Handle subject_eval section
        if section == "subject_eval":
            subject_id = payload.get("subject_id")
            existing = json_data.get("subject_eval")
            if not isinstance(existing, dict):
                existing = {}
            if subject_id:
                subject_data = {
                    "subject_id": subject_id,
                    "criteria": payload.get("criteria") or {},
                    "comments": payload.get("comments") or {},
                }
                
                test_scores = payload.get("test_scores")
                if test_scores and isinstance(test_scores, dict):
                    subject_data["test_scores"] = test_scores
                    if "values" in test_scores:
                        subject_data["test_point_values"] = test_scores["values"]
                elif payload.get("test_point_values"):
                    test_point_values = payload.get("test_point_values") or []
                    subject_data["test_point_values"] = test_point_values
                
                existing[subject_id] = subject_data
            json_data["subject_eval"] = existing
            
        # Handle intl_scores section
        elif section == "intl_scores":
            # 🔍 DEBUG: Log nhận được
            frappe.logger().info(f"[INTL_SCORES] Received payload: {payload}")
            frappe.logger().info(f"[INTL_SCORES] Payload type: {type(payload)}")
            
            subject_id = None
            if isinstance(payload, dict):
                subject_id = payload.get("subject_id")
                frappe.logger().info(f"[INTL_SCORES] subject_id from payload.get: {subject_id}")
            
            if not subject_id:
                for key, value in payload.items():
                    if key.startswith("SIS_ACTUAL_SUBJECT-"):
                        subject_id = key
                        payload = value
                        frappe.logger().info(f"[INTL_SCORES] subject_id from key scan: {subject_id}")
                        break
            
            frappe.logger().info(f"[INTL_SCORES] Final subject_id: {subject_id}")
            
            if subject_id:
                existing_intl_scores = json_data.get("intl_scores")
                if not isinstance(existing_intl_scores, dict):
                    existing_intl_scores = {}
                
                existing_subject_data = existing_intl_scores.get(subject_id, {})
                if not isinstance(existing_subject_data, dict):
                    existing_subject_data = {}
                
                normalized_payload = normalize_intl_scores(payload)
                
                # Deep merge
                for section_key in ["main_scores", "component_scores", "ielts_scores"]:
                    if section_key in normalized_payload:
                        if section_key not in existing_subject_data:
                            existing_subject_data[section_key] = {}
                        
                        incoming_section = normalized_payload[section_key]
                        if isinstance(incoming_section, dict):
                            for field_name, field_value in incoming_section.items():
                                if section_key == "ielts_scores" and isinstance(field_value, dict):
                                    if field_name not in existing_subject_data[section_key]:
                                        existing_subject_data[section_key][field_name] = {}
                                    for ielts_field, ielts_value in field_value.items():
                                        existing_subject_data[section_key][field_name][ielts_field] = ielts_value
                                else:
                                    existing_subject_data[section_key][field_name] = field_value
                
                # Merge top-level fields
                for top_key in ["overall_mark", "overall_grade", "comment", "subcurriculum_id", "subcurriculum_title_en", "intl_comment", "subject_title"]:
                    if top_key in normalized_payload and normalized_payload[top_key] is not None:
                        existing_subject_data[top_key] = normalized_payload[top_key]
                
                existing_intl_scores[subject_id] = existing_subject_data
                json_data["intl_scores"] = existing_intl_scores
                
                # 🔍 DEBUG: Log sau khi merge
                frappe.logger().info(f"[INTL_SCORES] Merged data for {subject_id}: {existing_subject_data}")
                frappe.logger().info(f"[INTL_SCORES] json_data keys after merge: {list(json_data.keys())}")
            else:
                return validation_error_response(
                    message="subject_id is required for intl_scores updates",
                    errors={"subject_id": ["Required"]}
                )
                
        # Handle scores section
        elif section == "scores":
            existing_scores = json_data.get("scores")
            if not isinstance(existing_scores, dict):
                existing_scores = {}
            
            # Detect multi-subject payload
            is_multi_subject = False
            if isinstance(payload, dict):
                payload_keys = list(payload.keys())
                if payload_keys and all(
                    k.startswith("SIS_ACTUAL_SUBJECT-") or k.startswith("SIS-ACTUAL-SUBJECT-") 
                    for k in payload_keys
                ):
                    is_multi_subject = True
                    
                    for subject_id, new_subject_data in payload.items():
                        if not subject_id.startswith("SIS_ACTUAL_SUBJECT-") and not subject_id.startswith("SIS-ACTUAL-SUBJECT-"):
                            continue
                        
                        if subject_id not in existing_scores:
                            existing_scores[subject_id] = {
                                "hs1_scores": [], "hs2_scores": [], "hs3_scores": [],
                                "hs1_average": None, "hs2_average": None, "hs3_average": None,
                                "final_average": None,
                            }
                        
                        if isinstance(new_subject_data, dict):
                            for field_name, field_value in new_subject_data.items():
                                if field_name in ['hs1_scores', 'hs2_scores', 'hs3_scores']:
                                    if isinstance(field_value, list):
                                        existing_scores[subject_id][field_name] = list(field_value)
                                    else:
                                        existing_scores[subject_id][field_name] = field_value
                                elif field_name == 'semester1_average':
                                    # Validate semester1_average
                                    if field_value is not None:
                                        if isinstance(field_value, (int, float)) and 0 <= field_value <= 10:
                                            existing_scores[subject_id][field_name] = field_value
                                        elif isinstance(field_value, str) and field_value in ["Đạt", "Không Đạt"]:
                                            existing_scores[subject_id][field_name] = field_value
                                elif field_value is not None:
                                    existing_scores[subject_id][field_name] = field_value
                        else:
                            existing_scores[subject_id] = new_subject_data
                    
                    json_data["scores"] = copy.deepcopy(existing_scores)
            
            if not is_multi_subject:
                # Single subject update
                subject_id = None
                if isinstance(payload, dict):
                    if any(key in payload for key in ['hs1_scores', 'hs2_scores', 'hs3_scores', 'hs1_average']):
                        subject_id = payload.get("subject_id") or data.get("subject_id")
                        if not subject_id:
                            for key in payload.keys():
                                if key.startswith("SIS_ACTUAL_SUBJECT-"):
                                    subject_id = key
                                    break
                
                if subject_id and isinstance(payload, dict):
                    if subject_id not in existing_scores:
                        existing_scores[subject_id] = {
                            "hs1_scores": [], "hs2_scores": [], "hs3_scores": [],
                            "hs1_average": None, "hs2_average": None, "hs3_average": None,
                            "final_average": None,
                        }
                    
                    new_subject_data = payload.get(subject_id, payload)
                    if isinstance(new_subject_data, dict):
                        for field_name, field_value in new_subject_data.items():
                            if field_name in ['hs1_scores', 'hs2_scores', 'hs3_scores']:
                                if isinstance(field_value, list):
                                    existing_scores[subject_id][field_name] = list(field_value)
                                else:
                                    existing_scores[subject_id][field_name] = field_value
                            elif field_name == 'semester1_average':
                                if field_value is not None:
                                    if isinstance(field_value, (int, float)) and 0 <= field_value <= 10:
                                        existing_scores[subject_id][field_name] = field_value
                                    elif isinstance(field_value, str) and field_value in ["Đạt", "Không Đạt"]:
                                        existing_scores[subject_id][field_name] = field_value
                            elif field_value is not None:
                                existing_scores[subject_id][field_name] = field_value
                    
                    json_data["scores"] = copy.deepcopy(existing_scores)
                else:
                    json_data["scores"] = payload
        else:
            # Other sections (homeroom, etc.)
            json_data[section] = payload

        # Save
        doc.data_json = json.dumps(json_data, ensure_ascii=False)
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        # 🔍 DEBUG: Log sau khi save
        frappe.logger().info(f"[UPDATE_SECTION] Saved report {report_id}, section={section}, json_data keys={list(json_data.keys())}")
        
        # Trả về debug info trong response
        debug_info = {
            "json_data_keys": list(json_data.keys()),
            "has_intl_scores": "intl_scores" in json_data,
        }
        if section == "intl_scores" and "intl_scores" in json_data:
            debug_info["intl_scores_subjects"] = list(json_data["intl_scores"].keys())
        
        return success_response({
            "report_id": report_id, 
            "section": section, 
            "message": f"Section '{section}' updated successfully",
            "debug": debug_info
        })

    except frappe.DoesNotExistError:
        return not_found_response("Report card not found")
    except Exception as e:
        frappe.log_error(f"update_report_section error: {str(e)}")
        return error_response(f"Failed to update report section: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def delete_report():
    """Xóa một student report card."""
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        if not report_id:
            return validation_error_response(
                message="report_id is required", 
                errors={"report_id": ["Required"]}
            )

        campus_id = get_current_campus_id()
        doc = frappe.get_doc("SIS Student Report Card", report_id)
        if doc.campus_id != campus_id:
            return forbidden_response("Access denied")

        if doc.status == "published":
            return validation_error_response(
                message="Cannot delete published report",
                errors={"status": ["Published reports cannot be deleted"]}
            )

        doc.delete(ignore_permissions=True)
        frappe.db.commit()

        return success_response({"message": f"Report {report_id} deleted successfully"})

    except frappe.DoesNotExistError:
        return not_found_response("Report card not found")
    except Exception as e:
        frappe.log_error(f"delete_report error: {str(e)}")
        return error_response(f"Failed to delete report: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_previous_semester_score():
    """
    Lấy điểm từ report End Term 1 cho End Term 2.
    
    Request payload:
        {
            "student_id": "...",
            "academic_year": "2024-2025",
            "subject_id": "SIS_ACTUAL_SUBJECT-..."
        }
    """
    try:
        data = get_request_payload()
        student_id = data.get("student_id")
        academic_year = data.get("academic_year")
        subject_id = data.get("subject_id")

        if not student_id:
            return validation_error_response("student_id is required", {"student_id": ["Required"]})
        if not academic_year:
            return validation_error_response("academic_year is required", {"academic_year": ["Required"]})
        if not subject_id:
            return validation_error_response("subject_id is required", {"subject_id": ["Required"]})

        campus_id = get_current_campus_id()

        # Find End Term 1 published report
        previous_reports = frappe.get_all(
            "SIS Student Report Card",
            fields=["name", "data_json", "status", "title"],
            filters={
                "student_id": student_id,
                "school_year": academic_year,
                "semester_part": "End Term 1",
                "status": "published",
                "campus_id": campus_id
            },
            order_by="creation desc",
            limit=1
        )

        if not previous_reports:
            return success_response({
                "overall_score": None,
                "report_id": None,
                "error": "Không tìm thấy báo cáo End Term 1 đã phê duyệt"
            })

        report = previous_reports[0]

        try:
            data_json = json.loads(report.get("data_json") or "{}")
        except Exception:
            return success_response({
                "overall_score": None,
                "report_id": report.get("name"),
                "error": "Không thể đọc dữ liệu báo cáo"
            })

        scores_data = data_json.get("scores", {})
        subject_scores = scores_data.get(subject_id, {})
        overall_score = subject_scores.get("final_average")

        if overall_score is None:
            return success_response({
                "overall_score": None,
                "report_id": report.get("name"),
                "error": f"Không tìm thấy điểm môn học trong báo cáo End Term 1"
            })

        try:
            overall_score = float(overall_score)
            if overall_score < 0 or overall_score > 10:
                return success_response({
                    "overall_score": None,
                    "report_id": report.get("name"),
                    "error": f"Điểm không hợp lệ: {overall_score}"
                })
        except (ValueError, TypeError):
            return success_response({
                "overall_score": None,
                "report_id": report.get("name"),
                "error": f"Điểm không đúng định dạng: {overall_score}"
            })

        return success_response({
            "overall_score": round(overall_score, 2),
            "report_id": report.get("name"),
            "report_title": report.get("title"),
            "error": None
        })

    except Exception as e:
        frappe.log_error(f"get_previous_semester_score error: {str(e)}")
        return error_response(f"Lỗi khi lấy điểm kỳ trước: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET"])
def debug_report_data():
    """
    Debug endpoint để kiểm tra data_json của một report.
    Trả về raw data để debug.
    """
    try:
        report_id = frappe.form_dict.get("report_id")
        subject_id = frappe.form_dict.get("subject_id")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        campus_id = get_current_campus_id()
        
        # Lấy report
        report = frappe.db.sql("""
            SELECT name, student_id, class_id, template_id, data_json
            FROM `tabSIS Student Report Card`
            WHERE name = %s AND campus_id = %s
        """, [report_id, campus_id], as_dict=True)
        
        if not report:
            return not_found_response("Report không tồn tại hoặc không có quyền truy cập")
        
        report = report[0]
        
        # Parse data_json
        try:
            data_json = json.loads(report.get("data_json") or "{}")
        except json.JSONDecodeError:
            data_json = {}
        
        result = {
            "report_id": report.get("name"),
            "student_id": report.get("student_id"),
            "class_id": report.get("class_id"),
            "template_id": report.get("template_id"),
            "data_json_keys": list(data_json.keys()),
            "has_intl_scores": "intl_scores" in data_json,
            "has_scores": "scores" in data_json,
            "has_homeroom": "homeroom" in data_json,
            "has_subject_eval": "subject_eval" in data_json,
        }
        
        # Nếu có subject_id, lấy data cho subject đó
        if subject_id:
            result["subject_id"] = subject_id
            
            # Check intl_scores
            intl_scores = data_json.get("intl_scores", {})
            subject_intl = intl_scores.get(subject_id, {})
            result["intl_scores_subject_keys"] = list(subject_intl.keys()) if subject_intl else []
            result["intl_scores_data"] = subject_intl
            
            # Check scores
            scores = data_json.get("scores", {})
            subject_scores = scores.get(subject_id, {})
            result["scores_subject_keys"] = list(subject_scores.keys()) if subject_scores else []
            result["scores_data"] = subject_scores
        else:
            # Liệt kê tất cả subjects có data
            result["intl_scores_subjects"] = list(data_json.get("intl_scores", {}).keys())
            result["scores_subjects"] = list(data_json.get("scores", {}).keys())
            result["subject_eval_subjects"] = list(data_json.get("subject_eval", {}).keys())
        
        return success_response(data=result, message="Debug data loaded")
    
    except Exception as e:
        frappe.log_error(f"debug_report_data error: {str(e)}")
        return error_response(f"Lỗi debug: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET"])
def debug_class_intl_data():
    """
    Debug endpoint để kiểm tra data_json của tất cả reports trong một class.
    Trả về summary về INTL data cho từng student.
    """
    try:
        class_id = frappe.form_dict.get("class_id")
        template_id = frappe.form_dict.get("template_id")
        subject_id = frappe.form_dict.get("subject_id")
        
        if not class_id or not template_id:
            return validation_error_response(
                message="class_id và template_id là bắt buộc",
                errors={"class_id": ["Required"], "template_id": ["Required"]}
            )
        
        campus_id = get_current_campus_id()
        
        # Lấy tất cả reports
        reports = frappe.db.sql("""
            SELECT name, student_id, data_json
            FROM `tabSIS Student Report Card`
            WHERE class_id = %s AND template_id = %s AND campus_id = %s
        """, [class_id, template_id, campus_id], as_dict=True)
        
        results = []
        for report in reports:
            try:
                data_json = json.loads(report.get("data_json") or "{}")
            except json.JSONDecodeError:
                data_json = {}
            
            intl_scores = data_json.get("intl_scores", {})
            
            item = {
                "report_id": report.get("name"),
                "student_id": report.get("student_id"),
                "has_intl_scores": bool(intl_scores),
                "intl_subjects": list(intl_scores.keys()),
            }
            
            if subject_id and subject_id in intl_scores:
                subject_data = intl_scores[subject_id]
                item["subject_data"] = {
                    "keys": list(subject_data.keys()),
                    "has_main_scores": "main_scores" in subject_data,
                    "main_scores": subject_data.get("main_scores"),
                    "overall_mark": subject_data.get("overall_mark"),
                    "overall_grade": subject_data.get("overall_grade"),
                    "approval": subject_data.get("approval"),
                }
            
            results.append(item)
        
        return success_response(
            data={
                "class_id": class_id,
                "template_id": template_id,
                "subject_id": subject_id,
                "total_reports": len(reports),
                "reports_with_intl_data": len([r for r in results if r["has_intl_scores"]]),
                "reports": results
            },
            message="Debug class data loaded"
        )
    
    except Exception as e:
        frappe.log_error(f"debug_class_intl_data error: {str(e)}")
        return error_response(f"Lỗi debug: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_report_field():
    """
    Update single field trong report card từ Approval flow.
    Cho phép L1/L2 approvers chỉnh sửa data trước khi approve.
    
    Request payload:
        {
            "template_id": "TEMPLATE-XXX",
            "class_id": "CLASS-XXX", 
            "student_id": "STUDENT-XXX",
            "section": "homeroom" | "scores" | "subject_eval" | "intl_scores",
            "subject_id": "SUBJECT-XXX" (required for scores/subject_eval/intl_scores),
            "field": "conduct" | "comments.key1" | "hs1_scores.0" | "main_scores.Title",
            "value": "tot" | "Comment text" | 8.5
        }
    """
    try:
        data = get_request_payload()
        campus_id = get_current_campus_id()
        
        # Validate required fields
        template_id = data.get("template_id")
        class_id = data.get("class_id")
        student_id = data.get("student_id")
        section = data.get("section")
        field = data.get("field")
        value = data.get("value")
        subject_id = data.get("subject_id")
        
        if not all([template_id, class_id, student_id, section, field]):
            return validation_error_response(
                "Validation failed",
                {"error": ["template_id, class_id, student_id, section, field là bắt buộc"]}
            )
        
        # Validate section-specific requirements
        if section in ["scores", "subject_eval", "intl_scores"] and not subject_id:
            return validation_error_response(
                "Validation failed",
                {"subject_id": ["subject_id là bắt buộc cho section: " + section]}
            )
        
        # Tìm report
        report_name = frappe.db.get_value(
            "SIS Student Report Card",
            {
                "template_id": template_id,
                "class_id": class_id,
                "student_id": student_id,
                "campus_id": campus_id
            },
            "name"
        )
        
        if not report_name:
            return not_found_response("Report not found")
        
        # Load report
        report_doc = frappe.get_doc("SIS Student Report Card", report_name)
        
        # Parse data_json
        try:
            data_json = json.loads(report_doc.data_json or "{}")
        except json.JSONDecodeError:
            data_json = {}
        
        # Update field based on section
        if section == "homeroom":
            if "homeroom" not in data_json:
                data_json["homeroom"] = {}
            
            # Handle nested field như "comments.key1"
            if "." in field:
                parent_key, child_key = field.split(".", 1)
                if parent_key not in data_json["homeroom"]:
                    data_json["homeroom"][parent_key] = {}
                data_json["homeroom"][parent_key][child_key] = value
            else:
                data_json["homeroom"][field] = value
        
        elif section == "scores":
            if "scores" not in data_json:
                data_json["scores"] = {}
            if subject_id not in data_json["scores"]:
                data_json["scores"][subject_id] = {}
            
            # Handle array field như "hs1_scores.0"
            if "." in field:
                array_key, index_str = field.split(".", 1)
                try:
                    index = int(index_str)
                    if array_key not in data_json["scores"][subject_id]:
                        data_json["scores"][subject_id][array_key] = []
                    # Đảm bảo array đủ dài
                    while len(data_json["scores"][subject_id][array_key]) <= index:
                        data_json["scores"][subject_id][array_key].append(None)
                    data_json["scores"][subject_id][array_key][index] = value
                except ValueError:
                    # Không phải index number, treat như nested object
                    parent_key, child_key = field.split(".", 1)
                    if parent_key not in data_json["scores"][subject_id]:
                        data_json["scores"][subject_id][parent_key] = {}
                    data_json["scores"][subject_id][parent_key][child_key] = value
            else:
                data_json["scores"][subject_id][field] = value
        
        elif section == "subject_eval":
            if "subject_eval" not in data_json:
                data_json["subject_eval"] = {}
            if subject_id not in data_json["subject_eval"]:
                data_json["subject_eval"][subject_id] = {}
            
            # Handle nested field như "criteria.key1"
            if "." in field:
                parent_key, child_key = field.split(".", 1)
                # Handle test_point_values.{index}
                try:
                    index = int(child_key)
                    if parent_key not in data_json["subject_eval"][subject_id]:
                        data_json["subject_eval"][subject_id][parent_key] = []
                    while len(data_json["subject_eval"][subject_id][parent_key]) <= index:
                        data_json["subject_eval"][subject_id][parent_key].append(None)
                    data_json["subject_eval"][subject_id][parent_key][index] = value
                except ValueError:
                    # Nested object
                    if parent_key not in data_json["subject_eval"][subject_id]:
                        data_json["subject_eval"][subject_id][parent_key] = {}
                    data_json["subject_eval"][subject_id][parent_key][child_key] = value
            else:
                data_json["subject_eval"][subject_id][field] = value
        
        elif section == "intl_scores":
            if "intl_scores" not in data_json:
                data_json["intl_scores"] = {}
            if subject_id not in data_json["intl_scores"]:
                data_json["intl_scores"][subject_id] = {}
            
            # Handle nested field như "main_scores.Title" hoặc "ielts.listening"
            if "." in field:
                parent_key, child_key = field.split(".", 1)
                if parent_key not in data_json["intl_scores"][subject_id]:
                    data_json["intl_scores"][subject_id][parent_key] = {}
                data_json["intl_scores"][subject_id][parent_key][child_key] = value
            else:
                data_json["intl_scores"][subject_id][field] = value
        
        else:
            return validation_error_response(
                "Invalid section",
                {"section": [f"Section '{section}' không hợp lệ"]}
            )
        
        # Save report
        report_doc.data_json = json.dumps(data_json, ensure_ascii=False)
        report_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={
                "updated": True,
                "report_id": report_name
            },
            message="Field updated successfully"
        )
    
    except Exception as e:
        frappe.log_error(f"update_report_field error: {str(e)}")
        return error_response(f"Lỗi cập nhật: {str(e)}")
