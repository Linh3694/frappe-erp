# -*- coding: utf-8 -*-
"""
Approval Helpers
================

Shared helper functions cho Report Card Approval module.
Tập trung các logic xử lý approval dùng chung.
"""

import frappe
from frappe import _
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from ..constants import ApprovalStatus, STATUS_PRIORITY, SectionType, SECTION_NAME_MAP


# =============================================================================
# CONTEXT MANAGERS
# =============================================================================

@contextmanager
def batch_operation_savepoint():
    """
    Context manager cho batch operations với savepoint.
    Cho phép rollback partial failures trong batch.
    
    Example:
        for report in reports:
            try:
                with batch_operation_savepoint():
                    # Process report
                    approved_count += 1
            except Exception as e:
                errors.append({"report_id": report.name, "error": str(e)})
    """
    savepoint = frappe.db.savepoint()
    try:
        yield
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


# =============================================================================
# DATA SYNC HELPERS
# =============================================================================

def sync_data_json_with_db(report_name: str, data_json: dict) -> dict:
    """
    Sync data_json với database fields để tránh mismatch.
    
    Khi update homeroom/scores content, có thể data_json approval bị mất.
    Function này đảm bảo approval status trong data_json match với database.
    
    Args:
        report_name: ID của report
        data_json: Parsed data_json object (sẽ được modify in-place)
    
    Returns:
        data_json đã được sync
    """
    try:
        db_fields = frappe.db.get_value(
            "SIS Student Report Card",
            report_name,
            ["homeroom_approval_status", "scores_approval_status"],
            as_dict=True
        )
        
        if not db_fields:
            return data_json
        
        l2_passed = [ApprovalStatus.LEVEL_2_APPROVED, ApprovalStatus.REVIEWED, ApprovalStatus.PUBLISHED]
        
        # Sync homeroom approval
        homeroom_db_status = db_fields.get("homeroom_approval_status")
        if homeroom_db_status and homeroom_db_status in l2_passed:
            if "homeroom" not in data_json:
                data_json["homeroom"] = {}
            if "approval" not in data_json["homeroom"]:
                data_json["homeroom"]["approval"] = {}
            
            # Chỉ sync nếu data_json chưa có status hoặc status thấp hơn
            current_data_status = data_json["homeroom"].get("approval", {}).get("status")
            if not current_data_status or current_data_status not in l2_passed:
                data_json["homeroom"]["approval"]["status"] = homeroom_db_status
                frappe.logger().info(f"[SYNC] Synced homeroom approval: {homeroom_db_status} for {report_name}")
        
        return data_json
        
    except Exception as sync_err:
        frappe.logger().warning(f"[SYNC] Failed to sync data_json for {report_name}: {str(sync_err)}")
        return data_json


# =============================================================================
# APPROVAL HISTORY
# =============================================================================

def add_approval_history(report, level: str, user: str, action: str, comment: str = ""):
    """
    Thêm entry vào approval_history của report.
    
    Args:
        report: SIS Student Report Card document
        level: Level duyệt (submit, level_1, level_2, review, publish, batch_submit, etc.)
        user: User ID
        action: Hành động (submitted, approved, rejected)
        comment: Ghi chú
    """
    try:
        history = json.loads(report.approval_history or "[]")
    except (json.JSONDecodeError, TypeError):
        history = []
    
    history.append({
        "level": level,
        "user": user,
        "action": action,
        "comment": comment,
        "timestamp": datetime.now().isoformat()
    })
    
    report.approval_history = json.dumps(history, ensure_ascii=False)


# =============================================================================
# SUBJECT APPROVAL DATA_JSON HELPERS
# =============================================================================

