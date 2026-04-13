"""
CRM Exam API - Quan ly ky thi KSDV
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


@frappe.whitelist()
def get_exams():
    """Lay danh sach ky thi"""
    check_crm_permission()
    
    academic_year = frappe.request.args.get("academic_year")
    campus_id = frappe.request.args.get("campus_id")
    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 20))
    
    filters = {}
    if academic_year:
        filters["academic_year"] = academic_year
    if campus_id:
        filters["campus_id"] = campus_id
    
    total = frappe.db.count("CRM Exam", filters=filters)
    offset = (page - 1) * per_page
    
    exams = frappe.get_all(
        "CRM Exam",
        filters=filters,
        fields=["name", "academic_year", "exam_date", "exam_time", "campus_id", "modified"],
        order_by="exam_date desc",
        start=offset,
        page_length=per_page
    )
    
    # Dem so HS trong moi ky thi
    for exam in exams:
        exam["student_count"] = frappe.db.count("CRM Exam Student", {"parent": exam["name"]})
    
    return paginated_response(exams, page, total, per_page)


@frappe.whitelist()
def get_exam():
    """Chi tiet ky thi"""
    check_crm_permission()
    
    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", name):
        return not_found_response(f"Khong tim thay ky thi {name}")
    
    doc = frappe.get_doc("CRM Exam", name)
    return single_item_response(doc.as_dict())


@frappe.whitelist(methods=["POST"])
def create_exam():
    """Tao ky thi moi"""
    check_crm_permission()
    data = get_request_data()
    
    required = ["academic_year", "exam_date", "campus_id"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)
    
    try:
        doc = frappe.new_doc("CRM Exam")
        doc.academic_year = data["academic_year"]
        doc.exam_date = data["exam_date"]
        doc.exam_time = data.get("exam_time", "")
        doc.campus_id = data["campus_id"]
        
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Tao ky thi thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao ky thi: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_exam():
    """Cap nhat ky thi"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", name):
        return not_found_response(f"Khong tim thay ky thi {name}")
    
    try:
        doc = frappe.get_doc("CRM Exam", name)
        for field in ["academic_year", "exam_date", "exam_time", "campus_id"]:
            if field in data:
                doc.set(field, data[field])
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Cap nhat ky thi thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")


@frappe.whitelist(methods=["POST"])
def delete_exam():
    """Xoa ky thi"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", name):
        return not_found_response(f"Khong tim thay ky thi {name}")
    
    try:
        frappe.delete_doc("CRM Exam", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message=f"Da xoa ky thi {name}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa: {str(e)}")


@frappe.whitelist(methods=["POST"])
def add_students_to_exam():
    """Them HS vao ky thi (validate: buoc QLead)"""
    check_crm_permission()
    data = get_request_data()
    
    exam_name = data.get("exam_name")
    lead_names = data.get("lead_names", [])
    
    if not exam_name or not lead_names:
        return validation_error_response("Thieu tham so", {
            "exam_name": ["Bat buoc"] if not exam_name else [],
            "lead_names": ["Bat buoc"] if not lead_names else []
        })
    
    if not frappe.db.exists("CRM Exam", exam_name):
        return not_found_response(f"Khong tim thay ky thi {exam_name}")
    
    doc = frappe.get_doc("CRM Exam", exam_name)
    existing_leads = [s.lead for s in doc.students]
    
    added = []
    errors = []
    
    for lead_name in lead_names:
        if lead_name in existing_leads:
            errors.append({"name": lead_name, "error": "Da co trong ky thi"})
            continue
        
        lead = frappe.db.get_value("CRM Lead", lead_name, ["step", "status", "student_name"], as_dict=True)
        if not lead:
            errors.append({"name": lead_name, "error": "Khong tim thay"})
            continue
        
        if lead.step != "QLead":
            errors.append({"name": lead_name, "error": f"Ho so o buoc {lead.step}, can buoc QLead"})
            continue
        
        doc.append("students", {
            "lead": lead_name,
            "student_name": lead.student_name,
            "email_status": "Chua gui"
        })
        added.append(lead_name)
    
    if added:
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    
    return success_response(
        {"added": added, "errors": errors},
        f"Da them {len(added)} hoc sinh"
    )


@frappe.whitelist(methods=["POST"])
def remove_student_from_exam():
    """Xoa HS khoi ky thi"""
    check_crm_permission()
    data = get_request_data()
    
    exam_name = data.get("exam_name")
    lead_name = data.get("lead_name")
    
    if not exam_name or not lead_name:
        return validation_error_response("Thieu tham so", {
            "exam_name": ["Bat buoc"] if not exam_name else [],
            "lead_name": ["Bat buoc"] if not lead_name else []
        })
    
    if not frappe.db.exists("CRM Exam", exam_name):
        return not_found_response(f"Khong tim thay ky thi {exam_name}")
    
    doc = frappe.get_doc("CRM Exam", exam_name)
    
    removed = False
    for i, student in enumerate(doc.students):
        if student.lead == lead_name:
            doc.students.pop(i)
            removed = True
            break
    
    if not removed:
        return error_response(f"Khong tim thay hoc sinh {lead_name} trong ky thi")
    
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    return success_response(message=f"Da xoa hoc sinh {lead_name} khoi ky thi")


@frappe.whitelist()
def export_exam_students():
    """Xuat danh sach HS trong ky thi"""
    check_crm_permission()
    
    exam_name = frappe.request.args.get("exam_name")
    if not exam_name:
        return validation_error_response("Thieu exam_name", {"exam_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", exam_name):
        return not_found_response(f"Khong tim thay ky thi {exam_name}")
    
    doc = frappe.get_doc("CRM Exam", exam_name)
    
    students_data = []
    for student in doc.students:
        lead_data = frappe.db.get_value(
            "CRM Lead", student.lead,
            ["student_name", "guardian_name", "target_grade", "campus_id", "student_code"],
            as_dict=True
        ) or {}
        
        # Lay SDT
        phone = frappe.db.get_value(
            "CRM Lead Phone",
            {"parent": student.lead, "is_primary": 1},
            "phone_number"
        ) or ""
        
        students_data.append({
            "lead": student.lead,
            "student_name": lead_data.get("student_name", ""),
            "student_code": lead_data.get("student_code", ""),
            "guardian_name": lead_data.get("guardian_name", ""),
            "phone": phone,
            "target_grade": lead_data.get("target_grade", ""),
            "email_status": student.email_status,
            "exam_result": student.exam_result or ""
        })
    
    return list_response(students_data)
