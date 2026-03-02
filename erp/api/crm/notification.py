"""
CRM Notification API - Tap trung gui email
"""

import frappe
from frappe import _
from frappe.utils import now, getdate
from erp.utils.api_response import (
    success_response, error_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


def _render_email_template(template_type, context):
    """Render template voi data"""
    template = frappe.db.get_value(
        "CRM Email Template",
        {"template_type": template_type},
        ["subject", "content"],
        as_dict=True
    )
    
    if not template:
        return None, None
    
    subject = template["subject"]
    content = template["content"]
    
    # Thay the cac bien trong template
    for key, val in context.items():
        subject = subject.replace(f"{{{{{key}}}}}", str(val))
        content = content.replace(f"{{{{{key}}}}}", str(val))
    
    return subject, content


def _send_email(recipients, subject, content, cc=None):
    """Wrapper gui email"""
    try:
        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=content,
            cc=cc
        )
        return True
    except Exception as e:
        frappe.log_error(f"Loi gui email: {str(e)}")
        return False


@frappe.whitelist(methods=["POST"])
def send_exam_schedule_email():
    """Gui email thong bao lich thi"""
    check_crm_permission()
    data = get_request_data()
    
    exam_name = data.get("exam_name")
    lead_names = data.get("lead_names", [])
    
    if not exam_name:
        return validation_error_response("Thieu exam_name", {"exam_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Exam", exam_name):
        return not_found_response(f"Khong tim thay ky thi {exam_name}")
    
    exam = frappe.get_doc("CRM Exam", exam_name)
    
    # Validate ngay gui <= ngay thi
    if getdate(now()) > getdate(exam.exam_date):
        return error_response("Khong the gui thong bao vi ngay gui > ngay thi")
    
    sent = 0
    errors = []
    
    target_leads = lead_names or [s.lead for s in exam.students]
    
    for lead_name in target_leads:
        lead = frappe.db.get_value(
            "CRM Lead", lead_name,
            ["guardian_email", "student_name", "guardian_name"],
            as_dict=True
        )
        
        if not lead or not lead.get("guardian_email"):
            errors.append({"lead": lead_name, "error": "Khong co email"})
            continue
        
        context = {
            "student_name": lead.get("student_name", ""),
            "guardian_name": lead.get("guardian_name", ""),
            "exam_date": str(exam.exam_date),
            "exam_time": exam.exam_time or "",
        }
        
        subject, content = _render_email_template("Exam Schedule", context)
        if not subject:
            subject = f"Thong bao lich thi KSDV - {lead.get('student_name', '')}"
            content = f"Lich thi: {exam.exam_date} {exam.exam_time or ''}"
        
        if _send_email([lead["guardian_email"]], subject, content, cc=["tuyensinh@wellspring.edu.vn"]):
            for student in exam.students:
                if student.lead == lead_name:
                    student.email_status = "Da gui"
                    break
            sent += 1
        else:
            errors.append({"lead": lead_name, "error": "Gui email that bai"})
    
    if sent > 0:
        exam.save(ignore_permissions=True)
        frappe.db.commit()
    
    return success_response({"sent": sent, "errors": errors}, f"Da gui {sent} email")


@frappe.whitelist(methods=["POST"])
def send_exam_result_email():
    """Gui email ket qua thi"""
    check_crm_permission()
    data = get_request_data()
    
    exam_name = data.get("exam_name")
    lead_names = data.get("lead_names", [])
    template_type = data.get("template_type", "Exam Result Pass")
    
    if not exam_name or not lead_names:
        return validation_error_response("Thieu tham so", {
            "exam_name": ["Bat buoc"] if not exam_name else [],
            "lead_names": ["Bat buoc"] if not lead_names else []
        })
    
    sent = 0
    errors = []
    
    for lead_name in lead_names:
        lead = frappe.db.get_value(
            "CRM Lead", lead_name,
            ["guardian_email", "student_name", "guardian_name"],
            as_dict=True
        )
        
        if not lead or not lead.get("guardian_email"):
            errors.append({"lead": lead_name, "error": "Khong co email"})
            continue
        
        context = {
            "student_name": lead.get("student_name", ""),
            "guardian_name": lead.get("guardian_name", ""),
        }
        
        subject, content = _render_email_template(template_type, context)
        if not subject:
            subject = f"Ket qua KSDV - {lead.get('student_name', '')}"
            content = f"Ket qua: {template_type}"
        
        if _send_email([lead["guardian_email"]], subject, content, cc=["tuyensinh@wellspring.edu.vn"]):
            sent += 1
        else:
            errors.append({"lead": lead_name, "error": "Gui email that bai"})
    
    return success_response({"sent": sent, "errors": errors}, f"Da gui {sent} email ket qua")


@frappe.whitelist(methods=["POST"])
def send_duplicate_warning_email():
    """Gui email canh bao ho so trung"""
    check_crm_permission()
    data = get_request_data()
    
    old_lead_name = data.get("old_lead_name")
    new_lead_name = data.get("new_lead_name")
    
    if not old_lead_name or not new_lead_name:
        return validation_error_response("Thieu tham so", {})
    
    old_lead = frappe.db.get_value("CRM Lead", old_lead_name, ["pic", "student_name"], as_dict=True)
    if not old_lead or not old_lead.get("pic"):
        return error_response("Khong tim thay PIC cua ho so cu")
    
    pic_email = frappe.db.get_value("User", old_lead["pic"], "email")
    if not pic_email:
        return error_response("Khong co email PIC")
    
    context = {
        "student_name": old_lead.get("student_name", ""),
        "old_lead": old_lead_name,
        "new_lead": new_lead_name,
    }
    
    subject, content = _render_email_template("Duplicate Warning", context)
    if not subject:
        subject = f"Canh bao: Ho so trung lap - {old_lead.get('student_name', '')}"
        content = f"Co ho so moi ({new_lead_name}) trung voi ho so cua ban ({old_lead_name})"
    
    if _send_email([pic_email], subject, content):
        return success_response(message="Da gui email canh bao")
    
    return error_response("Gui email that bai")