def get_subject_approval_from_data_json(data_json: dict, section: str, subject_id: str) -> dict:
    """
    Lấy approval info từ data_json cho một môn cụ thể.
    
    Args:
        data_json: Parsed data_json object
        section: scores, subject_eval, homeroom, hoặc intl board type (main_scores, ielts, comments)
        subject_id: ID của môn học (None cho homeroom)
    
    Returns:
        Dict với approval info, hoặc {} nếu không tìm thấy
    """
    if section == SectionType.HOMEROOM:
        homeroom_data = data_json.get("homeroom", {})
        return homeroom_data.get("approval", {})
    
    if section in [SectionType.SCORES, SectionType.SUBJECT_EVAL]:
        section_data = data_json.get(section, {})
        subject_data = section_data.get(subject_id, {})
        return subject_data.get("approval", {})
    
    # ✅ FIX: INTL sections (main_scores, ielts, comments) 
    # Mỗi INTL section có approval riêng để tránh ghi đè lẫn nhau:
    # - intl_scores.{subject_id}.main_scores_approval
    # - intl_scores.{subject_id}.ielts_approval
    # - intl_scores.{subject_id}.comments_approval
    # Backward compatible: fallback về approval chung nếu không có approval riêng
    if section in [SectionType.MAIN_SCORES, SectionType.IELTS, SectionType.COMMENTS]:
        intl_scores_data = data_json.get("intl_scores", {})
        subject_data = intl_scores_data.get(subject_id, {})
        
        # Lấy approval riêng cho section này
        approval_key = f"{section}_approval"
        section_approval = subject_data.get(approval_key, {})
        
        # Backward compatible: fallback về approval chung
        if not section_approval:
            section_approval = subject_data.get("approval", {})
        
        return section_approval
    
    return {}


def set_subject_approval_in_data_json(data_json: dict, section: str, subject_id: str, approval_info: dict) -> dict:
    """
    Set approval info trong data_json cho một môn cụ thể.
    
    Args:
        data_json: Parsed data_json object (sẽ được modify in-place)
        section: scores, subject_eval, homeroom, hoặc intl board type
        subject_id: ID của môn học (None cho homeroom)
        approval_info: Dict với approval info
    
    Returns:
        Modified data_json
    """
    if section == SectionType.HOMEROOM:
        if "homeroom" not in data_json:
            data_json["homeroom"] = {}
        data_json["homeroom"]["approval"] = approval_info
        return data_json
    
    if section in [SectionType.SCORES, SectionType.SUBJECT_EVAL]:
        if section not in data_json:
            data_json[section] = {}
        if subject_id not in data_json[section]:
            data_json[section][subject_id] = {}
        data_json[section][subject_id]["approval"] = approval_info
        return data_json
    
    # ✅ FIX: INTL sections (main_scores, ielts, comments)
    # Mỗi INTL section có approval riêng để tránh ghi đè lẫn nhau:
    # - intl_scores.{subject_id}.main_scores_approval
    # - intl_scores.{subject_id}.ielts_approval  
    # - intl_scores.{subject_id}.comments_approval
    if section in [SectionType.MAIN_SCORES, SectionType.IELTS, SectionType.COMMENTS]:
        if "intl_scores" not in data_json:
            data_json["intl_scores"] = {}
        if subject_id not in data_json["intl_scores"]:
            data_json["intl_scores"][subject_id] = {}
        
        # Lưu approval vào key riêng cho từng section
        approval_key = f"{section}_approval"
        data_json["intl_scores"][subject_id][approval_key] = approval_info
        return data_json
    
    return data_json


def detect_board_type_for_subject(data_json: dict, subject_id: str, current_statuses: List[str]) -> tuple:
    """
    Auto-detect board_type từ data_json cho một subject.
    
    Args:
        data_json: Parsed data_json object
        subject_id: ID của môn học
        current_statuses: List các status hợp lệ cần tìm
    
    Returns:
        (board_type, subject_approval) - board type và approval info của subject
    """
    board_type = None
    subject_approval = {}
    
    sections_to_check = [
        SectionType.SCORES, 
        SectionType.SUBJECT_EVAL, 
        SectionType.MAIN_SCORES, 
        SectionType.IELTS, 
        SectionType.COMMENTS
    ]
    
    for section_key in sections_to_check:
        section_approval = get_subject_approval_from_data_json(data_json, section_key, subject_id)
        if section_approval.get("status"):
            # Ưu tiên section có status trong current_statuses
            if section_approval.get("status") in current_statuses:
                board_type = section_key
                subject_approval = section_approval
                break
            elif not board_type:
                board_type = section_key
                subject_approval = section_approval
    
    # Fallback nếu không tìm thấy
    if not board_type:
        board_type = SectionType.SCORES
    
    return board_type, subject_approval


