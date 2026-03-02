"""
CRM Student Code API - Tao ma hoc sinh
Cau truc: [Ma truong][Nam hoc][Khoi][So tinh tien]
VD: WS12501001 = WS1 + 25 + 01 + 001
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, validation_error_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


def _get_academic_year_code(academic_year):
    """Lay 2 so dau cua nam bat dau nam hoc. VD: 2025-2026 -> 25"""
    if not academic_year:
        from frappe.utils import nowdate
        return str(int(nowdate()[:4]) % 100).zfill(2)
    
    # Lay nam tu SIS School Year
    year_name = frappe.db.get_value("SIS School Year", academic_year, "name") or academic_year
    
    # Thu parse tu name (co the la "2025-2026" hoac "SY-00001")
    try:
        if "-" in str(year_name) and len(str(year_name).split("-")[0]) == 4:
            return str(int(year_name.split("-")[0]) % 100).zfill(2)
    except (ValueError, IndexError):
        pass
    
    from frappe.utils import nowdate
    return str(int(nowdate()[:4]) % 100).zfill(2)


def _get_grade_code(grade):
    """Chuyen khoi thanh 2 chu so. VD: 1 -> 01, 10 -> 10"""
    try:
        return str(int(grade)).zfill(2)
    except (ValueError, TypeError):
        return "01"


def _get_next_sequence(campus_code, year_code, grade_code):
    """Lay so tinh tien tiep theo"""
    prefix = f"{campus_code}{year_code}{grade_code}"
    
    last_code = frappe.db.sql("""
        SELECT student_code FROM `tabCRM Lead`
        WHERE student_code LIKE %(prefix)s
        ORDER BY student_code DESC LIMIT 1
    """, {"prefix": f"{prefix}%"}, as_dict=True)
    
    if last_code and last_code[0].get("student_code"):
        try:
            code = last_code[0]["student_code"]
            seq_part = code[len(prefix):]
            return int(seq_part) + 1
        except (ValueError, IndexError):
            pass
    
    return 1


def _generate_code_internal(campus_code, academic_year, grade):
    """Internal: tao ma hoc sinh"""
    year_code = _get_academic_year_code(academic_year)
    grade_code = _get_grade_code(grade)
    seq = _get_next_sequence(campus_code or "WS1", year_code, grade_code)
    
    return f"{campus_code or 'WS1'}{year_code}{grade_code}{seq:03d}"


@frappe.whitelist(methods=["POST"])
def generate_student_code():
    """Tao ma hoc sinh"""
    check_crm_permission()
    data = get_request_data()
    
    campus_code = data.get("campus_code", "WS1")
    academic_year = data.get("academic_year", "")
    grade = data.get("grade", "1")
    
    code = _generate_code_internal(campus_code, academic_year, grade)
    
    return success_response({"student_code": code})


@frappe.whitelist()
def check_student_code_exists():
    """Kiem tra ma hoc sinh da ton tai chua"""
    check_crm_permission()
    
    code = frappe.request.args.get("code")
    if not code:
        return validation_error_response("Thieu code", {"code": ["Bat buoc"]})
    
    exists = frappe.db.exists("CRM Lead", {"student_code": code})
    return success_response({"exists": bool(exists), "code": code})
