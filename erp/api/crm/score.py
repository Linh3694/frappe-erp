"""
CRM Score API - Nhap diem & ket qua KSDV
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


@frappe.whitelist()
def download_score_template():
    """Tai file Excel mau de nhap diem"""
    check_crm_permission()
    
    exam_name = frappe.request.args.get("exam_name")
    if not exam_name:
        return validation_error_response("Thieu exam_name", {"exam_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", exam_name):
        return not_found_response(f"Khong tim thay ky thi {exam_name}")
    
    doc = frappe.get_doc("CRM Exam", exam_name)
    
    # Tao danh sach hoc sinh de xuat template
    template_data = []
    for student in doc.students:
        lead_data = frappe.db.get_value(
            "CRM Lead", student.lead,
            ["student_name", "student_code", "target_grade"],
            as_dict=True
        ) or {}
        template_data.append({
            "lead": student.lead,
            "student_name": lead_data.get("student_name", ""),
            "student_code": lead_data.get("student_code", ""),
            "target_grade": lead_data.get("target_grade", ""),
            "subject": "",
            "score": "",
            "result": ""
        })
    
    return list_response(template_data, "Template data cho Excel")


@frappe.whitelist(methods=["POST"])
def import_scores():
    """Import diem tu Excel/data"""
    check_crm_permission()
    data = get_request_data()
    
    exam_name = data.get("exam_name")
    scores_data = data.get("scores", [])
    
    if not exam_name:
        return validation_error_response("Thieu exam_name", {"exam_name": ["Bat buoc"]})
    if not scores_data:
        return validation_error_response("Thieu du lieu diem", {"scores": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", exam_name):
        return not_found_response(f"Khong tim thay ky thi {exam_name}")
    
    results = {"updated": 0, "created": 0, "errors": []}
    
    for score_item in scores_data:
        lead_name = score_item.get("lead")
        subject = score_item.get("subject")
        score_val = score_item.get("score")
        result = score_item.get("result", "")
        
        if not lead_name or not subject:
            results["errors"].append({"lead": lead_name, "error": "Thieu lead hoac mon thi"})
            continue
        
        try:
            # Kiem tra da co diem chua
            existing = frappe.db.get_value(
                "CRM Exam Score",
                {"lead": lead_name, "exam": exam_name, "subject": subject},
                "name"
            )
            
            if existing:
                frappe.db.set_value("CRM Exam Score", existing, {
                    "score": score_val,
                    "result": result
                })
                results["updated"] += 1
            else:
                frappe.get_doc({
                    "doctype": "CRM Exam Score",
                    "lead": lead_name,
                    "exam": exam_name,
                    "subject": subject,
                    "score": score_val,
                    "result": result
                }).insert(ignore_permissions=True)
                results["created"] += 1
            
            # Cap nhat ket qua tren exam student
            if result:
                exam_doc = frappe.get_doc("CRM Exam", exam_name)
                for student in exam_doc.students:
                    if student.lead == lead_name:
                        student.exam_result = result
                        break
                exam_doc.save(ignore_permissions=True)
                
                # Cap nhat trang thai lead theo ket qua
                result_status_map = {
                    "Dat": "Offered",
                    "Dat co dieu kien": "Retake",
                    "Khong dat": "Fail"
                }
                new_status = result_status_map.get(result)
                if new_status:
                    lead_step = frappe.db.get_value("CRM Lead", lead_name, "step")
                    if lead_step == "Test":
                        frappe.db.set_value("CRM Lead", lead_name, "status", new_status)
        
        except Exception as e:
            results["errors"].append({"lead": lead_name, "error": str(e)})
    
    frappe.db.commit()
    return success_response(results, f"Da nhap {results['created']} moi, cap nhat {results['updated']}")


@frappe.whitelist(methods=["POST"])
def update_score():
    """Cap nhat diem thu cong cho 1 HS"""
    check_crm_permission()
    data = get_request_data()
    
    lead_name = data.get("lead_name")
    exam_name = data.get("exam_name")
    scores = data.get("scores", [])
    
    if not lead_name or not exam_name:
        return validation_error_response("Thieu tham so", {
            "lead_name": ["Bat buoc"] if not lead_name else [],
            "exam_name": ["Bat buoc"] if not exam_name else []
        })
    
    results = {"updated": 0, "created": 0}
    
    for score_item in scores:
        subject = score_item.get("subject")
        score_val = score_item.get("score")
        result = score_item.get("result", "")
        
        existing = frappe.db.get_value(
            "CRM Exam Score",
            {"lead": lead_name, "exam": exam_name, "subject": subject},
            "name"
        )
        
        if existing:
            frappe.db.set_value("CRM Exam Score", existing, {
                "score": score_val,
                "result": result
            })
            results["updated"] += 1
        else:
            frappe.get_doc({
                "doctype": "CRM Exam Score",
                "lead": lead_name,
                "exam": exam_name,
                "subject": subject,
                "score": score_val,
                "result": result
            }).insert(ignore_permissions=True)
            results["created"] += 1
    
    frappe.db.commit()
    return success_response(results, "Cap nhat diem thanh cong")


@frappe.whitelist()
def get_student_exam_history():
    """Tong hop lich su thi cua 1 HS"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    # Lay tat ca ky thi co hoc sinh nay
    exams = frappe.db.sql("""
        SELECT ce.name as exam_name, ce.exam_date, ce.exam_time, ce.academic_year,
               ces.email_status, ces.exam_result
        FROM `tabCRM Exam` ce
        INNER JOIN `tabCRM Exam Student` ces ON ces.parent = ce.name
        WHERE ces.lead = %(lead)s
        ORDER BY ce.exam_date DESC
    """, {"lead": lead_name}, as_dict=True)
    
    # Lay diem cho tung ky thi
    for exam in exams:
        scores = frappe.get_all(
            "CRM Exam Score",
            filters={"lead": lead_name, "exam": exam["exam_name"]},
            fields=["subject", "score", "result"]
        )
        exam["scores"] = scores
    
    return success_response({
        "lead": lead_name,
        "total_exams": len(exams),
        "exams": exams
    })