# =============================================================================
# COUNTERS COMPUTATION
# =============================================================================

def compute_approval_counters(data_json: dict, template) -> dict:
    """
    Tính toán các counters dựa trên approval status trong data_json.
    
    Args:
        data_json: Parsed data_json object
        template: SIS Report Card Template document
    
    Returns:
        Dict với các counters:
        - homeroom_l2_approved
        - scores_submitted_count, scores_l2_approved_count, scores_total_count
        - subject_eval_submitted_count, subject_eval_l2_approved_count, subject_eval_total_count
        - intl_submitted_count, intl_l2_approved_count, intl_total_count
        - all_sections_l2_approved
    """
    counters = {
        "homeroom_l2_approved": 0,
        "scores_submitted_count": 0,
        "scores_l2_approved_count": 0,
        "scores_total_count": 0,
        "subject_eval_submitted_count": 0,
        "subject_eval_l2_approved_count": 0,
        "subject_eval_total_count": 0,
        "intl_submitted_count": 0,
        "intl_l2_approved_count": 0,
        "intl_total_count": 0,
    }
    
    # ✅ FIX: Các status đã passed L2 (bao gồm level_2_approved, reviewed, published)
    l2_passed_statuses = [ApprovalStatus.LEVEL_2_APPROVED, ApprovalStatus.REVIEWED, ApprovalStatus.PUBLISHED]
    
    # Homeroom
    if "homeroom" in data_json and isinstance(data_json["homeroom"], dict):
        h_approval = data_json["homeroom"].get("approval", {})
        h_status = h_approval.get("status")
        # ✅ FIX: Check status >= level_2_approved (bao gồm reviewed, published)
        if h_status in l2_passed_statuses:
            counters["homeroom_l2_approved"] = 1
    
    # Scores
    if "scores" in data_json and isinstance(data_json["scores"], dict):
        for subject_id, subject_data in data_json["scores"].items():
            if isinstance(subject_data, dict):
                counters["scores_total_count"] += 1
                approval = subject_data.get("approval", {})
                status = approval.get("status", ApprovalStatus.DRAFT)
                if status not in [ApprovalStatus.DRAFT, ApprovalStatus.ENTRY]:
                    counters["scores_submitted_count"] += 1
                # ✅ FIX: Check status >= level_2_approved
                if status in l2_passed_statuses:
                    counters["scores_l2_approved_count"] += 1
    
    # Subject Eval
    if "subject_eval" in data_json and isinstance(data_json["subject_eval"], dict):
        for subject_id, subject_data in data_json["subject_eval"].items():
            if isinstance(subject_data, dict):
                counters["subject_eval_total_count"] += 1
                approval = subject_data.get("approval", {})
                status = approval.get("status", ApprovalStatus.DRAFT)
                if status not in [ApprovalStatus.DRAFT, ApprovalStatus.ENTRY]:
                    counters["subject_eval_submitted_count"] += 1
                # ✅ FIX: Check status >= level_2_approved
                if status in l2_passed_statuses:
                    counters["subject_eval_l2_approved_count"] += 1
    
    # INTL - ✅ FIX: Read from new intl_scores structure
    # New structure: intl_scores.{subject_id}.{section}_approval (main_scores_approval, ielts_approval, comments_approval)
    # Old structure (backward compat): intl.{section}.{subject_id}.approval
    
    # Check new structure first (intl_scores)
    if "intl_scores" in data_json and isinstance(data_json["intl_scores"], dict):
        for subject_id, subject_data in data_json["intl_scores"].items():
            if not isinstance(subject_data, dict):
                continue
            # Skip non-subject keys (like metadata)
            if not subject_id.startswith("SIS_ACTUAL_SUBJECT-") and not subject_id.startswith("SIS-ACTUAL-SUBJECT-"):
                continue
            
            # Check each INTL section's approval
            for section_key in ["main_scores", "ielts", "comments"]:
                approval_key = f"{section_key}_approval"
                
                # Check if this section has data (main_scores, ielts_scores, or comment)
                has_section_data = False
                if section_key == "main_scores" and subject_data.get("main_scores"):
                    has_section_data = True
                elif section_key == "ielts" and subject_data.get("ielts_scores"):
                    has_section_data = True
                elif section_key == "comments" and (subject_data.get("comment") or subject_data.get("intl_comment")):
                    has_section_data = True
                
                # Only count if section has data or has approval (submitted)
                if has_section_data or approval_key in subject_data:
                    counters["intl_total_count"] += 1
                    
                    if approval_key in subject_data:
                        approval = subject_data.get(approval_key, {})
                        status = approval.get("status", ApprovalStatus.DRAFT)
                        if status not in [ApprovalStatus.DRAFT, ApprovalStatus.ENTRY]:
                            counters["intl_submitted_count"] += 1
                        # ✅ FIX: Check status >= level_2_approved
                        if status in l2_passed_statuses:
                            counters["intl_l2_approved_count"] += 1
    
    # Backward compatibility: Also check old structure (intl.{section}.{subject_id})
    elif "intl" in data_json and isinstance(data_json["intl"], dict):
        for section_key in [SectionType.MAIN_SCORES, SectionType.IELTS, SectionType.COMMENTS]:
            if section_key in data_json["intl"] and isinstance(data_json["intl"][section_key], dict):
                for subject_id, subject_data in data_json["intl"][section_key].items():
                    if isinstance(subject_data, dict):
                        counters["intl_total_count"] += 1
                        approval = subject_data.get("approval", {})
                        status = approval.get("status", ApprovalStatus.DRAFT)
                        if status not in [ApprovalStatus.DRAFT, ApprovalStatus.ENTRY]:
                            counters["intl_submitted_count"] += 1
                        # ✅ FIX: Check status >= level_2_approved
                        if status in l2_passed_statuses:
                            counters["intl_l2_approved_count"] += 1
    
    # Compute all_sections_l2_approved
    all_l2 = True
    
    # Check homeroom nếu enabled
    homeroom_enabled = getattr(template, 'homeroom_enabled', False) if template else False
    if homeroom_enabled and counters["homeroom_l2_approved"] != 1:
        all_l2 = False
    
    # Check scores nếu enabled (VN program)
    scores_enabled = getattr(template, 'scores_enabled', False) if template else False
    program_type = getattr(template, 'program_type', 'vn') if template else 'vn'
    if scores_enabled and program_type != 'intl':
        if counters["scores_total_count"] > 0 and counters["scores_l2_approved_count"] < counters["scores_total_count"]:
            all_l2 = False
    
    # Check subject_eval nếu enabled
    subject_eval_enabled = getattr(template, 'subject_eval_enabled', False) if template else False
    if subject_eval_enabled:
        if counters["subject_eval_total_count"] > 0 and counters["subject_eval_l2_approved_count"] < counters["subject_eval_total_count"]:
            all_l2 = False
    
    # Check INTL
    if program_type == 'intl':
        if counters["intl_total_count"] > 0 and counters["intl_l2_approved_count"] < counters["intl_total_count"]:
            all_l2 = False
    
    counters["all_sections_l2_approved"] = 1 if all_l2 else 0
    
    return counters


