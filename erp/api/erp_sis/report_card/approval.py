# -*- coding: utf-8 -*-
"""
Report Card Approval APIs
=========================

APIs cho việc phê duyệt Report Card và gửi notification.
"""

import frappe
from frappe import _
import json
from datetime import datetime
from typing import Optional

from erp.utils.api_response import (
    success_response,
    error_response,
)

from .utils import get_request_payload


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
