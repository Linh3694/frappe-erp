# -*- coding: utf-8 -*-
"""
Approval Configuration APIs
===========================

APIs cho việc quản lý cấu hình phê duyệt Report Card.
Bao gồm L3/L4 config, Subject Managers, và Teacher permissions.

Functions:
- get_approval_config: Lấy cấu hình L3/L4 theo educational_stage
- save_approval_config: Lưu cấu hình L3/L4
- get_subject_managers: Lấy managers của môn học
- update_subject_managers: Cập nhật managers
- get_teacher_class_permissions: Lấy quyền của GV với lớp
"""

import frappe
from frappe import _
from typing import Optional

from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

from ..utils import get_request_payload, get_current_campus_id


# =============================================================================
# APPROVAL CONFIG APIs (L3/L4)
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_approval_config(education_stage_id: Optional[str] = None):
    """
    Lấy cấu hình phê duyệt L3, L4 theo educational_stage.
    
    Args:
        education_stage_id: ID cấp học (optional - nếu không có sẽ lấy tất cả)
    """
    try:
        # Lấy params từ nhiều nguồn cho GET requests
        if not education_stage_id:
            education_stage_id = frappe.form_dict.get("education_stage_id")
        if not education_stage_id and hasattr(frappe.request, 'args'):
            education_stage_id = frappe.request.args.get("education_stage_id")
        
        campus_id = get_current_campus_id()
        
        filters = {"campus_id": campus_id}
        if education_stage_id:
            filters["education_stage_id"] = education_stage_id
        
        configs = frappe.get_all(
            "SIS Report Card Approval Config",
            filters=filters,
            fields=["name", "campus_id", "education_stage_id", "school_year_id", "is_active"]
        )
        
        # Helper: Lấy full_name từ User qua teacher_id
        def get_approver_with_full_name(approvers):
            """Bổ sung full_name cho mỗi approver từ User doctype"""
            result_approvers = []
            for approver in approvers:
                teacher_id = approver.get("teacher_id")
                user_id = approver.get("user_id")
                
                # Nếu chưa có user_id, lấy từ SIS Teacher
                if not user_id and teacher_id:
                    user_id = frappe.db.get_value("SIS Teacher", teacher_id, "user_id")
                
                # Lấy full_name từ User doctype
                full_name = None
                if user_id:
                    full_name = frappe.db.get_value("User", user_id, "full_name")
                
                result_approvers.append({
                    "teacher_id": teacher_id,
                    "teacher_name": full_name or approver.get("teacher_name") or user_id,
                    "user_id": user_id
                })
            return result_approvers
        
        result = []
        for config in configs:
            # Lấy L3 reviewers
            l3_reviewers_raw = frappe.get_all(
                "SIS Report Card Approver",
                filters={"parent": config.name, "parentfield": "level_3_reviewers"},
                fields=["teacher_id", "teacher_name", "user_id"]
            )
            
            # Lấy L4 approvers
            l4_approvers_raw = frappe.get_all(
                "SIS Report Card Approver",
                filters={"parent": config.name, "parentfield": "level_4_approvers"},
                fields=["teacher_id", "teacher_name", "user_id"]
            )
            
            # Bổ sung full_name cho reviewers và approvers
            l3_reviewers = get_approver_with_full_name(l3_reviewers_raw)
            l4_approvers = get_approver_with_full_name(l4_approvers_raw)
            
            # Lấy tên education_stage
            education_stage_title = frappe.db.get_value(
                "SIS Education Stage", 
                config.education_stage_id, 
                "title_vn"
            ) or frappe.db.get_value(
                "SIS Education Stage", 
                config.education_stage_id, 
                "title_en"
            )
            
            result.append({
                "name": config.name,
                "campus_id": config.campus_id,
                "education_stage_id": config.education_stage_id,
                "education_stage_title": education_stage_title,
                "school_year_id": config.school_year_id,
                "is_active": config.is_active,
                "level_3_reviewers": l3_reviewers,
                "level_4_approvers": l4_approvers
            })
        
        return success_response(
            data=result if not education_stage_id else (result[0] if result else None),
            message="Lấy cấu hình phê duyệt thành công"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in get_approval_config: {str(e)}")
        return error_response(f"Lỗi khi lấy cấu hình: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def save_approval_config():
    """
    Lưu cấu hình phê duyệt L3, L4.
    
    Request body:
        {
            "education_stage_id": "...",
            "school_year_id": "...",  # Optional
            "level_3_reviewers": [{"teacher_id": "..."}, ...],
            "level_4_approvers": [{"teacher_id": "..."}, ...]
        }
    """
    try:
        data = get_request_payload()
        campus_id = get_current_campus_id()
        
        education_stage_id = data.get("education_stage_id")
        school_year_id = data.get("school_year_id")
        level_3_reviewers = data.get("level_3_reviewers", [])
        level_4_approvers = data.get("level_4_approvers", [])
        
        if not education_stage_id:
            return validation_error_response(
                message="education_stage_id is required",
                errors={"education_stage_id": ["Required"]}
            )
        
        # Tìm config hiện có hoặc tạo mới
        existing = frappe.get_all(
            "SIS Report Card Approval Config",
            filters={
                "campus_id": campus_id,
                "education_stage_id": education_stage_id,
                "school_year_id": school_year_id or ["is", "not set"]
            },
            limit=1
        )
        
        if existing:
            doc = frappe.get_doc("SIS Report Card Approval Config", existing[0].name)
        else:
            doc = frappe.get_doc({
                "doctype": "SIS Report Card Approval Config",
                "campus_id": campus_id,
                "education_stage_id": education_stage_id,
                "school_year_id": school_year_id,
                "is_active": 1
            })
        
        # Cập nhật L3 reviewers
        doc.level_3_reviewers = []
        for reviewer in level_3_reviewers:
            teacher_id = reviewer.get("teacher_id")
            if teacher_id:
                doc.append("level_3_reviewers", {
                    "teacher_id": teacher_id
                })
        
        # Cập nhật L4 approvers
        doc.level_4_approvers = []
        for approver in level_4_approvers:
            teacher_id = approver.get("teacher_id")
            if teacher_id:
                doc.append("level_4_approvers", {
                    "teacher_id": teacher_id
                })
        
        if existing:
            doc.save(ignore_permissions=True)
        else:
            doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
        return success_response(
            data={"name": doc.name},
            message="Đã lưu cấu hình phê duyệt thành công"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in save_approval_config: {str(e)}")
        return error_response(f"Lỗi khi lưu cấu hình: {str(e)}")


# =============================================================================
# SUBJECT MANAGERS APIs
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_subject_managers(subject_id: Optional[str] = None):
    """
    Lấy danh sách managers của môn học.
    
    Args:
        subject_id: ID môn học
    """
    try:
        # Lấy subject_id từ nhiều nguồn
        if not subject_id:
            subject_id = frappe.form_dict.get("subject_id")
        if not subject_id and hasattr(frappe.request, 'args'):
            subject_id = frappe.request.args.get("subject_id")
        
        if not subject_id:
            return validation_error_response(
                message="subject_id is required",
                errors={"subject_id": ["Required"]}
            )
        
        campus_id = get_current_campus_id()
        
        # Kiểm tra subject tồn tại và thuộc campus
        subject = frappe.get_all(
            "SIS Actual Subject",
            filters={"name": subject_id, "campus_id": campus_id},
            limit=1
        )
        
        if not subject:
            return not_found_response("Môn học không tồn tại")
        
        # Lấy managers
        managers = frappe.get_all(
            "SIS Actual Subject Manager",
            filters={"parent": subject_id},
            fields=["name", "teacher_id", "teacher_name", "role"]
        )
        
        # Enrich với thông tin teacher
        for manager in managers:
            teacher_info = frappe.db.get_value(
                "SIS Teacher",
                manager.teacher_id,
                ["user_id", "name"],
                as_dict=True
            )
            if teacher_info and teacher_info.user_id:
                user_info = frappe.db.get_value(
                    "User",
                    teacher_info.user_id,
                    ["full_name", "email"],
                    as_dict=True
                )
                if user_info:
                    manager["teacher_full_name"] = user_info.full_name
                    manager["teacher_email"] = user_info.email
        
        return success_response(
            data=managers,
            message=f"Tìm thấy {len(managers)} managers"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in get_subject_managers: {str(e)}")
        return error_response(f"Lỗi khi lấy managers: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def update_subject_managers():
    """
    Cập nhật managers của môn học.
    
    Request body:
        {
            "subject_id": "...",
            "managers": [{"teacher_id": "..."}, ...]
        }
    """
    try:
        data = get_request_payload()
        subject_id = data.get("subject_id")
        managers = data.get("managers", [])
        
        if not subject_id:
            return validation_error_response(
                message="subject_id is required",
                errors={"subject_id": ["Required"]}
            )
        
        campus_id = get_current_campus_id()
        
        # Kiểm tra subject
        try:
            subject = frappe.get_doc("SIS Actual Subject", subject_id)
        except frappe.DoesNotExistError:
            return not_found_response("Môn học không tồn tại")
        
        if subject.campus_id != campus_id:
            return forbidden_response("Không có quyền cập nhật môn học này")
        
        # Xóa managers cũ và thêm mới
        subject.managers = []
        for manager in managers:
            teacher_id = manager.get("teacher_id")
            if teacher_id:
                subject.append("managers", {
                    "teacher_id": teacher_id,
                    "role": "Level 2 Approver"
                })
        
        subject.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={"subject_id": subject_id, "managers_count": len(subject.managers)},
            message="Đã cập nhật managers thành công"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in update_subject_managers: {str(e)}")
        return error_response(f"Lỗi khi cập nhật managers: {str(e)}")


# =============================================================================
# TEACHER CLASS PERMISSIONS API
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_teacher_class_permissions(class_id: Optional[str] = None):
    """
    Lấy quyền của teacher với class:
    - taught_subjects: danh sách subject_id mà GV dạy lớp này
    - is_homeroom_teacher: có phải GVCN không
    - is_vice_homeroom_teacher: có phải Phó CN không
    
    Args:
        class_id: ID của lớp
    """
    try:
        # Lấy class_id từ nhiều nguồn
        if not class_id:
            class_id = frappe.form_dict.get("class_id")
        if not class_id and hasattr(frappe.request, 'args'):
            class_id = frappe.request.args.get("class_id")
        
        if not class_id:
            return validation_error_response(
                message="class_id is required",
                errors={"class_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        # Lấy teacher của user
        teacher = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user, "campus_id": campus_id},
            fields=["name"],
            limit=1
        )
        
        if not teacher:
            return success_response(
                data={
                    "taught_subjects": [],
                    "is_homeroom_teacher": False,
                    "is_vice_homeroom_teacher": False
                },
                message="Không tìm thấy thông tin giáo viên"
            )
        
        teacher_id = teacher[0].name
        
        # Check GVCN/Phó CN từ SIS Class
        class_doc = frappe.db.get_value(
            "SIS Class",
            class_id,
            ["homeroom_teacher", "vice_homeroom_teacher"],
            as_dict=True
        )
        
        is_homeroom = class_doc.homeroom_teacher == teacher_id if class_doc else False
        is_vice_homeroom = class_doc.vice_homeroom_teacher == teacher_id if class_doc else False
        
        # Lấy môn học GV dạy lớp này từ SIS Subject Assignment
        assignments = frappe.get_all(
            "SIS Subject Assignment",
            filters={
                "teacher_id": teacher_id,
                "class_id": class_id,
                "campus_id": campus_id
            },
            fields=["actual_subject_id"]
        )
        
        taught_subjects = []
        for a in assignments:
            subject_info = frappe.db.get_value(
                "SIS Actual Subject",
                a.actual_subject_id,
                ["name", "title_vn", "title_en"],
                as_dict=True
            )
            if subject_info:
                taught_subjects.append({
                    "subject_id": subject_info.name,
                    "subject_title": subject_info.title_vn or subject_info.title_en or subject_info.name
                })
        
        return success_response(
            data={
                "teacher_id": teacher_id,
                "class_id": class_id,
                "taught_subjects": taught_subjects,
                "is_homeroom_teacher": is_homeroom,
                "is_vice_homeroom_teacher": is_vice_homeroom
            },
            message="Lấy thông tin quyền thành công"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in get_teacher_class_permissions: {str(e)}")
        return error_response(f"Lỗi khi lấy quyền: {str(e)}")