def update_report_counters(report_name: str, data_json: dict, template):
    """
    Cập nhật counters trong database cho một report.
    
    Args:
        report_name: ID của report
        data_json: Parsed data_json object
        template: SIS Report Card Template document
    
    Returns:
        Dict counters đã cập nhật
    """
    # ✅ FIX: Sync data_json với database fields để tránh mismatch
    # Khi update homeroom content, có thể data_json["homeroom"]["approval"] bị mất
    # Cần sync lại từ database field homeroom_approval_status
    try:
        db_fields = frappe.db.get_value(
            "SIS Student Report Card",
            report_name,
            ["homeroom_approval_status", "scores_approval_status"],
            as_dict=True
        )
        
        if db_fields:
            homeroom_db_status = db_fields.get("homeroom_approval_status")
            
            # Sync homeroom approval nếu database đã có status nhưng data_json không có
            if homeroom_db_status and homeroom_db_status in [
                ApprovalStatus.LEVEL_2_APPROVED, ApprovalStatus.REVIEWED, ApprovalStatus.PUBLISHED
            ]:
                if "homeroom" not in data_json:
                    data_json["homeroom"] = {}
                if "approval" not in data_json["homeroom"]:
                    data_json["homeroom"]["approval"] = {}
                
                # Chỉ sync nếu data_json chưa có status hoặc status thấp hơn
                current_data_status = data_json["homeroom"].get("approval", {}).get("status")
                l2_passed = [ApprovalStatus.LEVEL_2_APPROVED, ApprovalStatus.REVIEWED, ApprovalStatus.PUBLISHED]
                
                if not current_data_status or current_data_status not in l2_passed:
                    data_json["homeroom"]["approval"]["status"] = homeroom_db_status
                    frappe.logger().info(f"[SYNC] Synced homeroom approval status from DB: {homeroom_db_status} for report {report_name}")
    except Exception as sync_err:
        frappe.logger().warning(f"[SYNC] Failed to sync data_json for {report_name}: {str(sync_err)}")
    
    counters = compute_approval_counters(data_json, template)
    
    frappe.db.set_value(
        "SIS Student Report Card",
        report_name,
        counters,
        update_modified=True
    )
    
    return counters


