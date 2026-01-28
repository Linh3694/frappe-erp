# -*- coding: utf-8 -*-
"""
Report Card Approval APIs
=========================

APIs cho việc phê duyệt Report Card và gửi notification.
Multi-level approval flow:
- Level 1: Khối trưởng (chỉ cho Homeroom)
- Level 2: Subject Managers / Tổ trưởng
- Level 3: Reviewers (theo educational_stage)
- Level 4: Final Approvers (theo educational_stage)
"""

import frappe
from frappe import _
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from erp.utils.api_response import (
    success_response,
    error_response,
    validation_error_response,
    not_found_response,
    forbidden_response,
)

from .utils import get_request_payload, get_current_campus_id


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
            _send_report_card_notification(report)
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


def _send_report_card_notification(report):
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


def render_report_card_html(report_data):
    """
    Render report card data thành HTML (nếu cần cho PDF generation).
    
    Args:
        report_data: Dict chứa report data
    
    Returns:
        HTML string
    """
    try:
        form_code = report_data.get('form_code', 'PRIM_VN')
        student = report_data.get('student', {})
        report = report_data.get('report', {})
        subjects = report_data.get('subjects', [])
        
        homeroom_data = report_data.get('homeroom', {})
        if isinstance(homeroom_data, dict):
            homeroom = homeroom_data.get('comments', [])
        else:
            homeroom = homeroom_data if isinstance(homeroom_data, list) else []
        
        class_info = report_data.get('class', {})
        
        bg_url = f"{frappe.utils.get_url()}/files/report_forms/{form_code}/page_1.png"
        
        # Build subjects HTML
        subjects_html = ""
        if subjects:
            subjects_html = "<div style='margin-top: 20px;'>"
            subjects_html += "<h3 style='margin-bottom: 10px;'>Kết quả học tập</h3>"
            
            for idx, subject in enumerate(subjects, 1):
                subject_name = (
                    subject.get('title_vn', '') or 
                    subject.get('subject_title', '') or 
                    subject.get('subject_name', '') or 
                    subject.get('subject_id', '')
                )
                
                subjects_html += f"<div style='margin-bottom: 15px;'>"
                subjects_html += f"<h4 style='margin: 5px 0; color: #002855;'>{idx}. {subject_name}</h4>"
                subjects_html += "</div>"
            
            subjects_html += "</div>"
        
        # Build homeroom HTML
        homeroom_html = ""
        if homeroom:
            homeroom_html = "<div style='margin-top: 20px;'>"
            homeroom_html += "<h3 style='margin-bottom: 10px;'>Nhận xét</h3>"
            for comment in homeroom:
                label = comment.get('label', '') or comment.get('title', '')
                value = comment.get('value', '') or comment.get('comment', '')
                if label and value:
                    homeroom_html += f"<div style='margin-bottom: 10px;'>"
                    homeroom_html += f"<strong>{label}:</strong>"
                    homeroom_html += f"<p style='margin: 5px 0;'>{value}</p>"
                    homeroom_html += "</div>"
            homeroom_html += "</div>"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>{report.get('title_vn', 'Báo cáo học tập')}</title>
            <style>
                @page {{ size: A4; margin: 0; }}
                * {{ box-sizing: border-box; }}
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 40px; }}
                h1, h2, h3 {{ color: #002855; }}
            </style>
        </head>
        <body>
            <div style="text-align: center; margin-bottom: 20px;">
                <h1>{report.get('title_vn', 'Báo cáo học tập')}</h1>
            </div>
            
            <div style="margin-bottom: 20px;">
                <p><strong>Học sinh:</strong> {student.get('full_name', '')}</p>
                <p><strong>Mã học sinh:</strong> {student.get('code', '')}</p>
                <p><strong>Lớp:</strong> {class_info.get('short_title', '')}</p>
            </div>
            
            {subjects_html}
            {homeroom_html}
        </body>
        </html>
        """
        
        return html
        
    except Exception as e:
        frappe.logger().error(f"Error rendering report card HTML: {str(e)}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><title>Error</title></head>
        <body>
            <h1>Error generating report card</h1>
            <p>{str(e)}</p>
        </body>
        </html>
        """


# =============================================================================
# MULTI-LEVEL APPROVAL FLOW APIs
# =============================================================================

def _add_approval_history(report, level: str, user: str, action: str, comment: str = ""):
    """
    Thêm entry vào approval_history của report.
    
    Args:
        report: SIS Student Report Card document
        level: Level duyệt (submit, level_1, level_2, review, publish)
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


def _check_user_is_level_1_approver(user: str, template) -> bool:
    """Kiểm tra user có phải là Khối trưởng (Level 1) không."""
    if not template:
        return False
    
    homeroom_reviewer_l1 = getattr(template, 'homeroom_reviewer_level_1', None)
    if not homeroom_reviewer_l1:
        return False
    
    # Lấy user_id từ teacher
    teacher_user = frappe.db.get_value("SIS Teacher", homeroom_reviewer_l1, "user_id")
    return teacher_user == user


def _check_user_is_level_2_approver(user: str, template, subject_ids: List[str] = None) -> bool:
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


def _check_user_is_level_3_reviewer(user: str, education_stage_id: str, campus_id: str) -> bool:
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


def _check_user_is_level_4_approver(user: str, education_stage_id: str, campus_id: str) -> bool:
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
        
        _add_approval_history(report, "submit", user, "submitted", f"Section: {section}")
        
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
        
        if section in ["scores", "subject_eval", "main_scores", "ielts"]:
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
        # Homeroom có field riêng, Scores/Subject có field riêng
        if section == "homeroom":
            status_field = "homeroom_approval_status"
        elif section in ["scores", "subject_eval", "main_scores", "ielts", "comments"]:
            status_field = "scores_approval_status"
        else:
            # Fallback: dùng approval_status chung
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
                # ✅ Check section-specific status thay vì approval_status chung
                current_section_status = getattr(report_data, status_field, None) or 'draft'
                
                # Cho phép submit các report ở trạng thái draft, entry, hoặc rejected (re-submit)
                if current_section_status not in ['draft', 'entry', 'rejected']:
                    skipped_count += 1
                    continue
                
                # Cập nhật section-specific field
                update_values = {
                    status_field: target_status,
                    "submitted_at": now,
                    "submitted_by": user
                }
                
                # Cũng cập nhật approval_status chung nếu cả 2 section đều ở trạng thái tốt
                # Hoặc nếu đây là lần đầu submit
                current_general_status = report_data.approval_status or 'draft'
                if current_general_status in ['draft', 'entry']:
                    update_values["approval_status"] = target_status
                
                # Clear rejection info khi re-submit
                if current_section_status == 'rejected':
                    update_values["rejection_reason"] = None
                    update_values["rejected_by"] = None
                    update_values["rejected_at"] = None
                
                frappe.db.set_value(
                    "SIS Student Report Card",
                    report_data.name,
                    update_values,
                    update_modified=True
                )
                
                # Thêm approval history
                report = frappe.get_doc("SIS Student Report Card", report_data.name)
                _add_approval_history(
                    report, 
                    "batch_submit", 
                    user, 
                    target_status, 
                    f"Section: {section} ({status_field}), Subject: {subject_id or 'N/A'}"
                )
                report.save(ignore_permissions=True)
                
                submitted_count += 1
                
            except Exception as e:
                errors.append({
                    "report_id": report_data.name,
                    "student_id": report_data.student_id,
                    "error": str(e)
                })
        
        frappe.db.commit()
        
        # Tên section cho thông báo
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
                "errors": errors if errors else None
            },
            message=result_message
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in submit_class_reports: {str(e)}")
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
        if not _check_user_is_level_1_approver(user, template):
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
        
        _add_approval_history(report, "level_1", user, "approved", comment)
        
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
        if not _check_user_is_level_2_approver(user, template, subject_ids):
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
        
        _add_approval_history(report, "level_2", user, "approved", comment)
        
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
        if not _check_user_is_level_3_reviewer(user, education_stage, campus_id):
            user_roles = frappe.get_roles(user)
            if "SIS Manager" not in user_roles and "System Manager" not in user_roles:
                return forbidden_response("Bạn không có quyền Review (Level 3) cho báo cáo này")
        
        # Kiểm tra trạng thái
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        if current_status != 'level_2_approved':
            return error_response(
                message=f"Báo cáo cần ở trạng thái 'level_2_approved'. Hiện tại: '{current_status}'",
                code="INVALID_STATUS"
            )
        
        # Cập nhật
        report.approval_status = "reviewed"
        report.reviewed_at = datetime.now()
        report.reviewed_by = user
        
        _add_approval_history(report, "review", user, "approved", comment)
        
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
        if not _check_user_is_level_4_approver(user, education_stage, campus_id):
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
        
        _add_approval_history(report, "publish", user, "approved", comment)
        
        report.save(ignore_permissions=True)
        frappe.db.commit()
        
        # Gửi notification
        try:
            _send_report_card_notification(report)
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
        
        # Xác định các level user có quyền duyệt
        user_levels = []
        
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
                
                # Subject Manager - Lấy reports có subjects mà user là manager
                managed_subjects = frappe.get_all(
                    "SIS Actual Subject Manager",
                    filters={"teacher_id": teacher_id},
                    fields=["parent"]  # parent là subject_id
                )
                
                if managed_subjects:
                    subject_ids = [s.parent for s in managed_subjects]
                    
                    # Tìm templates có chứa các subjects này (trong scores hoặc subjects)
                    # Lấy tất cả templates của campus
                    all_templates = frappe.get_all(
                        "SIS Report Card Template",
                        filters={"campus_id": campus_id},
                        fields=["name"]
                    )
                    
                    # Filter templates có chứa subjects được quản lý
                    matching_templates = []
                    for tmpl in all_templates:
                        # Check trong scores
                        scores = frappe.get_all(
                            "SIS Report Card Score Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        # Check trong subjects (subject_eval)
                        subjects = frappe.get_all(
                            "SIS Report Card Subject Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        
                        template_subjects = [s.subject_id for s in scores] + [s.subject_id for s in subjects]
                        if any(sid in template_subjects for sid in subject_ids):
                            matching_templates.append(tmpl.name)
                    
                    if matching_templates:
                        # Lấy reports với status level_1_approved (chờ L2 duyệt)
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
                            # Tránh duplicate
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
                    is_l3 = any(
                        (r.user_id == user or frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id") == user)
                        for r in l3_reviewers
                    )
                    if is_l3:
                        # Lấy templates của education_stage này
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name", "homeroom_enabled", "scores_enabled"]
                        )
                        for tmpl in templates:
                            homeroom_enabled = tmpl.get("homeroom_enabled")
                            scores_enabled = tmpl.get("scores_enabled")
                            
                            # Skip nếu cả 2 đều disabled
                            if not homeroom_enabled and not scores_enabled:
                                continue
                            
                            # Level 3: Hiển thị khi ÍT NHẤT MỘT section đã level_2_approved
                            # (bỏ qua sections còn ở draft - chưa submit)
                            # Dùng OR condition: homeroom_approval_status = level_2_approved OR scores_approval_status = level_2_approved
                            or_filters = []
                            if homeroom_enabled:
                                or_filters.append(["homeroom_approval_status", "=", "level_2_approved"])
                            if scores_enabled:
                                or_filters.append(["scores_approval_status", "=", "level_2_approved"])
                            
                            if not or_filters:
                                continue
                            
                            # Query với OR condition
                            reports_l3 = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "campus_id": campus_id
                                },
                                or_filters=or_filters,
                                fields=["name", "title", "student_id", "class_id", "approval_status",
                                        "homeroom_approval_status", "scores_approval_status"]
                            )
                            for r in reports_l3:
                                r["pending_level"] = "review"
                                if not any(existing["name"] == r["name"] for existing in results):
                                    results.append(r)
                
                # Check if user is L4 approver
                if not level or level == "publish":
                    l4_approvers = frappe.get_all(
                        "SIS Report Card Approver",
                        filters={"parent": config.name, "parentfield": "level_4_approvers"},
                        fields=["teacher_id", "user_id"]
                    )
                    is_l4 = any(
                        (r.user_id == user or frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id") == user)
                        for r in l4_approvers
                    )
                    if is_l4:
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
                                    "approval_status": "reviewed",
                                    "campus_id": campus_id
                                },
                                fields=["name", "title", "student_id", "class_id", "approval_status"]
                            )
                            for r in reports_l4:
                                r["pending_level"] = "publish"
                                if r not in results:
                                    results.append(r)
        
        # Validate: Lọc bỏ orphan records (reports có template đã bị xóa)
        # Lấy danh sách template_id từ results để check
        template_ids_to_check = set()
        for r in results:
            report_doc = frappe.db.get_value("SIS Student Report Card", r["name"], "template_id")
            if report_doc:
                template_ids_to_check.add(report_doc)
        
        valid_template_ids = set()
        if template_ids_to_check:
            existing_templates = frappe.get_all(
                "SIS Report Card Template",
                filters={"name": ["in", list(template_ids_to_check)]},
                fields=["name"]
            )
            valid_template_ids = set(t["name"] for t in existing_templates)
        
        # Filter ra orphan records
        filtered_results = []
        for report in results:
            report_template_id = frappe.db.get_value("SIS Student Report Card", report["name"], "template_id")
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
            
            # Lấy tên education_stage (dùng title_vn hoặc title_en)
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
        # Lấy subject_id từ nhiều nguồn: function arg, form_dict, request.args
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
# GROUPED APPROVAL APIs - Hiển thị theo Lớp + Môn
# =============================================================================

@frappe.whitelist(allow_guest=False)
def get_pending_approvals_grouped(level: Optional[str] = None):
    """
    Lấy danh sách báo cáo đang chờ duyệt, grouped by (template, class, subject).
    Trả về dạng aggregated để hiển thị theo Lớp + Môn.
    
    Args:
        level: Filter theo level (level_1, level_2, review, publish)
    
    Returns:
        {
            "reports": [
                {
                    "template_id": "...",
                    "template_title": "...",
                    "class_id": "...",
                    "class_title": "6AB1",
                    "subject_id": "...",  # null nếu là homeroom
                    "subject_title": "Toán",
                    "pending_level": "level_2",
                    "student_count": 35,
                    "submitted_at": "...",
                    "submitted_by": "..."
                }
            ]
        }
    """
    try:
        # Lấy params từ nhiều nguồn cho GET requests
        if not level:
            level = frappe.form_dict.get("level")
        if not level and hasattr(frappe.request, 'args'):
            level = frappe.request.args.get("level")
        
        user = frappe.session.user
        campus_id = get_current_campus_id()
        
        # Lấy teacher của user
        teacher = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": user, "campus_id": campus_id},
            fields=["name"],
            limit=1
        )
        teacher_id = teacher[0].name if teacher else None
        
        # Thu thập tất cả reports theo từng level
        all_reports = []
        
        # Level 1: Khối trưởng duyệt homeroom
        # Query theo homeroom_approval_status thay vì approval_status chung
        if not level or level == "level_1":
            if teacher_id:
                templates_l1 = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"homeroom_reviewer_level_1": teacher_id, "campus_id": campus_id},
                    fields=["name", "title"]
                )
                for tmpl in templates_l1:
                    reports = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": tmpl.name,
                            "homeroom_approval_status": "submitted",
                            "campus_id": campus_id
                        },
                        fields=["name", "class_id", "homeroom_submitted_at", "homeroom_submitted_by"]
                    )
                    for r in reports:
                        r["template_id"] = tmpl.name
                        r["template_title"] = tmpl.title
                        r["pending_level"] = "level_1"
                        r["subject_id"] = None  # Homeroom không có subject
                        r["subject_title"] = "Nhận xét chủ nhiệm"
                        r["submitted_at"] = r.get("homeroom_submitted_at")
                        r["submitted_by"] = r.get("homeroom_submitted_by")
                        all_reports.append(r)
        
        # Level 2: Tổ trưởng hoặc Subject Manager
        if not level or level == "level_2":
            if teacher_id:
                # Tổ trưởng duyệt homeroom - query theo homeroom_approval_status
                # Bao gồm cả reports bị trả về từ Level 3 (có rejection_reason)
                templates_l2 = frappe.get_all(
                    "SIS Report Card Template",
                    filters={"homeroom_reviewer_level_2": teacher_id, "campus_id": campus_id},
                    fields=["name", "title"]
                )
                for tmpl in templates_l2:
                    reports = frappe.get_all(
                        "SIS Student Report Card",
                        filters={
                            "template_id": tmpl.name,
                            "homeroom_approval_status": ["in", ["submitted", "level_1_approved"]],
                            "campus_id": campus_id
                        },
                        fields=["name", "class_id", "homeroom_submitted_at", "homeroom_submitted_by", 
                                "rejection_reason", "rejected_from_level", "rejected_at", "rejected_section"]
                    )
                    for r in reports:
                        r["template_id"] = tmpl.name
                        r["template_title"] = tmpl.title
                        r["pending_level"] = "level_2"
                        r["subject_id"] = None
                        r["subject_title"] = "Nhận xét chủ nhiệm"
                        r["submitted_at"] = r.get("homeroom_submitted_at")
                        r["submitted_by"] = r.get("homeroom_submitted_by")
                        # Kiểm tra nếu bị reject từ L3 (rejected_from_level = 3)
                        if r.get("rejected_from_level") == 3:
                            r["was_rejected"] = True
                        all_reports.append(r)
                
                # Subject Manager - Query theo scores_approval_status
                managed_subjects = frappe.get_all(
                    "SIS Actual Subject Manager",
                    filters={"teacher_id": teacher_id},
                    fields=["parent"]  # parent là subject_id
                )
                
                if managed_subjects:
                    subject_ids = [s.parent for s in managed_subjects]
                    
                    # Lấy thông tin subjects
                    subject_info_map = {}
                    for sid in subject_ids:
                        subject_data = frappe.db.get_value(
                            "SIS Actual Subject", sid, ["title_vn", "title_en"], as_dict=True
                        )
                        if subject_data:
                            subject_info_map[sid] = subject_data.title_vn or subject_data.title_en or sid
                    
                    # Tìm templates có chứa các subjects này
                    all_templates = frappe.get_all(
                        "SIS Report Card Template",
                        filters={"campus_id": campus_id},
                        fields=["name", "title"]
                    )
                    
                    for tmpl in all_templates:
                        # Check trong scores
                        scores = frappe.get_all(
                            "SIS Report Card Score Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        # Check trong subjects (subject_eval)
                        subjects = frappe.get_all(
                            "SIS Report Card Subject Config",
                            filters={"parent": tmpl.name, "parenttype": "SIS Report Card Template"},
                            fields=["subject_id"]
                        )
                        
                        template_subjects = set([s.subject_id for s in scores] + [s.subject_id for s in subjects])
                        matching_subjects = [sid for sid in subject_ids if sid in template_subjects]
                        
                        if matching_subjects:
                            # Lấy reports theo scores_approval_status = submitted hoặc level_1_approved
                            # (level_1_approved khi submit đã skip L1 vì có Subject Manager)
                            # Bao gồm cả reports bị trả về từ Level 3 (có rejection_reason)
                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "scores_approval_status": ["in", ["submitted", "level_1_approved"]],
                                    "campus_id": campus_id
                                },
                                fields=["name", "class_id", "scores_submitted_at", "scores_submitted_by",
                                        "rejection_reason", "rejected_from_level", "rejected_at", "rejected_section"]
                            )
                            for r in reports:
                                for sid in matching_subjects:
                                    r_copy = r.copy()
                                    r_copy["template_id"] = tmpl.name
                                    r_copy["template_title"] = tmpl.title
                                    r_copy["pending_level"] = "level_2"
                                    r_copy["subject_id"] = sid
                                    r_copy["subject_title"] = subject_info_map.get(sid, sid)
                                    r_copy["submitted_at"] = r.get("scores_submitted_at")
                                    r_copy["submitted_by"] = r.get("scores_submitted_by")
                                    # Kiểm tra nếu bị reject từ L3
                                    if r.get("rejected_from_level") == 3:
                                        r_copy["was_rejected"] = True
                                    all_reports.append(r_copy)
        
        # Level 3 & 4: Kiểm tra approval config
        # Level 3, 4 duyệt toàn bộ report card
        # Điều kiện để đến Level 3: cả homeroom và scores đều đã level_2_approved
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
                    is_l3 = any(
                        (r.user_id == user or frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id") == user)
                        for r in l3_reviewers
                    )
                    if is_l3:
                        # Lấy templates với thông tin homeroom_enabled và scores_enabled
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name", "title", "homeroom_enabled", "scores_enabled"]
                        )
                        for tmpl in templates:
                            homeroom_enabled = tmpl.get("homeroom_enabled")
                            scores_enabled = tmpl.get("scores_enabled")
                            
                            # Nếu cả 2 đều disabled -> skip template này
                            if not homeroom_enabled and not scores_enabled:
                                continue
                            
                            # Level 3: Hiển thị khi ÍT NHẤT MỘT section đã level_2_approved
                            # (bỏ qua sections còn ở draft - chưa submit)
                            or_filters = []
                            if homeroom_enabled:
                                or_filters.append(["homeroom_approval_status", "=", "level_2_approved"])
                            if scores_enabled:
                                or_filters.append(["scores_approval_status", "=", "level_2_approved"])
                            
                            if not or_filters:
                                continue
                            
                            # Lấy reports với OR condition
                            # Bao gồm cả reports bị reject từ Level 4 (có rejection_reason)
                            reports = frappe.get_all(
                                "SIS Student Report Card",
                                filters={
                                    "template_id": tmpl.name,
                                    "campus_id": campus_id
                                },
                                or_filters=or_filters,
                                fields=["name", "class_id", "homeroom_submitted_at", "scores_submitted_at",
                                        "rejection_reason", "rejected_from_level", "rejected_at", "rejected_section"]
                            )
                            for r in reports:
                                r["template_id"] = tmpl.name
                                r["template_title"] = tmpl.title
                                r["pending_level"] = "review"
                                r["subject_id"] = None
                                r["subject_title"] = "Toàn bộ báo cáo"
                                # Lấy submitted_at muộn nhất giữa 2 sections
                                r["submitted_at"] = max(
                                    r.get("homeroom_submitted_at") or "",
                                    r.get("scores_submitted_at") or ""
                                ) or None
                                # Kiểm tra nếu bị reject từ L4
                                if r.get("rejected_from_level") == 4:
                                    r["was_rejected"] = True
                                all_reports.append(r)
                
                # Check if user is L4 approver
                if not level or level == "publish":
                    l4_approvers = frappe.get_all(
                        "SIS Report Card Approver",
                        filters={"parent": config.name, "parentfield": "level_4_approvers"},
                        fields=["teacher_id", "user_id"]
                    )
                    is_l4 = any(
                        (r.user_id == user or frappe.db.get_value("SIS Teacher", r.teacher_id, "user_id") == user)
                        for r in l4_approvers
                    )
                    if is_l4:
                        templates = frappe.get_all(
                            "SIS Report Card Template",
                            filters={"education_stage": config.education_stage_id, "campus_id": campus_id},
                            fields=["name", "title"]
                        )
                        for tmpl in templates:
                            # Level 4: approval_status = reviewed (toàn bộ report đã qua review)
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
                    "rejection_reason": r.get("rejection_reason"),  # Lý do trả về
                    "was_rejected": r.get("was_rejected", False),  # Flag bị trả về
                    "rejected_from_level": r.get("rejected_from_level"),  # Level mà bị reject
                    "rejected_section": r.get("rejected_section"),  # Section bị reject: homeroom/scores/both
                    "report_ids": set()  # Để tránh duplicate
                }
            if r["name"] not in grouped[key]["report_ids"]:
                grouped[key]["report_ids"].add(r["name"])
                grouped[key]["student_count"] += 1
                # Cập nhật submitted_at mới nhất
                if r.get("submitted_at") and (not grouped[key]["submitted_at"] or r["submitted_at"] > grouped[key]["submitted_at"]):
                    grouped[key]["submitted_at"] = r["submitted_at"]
                    grouped[key]["submitted_by"] = r.get("submitted_by")
                # Cập nhật rejection info nếu có
                if r.get("rejection_reason"):
                    grouped[key]["rejection_reason"] = r["rejection_reason"]
                    grouped[key]["was_rejected"] = True
                    grouped[key]["rejected_from_level"] = r.get("rejected_from_level")
                    grouped[key]["rejected_section"] = r.get("rejected_section")
        
        # Convert to list và enrich với thông tin class
        # Validate: chỉ giữ những reports có template_id còn tồn tại (bỏ qua orphan records)
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
            # Bỏ qua orphan records (template đã bị xóa)
            if data["template_id"] not in valid_template_ids:
                frappe.logger().warning(f"Skipping orphan report group: template_id={data['template_id']} không còn tồn tại")
                continue
            
            # Remove set (not JSON serializable)
            del data["report_ids"]
            
            # Enrich class info
            class_info = frappe.db.get_value(
                "SIS Class",
                data["class_id"],
                ["title", "short_title"],
                as_dict=True
            )
            if class_info:
                data["class_title"] = class_info.short_title or class_info.title
            
            results.append(data)
        
        # Sort by submitted_at desc
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
        subject_id = data.get("subject_id")  # Có thể null
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
        
        # Xác định section dựa trên subject_id
        is_homeroom = not subject_id
        section = "homeroom" if is_homeroom else "scores"
        
        # Mapping status field theo section và level
        if pending_level in ["level_1", "level_2"]:
            # Level 1, 2 dùng section-specific fields
            status_field = f"{section}_approval_status"
            status_map = {
                "level_1": {"current": ["submitted"], "next": "level_1_approved"},
                "level_2": {"current": ["submitted", "level_1_approved"], "next": "level_2_approved"}
            }
            # Field mapping cho section-specific
            field_map = {
                "level_1": (f"{section}_level_1_approved_at", f"{section}_level_1_approved_by"),
                "level_2": (f"{section}_level_2_approved_at", f"{section}_level_2_approved_by")
            }
        else:
            # Level 3, 4 dùng approval_status chung
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
        
        # Lấy tất cả reports matching
        filters = {
            "template_id": template_id,
            "class_id": class_id,
            "campus_id": campus_id
        }
        
        # Level 3 (review) cần filter theo section-specific fields thay vì approval_status
        # vì Level 2 chỉ update section-specific fields
        if pending_level == "review":
            # Lấy template config để biết sections nào được enable
            template = frappe.get_doc("SIS Report Card Template", template_id)
            homeroom_enabled = getattr(template, 'homeroom_enabled', False)
            scores_enabled = getattr(template, 'scores_enabled', False)
            
            # Nếu cả 2 đều disabled thì không có gì để approve
            if not homeroom_enabled and not scores_enabled:
                return error_response(
                    message="Template không có section nào được bật",
                    code="NO_SECTIONS"
                )
            
            # Level 3: Filter với OR condition - ÍT NHẤT MỘT section đã level_2_approved
            or_filters = []
            if homeroom_enabled:
                or_filters.append(["homeroom_approval_status", "=", "level_2_approved"])
            if scores_enabled:
                or_filters.append(["scores_approval_status", "=", "level_2_approved"])
        else:
            # Level 1, 2, publish: dùng status_field như trước
            filters[status_field] = ["in", current_statuses]
            or_filters = None
        
        # Query reports - sử dụng or_filters nếu có (cho Level 3)
        if or_filters:
            reports = frappe.get_all(
                "SIS Student Report Card",
                filters=filters,
                or_filters=or_filters,
                fields=["name", "student_id"]
            )
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
        
        for report_data in reports:
            try:
                update_values = {
                    status_field: next_status,
                    at_field: now,
                    by_field: user
                }
                
                # Nếu publish, cũng cập nhật status và is_approved
                if pending_level == "publish":
                    update_values["status"] = "published"
                    update_values["is_approved"] = 1
                
                frappe.db.set_value(
                    "SIS Student Report Card",
                    report_data.name,
                    update_values,
                    update_modified=True
                )
                
                # Thêm approval history
                report = frappe.get_doc("SIS Student Report Card", report_data.name)
                _add_approval_history(
                    report,
                    f"batch_{pending_level}_{section}",
                    user,
                    "approved",
                    f"Section: {section}, Class: {class_id}, Subject: {subject_id or 'homeroom'}. {comment}"
                )
                report.save(ignore_permissions=True)
                
                approved_count += 1
                
            except Exception as e:
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
                    _send_report_card_notification(report)
                except Exception as notif_error:
                    frappe.logger().error(f"Failed to send notification: {str(notif_error)}")
        
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
                "errors": errors if errors else None
            },
            message=f"Đã duyệt {approved_count}/{len(reports)} báo cáo ({section}) thành công"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in approve_class_reports: {str(e)}")
        return error_response(f"Lỗi khi duyệt: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def reject_class_reports():
    """
    Batch reject tất cả reports trong 1 class cho 1 subject.
    Chuyển trạng thái về 'rejected' và lưu lý do.
    
    Level 1, 2 sử dụng section-specific fields:
    - subject_id = null -> homeroom_approval_status
    - subject_id != null -> scores_approval_status
    
    Level 3, 4 dùng approval_status chung.
    
    Request body:
        {
            "template_id": "...",
            "class_id": "...",
            "subject_id": "...",  # Optional, null cho homeroom
            "pending_level": "level_1" | "level_2" | "review" | "publish",
            "reason": "..."  # Required - Lý do trả về
        }
    """
    try:
        data = get_request_payload()
        template_id = data.get("template_id")
        class_id = data.get("class_id")
        subject_id = data.get("subject_id")
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
        
        # Xác định section dựa trên subject_id
        is_homeroom = not subject_id
        section = "homeroom" if is_homeroom else "scores"
        
        # Xác định status field và current_status dựa trên pending_level
        if pending_level in ["level_1", "level_2"]:
            status_field = f"{section}_approval_status"
            status_map = {
                "level_1": ["submitted"],
                "level_2": ["submitted", "level_1_approved"]
            }
            # Rejection fields cho section-specific
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
        
        # Lấy tất cả reports matching
        filters = {
            "template_id": template_id,
            "class_id": class_id,
            status_field: ["in", current_statuses],
            "campus_id": campus_id
        }
        
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
        
        for report_data in reports:
            try:
                update_values = {
                    rejection_fields["status_field"]: "rejected",
                    rejection_fields["rejected_at"]: now,
                    rejection_fields["rejected_by"]: user,
                    rejection_fields["rejection_reason"]: reason
                }
                
                frappe.db.set_value(
                    "SIS Student Report Card",
                    report_data.name,
                    update_values,
                    update_modified=True
                )
                
                # Thêm approval history
                report = frappe.get_doc("SIS Student Report Card", report_data.name)
                _add_approval_history(
                    report,
                    f"batch_reject_{pending_level}_{section}",
                    user,
                    "rejected",
                    f"Section: {section}, Class: {class_id}, Subject: {subject_id or 'homeroom'}. Reason: {reason}"
                )
                report.save(ignore_permissions=True)
                
                rejected_count += 1
                
            except Exception as e:
                errors.append({
                    "report_id": report_data.name,
                    "student_id": report_data.student_id,
                    "error": str(e)
                })
        
        frappe.db.commit()
        
        return success_response(
            data={
                "template_id": template_id,
                "class_id": class_id,
                "subject_id": subject_id,
                "section": section,
                "pending_level": pending_level,
                "rejected_count": rejected_count,
                "total_reports": len(reports),
                "reason": reason,
                "errors": errors if errors else None
            },
            message=f"Đã trả về {rejected_count}/{len(reports)} báo cáo ({section})"
        )
        
    except Exception as e:
        frappe.logger().error(f"Error in reject_class_reports: {str(e)}")
        return error_response(f"Lỗi khi trả về: {str(e)}")


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


# =============================================================================
# BATCH REVIEW & PUBLISH APIs - Cho Level 3, Level 4
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
                
                # Kiểm tra campus
                if report.campus_id != campus_id:
                    errors.append({
                        "report_id": report_id,
                        "error": "Không có quyền truy cập báo cáo này"
                    })
                    continue
                
                # Kiểm tra trạng thái
                current_status = getattr(report, 'approval_status', 'draft') or 'draft'
                if current_status != 'level_2_approved':
                    skipped_count += 1
                    continue
                
                # Cập nhật
                report.approval_status = "reviewed"
                report.reviewed_at = now
                report.reviewed_by = user
                
                _add_approval_history(report, "batch_review", user, "approved", "Batch review from ApprovalList")
                
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
    Không render images - frontend sẽ gọi render riêng nếu cần.
    
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
                
                # Kiểm tra campus
                if report.campus_id != campus_id:
                    errors.append({
                        "report_id": report_id,
                        "error": "Không có quyền truy cập báo cáo này"
                    })
                    continue
                
                # Kiểm tra trạng thái
                current_status = getattr(report, 'approval_status', 'draft') or 'draft'
                if current_status != 'reviewed':
                    skipped_count += 1
                    continue
                
                # Cập nhật
                report.approval_status = "published"
                report.status = "published"
                report.is_approved = 1
                report.approved_at = now
                report.approved_by = user
                
                _add_approval_history(report, "batch_publish", user, "published", "Batch publish from ApprovalList")
                
                report.save(ignore_permissions=True)
                
                # Gửi notification
                try:
                    _send_report_card_notification(report)
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
    
    - Reject từ L4 (reviewed) -> quay về L3 (level_2_approved)
    - Reject từ L3 (level_2_approved) -> quay về L2, chỉ reject section được chọn
    
    Request body:
        {
            "report_id": "...",
            "reason": "Lý do trả lại",
            "section": "homeroom" | "scores" | "both" (mặc định "both" nếu không cung cấp)
        }
    """
    try:
        data = get_request_payload()
        report_id = data.get("report_id")
        reason = data.get("reason", "").strip()
        section = data.get("section", "both")  # homeroom | scores | both
        
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
        
        if section not in ['homeroom', 'scores', 'both']:
            return validation_error_response(
                message="section must be 'homeroom', 'scores', or 'both'",
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
        
        current_status = getattr(report, 'approval_status', 'draft') or 'draft'
        now = datetime.now()
        
        # Chỉ cho phép reject từ Level 3 hoặc Level 4
        if current_status not in ['level_2_approved', 'reviewed']:
            return error_response(
                message=f"Không thể trả lại báo cáo ở trạng thái '{current_status}'",
                code="INVALID_STATUS"
            )
        
        # Lưu thông tin rejection chung
        report.rejection_reason = reason
        report.rejected_by = user
        report.rejected_at = now
        report.rejected_section = section  # Field mới: section nào bị reject
        
        # Xác định section name cho message
        section_names = {
            'homeroom': 'Nhận xét GVCN',
            'scores': 'Điểm/Đánh giá GVBM', 
            'both': 'Toàn bộ'
        }
        section_name = section_names.get(section, section)
        
        if current_status == 'reviewed':
            # Từ L4 -> quay về L3: chỉ đổi approval_status chung
            # L4 reject không phân biệt section (vì L3 review toàn bộ)
            report.approval_status = 'level_2_approved'
            report.rejected_from_level = 4
            rejected_from_level = 4
            target_level = 3
            
        else:  # level_2_approved (từ L3)
            # Từ L3 -> quay về L2: CHỈ reject section được chọn
            report.rejected_from_level = 3
            rejected_from_level = 3
            target_level = 2
            
            if section == 'homeroom':
                # Chỉ reject homeroom -> quay về L2 cho Tổ trưởng
                report.homeroom_approval_status = 'level_1_approved'
                report.homeroom_rejection_reason = reason
                report.homeroom_rejected_by = user
                report.homeroom_rejected_at = now
                # Giữ nguyên scores_approval_status
                # approval_status chung đặt về level_1_approved nếu homeroom bị reject
                report.approval_status = 'level_1_approved'
                
            elif section == 'scores':
                # Chỉ reject scores -> quay về L2 cho Subject Manager  
                report.scores_approval_status = 'level_1_approved'
                report.scores_rejection_reason = reason
                report.scores_rejected_by = user
                report.scores_rejected_at = now
                # Giữ nguyên homeroom_approval_status
                # approval_status chung đặt về level_1_approved nếu scores bị reject
                report.approval_status = 'level_1_approved'
                
            else:  # both
                # Reject cả hai section
                report.approval_status = 'level_1_approved'
                report.homeroom_approval_status = 'level_1_approved'
                report.scores_approval_status = 'level_1_approved'
                # Lưu rejection info cho cả hai
                report.homeroom_rejection_reason = reason
                report.homeroom_rejected_by = user
                report.homeroom_rejected_at = now
                report.scores_rejection_reason = reason
                report.scores_rejected_by = user
                report.scores_rejected_at = now
        
        _add_approval_history(
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
