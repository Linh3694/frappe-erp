"""
Debit Note PDF Generation API
Tạo file PDF Debit Note cho học sinh.
"""

import frappe
from frappe import _
from frappe.utils import now, getdate
from frappe.utils.pdf import get_pdf
import json
import os

from erp.utils.api_response import (
    error_response, 
    success_response, 
)


def _check_admin_permission():
    """Kiểm tra quyền admin"""
    user_roles = frappe.get_roles(frappe.session.user)
    allowed_roles = ['System Manager', 'SIS Manager', 'Registrar', 'SIS BOD']
    
    if not any(role in user_roles for role in allowed_roles):
        return False
    return True


def _format_currency(amount):
    """Format số tiền theo định dạng VND"""
    if not amount:
        return "-"
    return "{:,.0f}".format(amount)


def _build_debit_note_html(order_student_id, milestone_number):
    """
    Xây dựng HTML cho Debit Note.
    
    Args:
        order_student_id: ID Order Student
        milestone_number: Số mốc áp dụng
    
    Returns:
        HTML string
    """
    # Lấy thông tin học sinh
    order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
    order = frappe.get_doc("SIS Finance Order", order_student.order_id)
    
    # Lấy thông tin năm tài chính
    finance_year = frappe.get_doc("SIS Finance Year", order.finance_year_id)
    
    # Build các dòng khoản phí
    milestone_key = f"m{milestone_number}"
    lines_html = ""
    
    for fee_line in order_student.fee_lines:
        order_line = order.get_fee_line(fee_line.line_number)
        if not order_line:
            continue
        
        # Parse amounts
        amounts = {}
        if fee_line.amounts_json:
            try:
                amounts = json.loads(fee_line.amounts_json)
            except:
                pass
        
        # Xác định style dựa trên line_type
        row_class = ""
        if fee_line.line_type in ['category', 'total']:
            row_class = "font-bold bg-gray-100"
        elif fee_line.line_type == 'subtotal':
            row_class = "font-medium"
        
        # Build các cột số tiền cho từng mốc
        amount_cells = ""
        for m in order.milestones:
            m_key = f"m{m.milestone_number}"
            amount = amounts.get(m_key, 0) or 0
            is_current = m.milestone_number == int(milestone_number)
            is_deduction = order_line.is_deduction
            
            cell_class = "text-right"
            if is_current:
                cell_class += " bg-green-100"
            
            formatted = _format_currency(amount) if amount else "-"
            if is_deduction and amount:
                formatted = f"-{formatted}"
                cell_class += " text-red-600"
            
            amount_cells += f'<td class="{cell_class}">{formatted}</td>'
        
        # Note column
        note = ""
        if order_line.is_compulsory:
            note = "Compulsory"
        if fee_line.note:
            note += f" {fee_line.note}" if note else fee_line.note
        
        lines_html += f'''
        <tr class="{row_class}">
            <td class="text-center">{fee_line.line_number}</td>
            <td>
                <div>{order_line.title_en}</div>
                <div class="text-gray-500 text-sm">{order_line.title_vn}</div>
            </td>
            {amount_cells}
            <td class="text-sm text-gray-500">{note}</td>
        </tr>
        '''
    
    # Build header cho các mốc
    milestone_headers = ""
    for m in order.milestones:
        is_current = m.milestone_number == int(milestone_number)
        header_class = "bg-navy text-white text-right"
        if is_current:
            header_class = "bg-green-600 text-white text-right"
        
        deadline_str = ""
        if m.deadline_date:
            deadline_str = getdate(m.deadline_date).strftime("%d/%m/%Y")
        
        milestone_headers += f'''
        <th class="{header_class}">
            {m.title}
            <br>
            <span class="text-xs font-normal">{deadline_str}</span>
        </th>
        '''
    
    # Build HTML hoàn chỉnh
    html = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @page {{
            size: A4;
            margin: 15mm;
        }}
        body {{
            font-family: Arial, sans-serif;
            font-size: 11px;
            line-height: 1.4;
            color: #333;
        }}
        .header {{
            border-bottom: 2px solid #002855;
            padding-bottom: 15px;
            margin-bottom: 15px;
        }}
        .logo {{
            width: 60px;
            height: auto;
        }}
        .school-name {{
            font-size: 16px;
            font-weight: bold;
            color: #002855;
        }}
        .document-title {{
            font-size: 20px;
            font-weight: bold;
            color: #002855;
            text-align: center;
            margin: 15px 0;
        }}
        .student-info {{
            background-color: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 15px;
        }}
        .student-info table {{
            width: 100%;
        }}
        .student-info td {{
            padding: 3px 10px;
        }}
        .student-info .label {{
            color: #666;
            width: 120px;
        }}
        .student-info .value {{
            font-weight: bold;
        }}
        table.fee-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 15px;
        }}
        table.fee-table th, table.fee-table td {{
            border: 1px solid #ddd;
            padding: 6px 8px;
        }}
        table.fee-table th {{
            background-color: #002855;
            color: white;
            font-weight: bold;
        }}
        .bg-navy {{
            background-color: #002855;
        }}
        .bg-green-600 {{
            background-color: #16a34a;
        }}
        .bg-green-100 {{
            background-color: #dcfce7;
        }}
        .bg-gray-100 {{
            background-color: #f3f4f6;
        }}
        .text-right {{
            text-align: right;
        }}
        .text-center {{
            text-align: center;
        }}
        .text-gray-500 {{
            color: #6b7280;
        }}
        .text-red-600 {{
            color: #dc2626;
        }}
        .font-bold {{
            font-weight: bold;
        }}
        .font-medium {{
            font-weight: 500;
        }}
        .text-sm {{
            font-size: 10px;
        }}
        .text-xs {{
            font-size: 9px;
        }}
        .footer {{
            margin-top: 20px;
            font-size: 10px;
            color: #666;
            border-top: 1px solid #ddd;
            padding-top: 10px;
        }}
        .footer-notes {{
            margin-bottom: 10px;
        }}
        .footer-notes p {{
            margin: 3px 0;
        }}
    </style>