# =============================================================================
# PERMISSION CHECKS
# =============================================================================

def check_user_is_level_1_approver(user: str, template) -> bool:
    """Kiểm tra user có phải là Khối trưởng (Level 1) không."""
    if not template:
        return False
    
    homeroom_reviewer_l1 = getattr(template, 'homeroom_reviewer_level_1', None)
    if not homeroom_reviewer_l1:
        return False
    
    # Lấy user_id từ teacher
    teacher_user = frappe.db.get_value("SIS Teacher", homeroom_reviewer_l1, "user_id")
    return teacher_user == user


def check_user_is_level_2_approver(user: str, template, subject_ids: List[str] = None) -> bool:
    """
    Kiểm tra user có phải là Level 2 approver không.
    
    Level 2 có thể là:
    - Tổ trưởng (cho homeroom): từ template.homeroom_reviewer_level_2
    - Subject Manager (cho môn học): từ SIS Actual Subject.managers
    """
    if not template:
        return False
    
    # Check Tổ trưởng
    homeroom_reviewer_l2 = getattr(template, 'homeroom_reviewer_level_2', None)
    if homeroom_reviewer_l2:
        teacher_user = frappe.db.get_value("SIS Teacher", homeroom_reviewer_l2, "user_id")
        if teacher_user == user:
            return True
    
    # Check Subject Managers
    if subject_ids:
        for subject_id in subject_ids:
            managers = frappe.get_all(
                "SIS Actual Subject Manager",
                filters={"parent": subject_id},
                fields=["teacher_id"]
            )
            for manager in managers:
                manager_user = frappe.db.get_value("SIS Teacher", manager.teacher_id, "user_id")
                if manager_user == user:
                    return True
    
    return False


def check_user_is_level_3_reviewer(user: str, education_stage_id: str, campus_id: str) -> bool:
    """Kiểm tra user có phải là Level 3 Reviewer không."""
    config = frappe.get_all(
        "SIS Report Card Approval Config",
        filters={
            "campus_id": campus_id,
            "education_stage_id": education_stage_id,
            "is_active": 1
        },
        limit=1
    )
    
    if not config:
        return False
    
    reviewers = frappe.get_all(
        "SIS Report Card Approver",
        filters={
            "parent": config[0].name,
            "parentfield": "level_3_reviewers"
        },
        fields=["teacher_id", "user_id"]
    )
    
    for reviewer in reviewers:
        reviewer_user = reviewer.user_id or frappe.db.get_value("SIS Teacher", reviewer.teacher_id, "user_id")
        if reviewer_user == user:
            return True
    
    return False


def check_user_is_level_4_approver(user: str, education_stage_id: str, campus_id: str) -> bool:
    """Kiểm tra user có phải là Level 4 Approver không."""
    config = frappe.get_all(
        "SIS Report Card Approval Config",
        filters={
            "campus_id": campus_id,
            "education_stage_id": education_stage_id,
            "is_active": 1
        },
        limit=1
    )
    
    if not config:
        return False
    
    approvers = frappe.get_all(
        "SIS Report Card Approver",
        filters={
            "parent": config[0].name,
            "parentfield": "level_4_approvers"
        },
        fields=["teacher_id", "user_id"]
    )
    
    for approver in approvers:
        approver_user = approver.user_id or frappe.db.get_value("SIS Teacher", approver.teacher_id, "user_id")
        if approver_user == user:
            return True
    
    return False


