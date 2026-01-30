# -*- coding: utf-8 -*-
"""
Approval Utilities
==================

Utility functions cho Report Card Approval module.
Bao gồm HTML rendering và các helper functions.

Functions:
- render_report_card_html: Render report card data thành HTML (cho PDF)
"""

import frappe
from frappe import _


# =============================================================================
# HTML RENDERING
# =============================================================================

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