</head>
<body>
    <!-- Header -->
    <div class="header">
        <table style="width: 100%;">
            <tr>
                <td style="width: 80px;">
                    <img src="/assets/erp/images/wellspring-logo.png" alt="Logo" class="logo" onerror="this.style.display='none'">
                </td>
                <td>
                    <div class="school-name">WELLSPRING INTERNATIONAL BILINGUAL SCHOOL</div>
                    <div>Trường Quốc Tế Song Ngữ Wellspring</div>
                </td>
                <td style="text-align: right;">
                    <div>School Year: {finance_year.title}</div>
                    <div>Date: {getdate(now()).strftime("%d/%m/%Y")}</div>
                </td>
            </tr>
        </table>
    </div>

    <!-- Document Title -->
    <div class="document-title">DEBIT NOTE / THÔNG BÁO PHÍ</div>
    <div style="text-align: center; color: #666; margin-bottom: 15px;">{order.title}</div>

    <!-- Student Info -->
    <div class="student-info">
        <table>
            <tr>
                <td class="label">Student Code / Mã HS:</td>
                <td class="value">{order_student.student_code}</td>
                <td class="label">Class / Lớp:</td>
                <td class="value">{order_student.class_title or '-'}</td>
            </tr>
            <tr>
                <td class="label">Student Name / Họ tên:</td>
                <td class="value" colspan="3">{order_student.student_name}</td>
            </tr>
        </table>
    </div>

    <!-- Fee Table -->
    <table class="fee-table">
        <thead>
            <tr>
                <th class="bg-navy text-center" style="width: 50px;">STT</th>
                <th class="bg-navy">Description / Nội dung</th>
                {milestone_headers}
                <th class="bg-navy" style="width: 100px;">Note / Ghi chú</th>
            </tr>
        </thead>
        <tbody>
            {lines_html}
        </tbody>
    </table>

    <!-- Footer -->
    <div class="footer">
        <div class="footer-notes">
            <p>* Vui lòng thanh toán trước hạn để được hưởng ưu đãi.</p>
            <p>* Các khoản phí có thể thay đổi tùy theo chính sách của nhà trường.</p>
            <p>* Mọi thắc mắc xin liên hệ Phòng Kế toán: ketoan@wellspring.edu.vn</p>
        </div>
        <div style="text-align: center; color: #999;">
            Generated on: {now()}
        </div>
    </div>