def check_user_has_manager_role(user: str) -> bool:
    """Kiểm tra user có role SIS Manager, SIS BOD hoặc System Manager không."""
    user_roles = frappe.get_roles(user)
    allowed_roles = ["SIS Manager", "SIS BOD", "System Manager"]
    return any(role in user_roles for role in allowed_roles)


# =============================================================================
# LEVEL 3 CHECK
# =============================================================================

def can_approve_level_3(report, template) -> tuple:
    """
    Kiểm tra xem report có đủ điều kiện để approve ở Level 3 không.
    
    Args:
        report: SIS Student Report Card document
        template: SIS Report Card Template document
    
    Returns:
        (can_approve, missing_items) - Tuple với bool và list các phần còn thiếu
    """
    missing = []
    
    # Check homeroom
    if template.homeroom_enabled:
        if not report.homeroom_l2_approved:
            missing.append("Homeroom (Nhận xét GVCN)")
    
    # Check scores (VN program)
    if template.scores_enabled and template.program_type != 'intl':
        if report.scores_total_count > 0 and report.scores_l2_approved_count < report.scores_total_count:
            missing.append(f"Scores ({report.scores_l2_approved_count}/{report.scores_total_count} môn)")
    
    # Check subject_eval
    if template.subject_eval_enabled:
        if report.subject_eval_total_count > 0 and report.subject_eval_l2_approved_count < report.subject_eval_total_count:
            missing.append(f"Subject Eval ({report.subject_eval_l2_approved_count}/{report.subject_eval_total_count} môn)")
    
    # Check INTL
    if template.program_type == 'intl':
        if report.intl_total_count > 0 and report.intl_l2_approved_count < report.intl_total_count:
            missing.append(f"INTL ({report.intl_l2_approved_count}/{report.intl_total_count} phần)")
    
    can_approve = len(missing) == 0
    return (can_approve, missing)


# =============================================================================
# NOTIFICATION
# =============================================================================

def send_report_card_notification(report):
    """
    Gửi push notification đến phụ huynh khi report card được phê duyệt.
    
    Args:
        report: SIS Student Report Card document
    """
    try:
        student_id = report.student_id
        student_name = frappe.db.get_value("CRM Student", student_id, "student_name")
        
        if not student_name:
            frappe.logger().warning(f"Student not found: {student_id}")
            return
        
        # Get semester info
        semester_part = (
            getattr(report, 'semester_part', None) or
            getattr(report, 'semester', None) or
            'học kỳ 1'
        )

        # Send notification
        from erp.utils.notification_handler import send_bulk_parent_notifications

        result = send_bulk_parent_notifications(
            recipient_type="report_card",
            recipients_data={
                "student_ids": [student_id],
                "report_id": report.name
            },
            title="Báo cáo học tập",
            body=f"Học sinh {student_name} có báo cáo học tập của {semester_part}.",
            icon="/icon.png",
            data={
                "type": "report_card",
                "student_id": student_id,
                "student_name": student_name,
                "report_id": report.name,
                "report_card_id": report.name
            }
        )
        
        frappe.logger().info(f"Notification sent to {result.get('total_parents', 0)} parents")
        return result
    
    except Exception as e:
        frappe.logger().error(f"Report Card Notification Error: {str(e)}")
        frappe.log_error(f"Report Card Notification Error: {str(e)}", "Report Card Notification")


# =============================================================================
# UTILITY
# =============================================================================

def get_section_name(section: str) -> str:
    """Lấy tên hiển thị tiếng Việt cho section."""
    return SECTION_NAME_MAP.get(section, section)


def get_teacher_for_user(user: str, campus_id: str) -> Optional[str]:
    """Lấy teacher_id từ user_id."""
    teacher = frappe.get_all(
        "SIS Teacher",
        filters={"user_id": user, "campus_id": campus_id},
        fields=["name"],
        limit=1
    )
    return teacher[0].name if teacher else None
