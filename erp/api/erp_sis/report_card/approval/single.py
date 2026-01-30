# -*- coding: utf-8 -*-
"""
Single Report Approval APIs
===========================

APIs cho việc phê duyệt từng Report Card riêng lẻ.
Bao gồm các level từ Submit đến Publish.

Functions:
- approve_report_card: Legacy approval (direct approve)
- submit_section: GV submit sau khi nhập xong
- approve_level_1: Khối trưởng duyệt Homeroom
- approve_level_2: Tổ trưởng/Subject Manager duyệt
- review_report: L3 Reviewer duyệt
- final_publish: L4 Approver xuất bản
"""

import frappe
from frappe import _
import json
from datetime import datetime
from typing import Optional

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
    add_approval_history,
    send_report_card_notification,
    check_user_is_level_1_approver,
    check_user_is_level_2_approver,
    check_user_is_level_3_reviewer,
    check_user_is_level_4_approver,
)


# =============================================================================
# LEGACY APPROVAL API
# =============================================================================

@frappe.whitelist(allow_guest=False, methods=["POST"])
def approve_report_card():
    """
    Phê duyệt report card.
    Chỉ users có role 'SIS Manager', 'SIS BOD', hoặc 'System Manager' được phép.
    
    Request body:
        {
            "report_id": "..."
        }
    """
    try:
        # Check permissions
        user = frappe.session.user
        user_roles = frappe.get_roles(user)
        
        allowed_roles = ["SIS Manager", "SIS BOD", "System Manager"]
        has_permission = any(role in user_roles for role in allowed_roles)
        
        if not has_permission:
            return error_response(
                message="Bạn không có quyền phê duyệt báo cáo học tập. Cần có role SIS Manager, SIS BOD, hoặc System Manager.",
                code="PERMISSION_DENIED"
            )
        
        # Get request body
        body = {}
        try:
            request_data = frappe.request.get_data(as_text=True)
            if request_data:
                body = json.loads(request_data)
        except Exception:
            body = frappe.form_dict
        
        report_id = body.get('report_id')
        
        if not report_id:
            return error_response(
                message="Missing report_id",
                code="MISSING_PARAMS"
            )
        
        # Get report
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id, ignore_permissions=True)
        except frappe.DoesNotExistError:
            return error_response(
                message="Không tìm thấy báo cáo học tập",
                code="NOT_FOUND"
            )
        
        is_reapproval = bool(report.is_approved)
        
        # Approve
        report.is_approved = 1
        report.approved_by = user
        report.approved_at = datetime.now()
        report.status = "published"
        report.save(ignore_permissions=True)
        
        frappe.db.commit()
        
        # Send notification
        try:
            send_report_card_notification(report)
        except Exception as notif_error:
            frappe.logger().error(f"Failed to send notification for report {report_id}: {str(notif_error)}")
        
        return success_response(
            data={
                "report_id": report_id,
                "approved_by": user,
                "approved_at": report.approved_at
            },
            message="Báo cáo học tập đã được phê duyệt thành công."
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in approve_report_card: {str(e)}")
        frappe.logger().error(frappe.get_traceback())
        return error_response(
            message=f"Lỗi khi phê duyệt báo cáo: {str(e)}",
            code="SERVER_ERROR"
        )


# =============================================================================
# MULTI-LEVEL APPROVAL APIs
# =============================================================================

@frappe.whitelist(allow_guest=False, methods=["POST"])
def submit_section():
    """
    GV submit sau khi nhập xong.
    Chuyển approval_status từ 'entry' -> 'submitted'
    
    Request body:
        {
            "report_id": "...",
            "section": "scores" | "homeroom" | "subject_eval" | "all"  # Optional
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        section = data.get("section", "all")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id)
        except frappe.DoesNotExistError:
            return not_found_response("Báo cáo học tập không tồn tại")
        
        if report.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập báo cáo này")
        
        # Kiểm tra trạng thái hiện tại
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        if current_status not in ['draft', 'entry']:
            return error_response(
                message=f"Báo cáo đã ở trạng thái '{current_status}', không thể submit",
                code="INVALID_STATUS"
            )
        
        # Cập nhật trạng thái
        report.approval_status = "submitted"
        report.submitted_at = datetime.now()
        report.submitted_by = user
        
        add_approval_history(report, "submit", user, "submitted", f"Section: {section}")
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={
                "report_id": report_id,
                "approval_status": "submitted",
                "submitted_at": report.submitted_at,
                "submitted_by": user
            },
            message="Đã submit báo cáo thành công. Đang chờ phê duyệt."
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in submit_section: {str(e)}")
        return error_response(f"Lỗi khi submit: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def approve_level_1():
    """
    Khối trưởng duyệt Homeroom comments (Level 1).
    Chỉ áp dụng cho homeroom section.
    
    Request body:
        {
            "report_id": "...",
            "comment": "..."  # Optional
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        comment = data.get("comment", "")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id)
        except frappe.DoesNotExistError:
            return not_found_response("Báo cáo học tập không tồn tại")
        
        if report.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập báo cáo này")
        
        # Lấy template để kiểm tra quyền
        template = frappe.get_doc("SIS Report Card Template", report.template_id)
        
        # Kiểm tra quyền Level 1
        if not check_user_is_level_1_approver(user, template):
            # Fallback: cho phép SIS Manager
            user_roles = frappe.get_roles(user)
            if "SIS Manager" not in user_roles and "System Manager" not in user_roles:
                return forbidden_response("Bạn không có quyền duyệt Level 1 cho báo cáo này")
        
        # Kiểm tra trạng thái
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        if current_status != 'submitted':
            return error_response(
                message=f"Báo cáo cần ở trạng thái 'submitted' để duyệt Level 1. Hiện tại: '{current_status}'",
                code="INVALID_STATUS"
            )
        
        # Cập nhật
        report.approval_status = "level_1_approved"
        report.level_1_approved_at = datetime.now()
        report.level_1_approved_by = user
        
        add_approval_history(report, "level_1", user, "approved", comment)
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={
                "report_id": report_id,
                "approval_status": "level_1_approved",
                "approved_at": report.level_1_approved_at,
                "approved_by": user
            },
            message="Đã duyệt Level 1 thành công. Chuyển sang Level 2."
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in approve_level_1: {str(e)}")
        return error_response(f"Lỗi khi duyệt Level 1: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def approve_level_2():
    """
    Subject Manager / Tổ trưởng duyệt (Level 2).
    
    Request body:
        {
            "report_id": "...",
            "subject_id": "..."  # Optional - cho Subject Manager
            "comment": "..."  # Optional
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        subject_id = data.get("subject_id")
        comment = data.get("comment", "")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id)
        except frappe.DoesNotExistError:
            return not_found_response("Báo cáo học tập không tồn tại")
        
        if report.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập báo cáo này")
        
        # Lấy template
        template = frappe.get_doc("SIS Report Card Template", report.template_id)
        
        # Lấy danh sách subject_ids từ data_json
        subject_ids = []
        try:
            data_json = json.loads(report.data_json or "{}")
            if "scores" in data_json:
                subject_ids.extend(data_json["scores"].keys())
            if "subject_eval" in data_json:
                subject_ids.extend(data_json["subject_eval"].keys())
        except Exception:
            pass
        
        # Kiểm tra quyền Level 2
        if not check_user_is_level_2_approver(user, template, subject_ids):
            user_roles = frappe.get_roles(user)
            if "SIS Manager" not in user_roles and "System Manager" not in user_roles:
                return forbidden_response("Bạn không có quyền duyệt Level 2 cho báo cáo này")
        
        # Kiểm tra trạng thái
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        # Cho phép duyệt từ submitted (nếu môn học skip L1) hoặc level_1_approved
        if current_status not in ['submitted', 'level_1_approved']:
            return error_response(
                message=f"Báo cáo cần ở trạng thái 'submitted' hoặc 'level_1_approved'. Hiện tại: '{current_status}'",
                code="INVALID_STATUS"
            )
        
        # Cập nhật
        report.approval_status = "level_2_approved"
        report.level_2_approved_at = datetime.now()
        report.level_2_approved_by = user
        
        add_approval_history(report, "level_2", user, "approved", comment)
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={
                "report_id": report_id,
                "approval_status": "level_2_approved",
                "approved_at": report.level_2_approved_at,
                "approved_by": user
            },
            message="Đã duyệt Level 2 thành công. Chuyển sang Review."
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in approve_level_2: {str(e)}")
        return error_response(f"Lỗi khi duyệt Level 2: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def review_report():
    """
    L3 Reviewer duyệt toàn bộ báo cáo.
    Chuyển approval_status -> 'reviewed'
    
    Request body:
        {
            "report_id": "...",
            "comment": "..."  # Optional
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        comment = data.get("comment", "")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id)
        except frappe.DoesNotExistError:
            return not_found_response("Báo cáo học tập không tồn tại")
        
        if report.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập báo cáo này")
        
        # Lấy education_stage từ template
        template = frappe.get_doc("SIS Report Card Template", report.template_id)
        education_stage = getattr(template, 'education_stage', None)
        
        # Kiểm tra quyền Level 3
        if not check_user_is_level_3_reviewer(user, education_stage, campus_id):
            user_roles = frappe.get_roles(user)
            if "SIS Manager" not in user_roles and "System Manager" not in user_roles:
                return forbidden_response("Bạn không có quyền Review (Level 3) cho báo cáo này")
        
        # Kiểm tra trạng thái - sử dụng cả approval_status và all_sections_l2_approved
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        all_sections_approved = getattr(report, 'all_sections_l2_approved', 0)
        
        # Cho phép approve L3 nếu:
        # 1. approval_status = 'level_2_approved' (cách cũ)
        # 2. HOẶC all_sections_l2_approved = 1 (tất cả sections đã L2 approved)
        if current_status != 'level_2_approved' and not all_sections_approved:
            return error_response(
                message=f"Báo cáo chưa đủ điều kiện Review. Trạng thái: '{current_status}', all_sections_l2_approved: {all_sections_approved}",
                code="INVALID_STATUS"
            )
        
        # Cập nhật
        report.approval_status = "reviewed"
        report.reviewed_at = datetime.now()
        report.reviewed_by = user
        
        add_approval_history(report, "review", user, "approved", comment)
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        return success_response(
            data={
                "report_id": report_id,
                "approval_status": "reviewed",
                "reviewed_at": report.reviewed_at,
                "reviewed_by": user
            },
            message="Đã Review thành công. Chuyển sang phê duyệt xuất bản."
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in review_report: {str(e)}")
        return error_response(f"Lỗi khi Review: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def final_publish():
    """
    L4 Approver xuất bản chính thức.
    Chuyển approval_status -> 'published', status -> 'published'
    
    Request body:
        {
            "report_id": "...",
            "comment": "..."  # Optional
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        comment = data.get("comment", "")
        
        if not report_id:
            return validation_error_response(
                message="report_id is required",
                errors={"report_id": ["Required"]}
            )
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        try:
            report = frappe.get_doc("SIS Student Report Card", report_id)
        except frappe.DoesNotExistError:
            return not_found_response("Báo cáo học tập không tồn tại")
        
        if report.campus_id != campus_id:
            return forbidden_response("Không có quyền truy cập báo cáo này")
        
        # Lấy education_stage từ template
        template = frappe.get_doc("SIS Report Card Template", report.template_id)
        education_stage = getattr(template, 'education_stage', None)
        
        # Kiểm tra quyền Level 4
        if not check_user_is_level_4_approver(user, education_stage, campus_id):
            user_roles = frappe.get_roles(user)
            if "SIS Manager" not in user_roles and "System Manager" not in user_roles and "SIS BOD" not in user_roles:
                return forbidden_response("Bạn không có quyền xuất bản (Level 4) báo cáo này")
        
        # Kiểm tra trạng thái
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        if current_status != 'reviewed':
            return error_response(
                message=f"Báo cáo cần ở trạng thái 'reviewed'. Hiện tại: '{current_status}'",
                code="INVALID_STATUS"
            )
        
        # Cập nhật
        report.approval_status = "published"
        report.status = "published"
        report.is_approved = 1
        report.approved_at = datetime.now()
        report.approved_by = user
        
        add_approval_history(report, "publish", user, "approved", comment)
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        # Gửi notification
        try:
            send_report_card_notification(report)
        except Exception as notif_error:
            frappe.logger().error(f"Failed to send notification: {str(notif_error)}")
        
        return success_response(
            data={
                "report_id": report_id,
                "approval_status": "published",
                "approved_at": report.approved_at,
                "approved_by": user
            },
            message="Đã xuất bản báo cáo thành công. Phụ huynh có thể xem báo cáo."
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in final_publish: {str(e)}")
        return error_response(f"Lỗi khi xuất bản: {str(e)}")