</body>
</html>
'''
    
    return html


@frappe.whitelist()
def generate_debit_note_pdf(order_student_id=None, milestone_number=None):
    """
    Generate Debit Note PDF cho học sinh.
    
    Args:
        order_student_id: ID Order Student
        milestone_number: Số mốc áp dụng
    
    Returns:
        URL file PDF
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo PDF", logs=logs)
        
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id') or frappe.form_dict.get('order_student_id')
        if not milestone_number:
            milestone_number = frappe.request.args.get('milestone_number') or frappe.form_dict.get('milestone_number')
        
        if not order_student_id:
            return error_response("Thiếu order_student_id", logs=logs)
        
        # Mặc định lấy mốc 1
        if not milestone_number:
            order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
            order = frappe.get_doc("SIS Finance Order", order_student.order_id)
            if order.milestones:
                milestone_number = order.milestones[0].milestone_number
            else:
                milestone_number = 1
        
        logs.append(f"Generate PDF cho {order_student_id}, mốc {milestone_number}")
        
        # Build HTML
        html = _build_debit_note_html(order_student_id, int(milestone_number))
        
        # Generate PDF
        pdf_content = get_pdf(html)
        
        # Lưu file
        order_student = frappe.get_doc("SIS Finance Order Student", order_student_id)
        file_name = f"debit_note_{order_student.student_code}_{milestone_number}_{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}.pdf"
        
        # Tạo file attachment
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "attached_to_doctype": "SIS Finance Order Student",
            "attached_to_name": order_student_id,
            "content": pdf_content,
            "is_private": 0
        })
        file_doc.save(ignore_permissions=True)
        
        file_url = file_doc.file_url
        
        logs.append(f"Đã tạo PDF: {file_url}")
        
        return success_response(
            data={
                "pdf_url": file_url,
                "file_name": file_name,
                "order_student_id": order_student_id,
                "milestone_number": int(milestone_number)
            },
            message="Tạo PDF thành công",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Generate Debit Note PDF Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist()
def generate_batch_debit_notes(send_batch_id=None):
    """
    Generate Debit Notes cho tất cả học sinh trong đợt gửi.
    
    Args:
        send_batch_id: ID Send Batch
    
    Returns:
        Số PDF đã tạo
    """
    logs = []
    
    try:
        if not _check_admin_permission():
            return error_response("Bạn không có quyền tạo PDF", logs=logs)
        
        if not send_batch_id:
            send_batch_id = frappe.form_dict.get('send_batch_id')
        
        if not send_batch_id:
            return error_response("Thiếu send_batch_id", logs=logs)
        
        # Lấy thông tin đợt gửi
        send_batch = frappe.get_doc("SIS Finance Send Batch", send_batch_id)
        milestone_number = send_batch.milestone_number
        
        logs.append(f"Generate PDFs cho đợt gửi {send_batch_id}, mốc {milestone_number}")
        
        # Lấy danh sách học sinh từ Debit Note History
        histories = frappe.get_all(
            "SIS Finance Debit Note History",
            filters={"send_batch_id": send_batch_id},
            fields=["name", "order_student_id"]
        )
        
        success_count = 0
        error_count = 0
        
        for history in histories:
            try:
                # Generate PDF
                html = _build_debit_note_html(history.order_student_id, milestone_number)
                pdf_content = get_pdf(html)
                
                # Lưu file
                order_student = frappe.get_doc("SIS Finance Order Student", history.order_student_id)
                file_name = f"debit_note_{order_student.student_code}_v{len(frappe.get_all('SIS Finance Debit Note History', filters={'order_student_id': history.order_student_id}))}_{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S')}.pdf"
                
                file_doc = frappe.get_doc({
                    "doctype": "File",
                    "file_name": file_name,
                    "attached_to_doctype": "SIS Finance Debit Note History",
                    "attached_to_name": history.name,
                    "content": pdf_content,
                    "is_private": 0
                })
                file_doc.save(ignore_permissions=True)
                
                # Cập nhật Debit Note History
                frappe.db.set_value("SIS Finance Debit Note History", history.name, "pdf_url", file_doc.file_url)
                
                success_count += 1
                
            except Exception as e:
                logs.append(f"Lỗi tạo PDF cho {history.order_student_id}: {str(e)}")
                error_count += 1
        
        frappe.db.commit()
        
        logs.append(f"Hoàn thành: {success_count} thành công, {error_count} lỗi")
        
        return success_response(
            data={
                "success_count": success_count,
                "error_count": error_count,
                "total": len(histories)
            },
            message=f"Đã tạo {success_count} PDF",
            logs=logs
        )
        
    except Exception as e:
        logs.append(f"Lỗi: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Generate Batch Debit Notes Error")
        return error_response(f"Lỗi: {str(e)}", logs=logs)


@frappe.whitelist(allow_guest=True)
def download_debit_note_pdf(order_student_id=None, milestone_number=None):
    """
    Download Debit Note PDF (public API cho phụ huynh).
    Trả về file PDF trực tiếp.
    """
    try:
        if not order_student_id:
            order_student_id = frappe.request.args.get('order_student_id')
        if not milestone_number:
            milestone_number = frappe.request.args.get('milestone_number')
        
        if not order_student_id:
            frappe.throw("Thiếu order_student_id")
        
        # Build HTML
        html = _build_debit_note_html(order_student_id, int(milestone_number or 1))
        
        # Generate PDF
        pdf_content = get_pdf(html)
        
        # Trả về file PDF
        frappe.local.response.filename = f"debit_note_{order_student_id}.pdf"
        frappe.local.response.filecontent = pdf_content
        frappe.local.response.type = "download"
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Download Debit Note PDF Error")
        frappe.throw(f"Lỗi: {str(e)}")
