# -*- coding: utf-8 -*-
"""
Batch Approval Operations APIs
==============================

APIs cho các thao tác phê duyệt hàng loạt (batch operations).
Bao gồm submit/approve/reject cho cả lớp và nhiều báo cáo.

Functions:
- submit_class_reports: Batch submit cả lớp
- approve_class_reports: Batch approve cả lớp
- reject_class_reports: Batch reject cả lớp
- review_batch_reports: Batch review nhiều báo cáo
- publish_batch_reports: Batch publish nhiều báo cáo
- reject_single_report: Reject từ L3/L4 (single report)
"""

import frappe
from frappe import _
import json
from datetime import datetime
from typing import Optional, List

from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

from ..utils import get_request_payload, get_current_campus_id

# Import helpers từ approval_helpers
from ..approval_helpers.helpers import (
    get_subject_approval_from_data_json,
    set_subject_approval_in_data_json,
    compute_approval_counters,
    update_report_counters,
    add_approval_history,
    send_report_card_notification,
)


# =============================================================================
# BATCH SUBMIT
# =============================================================================

@frappe.whitelist(allow_guest=False, methods=["POST"])
def submit_class_reports():
    """
    Batch submit tất cả reports trong 1 class cho 1 section.
    Tự động xác định approval level phù hợp:
    - Scores/Subject Eval: Có managers → Level 2, không có → submitted
    - Homeroom: Có L1 → submitted (chờ L1), không L1 có L2 → level_1_approved (chờ L2),
                không cả 2 → level_2_approved (chờ L3)
    
    Request body:
        {
            "template_id": "...",
            "class_id": "...",
            "section": "scores" | "homeroom" | "subject_eval" | "all",
            "subject_id": "..." (optional, chỉ dùng khi submit scores/subject_eval)
        }
    """
    try:
        data = get_request_payload()
        template_id = data.get("template_id")
        class_id = data.get("class_id")
        section = data.get("section", "all")
        subject_id = data.get("subject_id")
        
        if not template_id:
            return validation_error_response(
                message="template_id is required",
                errors={"template_id": ["Required"]}
            )
        
        if not class_id:
            return validation_error_response(
                message="class_id is required",
                errors={"class_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        # Lấy template để kiểm tra config
        try:
            template = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            return not_found_response("Template không tồn tại")
        
        if template.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập template này")
        
        # Xác định approval level dựa trên section và config
        target_status = "submitted"  # Default
        approval_message = "Đang chờ phê duyệt"
        
        if section in ["scores", "subject_eval", "main_scores", "ielts", "comments"]:
            # Kiểm tra subject có managers không
            has_managers = False
            if subject_id:
                managers = frappe.get_all(
                    "SIS Actual Subject Manager",
                    filters={"parent": subject_id},
                    limit=1
                )
                has_managers = len(managers) > 0
            
            if has_managers:
                # Có managers → Skip L1, chuyển thẳng sang chờ L2
                target_status = "level_1_approved"
                approval_message = "Đang chờ phê duyệt Level 2 (Subject Manager)"
            else:
                # Không managers → submitted, sẽ qua L1 nếu được assign
                target_status = "submitted"
                approval_message = "Đang chờ phê duyệt"
        
        elif section == "homeroom":
            # Kiểm tra homeroom reviewers trong template
            has_level_1 = bool(getattr(template, 'homeroom_reviewer_level_1', None))
            has_level_2 = bool(getattr(template, 'homeroom_reviewer_level_2', None))
            
            if has_level_1:
                # Có L1 → chờ L1 duyệt
                target_status = "submitted"
                approval_message = "Đang chờ Khối trưởng (Level 1) phê duyệt"
            elif has_level_2:
                # Không L1 nhưng có L2 → skip L1, chờ L2
                target_status = "level_1_approved"
                approval_message = "Đang chờ Tổ trưởng (Level 2) phê duyệt"
            else:
                # Không L1, không L2 → skip cả 2, chờ Review (L3)
                target_status = "level_2_approved"
                approval_message = "Đang chờ Review (Level 3)"
        
        # Xác định field để check và update dựa trên section
        if section == "homeroom":
            status_field = "homeroom_approval_status"
        elif section in ["scores", "subject_eval", "main_scores", "ielts", "comments"]:
            status_field = "scores_approval_status"
        else:
            status_field = "approval_status"
        
        # Lấy tất cả reports của class với template này
        reports = frappe.get_all(
            "SIS Student Report Card",
            filters={
                "template_id": template_id,
                "class_id": class_id,
                "campus_id": campus_id
            },
            fields=["name", "approval_status", "homeroom_approval_status", "scores_approval_status", "student_id"]
        )
        
        if not reports:
            return error_response(
                message="Không tìm thấy báo cáo nào cho lớp này",
                code="NO_REPORTS"
            )
        
        submitted_count = 0
        skipped_count = 0
        errors = []
        
        now = datetime.now()
        
        for report_data in reports:
            try:
                # Load full report để lấy data_json
                report = frappe.get_doc("SIS Student Report Card", report_data.name)
                
                # Parse data_json
                try:
                    data_json = json.loads(report.data_json or "{}")
                except json.JSONDecodeError:
                    data_json = {}
                
                # Check approval status trong data_json nếu có subject_id
                if subject_id and section in ["scores", "subject_eval", "main_scores", "ielts", "comments"]:
                    subject_approval = get_subject_approval_from_data_json(data_json, section, subject_id)
                    current_subject_status = subject_approval.get("status", "draft")
                    
                    if current_subject_status not in ["draft", "entry", "rejected"]:
                        skipped_count += 1
                        continue
                    
                    new_approval = {
                        "status": target_status,
                        "submitted_at": str(now),
                        "submitted_by": user,
                        "board_type": section
                    }
                    
                    if current_subject_status == "rejected":
                        new_approval["rejection_reason"] = None
                        new_approval["rejected_from_level"] = None
                    
                    data_json = set_subject_approval_in_data_json(data_json, section, subject_id, new_approval)
                    
                else:
                    current_section_status = getattr(report_data, status_field, None) or 'draft'
                    
                    if current_section_status not in ['draft', 'entry', 'rejected']:
                        skipped_count += 1
                        continue
                    
                    if section == "homeroom":
                        new_approval = {
                            "status": target_status,
                            "submitted_at": str(now),
                            "submitted_by": user
                        }
                        if current_section_status == "rejected":
                            new_approval["rejection_reason"] = None
                            new_approval["rejected_from_level"] = None
                        
                        data_json = set_subject_approval_in_data_json(data_json, "homeroom", None, new_approval)
                
                # Chuẩn bị update values
                update_values = {
                    "submitted_at": now,
                    "submitted_by": user,
                    "data_json": json.dumps(data_json, ensure_ascii=False)
                }
                
                current_section_status = getattr(report_data, status_field, None) or 'draft'
                status_order = ['draft', 'entry', 'rejected', 'submitted', 'level_1_approved', 'level_2_approved', 'reviewed', 'published']
                
                if section == "homeroom" or not subject_id:
                    update_values[status_field] = target_status
                
                current_general_status = report_data.approval_status or 'draft'
                if current_general_status in ['draft', 'entry']:
                    update_values["approval_status"] = target_status
                
                # Clear rejection info khi re-submit
                should_clear_rejection = False
                if current_section_status == 'rejected':
                    should_clear_rejection = True
                elif subject_id and section in ["main_scores", "ielts", "comments"]:
                    subject_approval = get_subject_approval_from_data_json(data_json, section, subject_id)
                    if subject_approval.get("status") == "rejected":
                        should_clear_rejection = True
                
                if should_clear_rejection:
                    update_values["rejection_reason"] = None
                    update_values["rejected_by"] = None
                    update_values["rejected_at"] = None
                    
                    if section == "homeroom":
                        update_values["homeroom_rejection_reason"] = None
                        update_values["homeroom_rejected_by"] = None
                        update_values["homeroom_rejected_at"] = None
                    elif section in ["scores", "subject_eval", "main_scores", "ielts", "comments"]:
                        update_values["scores_rejection_reason"] = None
                        update_values["scores_rejected_by"] = None
                        update_values["scores_rejected_at"] = None
                    
                    current_rejected_section = report.rejected_section or ""
                    if current_rejected_section:
                        if (section == "homeroom" and current_rejected_section in ["homeroom", "both"]) or \
                           (section in ["scores", "subject_eval", "main_scores", "ielts", "comments"] and current_rejected_section in ["scores", "both"]):
                            update_values["rejected_section"] = ""
                            update_values["rejected_from_level"] = 0
                
                # Compute counters
                counters = compute_approval_counters(data_json, template)
                update_values.update(counters)
                
                # Thêm approval history
                try:
                    history = json.loads(report.approval_history or "[]")
                except (json.JSONDecodeError, TypeError):
                    history = []
                
                history.append({
                    "level": "batch_submit",
                    "user": user,
                    "action": target_status,
                    "comment": f"Section: {section} ({status_field}), Subject: {subject_id or 'N/A'}",
                    "timestamp": now.isoformat()
                })
                update_values["approval_history"] = json.dumps(history, ensure_ascii=False)
                
                frappe.db.set_value(
                    "SIS Student Report Card",
                    report_data.name,
                    update_values,
                    update_modified=True
                )
                
                submitted_count += 1
                
            except Exception as e:
                frappe.logger().error(f"Error submitting report {report_data.name}: {str(e)}")
                errors.append({
                    "report_id": report_data.name,
                    "student_id": report_data.student_id,
                    "error": str(e)
                })
        
        frappe.db.commit()
        
        section_name_map = {
            "homeroom": "Nhận xét GVCN",
            "scores": "Bảng điểm",
            "subject_eval": "Đánh giá môn học",
            "main_scores": "Điểm INTL",
            "ielts": "IELTS",
            "comments": "Nhận xét",
            "all": "Tất cả"
        }
        section_name = section_name_map.get(section, section)
        
        result_message = f"Đã submit {submitted_count} báo cáo [{section_name}]. {approval_message}"
        if skipped_count > 0:
            result_message += f" ({skipped_count} báo cáo đã được submit trước đó cho section này)"
        
        return success_response(
            data={
                "template_id": template_id,
                "class_id": class_id,
                "section": section,
                "status_field": status_field,
                "target_status": target_status,
                "submitted_count": submitted_count,
                "skipped_count": skipped_count,
                "total_reports": len(reports),
                "errors": errors if errors else None,
                "subject_id": subject_id
            },
            message=result_message
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in submit_class_reports: {str(e)}")
        return error_response(f"Lỗi khi submit: {str(e)}")


# =============================================================================
# BATCH APPROVE
# =============================================================================

@frappe.whitelist(allow_guest=False, methods=["POST"])
def approve_class_reports():
    """
    Batch approve tất cả reports trong 1 class cho 1 subject.
    Chuyển trạng thái sang level tiếp theo.
    
    Level 1, 2 sử dụng section-specific fields:
    - subject_id = null -> homeroom_approval_status
    - subject_id != null -> scores_approval_status
    
    Level 3, 4 (review, publish) dùng approval_status chung (toàn bộ report).
    
    Request body:
        {
            "template_id": "...",
            "class_id": "...",
            "subject_id": "...",  # Optional, null cho homeroom
            "pending_level": "level_1" | "level_2" | "review" | "publish",
            "comment": "..."  # Optional
        }
    """
    try:
        data = get_request_payload()
        template_id = data.get("template_id")
        class_id = data.get("class_id")
        subject_id = data.get("subject_id")
        pending_level = data.get("pending_level")
        comment = data.get("comment", "")
        
        if not template_id:
            return validation_error_response(
                message="template_id is required",
                errors={"template_id": ["Required"]}
            )
        
        if not class_id:
            return validation_error_response(
                message="class_id is required",
                errors={"class_id": ["Required"]}
            )
        
        if not pending_level:
            return validation_error_response(
                message="pending_level is required",
                errors={"pending_level": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        is_homeroom = not subject_id
        section = "homeroom" if is_homeroom else "scores"
        
        # Mapping status field theo section và level
        if pending_level in ["level_1", "level_2"]:
            status_field = f"{section}_approval_status"
            status_map = {
                "level_1": {"current": ["submitted"], "next": "level_1_approved"},
                "level_2": {"current": ["submitted", "level_1_approved"], "next": "level_2_approved"}
            }
            field_map = {
                "level_1": (f"{section}_level_1_approved_at", f"{section}_level_1_approved_by"),
                "level_2": (f"{section}_level_2_approved_at", f"{section}_level_2_approved_by")
            }
        else:
            status_field = "approval_status"
            status_map = {
                "review": {"current": ["level_2_approved"], "next": "reviewed"},
                "publish": {"current": ["reviewed"], "next": "published"}
            }
            field_map = {
                "review": ("reviewed_at", "reviewed_by"),
                "publish": ("approved_at", "approved_by")
            }
        
        if pending_level not in status_map:
            return error_response(f"Invalid pending_level: {pending_level}", code="INVALID_LEVEL")
        
        current_statuses = status_map[pending_level]["current"]
        next_status = status_map[pending_level]["next"]
        
        # Check skip Level 2 cho homeroom khi approve Level 1
        skip_l2 = False
        if pending_level == "level_1" and is_homeroom:
            try:
                template_for_skip = frappe.get_doc("SIS Report Card Template", template_id)
                has_level_2 = bool(getattr(template_for_skip, 'homeroom_reviewer_level_2', None))
                if not has_level_2:
                    next_status = "level_2_approved"
                    skip_l2 = True
                    frappe.logger().info(f"[APPROVE] Skip L2 cho homeroom - template {template_id} không có homeroom_reviewer_level_2")
            except Exception as skip_check_err:
                frappe.logger().warning(f"[APPROVE] Lỗi khi check skip L2: {str(skip_check_err)}")
        
        # Lấy reports matching
        filters = {
            "template_id": template_id,
            "class_id": class_id,
            "campus_id": campus_id
        }
        
        use_per_subject_filter = False
        or_filters = None
        
        # Level 3 (review) - Filter theo counters
        if pending_level == "review":
            template = frappe.get_doc("SIS Report Card Template", template_id)
            homeroom_enabled = getattr(template, 'homeroom_enabled', False)
            scores_enabled = getattr(template, 'scores_enabled', False)
            subject_eval_enabled = getattr(template, 'subject_eval_enabled', False)
            is_intl = getattr(template, 'program_type', 'vn') == 'intl'
            
            if not homeroom_enabled and not scores_enabled and not subject_eval_enabled and not is_intl:
                return error_response(
                    message="Template không có section nào được bật",
                    code="NO_SECTIONS"
                )
            
            or_filters = []
            if homeroom_enabled:
                or_filters.append(["homeroom_l2_approved", "=", 1])
            if scores_enabled and not is_intl:
                or_filters.append(["scores_l2_approved_count", ">", 0])
            if subject_eval_enabled:
                or_filters.append(["subject_eval_l2_approved_count", ">", 0])
            if is_intl:
                or_filters.append(["intl_l2_approved_count", ">", 0])
            
            if not or_filters:
                or_filters = None
        
        elif pending_level in ["level_1", "level_2"] and subject_id and section == "scores":
            or_filters = None
            use_per_subject_filter = True
        
        else:
            filters[status_field] = ["in", current_statuses]
        
        # Query reports
        if or_filters:
            reports = frappe.get_all(
                "SIS Student Report Card",
                filters=filters,
                or_filters=or_filters,
                fields=["name", "student_id", "all_sections_l2_approved",
                        "scores_l2_approved_count", "scores_total_count",
                        "subject_eval_l2_approved_count", "subject_eval_total_count",
                        "intl_l2_approved_count", "intl_total_count",
                        "homeroom_l2_approved"]
            )
        elif use_per_subject_filter:
            reports = frappe.get_all(
                "SIS Student Report Card",
                filters=filters,
                fields=["name", "student_id", "data_json"]
            )
            
            filtered_reports = []
            for r in reports:
                try:
                    report_data_json = json.loads(r.get("data_json") or "{}")
                except json.JSONDecodeError:
                    report_data_json = {}
                
                sections_to_check = ["scores", "subject_eval", "main_scores", "ielts", "comments"]
                subject_status = "draft"
                
                for section_key in sections_to_check:
                    section_approval = get_subject_approval_from_data_json(report_data_json, section_key, subject_id)
                    if section_approval.get("status"):
                        if section_approval.get("status") in current_statuses:
                            subject_status = section_approval.get("status")
                            break
                        elif subject_status == "draft":
                            subject_status = section_approval.get("status")
                
                if subject_status in current_statuses:
                    filtered_reports.append(frappe._dict({"name": r.name, "student_id": r.student_id}))
            
            reports = filtered_reports
        else:
            reports = frappe.get_all(
                "SIS Student Report Card",
                filters=filters,
                fields=["name", "student_id"]
            )
        
        if not reports:
            return error_response(
                message="Không tìm thấy báo cáo nào để duyệt",
                code="NO_REPORTS"
            )
        
        approved_count = 0
        errors = []
        now = datetime.now()
        
        at_field, by_field = field_map.get(pending_level, ("approved_at", "approved_by"))
        
        try:
            template = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            template = None
        
        # Level 3: Check all_sections_l2_approved
        skipped_incomplete = []
        if pending_level == "review":
            for report_data in reports:
                if not getattr(report_data, 'all_sections_l2_approved', 0):
                    progress_info = []
                    if template and template.homeroom_enabled:
                        h_status = "✓" if getattr(report_data, 'homeroom_l2_approved', 0) else "✗"
                        progress_info.append(f"Homeroom: {h_status}")
                    if template and template.scores_enabled and template.program_type != 'intl':
                        s_approved = getattr(report_data, 'scores_l2_approved_count', 0)
                        s_total = getattr(report_data, 'scores_total_count', 0)
                        progress_info.append(f"Scores: {s_approved}/{s_total}")
                    if template and template.subject_eval_enabled:
                        e_approved = getattr(report_data, 'subject_eval_l2_approved_count', 0)
                        e_total = getattr(report_data, 'subject_eval_total_count', 0)
                        progress_info.append(f"Eval: {e_approved}/{e_total}")
                    if template and template.program_type == 'intl':
                        i_approved = getattr(report_data, 'intl_l2_approved_count', 0)
                        i_total = getattr(report_data, 'intl_total_count', 0)
                        progress_info.append(f"INTL: {i_approved}/{i_total}")
                    
                    skipped_incomplete.append({
                        "report_id": report_data.name,
                        "student_id": report_data.student_id,
                        "progress": ", ".join(progress_info)
                    })
            
            reports = [r for r in reports if getattr(r, 'all_sections_l2_approved', 0)]
            
            if not reports:
                return error_response(
                    message=f"Không có báo cáo nào đủ điều kiện duyệt Level 3. {len(skipped_incomplete)} báo cáo chưa hoàn tất duyệt Level 2.",
                    code="INCOMPLETE_L2_APPROVAL",
                    data={"incomplete_reports": skipped_incomplete[:10]}
                )
        
        for report_data in reports:
            try:
                report = frappe.get_doc("SIS Student Report Card", report_data.name)
                
                try:
                    data_json = json.loads(report.data_json or "{}")
                except json.JSONDecodeError:
                    data_json = {}
                
                # Update approval trong data_json cho Level 1, 2
                if pending_level in ["level_1", "level_2"] and subject_id:
                    board_type = data.get("board_type")
                    subject_approval = {}
                    
                    if not board_type:
                        sections_to_check = ["scores", "subject_eval", "main_scores", "ielts", "comments"]
                        for section_key in sections_to_check:
                            section_approval = get_subject_approval_from_data_json(data_json, section_key, subject_id)
                            if section_approval.get("status"):
                                if section_approval.get("status") in current_statuses:
                                    board_type = section_key
                                    subject_approval = section_approval
                                    break
                                elif not board_type:
                                    board_type = section_key
                                    subject_approval = section_approval
                        
                        if not board_type:
                            board_type = "scores"
                    else:
                        subject_approval = get_subject_approval_from_data_json(data_json, board_type, subject_id)
                    
                    new_approval = subject_approval.copy() if subject_approval else {}
                    new_approval["status"] = next_status
                    new_approval[f"level_{pending_level[-1]}_approved_at"] = str(now)
                    new_approval[f"level_{pending_level[-1]}_approved_by"] = user
                    
                    data_json = set_subject_approval_in_data_json(data_json, board_type, subject_id, new_approval)
                    frappe.logger().info(f"[APPROVE] Auto-detected board_type={board_type} for subject {subject_id}")
                
                elif pending_level in ["level_1", "level_2"] and not subject_id:
                    homeroom_approval = get_subject_approval_from_data_json(data_json, "homeroom", None)
                    new_approval = homeroom_approval.copy() if homeroom_approval else {}
                    new_approval["status"] = next_status
                    new_approval[f"level_{pending_level[-1]}_approved_at"] = str(now)
                    new_approval[f"level_{pending_level[-1]}_approved_by"] = user
                    
                    if pending_level == "level_1" and next_status == "level_2_approved":
                        new_approval["level_2_approved_at"] = str(now)
                        new_approval["level_2_approved_by"] = user
                    
                    data_json = set_subject_approval_in_data_json(data_json, "homeroom", None, new_approval)
                
                # Update database
                if subject_id and pending_level in ["level_1", "level_2"]:
                    update_values = {
                        at_field: now,
                        by_field: user,
                        "data_json": json.dumps(data_json, ensure_ascii=False)
                    }
                else:
                    update_values = {
                        status_field: next_status,
                        at_field: now,
                        by_field: user,
                        "data_json": json.dumps(data_json, ensure_ascii=False)
                    }
                    
                    if next_status == "level_2_approved" and section == "homeroom":
                        counters = compute_approval_counters(data_json, template)
                        update_values["homeroom_l2_approved"] = counters.get("homeroom_l2_approved", 0)
                        update_values["homeroom_level_2_approved_at"] = now
                        update_values["homeroom_level_2_approved_by"] = user
                        if counters.get("all_sections_l2_approved", 0):
                            update_values["approval_status"] = "level_2_approved"
                            update_values["all_sections_l2_approved"] = 1
                
                if pending_level == "publish":
                    update_values["status"] = "published"
                    update_values["is_approved"] = 1
                
                frappe.db.set_value(
                    "SIS Student Report Card",
                    report_data.name,
                    update_values,
                    update_modified=True
                )
                
                if pending_level in ["level_1", "level_2"]:
                    update_report_counters(report_data.name, data_json, template)
                
                report.reload()
                add_approval_history(
                    report,
                    f"batch_{pending_level}_{section}",
                    user,
                    "approved",
                    f"Section: {section}, Class: {class_id}, Subject: {subject_id or 'homeroom'}. {comment}"
                )
                report.save(ignore_permissions=True)
                
                approved_count += 1
                
            except Exception as e:
                frappe.logger().error(f"Error approving report {report_data.name}: {str(e)}")
                errors.append({
                    "report_id": report_data.name,
                    "student_id": report_data.student_id,
                    "error": str(e)
                })
        
        frappe.db.commit()
        
        # Gửi notification nếu publish
        if pending_level == "publish":
            for report_data in reports:
                try:
                    report = frappe.get_doc("SIS Student Report Card", report_data.name)
                    send_report_card_notification(report)
                except Exception as notif_error:
                    frappe.logger().error(f"Failed to send notification: {str(notif_error)}")
        
        message = f"Đã duyệt {approved_count}/{len(reports)} báo cáo ({section}) thành công"
        if pending_level == "review" and skipped_incomplete:
            message += f". {len(skipped_incomplete)} báo cáo chưa đủ điều kiện (chờ hoàn tất Level 2)"
        
        return success_response(
            data={
                "template_id": template_id,
                "class_id": class_id,
                "subject_id": subject_id,
                "section": section,
                "pending_level": pending_level,
                "next_status": next_status,
                "approved_count": approved_count,
                "total_reports": len(reports),
                "skipped_incomplete": len(skipped_incomplete) if pending_level == "review" else 0,
                "errors": errors if errors else None
            },
            message=message
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in approve_class_reports: {str(e)}")
        return error_response(f"Lỗi khi duyệt: {str(e)}")


# =============================================================================
# BATCH REJECT
# =============================================================================

@frappe.whitelist(allow_guest=False, methods=["POST"])
def reject_class_reports():
    """
    Batch reject tất cả reports trong 1 class cho 1 subject.
    Chuyển trạng thái về 'rejected' và lưu lý do.
    
    Request body:
        {
            "template_id": "...",
            "class_id": "...",
            "subject_id": "...",  # Optional, null cho homeroom
            "section_type": "homeroom" | "scores",  # Deprecated
            "board_type": "scores" | "subject_eval" | "main_scores" | "ielts" | "comments",  # Optional
            "pending_level": "level_1" | "level_2" | "review" | "publish",
            "reason": "..."  # Required
        }
    """
    try:
        data = get_request_payload()
        template_id = data.get("template_id")
        class_id = data.get("class_id")
        subject_id = data.get("subject_id")
        section_type = data.get("section_type")
        board_type = data.get("board_type")
        pending_level = data.get("pending_level")
        reason = data.get("reason", "").strip()
        
        if not template_id:
            return validation_error_response(
                message="template_id is required",
                errors={"template_id": ["Required"]}
            )
        
        if not class_id:
            return validation_error_response(
                message="class_id is required",
                errors={"class_id": ["Required"]}
            )
        
        if not pending_level:
            return validation_error_response(
                message="pending_level is required",
                errors={"pending_level": ["Required"]}
            )
        
        if not reason:
            return validation_error_response(
                message="reason is required",
                errors={"reason": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        if section_type:
            is_homeroom = (section_type == "homeroom")
            section = section_type
        else:
            is_homeroom = not subject_id
            section = "homeroom" if is_homeroom else "scores"
        
        use_per_subject_filter = False
        if pending_level in ["level_1", "level_2"] and subject_id and section == "scores":
            use_per_subject_filter = True
        if pending_level == "review" and board_type in ["main_scores", "ielts", "comments"]:
            use_per_subject_filter = True
        
        if pending_level in ["level_1", "level_2"]:
            status_field = f"{section}_approval_status"
            status_map = {
                "level_1": ["submitted"],
                "level_2": ["submitted", "level_1_approved"]
            }
            rejection_fields = {
                "status_field": status_field,
                "rejected_at": f"{section}_rejected_at",
                "rejected_by": f"{section}_rejected_by",
                "rejection_reason": f"{section}_rejection_reason"
            }
        else:
            status_field = "approval_status"
            status_map = {
                "review": ["level_2_approved"],
                "publish": ["reviewed"]
            }
            rejection_fields = {
                "status_field": status_field,
                "rejected_at": "rejected_at",
                "rejected_by": "rejected_by",
                "rejection_reason": "rejection_reason"
            }
        
        if pending_level not in status_map:
            return error_response(f"Invalid pending_level: {pending_level}", code="INVALID_LEVEL")
        
        current_statuses = status_map[pending_level]
        
        filters = {
            "template_id": template_id,
            "class_id": class_id,
            "campus_id": campus_id
        }
        
        if not use_per_subject_filter:
            filters[status_field] = ["in", current_statuses]
        
        reports = frappe.get_all(
            "SIS Student Report Card",
            filters=filters,
            fields=["name", "student_id", status_field]
        )
        
        if not reports:
            return error_response(
                message="Không tìm thấy báo cáo nào để trả về",
                code="NO_REPORTS"
            )
        
        rejected_count = 0
        errors = []
        now = datetime.now()
        
        level_map = {"level_1": 1, "level_2": 2, "review": 3, "publish": 4}
        rejected_from_level_value = level_map.get(pending_level, 1)
        detected_board_type = board_type or section
        
        try:
            template_for_rollback = frappe.get_doc("SIS Report Card Template", template_id)
        except frappe.DoesNotExistError:
            template_for_rollback = None
        
        for report_data in reports:
            try:
                report = frappe.get_doc("SIS Student Report Card", report_data.name)
                
                try:
                    data_json = json.loads(report.data_json or "{}")
                except json.JSONDecodeError:
                    data_json = {}
                
                # Per-subject filter check
                if use_per_subject_filter:
                    found_valid_subject = False
                    
                    if subject_id:
                        check_board_type = board_type
                        if not check_board_type:
                            for section_key in ["scores", "subject_eval", "main_scores", "ielts", "comments"]:
                                section_approval = get_subject_approval_from_data_json(data_json, section_key, subject_id)
                                if section_approval.get("status") in current_statuses:
                                    check_board_type = section_key
                                    break
                        
                        if check_board_type:
                            subject_approval = get_subject_approval_from_data_json(data_json, check_board_type, subject_id)
                            current_subject_status = subject_approval.get("status", "")
                            
                            if current_subject_status in current_statuses:
                                found_valid_subject = True
                    
                    elif board_type in ["main_scores", "ielts", "comments"]:
                        intl_scores_data = data_json.get("intl_scores", {})
                        approval_key = f"{board_type}_approval"
                        
                        for subj_id, subj_data in intl_scores_data.items():
                            if isinstance(subj_data, dict):
                                approval = subj_data.get(approval_key, {})
                                if isinstance(approval, dict) and approval.get("status") in current_statuses:
                                    found_valid_subject = True
                                    break
                    
                    if not found_valid_subject:
                        continue
                
                rejection_info = {
                    "status": "rejected",
                    "rejection_reason": reason,
                    "rejected_from_level": rejected_from_level_value,
                    "rejected_by": user,
                    "rejected_at": str(now)
                }
                
                # Update data_json
                if is_homeroom:
                    data_json = set_subject_approval_in_data_json(data_json, "homeroom", None, rejection_info.copy())
                    detected_board_type = "homeroom"
                    
                elif subject_id and pending_level in ["level_1", "level_2"]:
                    detected_board_type = board_type
                    subject_approval = {}
                    
                    if not detected_board_type:
                        sections_to_check = ["scores", "subject_eval", "main_scores", "ielts", "comments"]
                        for section_key in sections_to_check:
                            section_approval = get_subject_approval_from_data_json(data_json, section_key, subject_id)
                            if section_approval.get("status"):
                                if section_approval.get("status") in current_statuses:
                                    detected_board_type = section_key
                                    subject_approval = section_approval
                                    break
                                elif not detected_board_type:
                                    detected_board_type = section_key
                                    subject_approval = section_approval
                        
                        if not detected_board_type:
                            detected_board_type = "scores"
                    
                    data_json = set_subject_approval_in_data_json(data_json, detected_board_type, subject_id, rejection_info.copy())
                    frappe.logger().info(f"[REJECT] Per-subject reject: board_type={detected_board_type}, subject={subject_id}")
                    
                elif pending_level == "review" and board_type in ["main_scores", "ielts", "comments"]:
                    detected_board_type = board_type
                    intl_scores_data = data_json.get("intl_scores", {})
                    approval_key = f"{board_type}_approval"
                    
                    for subj_id, subj_data in intl_scores_data.items():
                        if isinstance(subj_data, dict):
                            existing_approval = subj_data.get(approval_key, {})
                            if isinstance(existing_approval, dict) and existing_approval.get("status") in current_statuses:
                                subj_data[approval_key] = rejection_info.copy()
                    
                    frappe.logger().info(f"[REJECT] L3 INTL reject: board_type={board_type}")
                    
                else:
                    detected_board_type = "all"
                    for section_key in ["scores", "subject_eval"]:
                        if section_key in data_json and isinstance(data_json[section_key], dict):
                            for subj_id in data_json[section_key]:
                                if isinstance(data_json[section_key][subj_id], dict):
                                    data_json[section_key][subj_id]["approval"] = rejection_info.copy()
                    
                    if "homeroom" in data_json and isinstance(data_json["homeroom"], dict):
                        data_json["homeroom"]["approval"] = rejection_info.copy()
                    
                    if "intl_scores" in data_json and isinstance(data_json["intl_scores"], dict):
                        for subj_id in data_json["intl_scores"]:
                            if isinstance(data_json["intl_scores"][subj_id], dict):
                                for intl_section in ["main_scores", "ielts", "comments"]:
                                    approval_key = f"{intl_section}_approval"
                                    data_json["intl_scores"][subj_id][approval_key] = rejection_info.copy()
                
                # Determine rollback status
                status_rollback_map = {
                    "level_1": "rejected",
                    "level_2": "submitted",
                    "review": "level_1_approved",
                    "publish": "level_2_approved"
                }
                new_status = status_rollback_map.get(pending_level, "rejected")
                
                if pending_level == "review" and is_homeroom and template_for_rollback:
                    has_homeroom_l2 = bool(getattr(template_for_rollback, 'homeroom_reviewer_level_2', None))
                    has_homeroom_l1 = bool(getattr(template_for_rollback, 'homeroom_reviewer_level_1', None))
                    
                    if has_homeroom_l2:
                        new_status = "level_1_approved"
                    elif has_homeroom_l1:
                        new_status = "submitted"
                    else:
                        new_status = "draft"
                    
                    frappe.logger().info(f"[REJECT_CLASS] L3 reject homeroom: has_L1={has_homeroom_l1}, has_L2={has_homeroom_l2} → new_status={new_status}")
                
                update_values = {
                    rejection_fields["status_field"]: new_status,
                    rejection_fields["rejected_at"]: now,
                    rejection_fields["rejected_by"]: user,
                    rejection_fields["rejection_reason"]: reason,
                    "rejected_from_level": rejected_from_level_value,
                    "rejected_section": section,
                    "data_json": json.dumps(data_json, ensure_ascii=False)
                }
                
                if pending_level == "review":
                    if is_homeroom:
                        update_values["homeroom_l2_approved"] = 0
                    update_values["all_sections_l2_approved"] = 0
                
                frappe.db.set_value(
                    "SIS Student Report Card",
                    report_data.name,
                    update_values,
                    update_modified=True
                )
                
                report.reload()
                
                if pending_level in ["review", "publish"]:
                    try:
                        template = frappe.get_doc("SIS Report Card Template", template_id)
                        updated_data_json = json.loads(report.data_json or "{}")
                        new_counters = compute_approval_counters(updated_data_json, template)
                        report.homeroom_l2_approved = new_counters.get("homeroom_l2_approved", 0)
                        report.scores_l2_approved_count = new_counters.get("scores_l2_approved_count", 0)
                        report.subject_eval_l2_approved_count = new_counters.get("subject_eval_l2_approved_count", 0)
                        report.intl_l2_approved_count = new_counters.get("intl_l2_approved_count", 0)
                        report.all_sections_l2_approved = new_counters.get("all_sections_l2_approved", 0)
                    except Exception as counter_err:
                        frappe.logger().warning(f"Could not recompute counters: {str(counter_err)}")
                
                add_approval_history(
                    report,
                    f"batch_reject_{pending_level}_{detected_board_type}",
                    user,
                    "rejected",
                    f"Board: {detected_board_type}, Class: {class_id}, Subject: {subject_id or 'homeroom'}. Reason: {reason}"
                )
                report.save(ignore_permissions=True)
                
                rejected_count += 1
                
            except Exception as e:
                frappe.logger().error(f"Error rejecting report {report_data.name}: {str(e)}")
                errors.append({
                    "report_id": report_data.name,
                    "student_id": report_data.student_id,
                    "error": str(e)
                })
        
        if rejected_count == 0 and not errors:
            return error_response(
                message="Không tìm thấy báo cáo nào để trả về",
                code="NO_REPORTS"
            )
        
        frappe.db.commit()
        
        return success_response(
            data={
                "template_id": template_id,
                "class_id": class_id,
                "subject_id": subject_id,
                "section": section,
                "board_type": detected_board_type,
                "pending_level": pending_level,
                "rejected_count": rejected_count,
                "total_reports": len(reports),
                "reason": reason,
                "errors": errors if errors else None
            },
            message=f"Đã trả về {rejected_count}/{len(reports)} báo cáo ({detected_board_type})"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in reject_class_reports: {str(e)}")
        return error_response(f"Lỗi khi trả về: {str(e)}")


# =============================================================================
# BATCH REVIEW & PUBLISH
# =============================================================================

@frappe.whitelist(allow_guest=False, methods=["POST"])
def review_batch_reports():
    """
    Batch review nhiều báo cáo từ level_2_approved -> reviewed (Level 3).
    
    Request body:
        {
            "report_ids": ["id1", "id2", ...]
        }
    """
    try:
        data = get_request_payload()
        report_ids = data.get("report_ids", [])
        
        if not report_ids or not isinstance(report_ids, list):
            return validation_error_response(
                message="report_ids is required and must be a list",
                errors={"report_ids": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        reviewed_count = 0
        skipped_count = 0
        errors = []
        now = datetime.now()
        
        for report_id in report_ids:
            try:
                report = frappe.get_doc("SIS Student Report Card", report_id)
                
                if report.campus_id != campus_id:
                    errors.append({
                        "report_id": report_id,
                        "error": "Không có quyền truy cập báo cáo này"
                    })
                    continue
                
                current_status = getattr(report, 'approval_status', 'draft') or 'draft'
                all_sections_approved = getattr(report, 'all_sections_l2_approved', 0)
                
                if current_status != 'level_2_approved' and not all_sections_approved:
                    skipped_count += 1
                    continue
                
                report.approval_status = "reviewed"
                report.reviewed_at = now
                report.reviewed_by = user
                
                add_approval_history(report, "batch_review", user, "approved", "Batch review from ApprovalList")
                
                report.save(ignore_permissions=True)
                reviewed_count += 1
                
            except frappe.DoesNotExistError:
                errors.append({
                    "report_id": report_id,
                    "error": "Báo cáo không tồn tại"
                })
            except Exception as e:
                errors.append({
                    "report_id": report_id,
                    "error": str(e)
                })
        
        frappe.db.commit()
        
        return success_response(
            data={
                "reviewed_count": reviewed_count,
                "skipped_count": skipped_count,
                "total_requested": len(report_ids),
                "errors": errors if errors else None
            },
            message=f"Đã review {reviewed_count}/{len(report_ids)} báo cáo"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in review_batch_reports: {str(e)}")
        return error_response(f"Lỗi khi review batch: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def publish_batch_reports():
    """
    Batch publish nhiều báo cáo từ reviewed -> published (Level 4).
    
    Request body:
        {
            "report_ids": ["id1", "id2", ...]
        }
    """
    try:
        data = get_request_payload()
        report_ids = data.get("report_ids", [])
        
        if not report_ids or not isinstance(report_ids, list):
            return validation_error_response(
                message="report_ids is required and must be a list",
                errors={"report_ids": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        published_count = 0
        skipped_count = 0
        errors = []
        now = datetime.now()
        
        for report_id in report_ids:
            try:
                report = frappe.get_doc("SIS Student Report Card", report_id)
                
                if report.campus_id != campus_id:
                    errors.append({
                        "report_id": report_id,
                        "error": "Không có quyền truy cập báo cáo này"
                    })
                    continue
                
                current_status = getattr(report, 'approval_status', 'draft') or 'draft'
                if current_status != 'reviewed':
                    skipped_count += 1
                    continue
                
                report.approval_status = "published"
                report.status = "published"
                report.is_approved = 1
                report.approved_at = now
                report.approved_by = user
                
                add_approval_history(report, "batch_publish", user, "published", "Batch publish from ApprovalList")
                
                report.save(ignore_permissions=True)
                
                try:
                    send_report_card_notification(report)
                except Exception as notif_error:
                    frappe.logger().error(f"Failed to send notification for {report_id}: {str(notif_error)}")
                
                published_count += 1
                
            except frappe.DoesNotExistError:
                errors.append({
                    "report_id": report_id,
                    "error": "Báo cáo không tồn tại"
                })
            except Exception as e:
                errors.append({
                    "report_id": report_id,
                    "error": str(e)
                })
        
        frappe.db.commit()
        
        return success_response(
            data={
                "published_count": published_count,
                "skipped_count": skipped_count,
                "total_requested": len(report_ids),
                "errors": errors if errors else None
            },
            message=f"Đã xuất bản {published_count}/{len(report_ids)} báo cáo"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in publish_batch_reports: {str(e)}")
        return error_response(f"Lỗi khi xuất bản batch: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def reject_single_report():
    """
    Reject (trả lại) một báo cáo từ Level 3 hoặc Level 4.
    Trả về level ngay dưới để duyệt lại, kèm lý do reject.
    
    Request body:
        {
            "report_id": "...",
            "reason": "Lý do trả lại",
            "section": "homeroom" | "scores" | "subject_eval" | "main_scores" | "ielts" | "comments" | "both",
            "subject_id": "..." (optional)
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        reason = data.get("reason", "").strip()
        section = data.get("section", "both")
        subject_id = data.get("subject_id")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        if not reason:
            return validation_error_response(
                message="reason is required",
                errors={"reason": ["Required"]}
            )
        
        valid_sections = ['homeroom', 'scores', 'subject_eval', 'main_scores', 'ielts', 'comments', 'both']
        if section not in valid_sections:
            return validation_error_response(
                message=f"section must be one of: {', '.join(valid_sections)}",
                errors={"section": ["Invalid value"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id)
        except frappe.DoesNotExistError:
            return not_found_response("Báo cáo học tập không tồn tại")
        
        if report.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập báo cáo này")
        
        approval_status = getattr(report, 'approval_status', 'draft') or 'draft'
        homeroom_status = getattr(report, 'homeroom_approval_status', 'draft') or 'draft'
        scores_status = getattr(report, 'scores_approval_status', 'draft') or 'draft'
        now = datetime.now()
        
        can_reject = False
        current_status = approval_status
        
        try:
            data_json = json.loads(report.data_json or "{}")
        except json.JSONDecodeError:
            data_json = {}
        
        detected_intl_section = None
        try:
            template = frappe.get_doc("SIS Report Card Template", report.template_id)
            is_intl_template = getattr(template, 'program_type', 'vn') == 'intl'
            if is_intl_template and section == 'scores':
                intl_scores_data = data_json.get("intl_scores", {})
                for intl_section in ["main_scores", "ielts", "comments"]:
                    approval_key = f"{intl_section}_approval"
                    for subj_id, subj_data in intl_scores_data.items():
                        if isinstance(subj_data, dict):
                            approval = subj_data.get(approval_key, {})
                            if isinstance(approval, dict) and approval.get("status") == "level_2_approved":
                                detected_intl_section = intl_section
                                break
                    if detected_intl_section:
                        break
        except Exception:
            is_intl_template = False
        
        # Check can_reject conditions
        if approval_status == 'reviewed':
            can_reject = True
            current_status = 'reviewed'
        elif section == 'homeroom' and homeroom_status == 'level_2_approved':
            can_reject = True
            current_status = 'level_2_approved'
        elif section == 'scores' and scores_status == 'level_2_approved':
            can_reject = True
            current_status = 'level_2_approved'
        elif section == 'scores' and detected_intl_section:
            can_reject = True
            current_status = 'level_2_approved'
        elif section in ['main_scores', 'ielts', 'comments']:
            if subject_id:
                intl_approval = get_subject_approval_from_data_json(data_json, section, subject_id)
                intl_status = intl_approval.get("status", "")
                if intl_status == "level_2_approved":
                    can_reject = True
                    current_status = 'level_2_approved'
            else:
                intl_scores_data = data_json.get("intl_scores", {})
                for subj_id, subj_data in intl_scores_data.items():
                    if isinstance(subj_data, dict):
                        approval_key = f"{section}_approval"
                        approval = subj_data.get(approval_key, {})
                        if isinstance(approval, dict) and approval.get("status") == "level_2_approved":
                            can_reject = True
                            current_status = 'level_2_approved'
                            break
        elif section == 'subject_eval':
            subject_eval_l2_count = getattr(report, 'subject_eval_l2_approved_count', 0) or 0
            
            if subject_id:
                subject_eval_approval = get_subject_approval_from_data_json(data_json, 'subject_eval', subject_id)
                if subject_eval_approval.get("status") == "level_2_approved":
                    can_reject = True
                    current_status = 'level_2_approved'
            elif subject_eval_l2_count > 0:
                can_reject = True
                current_status = 'level_2_approved'
            else:
                subject_eval_data = data_json.get("subject_eval", {})
                for subj_id, subj_data in subject_eval_data.items():
                    if isinstance(subj_data, dict):
                        approval = subj_data.get("approval", {})
                        if isinstance(approval, dict) and approval.get("status") == "level_2_approved":
                            can_reject = True
                            current_status = 'level_2_approved'
                            break
        elif section == 'both':
            subject_eval_l2_count = getattr(report, 'subject_eval_l2_approved_count', 0) or 0
            if homeroom_status == 'level_2_approved' or scores_status == 'level_2_approved' or subject_eval_l2_count > 0:
                can_reject = True
                current_status = 'level_2_approved'
        
        if not can_reject:
            return error_response(
                message=f"Không thể trả lại báo cáo. Section '{section}' chưa ở trạng thái 'level_2_approved' hoặc 'reviewed'",
                code="INVALID_STATUS"
            )
        
        report.rejection_reason = reason
        report.rejected_by = user
        report.rejected_at = now
        report.rejected_section = section
        
        section_names = {
            'homeroom': 'Nhận xét GVCN',
            'scores': 'Điểm/Đánh giá GVBM',
            'both': 'Toàn bộ'
        }
        section_name = section_names.get(section, section)
        
        if current_status == 'reviewed':
            report.approval_status = 'level_2_approved'
            report.rejected_from_level = 4
            rejected_from_level = 4
            target_level = 3
            
        else:
            report.rejected_from_level = 3
            rejected_from_level = 3
            target_level = 2
            
            try:
                data_json = json.loads(report.data_json or "{}")
            except json.JSONDecodeError:
                data_json = {}
            
            try:
                template = frappe.get_doc("SIS Report Card Template", report.template_id)
            except frappe.DoesNotExistError:
                template = None
            
            if section == 'homeroom':
                has_level_2 = bool(getattr(template, 'homeroom_reviewer_level_2', None)) if template else False
                has_level_1 = bool(getattr(template, 'homeroom_reviewer_level_1', None)) if template else False
                
                if has_level_2:
                    homeroom_target_status = 'level_1_approved'
                    target_level = 2
                elif has_level_1:
                    homeroom_target_status = 'submitted'
                    target_level = 1
                else:
                    homeroom_target_status = 'draft'
                    target_level = 0
                
                frappe.logger().info(f"[REJECT] L3 reject homeroom: has_L1={has_level_1}, has_L2={has_level_2} → target_status={homeroom_target_status}")
                
                report.homeroom_approval_status = homeroom_target_status
                report.homeroom_rejection_reason = reason
                report.homeroom_rejected_by = user
                report.homeroom_rejected_at = now
                report.homeroom_l2_approved = 0
                report.approval_status = homeroom_target_status
                
                if "homeroom" in data_json and isinstance(data_json["homeroom"], dict):
                    data_json["homeroom"]["approval"] = {
                        "status": homeroom_target_status,
                        "rejection_reason": reason,
                        "rejected_from_level": 3,
                        "rejected_by": user,
                        "rejected_at": str(now)
                    }
                
            elif section in ['scores', 'subject_eval', 'main_scores', 'ielts', 'comments']:
                actual_section = detected_intl_section if detected_intl_section else section
                
                if subject_id:
                    subject_approval = get_subject_approval_from_data_json(data_json, actual_section, subject_id)
                    if subject_approval.get("status") == "level_2_approved":
                        new_approval = {
                            "status": "level_1_approved",
                            "rejection_reason": reason,
                            "rejected_from_level": 3,
                            "rejected_by": user,
                            "rejected_at": str(now)
                        }
                        data_json = set_subject_approval_in_data_json(data_json, actual_section, subject_id, new_approval)
                        
                        if actual_section in ['scores', 'subject_eval']:
                            report.scores_approval_status = 'level_1_approved'
                            report.scores_rejection_reason = reason
                            report.scores_rejected_by = user
                            report.scores_rejected_at = now
                        
                        report.approval_status = 'level_1_approved'
                else:
                    report.approval_status = 'level_1_approved'
                    
                    if actual_section in ['scores', 'subject_eval']:
                        report.scores_approval_status = 'level_1_approved'
                        report.scores_rejection_reason = reason
                        report.scores_rejected_by = user
                        report.scores_rejected_at = now
                        
                        section_data = data_json.get(actual_section, {})
                        for subj_id in section_data:
                            if isinstance(section_data[subj_id], dict):
                                section_data[subj_id]["approval"] = {
                                    "status": "level_1_approved",
                                    "rejection_reason": reason,
                                    "rejected_from_level": 3,
                                    "rejected_by": user,
                                    "rejected_at": str(now)
                                }
                    
                    elif actual_section in ['main_scores', 'ielts', 'comments']:
                        intl_scores_data = data_json.get("intl_scores", {})
                        approval_key = f"{actual_section}_approval"
                        rejection_info = {
                            "status": "level_1_approved",
                            "rejection_reason": reason,
                            "rejected_from_level": 3,
                            "rejected_by": user,
                            "rejected_at": str(now)
                        }
                        
                        for subj_id, subj_data in intl_scores_data.items():
                            if isinstance(subj_data, dict):
                                existing_approval = subj_data.get(approval_key, {})
                                if isinstance(existing_approval, dict) and existing_approval.get("status") == "level_2_approved":
                                    subj_data[approval_key] = rejection_info.copy()
                
            else:  # both
                has_homeroom_l2 = bool(getattr(template, 'homeroom_reviewer_level_2', None)) if template else False
                has_homeroom_l1 = bool(getattr(template, 'homeroom_reviewer_level_1', None)) if template else False
                
                if has_homeroom_l2:
                    homeroom_target_status = 'level_1_approved'
                elif has_homeroom_l1:
                    homeroom_target_status = 'submitted'
                else:
                    homeroom_target_status = 'draft'
                
                scores_target_status = 'level_1_approved'
                
                overall_status = homeroom_target_status if homeroom_target_status in ['draft', 'submitted'] else scores_target_status
                
                frappe.logger().info(f"[REJECT] L3 reject both: homeroom_status={homeroom_target_status}, scores_status={scores_target_status}")
                
                report.approval_status = overall_status
                report.homeroom_approval_status = homeroom_target_status
                report.scores_approval_status = scores_target_status
                report.homeroom_l2_approved = 0
                
                report.homeroom_rejection_reason = reason
                report.homeroom_rejected_by = user
                report.homeroom_rejected_at = now
                report.scores_rejection_reason = reason
                report.scores_rejected_by = user
                report.scores_rejected_at = now
                
                if "homeroom" in data_json and isinstance(data_json["homeroom"], dict):
                    data_json["homeroom"]["approval"] = {
                        "status": homeroom_target_status,
                        "rejection_reason": reason,
                        "rejected_from_level": 3,
                        "rejected_by": user,
                        "rejected_at": str(now)
                    }
                
                if "scores" in data_json:
                    for subj_id in data_json["scores"]:
                        if isinstance(data_json["scores"][subj_id], dict):
                            data_json["scores"][subj_id]["approval"] = {
                                "status": scores_target_status,
                                "rejection_reason": reason,
                                "rejected_from_level": 3,
                                "rejected_by": user,
                                "rejected_at": str(now)
                            }
                
                if "subject_eval" in data_json:
                    for subj_id in data_json["subject_eval"]:
                        if isinstance(data_json["subject_eval"][subj_id], dict):
                            data_json["subject_eval"][subj_id]["approval"] = {
                                "status": scores_target_status,
                                "rejection_reason": reason,
                                "rejected_from_level": 3,
                                "rejected_by": user,
                                "rejected_at": str(now)
                            }
            
            report.data_json = json.dumps(data_json, ensure_ascii=False)
            
            if template:
                counters = compute_approval_counters(data_json, template)
                report.homeroom_l2_approved = counters.get("homeroom_l2_approved", 0)
                report.scores_submitted_count = counters.get("scores_submitted_count", 0)
                report.scores_l2_approved_count = counters.get("scores_l2_approved_count", 0)
                report.scores_total_count = counters.get("scores_total_count", 0)
                report.subject_eval_submitted_count = counters.get("subject_eval_submitted_count", 0)
                report.subject_eval_l2_approved_count = counters.get("subject_eval_l2_approved_count", 0)
                report.subject_eval_total_count = counters.get("subject_eval_total_count", 0)
                report.intl_submitted_count = counters.get("intl_submitted_count", 0)
                report.intl_l2_approved_count = counters.get("intl_l2_approved_count", 0)
                report.intl_total_count = counters.get("intl_total_count", 0)
                report.all_sections_l2_approved = counters.get("all_sections_l2_approved", 0)
        
        add_approval_history(
            report,
            f"reject_from_level_{rejected_from_level}",
            user,
            "rejected",
            f"Trả lại [{section_name}] từ Level {rejected_from_level} về Level {target_level}. Lý do: {reason}"
        )
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={
                "report_id": report_id,
                "previous_status": current_status,
                "new_status": report.approval_status,
                "rejected_from_level": rejected_from_level,
                "target_level": target_level,
                "rejected_section": section,
                "reason": reason
            },
            message=f"Đã trả lại [{section_name}] từ Level {rejected_from_level} về Level {target_level}"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in reject_single_report: {str(e)}")
        return error_response(f"Lỗi khi trả lại: {str(e)}")
