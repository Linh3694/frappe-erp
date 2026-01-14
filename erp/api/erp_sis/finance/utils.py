"""
Finance API Utility Functions
Các hàm helper dùng chung cho Finance APIs

Không được export ra bên ngoài - chỉ dùng nội bộ trong module finance.
"""

import frappe
from frappe import _
import json


def _check_admin_permission():
    """Kiểm tra quyền admin"""
    user_roles = frappe.get_roles(frappe.session.user)
    allowed_roles = ['System Manager', 'SIS Manager', 'Registrar', 'SIS BOD']
    
    if not any(role in user_roles for role in allowed_roles):
        return False
    return True


def _resolve_campus_id(campus_id):
    """
    Chuyển đổi campus_id từ format frontend (campus-1) sang format database (CAMPUS-00001)
    """
    if not campus_id:
        return None
    
    # Nếu đã đúng format CAMPUS-xxxxx thì return luôn
    if campus_id.startswith("CAMPUS-"):
        if frappe.db.exists("SIS Campus", campus_id):
            return campus_id
    
    # Nếu là format campus-1, campus-2, etc.
    if campus_id.startswith("campus-"):
        try:
            campus_index = int(campus_id.split("-")[1])
            mapped_campus = f"CAMPUS-{campus_index:05d}"
            if frappe.db.exists("SIS Campus", mapped_campus):
                return mapped_campus
        except (ValueError, IndexError):
            pass
    
    # Thử tìm theo name trực tiếp
    if frappe.db.exists("SIS Campus", campus_id):
        return campus_id
    
    # Thử tìm campus đầu tiên
    first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
    if first_campus:
        return first_campus
    
    return None


def _get_request_data():
    """
    Lấy dữ liệu từ request body, hỗ trợ cả JSON và form data
    """
    if frappe.request.is_json:
        return frappe.request.json or {}
    else:
        return frappe.form_dict


def _format_currency_vnd(amount):
    """Format số tiền thành VND string"""
    if not amount:
        return "0 đ"
    return f"{int(amount):,}".replace(",", ".") + " đ"


def _apply_mail_merge(content: str, student_data: dict) -> str:
    """
    Thay thế các placeholder mail merge bằng dữ liệu học sinh.
    
    Placeholders:
    - {{student_name}} -> Tên học sinh
    - {{student_code}} -> Mã học sinh
    - {{class_name}} -> Tên lớp
    - {{total_amount}} -> Tổng số tiền (format VND)
    - {{deadline}} -> Hạn đóng phí
    """
    if not content:
        return content
    
    replacements = {
        "{{student_name}}": student_data.get("student_name", ""),
        "{{student_code}}": student_data.get("student_code", ""),
        "{{class_name}}": student_data.get("class_name", ""),
        "{{total_amount}}": _format_currency_vnd(student_data.get("total_amount", 0)),
        "{{deadline}}": student_data.get("deadline", ""),
    }
    
    result = content
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, str(value))
    
    return result
