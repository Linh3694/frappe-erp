# -*- coding: utf-8 -*-
"""
Pending Approvals Queries APIs
==============================

APIs cho việc lấy danh sách báo cáo đang chờ phê duyệt.
Hỗ trợ cả flat list và grouped view.

Functions:
- get_pending_approvals: Lấy danh sách flat (từng report)
- get_pending_approvals_grouped: Lấy danh sách grouped by class/subject
"""

import frappe
from frappe import _
import json
from typing import Optional

from erp.utils.api_response import (
    success_response,
    error_response,
)

from ..utils import get_current_campus_id

# Import helpers
from ..approval_helpers.helpers import (
    get_subject_approval_from_data_json,
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _is_manager_role(user):
    """
    Check if user has SIS Manager, SIS BOD, or System Manager role.
    Những roles này có quyền xem TẤT CẢ báo cáo chờ duyệt (nhưng không có quyền duyệt).
    """
    user_roles = frappe.get_roles(user)
    return any(role in user_roles for role in ["SIS Manager", "SIS BOD", "System Manager"])


def _get_teacher_name(teacher_id):
    """Lấy tên teacher từ teacher_id"""
    if not teacher_id:
        return None
    # Lấy user_id từ SIS Teacher
    user_id = frappe.db.get_value("SIS Teacher", teacher_id, "user_id")
    if user_id:
        # Lấy full_name từ User doctype
        full_name = frappe.db.get_value("User", user_id, "full_name")
        if full_name:
            return full_name
    return teacher_id


def _get_approvers_for_level(level, template=None, config=None, subject_id=None, campus_id=None):
    """
    Lấy danh sách người có quyền duyệt cho một level cụ thể.
    
    Args:
        level: level_1, level_2, review, publish
        template: SIS Report Card Template doc (cho L1, L2)
        config: SIS Report Card Approval Config doc (cho L3, L4)
        subject_id: ID môn học (cho L2 subject manager)
        campus_id: Campus ID
    
    Returns:
        List of approver names
    """
    approvers = []
    
    if level == "level_1" and template:
        # L1: Khối trưởng từ template
        reviewer_id = template.get("homeroom_reviewer_level_1")
        if reviewer_id:
            name = _get_teacher_name(reviewer_id)
            if name:
                approvers.append(name)
    
    elif level == "level_2":
        if template:
            # L2 Homeroom: Tổ trưởng từ template
            reviewer_id = template.get("homeroom_reviewer_level_2")
            if reviewer_id:
                name = _get_teacher_name(reviewer_id)
                if name:
                    approvers.append(name)
        
        if subject_id:
            # L2 Subject: Subject Managers
            managers = frappe.get_all(
                "SIS Actual Subject Manager",
                filters={"parent": subject_id},
                fields=["teacher_id"]
            )
            for m in managers:
                name = _get_teacher_name(m.teacher_id)
                if name and name not in approvers:
                    approvers.append(name)
    
    elif level == "review" and config:
        # L3: Reviewers từ approval config
        l3_reviewers = frappe.get_all(
            "SIS Report Card Approver",
            filters={"parent": config.name, "parentfield": "level_3_reviewers"},
            fields=["teacher_id"]
        )
        for r in l3_reviewers:
            name = _get_teacher_name(r.teacher_id)
            if name and name not in approvers:
                approvers.append(name)
    
    elif level == "publish" and config:
        # L4: Approvers từ approval config
        l4_approvers = frappe.get_all(
            "SIS Report Card Approver",
            filters={"parent": config.name, "parentfield": "level_4_approvers"},
            fields=["teacher_id"]
        )
        for a in l4_approvers:
            name = _get_teacher_name(a.teacher_id)
            if name and name not in approvers:
                approvers.append(name)
    
    return approvers


# =============================================================================
# PENDING APPROVALS - FLAT LIST
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_pending_approvals(level: Optional[str] = None):
    """
    Lấy danh sách báo cáo đang chờ duyệt cho user hiện tại.
    
    Args:
        level: Filter theo level (level_1, level_2, review, publish)
    """
    try:
        # Lấy params từ nhiều nguồn cho GET requests
        if not level:
            level = frappe.form_dict.get("level")
        if not level and hasattr(frappe.request, 'args'):
            level = frappe.request.args.get("level")
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        # Check if user is manager (can view all reports)
        is_manager = _is_manager_role(user)
        
        # Lấy teacher của user
        teacher = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user, "campus_id": campus_id},
            fields=["name"],
            limit=1
        )
        teacher_id = teacher[0].name if teacher else None
        
        results = []
        
        # Level 1: Kiểm tra các template có homeroom_reviewer_level_1 là teacher này
        if not level or level == "level_1":
            if teacher_id:
                templates_l1 = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"homeroom_reviewer_level_1": teacher_id, "campus_id": campus_id},
                    fields=["name"]
                )
                if templates_l1:
                    reports_l1 = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": ["in", [t.name for t in templates_l1]],
                            "approval_status": "submitted",
                            "campus_id": campus_id
                        },
                        fields=["name", "title", "student_id", "class_id", "approval_status", "submitted_at"]
                    )
                    for r in reports_l1:
                        r["pending_level"] = "level_1"
                        results.append(r)
        
        # Level 2: Kiểm tra templates có homeroom_reviewer_level_2 hoặc subject managers
        if not level or level == "level_2":
            if teacher_id:
                # Tổ trưởng
                templates_l2 = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"homeroom_reviewer_level_2": teacher_id, "campus_id": campus_id},
                    fields=["name"]
                )
                if templates_l2:
                    reports_l2 = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": ["in", [t.name for t in templates_l2]],
                            "approval_status": ["in", ["submitted", "level_1_approved"]],
                            "campus_id": campus_id
                        },
                        fields=["name", "title", "student_id", "class_id", "approval_status", "submitted_at"]
                    )
                    for r in reports_l2:
                        r["pending_level"] = "level_2"
                        if r not in results:
                            results.append(r)
                
                # Subject Manager
                managed_subjects = frappe.get_all(
                    "SIS Actual Subject Manager",
                    filters={"teacher_id": teacher_id},
                    fields=["parent"]
                )
                
                if managed_subjects:
                    subject_ids = [s.parent for s in managed_subjects]
                    
                    all_templates = frappe.get_all(
                        "SIS Report Card Template",
                        filters={"campus_id": campus_id},
                        fields=["name"]
                    )
                    
                    matching_templates = []
                    for tmpl in all_templates:
                        scores = frappe.get_all(
                            "SIS Report Card Score Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        subjects = frappe.get_all(
                            "SIS Report Card Subject Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        
                        template_subjects = [s.subject_id for s in scores] + [s.subject_id for s in subjects]
                        if any(sid in template_subjects for sid in subject_ids):
                            matching_templates.append(tmpl.name)
                    
                    if matching_templates:
                        reports_sm = frappe.get_all(
                            "SIS Student Report Card",
                            filters={
                                "template_id": ["in", matching_templates],
                                "approval_status": "level_1_approved",
                                "campus_id": campus_id
                            },
                            fields=["name", "title", "student_id", "class_id", "approval_status", "submitted_at"]
                        )
                        for r in reports_sm:
                            r["pending_level"] = "level_2"
                            if not any(existing["name"] == r["name"] for existing in results):
                                results.append(r)
        
        # Level 3 & 4: Kiểm tra approval config
        if not level or level in ["review", "publish"]:
            configs = frappe.get_all(
                "SIS Report Card Approval Config",
                filters={"campus_id": campus_id, "is_active": 1},
                fields=["name", "education_stage_id"]
            )
            
            for config in configs:
                # Check if user is L3 reviewer
                if not level or level == "review":
                    l3_reviewers = frappe.get_all(
                        "SIS Report Card Approver",
                        filters={"parent": config.name, "parentfield": "level_3_reviewers"},
                        fields=["teacher_id", "user_id"]
                    )
                    # Safe check for is_l3
                    is_l3 = False
                    for r in l3_reviewers:
                        if r.user_id == user:
                            is_l3 = True
                            break
                        if r.teacher_id:
                            teacher_user = frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id")
                            if teacher_user == user:
                                is_l3 = True
                                break
                    # User là L3 reviewer - hoặc là manager (sẽ set viewer_only)
                    if is_l3 or is_manager:
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name", "homeroom_enabled", "scores_enabled", "subject_eval_enabled", "program_type"]
                        )
                        for tmpl in templates:
                            homeroom_enabled = tmpl.get("homeroom_enabled")
                            scores_enabled = tmpl.get("scores_enabled")
                            subject_eval_enabled = tmpl.get("subject_eval_enabled")
                            is_intl = tmpl.get("program_type") == "intl"
                            
                            if not homeroom_enabled and not scores_enabled and not subject_eval_enabled and not is_intl:
                                continue
                            
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
                                continue
                            
                            reports_l3 = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "campus_id": campus_id,
                                    "approval_status": ["not in", ["reviewed", "published"]]
                                },
                                or_filters=or_filters,
                                fields=[
                                    "name", "title", "student_id", "class_id", "approval_status",
                                    "homeroom_approval_status", "scores_approval_status",
                                    "homeroom_l2_approved", "all_sections_l2_approved",
                                    "scores_submitted_count", "scores_l2_approved_count", "scores_total_count",
                                    "subject_eval_submitted_count", "subject_eval_l2_approved_count", "subject_eval_total_count",
                                    "intl_submitted_count", "intl_l2_approved_count", "intl_total_count"
                                ]
                            )
                            for r in reports_l3:
                                r["pending_level"] = "review"
                                r["is_complete"] = bool(r.get("all_sections_l2_approved"))
                                r["progress"] = {
                                    "homeroom_l2_approved": r.get("homeroom_l2_approved"),
                                    "scores": f"{r.get('scores_l2_approved_count', 0)}/{r.get('scores_total_count', 0)}",
                                    "subject_eval": f"{r.get('subject_eval_l2_approved_count', 0)}/{r.get('subject_eval_total_count', 0)}",
                                    "intl": f"{r.get('intl_l2_approved_count', 0)}/{r.get('intl_total_count', 0)}"
                                }
                                # Mark as viewer only if manager không phải là actual L3 reviewer
                                if is_manager and not is_l3:
                                    r["is_viewer_only"] = True
                                # Lấy approvers
                                config_doc = frappe.get_doc("SIS Report Card Approval Config", config.name)
                                r["approvers"] = _get_approvers_for_level("review", config=config_doc, campus_id=campus_id)
                                if not any(existing["name"] == r["name"] for existing in results):
                                    results.append(r)
                
                # Check if user is L4 approver
                if not level or level == "publish":
                    l4_approvers = frappe.get_all(
                        "SIS Report Card Approver",
                        filters={"parent": config.name, "parentfield": "level_4_approvers"},
                        fields=["teacher_id", "user_id"]
                    )
                    # Safe check for is_l4
                    is_l4 = False
                    for r in l4_approvers:
                        if r.user_id == user:
                            is_l4 = True
                            break
                        if r.teacher_id:
                            teacher_user = frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id")
                            if teacher_user == user:
                                is_l4 = True
                                break
                    # User là L4 approver - hoặc là manager (sẽ set viewer_only)
                    if is_l4 or is_manager:
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name"]
                        )
                        if templates:
                            reports_l4 = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": ["in", [t.name for t in templates]],
                                    "approval_status": ["in", ["reviewed", "published"]],
                                    "campus_id": campus_id
                                },
                                fields=["name", "title", "student_id", "class_id", "approval_status"]
                            )
                            for r in reports_l4:
                                r["pending_level"] = "publish"
                                # Mark as viewer only if manager không phải là actual L4 approver
                                if is_manager and not is_l4:
                                    r["is_viewer_only"] = True
                                # Lấy approvers
                                config_doc = frappe.get_doc("SIS Report Card Approval Config", config.name)
                                r["approvers"] = _get_approvers_for_level("publish", config=config_doc, campus_id=campus_id)
                                if r not in results:
                                    results.append(r)
        
        # Validate: Lọc bỏ orphan records
        if results:
            report_names = [r["name"] for r in results]
            report_templates = frappe.get_all(
                "SIS Student Report Card",
                filters={"name": ["in", report_names]},
                fields=["name", "template_id"]
            )
            report_template_map = {r.name: r.template_id for r in report_templates}
            
            template_ids_to_check = set(tid for tid in report_template_map.values() if tid)
            
            valid_template_ids = set()
            if template_ids_to_check:
                existing_templates = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"name": ["in", list(template_ids_to_check)]},
                    fields=["name"]
                )
                valid_template_ids = set(t["name"] for t in existing_templates)
            
            filtered_results = []
            for report in results:
                report_template_id = report_template_map.get(report["name"])
                if report_template_id and report_template_id not in valid_template_ids:
                    frappe.logger().warning(f"Skipping orphan report: {report['name']}, template_id={report_template_id} không còn tồn tại")
                    continue
                filtered_results.append(report)
            
            results = filtered_results
        
        # Enrich với thông tin học sinh
        for report in results:
            student_info = frappe.db.get_value(
                "CRM Student", 
                report["student_id"], 
                ["student_name", "student_code"],
                as_dict=True
            )
            if student_info:
                report["student_name"] = student_info.student_name
                report["student_code"] = student_info.student_code
            
            class_info = frappe.db.get_value(
                "SIS Class",
                report["class_id"],
                ["title", "short_title"],
                as_dict=True
            )
            if class_info:
                report["class_title"] = class_info.title or class_info.short_title
        
        return success_response(
            data={
                "reports": results,
                "total": len(results)
            },
            message=f"Tìm thấy {len(results)} báo cáo đang chờ duyệt"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in get_pending_approvals: {str(e)}")
        return error_response(f"Lỗi khi lấy danh sách chờ duyệt: {str(e)}")


# =============================================================================
# PENDING APPROVALS - GROUPED BY CLASS/SUBJECT
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_pending_approvals_grouped(level: Optional[str] = None):
    """
    Lấy danh sách báo cáo đang chờ duyệt, grouped by (template, class, subject).
    Trả về dạng aggregated để hiển thị theo Lớp + Môn.
    
    Args:
        level: Filter theo level (level_1, level_2, review, publish)
    """
    try:
        if not level:
            level = frappe.form_dict.get("level")
        if not level and hasattr(frappe.request, 'args'):
            level = frappe.request.args.get("level")
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        # Check if user is manager (can view all reports)
        is_manager = _is_manager_role(user)
        
        teacher = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user, "campus_id": campus_id},
            fields=["name"],
            limit=1
        )
        teacher_id = teacher[0].name if teacher else None
        
        all_reports = []
        
        # Cache templates và configs cho approvers lookup (dùng sau khi group)
        template_cache = {}
        config_cache = {}
        
        # Level 1: Khối trưởng duyệt homeroom
        if not level or level == "level_1":
            # Teacher có quyền duyệt L1
            if teacher_id:
                templates_l1 = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"homeroom_reviewer_level_1": teacher_id, "campus_id": campus_id},
                    fields=["name", "title", "homeroom_reviewer_level_1"]
                )
                for tmpl in templates_l1:
                    # Cache template cho approvers lookup
                    template_cache[tmpl.name] = tmpl
                    
                    reports = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": tmpl.name,
                            "homeroom_approval_status": "submitted",
                            "campus_id": campus_id
                        },
                        fields=["name", "class_id", "homeroom_submitted_at", "homeroom_submitted_by",
                                "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
                                "rejected_from_level", "rejected_section"]
                    )
                    for r in reports:
                        r["template_id"] = tmpl.name
                        r["template_title"] = tmpl.title
                        r["pending_level"] = "level_1"
                        r["subject_id"] = None
                        r["subject_title"] = "Nhận xét chủ nhiệm"
                        r["submitted_at"] = r.get("homeroom_submitted_at")
                        r["submitted_by"] = r.get("homeroom_submitted_by")
                        if r.get("homeroom_rejection_reason") and r.get("rejected_from_level") == 2:
                            r["was_rejected"] = True
                            r["rejection_reason"] = r.get("homeroom_rejection_reason")
                        all_reports.append(r)
            
            # Manager xem tất cả L1 reports (viewer only)
            elif is_manager:
                all_l1_templates = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"campus_id": campus_id},
                    fields=["name", "title", "homeroom_reviewer_level_1"]
                )
                # Chỉ lấy templates có người duyệt L1
                for tmpl in all_l1_templates:
                    if not tmpl.get("homeroom_reviewer_level_1"):
                        continue
                    template_cache[tmpl.name] = tmpl
                    
                    reports = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": tmpl.name,
                            "homeroom_approval_status": "submitted",
                            "campus_id": campus_id
                        },
                        fields=["name", "class_id", "homeroom_submitted_at", "homeroom_submitted_by",
                                "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
                                "rejected_from_level", "rejected_section"]
                    )
                    for r in reports:
                        r["template_id"] = tmpl.name
                        r["template_title"] = tmpl.title
                        r["pending_level"] = "level_1"
                        r["subject_id"] = None
                        r["subject_title"] = "Nhận xét chủ nhiệm"
                        r["submitted_at"] = r.get("homeroom_submitted_at")
                        r["submitted_by"] = r.get("homeroom_submitted_by")
                        if r.get("homeroom_rejection_reason") and r.get("rejected_from_level") == 2:
                            r["was_rejected"] = True
                            r["rejection_reason"] = r.get("homeroom_rejection_reason")
                        r["is_viewer_only"] = True
                        all_reports.append(r)
        
        # Level 2: Tổ trưởng hoặc Subject Manager
        if not level or level == "level_2":
            if teacher_id:
                # Tổ trưởng duyệt homeroom
                templates_l2 = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"homeroom_reviewer_level_2": teacher_id, "campus_id": campus_id},
                    fields=["name", "title", "homeroom_reviewer_level_2"]
                )
                for tmpl in templates_l2:
                    # Cache template
                    if tmpl.name not in template_cache:
                        template_cache[tmpl.name] = tmpl
                    
                    reports = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": tmpl.name,
                            "homeroom_approval_status": "level_1_approved",
                            "campus_id": campus_id
                        },
                        fields=["name", "class_id", "homeroom_submitted_at", "homeroom_submitted_by", 
                                "homeroom_rejection_reason", "homeroom_rejected_by", "homeroom_rejected_at",
                                "rejected_from_level", "rejected_section"]
                    )
                    for r in reports:
                        r["template_id"] = tmpl.name
                        r["template_title"] = tmpl.title
                        r["pending_level"] = "level_2"
                        r["subject_id"] = None
                        r["subject_title"] = "Nhận xét chủ nhiệm"
                        r["submitted_at"] = r.get("homeroom_submitted_at")
                        r["submitted_by"] = r.get("homeroom_submitted_by")
                        if r.get("homeroom_rejection_reason") and r.get("rejected_from_level") == 3:
                            r["was_rejected"] = True
                            r["rejection_reason"] = r.get("homeroom_rejection_reason")
                        elif r.get("rejected_from_level") == 3 and r.get("rejected_section") in ["homeroom", "both"]:
                            r["was_rejected"] = True
                        all_reports.append(r)
                
                # Subject Manager
                managed_subjects = frappe.get_all(
                    "SIS Actual Subject Manager",
                    filters={"teacher_id": teacher_id},
                    fields=["parent"]
                )
                
                if managed_subjects:
                    subject_ids = [s.parent for s in managed_subjects]
                    
                    subject_info_map = {}
                    for sid in subject_ids:
                        subject_data = frappe.db.get_value(
                            "SIS Actual Subject", sid, ["title_vn", "title_en"], as_dict=True
                        )
                        if subject_data:
                            subject_info_map[sid] = subject_data.title_vn or subject_data.title_en or sid
                    
                    all_templates = frappe.get_all(
                        "SIS Report Card Template",
                        filters={"campus_id": campus_id},
                        fields=["name", "title"]
                    )
                    
                    for tmpl in all_templates:
                        scores = frappe.get_all(
                            "SIS Report Card Score Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        subjects = frappe.get_all(
                            "SIS Report Card Subject Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        
                        template_subjects = set([s.subject_id for s in scores] + [s.subject_id for s in subjects])
                        matching_subjects = [sid for sid in subject_ids if sid in template_subjects]
                        
                        if matching_subjects:
                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "campus_id": campus_id
                                },
                                fields=["name", "class_id", "data_json", "scores_submitted_at", "scores_submitted_by",
                                        "scores_rejection_reason", "scores_rejected_by", "scores_rejected_at",
                                        "rejected_from_level", "rejected_section"]
                            )
                            
                            for r in reports:
                                try:
                                    report_data_json = json.loads(r.get("data_json") or "{}")
                                except json.JSONDecodeError:
                                    report_data_json = {}
                                
                                for sid in matching_subjects:
                                    subject_approval = {}
                                    found_board_type = None
                                    found_section = None
                                    
                                    for board_type_key in ["scores", "subject_eval"]:
                                        section_approval = get_subject_approval_from_data_json(report_data_json, board_type_key, sid)
                                        if section_approval.get("status") in ["submitted", "level_1_approved"]:
                                            subject_approval = section_approval
                                            found_board_type = board_type_key
                                            found_section = board_type_key
                                            break
                                    
                                    if not found_board_type:
                                        for intl_board_type in ["main_scores", "ielts", "comments"]:
                                            intl_approval = get_subject_approval_from_data_json(report_data_json, intl_board_type, sid)
                                            if intl_approval.get("status") in ["submitted", "level_1_approved"]:
                                                subject_approval = intl_approval
                                                found_board_type = intl_approval.get("board_type", intl_board_type)
                                                found_section = "intl"
                                                break
                                    
                                    subject_status = subject_approval.get("status", "draft")
                                    
                                    if subject_status not in ["submitted", "level_1_approved"]:
                                        continue
                                    
                                    r_copy = r.copy()
                                    del r_copy["data_json"]
                                    r_copy["template_id"] = tmpl.name
                                    r_copy["template_title"] = tmpl.title
                                    r_copy["pending_level"] = "level_2"
                                    r_copy["subject_id"] = sid
                                    r_copy["subject_title"] = subject_info_map.get(sid, sid)
                                    r_copy["section_type"] = found_section
                                    r_copy["board_type"] = found_board_type
                                    r_copy["submitted_at"] = subject_approval.get("submitted_at") or r.get("scores_submitted_at")
                                    r_copy["submitted_by"] = subject_approval.get("submitted_by") or r.get("scores_submitted_by")
                                    if subject_approval.get("rejection_reason"):
                                        r_copy["was_rejected"] = True
                                        r_copy["rejection_reason"] = subject_approval.get("rejection_reason")
                                        r_copy["rejected_from_level"] = subject_approval.get("rejected_from_level")
                                    all_reports.append(r_copy)
        
        # Level 3 & 4
        if not level or level in ["review", "publish"]:
            configs = frappe.get_all(
                "SIS Report Card Approval Config",
                filters={"campus_id": campus_id, "is_active": 1},
                fields=["name", "education_stage_id"]
            )
            
            for config in configs:
                # Cache config
                config_cache[config.name] = config
                
                # L3 reviewer
                if not level or level == "review":
                    l3_reviewers = frappe.get_all(
                        "SIS Report Card Approver",
                        filters={"parent": config.name, "parentfield": "level_3_reviewers"},
                        fields=["teacher_id", "user_id"]
                    )
                    # Safe check for is_l3
                    is_l3 = False
                    for r in l3_reviewers:
                        if r.user_id == user:
                            is_l3 = True
                            break
                        if r.teacher_id:
                            teacher_user = frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id")
                            if teacher_user == user:
                                is_l3 = True
                                break
                    # User là L3 reviewer - hoặc là manager (sẽ set viewer_only)
                    if is_l3 or is_manager:
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name", "title", "homeroom_enabled", "scores_enabled", "subject_eval_enabled"]
                        )
                        for tmpl in templates:
                            homeroom_enabled = tmpl.get("homeroom_enabled")
                            scores_enabled = tmpl.get("scores_enabled")
                            subject_eval_enabled = tmpl.get("subject_eval_enabled")
                            
                            # ✅ FIX: Check cả subject_eval_enabled
                            if not homeroom_enabled and not scores_enabled and not subject_eval_enabled:
                                continue
                            
                            or_filters = []
                            if homeroom_enabled:
                                or_filters.append(["homeroom_approval_status", "=", "level_2_approved"])
                            if scores_enabled:
                                or_filters.append(["scores_approval_status", "=", "level_2_approved"])
                            # ✅ FIX: Thêm filter cho subject_eval (dùng scores_approval_status vì subject_eval share field này)
                            # Hoặc check homeroom_l2_approved = 1 để bắt case homeroom đã L2 approved
                            if subject_eval_enabled:
                                or_filters.append(["homeroom_l2_approved", "=", 1])
                            
                            if not or_filters:
                                continue
                            
                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "campus_id": campus_id
                                },
                                or_filters=or_filters,
                                fields=["name", "class_id", "homeroom_submitted_at", "scores_submitted_at",
                                        "rejection_reason", "rejected_from_level", "rejected_at", "rejected_section",
                                        "homeroom_l2_approved", "all_sections_l2_approved"]
                            )
                            for r in reports:
                                r["template_id"] = tmpl.name
                                r["template_title"] = tmpl.title
                                r["pending_level"] = "review"
                                r["subject_id"] = None
                                r["subject_title"] = "Toàn bộ báo cáo"
                                r["submitted_at"] = max(
                                    r.get("homeroom_submitted_at") or "",
                                    r.get("scores_submitted_at") or ""
                                ) or None
                                if r.get("rejected_from_level") == 4:
                                    r["was_rejected"] = True
                                # Mark as viewer only if manager không phải là actual L3 reviewer
                                if is_manager and not is_l3:
                                    r["is_viewer_only"] = True
                                r["_config_name"] = config.name  # Store để lấy approvers sau
                                all_reports.append(r)
                
                # L4 approver
                if not level or level == "publish":
                    l4_approvers = frappe.get_all(
                        "SIS Report Card Approver",
                        filters={"parent": config.name, "parentfield": "level_4_approvers"},
                        fields=["teacher_id", "user_id"]
                    )
                    # Safe check for is_l4
                    is_l4 = False
                    for r in l4_approvers:
                        if r.user_id == user:
                            is_l4 = True
                            break
                        if r.teacher_id:
                            teacher_user = frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id")
                            if teacher_user == user:
                                is_l4 = True
                                break
                    # User là L4 approver - hoặc là manager (sẽ set viewer_only)
                    if is_l4 or is_manager:
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name", "title"]
                        )
                        for tmpl in templates:
                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "approval_status": "reviewed",
                                    "campus_id": campus_id
                                },
                                fields=["name", "class_id", "submitted_at", "submitted_by"]
                            )
                            for r in reports:
                                r["template_id"] = tmpl.name
                                r["template_title"] = tmpl.title
                                r["pending_level"] = "publish"
                                r["subject_id"] = None
                                r["subject_title"] = "Toàn bộ báo cáo"
                                # Mark as viewer only if manager không phải là actual L4 approver
                                if is_manager and not is_l4:
                                    r["is_viewer_only"] = True
                                r["_config_name"] = config.name  # Store để lấy approvers sau
                                all_reports.append(r)
        
        # Group by (template_id, class_id, subject_id, pending_level)
        grouped = {}
        for r in all_reports:
            key = (r["template_id"], r["class_id"], r.get("subject_id"), r["pending_level"])
            if key not in grouped:
                grouped[key] = {
                    "template_id": r["template_id"],
                    "template_title": r.get("template_title", ""),
                    "class_id": r["class_id"],
                    "subject_id": r.get("subject_id"),
                    "subject_title": r.get("subject_title", ""),
                    "pending_level": r["pending_level"],
                    "student_count": 0,
                    "submitted_at": r.get("submitted_at"),
                    "submitted_by": r.get("submitted_by"),
                    "rejection_reason": r.get("rejection_reason"),
                    "was_rejected": r.get("was_rejected", False),
                    "rejected_from_level": r.get("rejected_from_level"),
                    "rejected_section": r.get("rejected_section"),
                    "report_ids": set(),
                    "is_viewer_only": r.get("is_viewer_only", False),
                    "_config_name": r.get("_config_name")  # Temporary for approvers lookup
                }
            if r["name"] not in grouped[key]["report_ids"]:
                grouped[key]["report_ids"].add(r["name"])
                grouped[key]["student_count"] += 1
                if r.get("submitted_at") and (not grouped[key]["submitted_at"] or r["submitted_at"] > grouped[key]["submitted_at"]):
                    grouped[key]["submitted_at"] = r["submitted_at"]
                    grouped[key]["submitted_by"] = r.get("submitted_by")
                if r.get("rejection_reason"):
                    grouped[key]["rejection_reason"] = r["rejection_reason"]
                    grouped[key]["was_rejected"] = True
                    grouped[key]["rejected_from_level"] = r.get("rejected_from_level")
                    grouped[key]["rejected_section"] = r.get("rejected_section")
                # Merge is_viewer_only - nếu bất kỳ report nào không phải viewer_only thì group không phải viewer_only
                if not r.get("is_viewer_only", False):
                    grouped[key]["is_viewer_only"] = False
        
        # Validate orphan records
        valid_template_ids = set()
        template_ids_to_check = set(data["template_id"] for data in grouped.values())
        if template_ids_to_check:
            existing_templates = frappe.get_all(
                "SIS Report Card Template",
                filters={"name": ["in", list(template_ids_to_check)]},
                fields=["name"]
            )
            valid_template_ids = set(t["name"] for t in existing_templates)
        
        results = []
        for key, data in grouped.items():
            if data["template_id"] not in valid_template_ids:
                frappe.logger().warning(f"Skipping orphan report group: template_id={data['template_id']} không còn tồn tại")
                continue
            
            del data["report_ids"]
            
            class_info = frappe.db.get_value(
                "SIS Class",
                data["class_id"],
                ["title", "short_title"],
                as_dict=True
            )
            if class_info:
                data["class_title"] = class_info.short_title or class_info.title
            
            # Lấy template doc nếu chưa có
            template = template_cache.get(data["template_id"])
            if not template:
                template = frappe.db.get_value(
                    "SIS Report Card Template",
                    data["template_id"],
                    ["name", "homeroom_reviewer_level_1", "homeroom_reviewer_level_2", "education_stage"],
                    as_dict=True
                )
                if template:
                    template_cache[data["template_id"]] = template
            
            # Lấy config doc nếu cần (cho L3, L4)
            config = None
            config_name = data.get("_config_name")
            if config_name:
                config = config_cache.get(config_name)
                if not config:
                    config = frappe.get_doc("SIS Report Card Approval Config", config_name)
                    config_cache[config_name] = config
            elif template and data["pending_level"] in ["review", "publish"]:
                # Tìm config theo education_stage
                config_results = frappe.get_all(
                    "SIS Report Card Approval Config",
                    filters={
                        "education_stage_id": template.get("education_stage"),
                        "campus_id": campus_id,
                        "is_active": 1
                    },
                    fields=["name"]
                )
                if config_results:
                    config = frappe.get_doc("SIS Report Card Approval Config", config_results[0].name)
            
            # Lấy danh sách approvers
            approvers = _get_approvers_for_level(
                level=data["pending_level"],
                template=template,
                config=config,
                subject_id=data.get("subject_id"),
                campus_id=campus_id
            )
            data["approvers"] = approvers
            
            # Clean up temporary field
            if "_config_name" in data:
                del data["_config_name"]
            
            results.append(data)
        
        results.sort(key=lambda x: x.get("submitted_at") or "", reverse=True)
        
        return success_response(
            data={
                "reports": results,
                "total": len(results)
            },
            message=f"Tìm thấy {len(results)} nhóm báo cáo đang chờ duyệt"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in get_pending_approvals_grouped: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(f"Lỗi khi lấy danh sách chờ duyệt: {str(e)}")
