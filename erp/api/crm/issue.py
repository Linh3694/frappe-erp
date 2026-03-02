"""
CRM Issue API - Van de chung cua hoc sinh
"""

import frappe
from frappe import _
from frappe.utils import now
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


def _generate_issue_code(issue_type):
    """Tu dong tao ma van de: I-xxx hoac C-xxx"""
    prefix = "I" if issue_type == "Phan anh, phan nan" else "C"
    
    last_code = frappe.db.sql("""
        SELECT issue_code FROM `tabCRM Issue`
        WHERE issue_code LIKE %(prefix)s
        ORDER BY creation DESC LIMIT 1
    """, {"prefix": f"{prefix}-%"}, as_dict=True)
    
    if last_code and last_code[0].get("issue_code"):
        try:
            last_num = int(last_code[0]["issue_code"].split("-")[1])
            return f"{prefix}-{last_num + 1:03d}"
        except (ValueError, IndexError):
            pass
    
    return f"{prefix}-001"


@frappe.whitelist()
def get_issues():
    """Lay danh sach van de"""
    check_crm_permission()
    
    student_id = frappe.request.args.get("student_id")
    lead_name = frappe.request.args.get("lead_name")
    status = frappe.request.args.get("status")
    issue_type = frappe.request.args.get("issue_type")
    page = int(frappe.request.args.get("page", 1))
    per_page = int(frappe.request.args.get("per_page", 20))
    
    filters = {}
    if student_id:
        filters["student"] = student_id
    if lead_name:
        filters["lead"] = lead_name
    if status:
        filters["status"] = status
    if issue_type:
        filters["issue_type"] = issue_type
    
    total = frappe.db.count("CRM Issue", filters=filters)
    offset = (page - 1) * per_page
    
    issues = frappe.get_all(
        "CRM Issue",
        filters=filters,
        fields=["name", "issue_code", "title", "issue_type", "status", "result",
                "pic", "occurred_at", "lead", "student", "modified"],
        order_by="creation desc",
        start=offset,
        page_length=per_page
    )
    
    return paginated_response(issues, page, total, per_page)


@frappe.whitelist()
def get_issue():
    """Chi tiet van de"""
    check_crm_permission()
    
    name = frappe.request.args.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")
    
    doc = frappe.get_doc("CRM Issue", name)
    return single_item_response(doc.as_dict())


@frappe.whitelist(methods=["POST"])
def create_issue():
    """Tao van de moi"""
    check_crm_permission()
    data = get_request_data()
    
    required = ["title", "content", "issue_type"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)
    
    try:
        doc = frappe.new_doc("CRM Issue")
        doc.title = data["title"]
        doc.content = data["content"]
        doc.issue_type = data["issue_type"]
        doc.issue_code = _generate_issue_code(data["issue_type"])
        doc.occurred_at = data.get("occurred_at", now())
        doc.lead = data.get("lead", "")
        doc.student = data.get("student", "")
        doc.pic = data.get("pic", "")
        doc.departments = data.get("departments", "")
        doc.attachment = data.get("attachment", "")
        doc.status = "Tiep nhan"
        
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Tao van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao van de: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_issue():
    """Cap nhat van de"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")
    
    try:
        doc = frappe.get_doc("CRM Issue", name)
        updatable = ["title", "content", "issue_type", "occurred_at", "pic", "departments", "attachment"]
        for field in updatable:
            if field in data:
                doc.set(field, data[field])
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Cap nhat van de thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat: {str(e)}")


@frappe.whitelist(methods=["POST"])
def change_issue_status():
    """Chuyen trang thai van de"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    status = data.get("status")
    result = data.get("result", "")
    
    if not name or not status:
        return validation_error_response("Thieu tham so", {
            "name": ["Bat buoc"] if not name else [],
            "status": ["Bat buoc"] if not status else []
        })
    
    valid_statuses = ["Tiep nhan", "Dang xu ly", "Hoan thanh"]
    if status not in valid_statuses:
        return error_response(f"Trang thai khong hop le. Cac trang thai: {', '.join(valid_statuses)}")
    
    if status == "Hoan thanh" and not result:
        return validation_error_response("Can co ket qua khi hoan thanh", {"result": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Issue", name):
        return not_found_response(f"Khong tim thay van de {name}")
    
    doc = frappe.get_doc("CRM Issue", name)
    doc.status = status
    if result:
        doc.result = result
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    return single_item_response(doc.as_dict(), f"Da chuyen trang thai sang {status}")


@frappe.whitelist(methods=["POST"])
def add_process_log():
    """Them log qua trinh xu ly"""
    check_crm_permission()
    data = get_request_data()
    
    issue_name = data.get("issue_name")
    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")
    
    required = ["title", "content"]
    errors = {}
    for f in required:
        if not data.get(f):
            errors[f] = ["Bat buoc"]
    if errors:
        return validation_error_response("Thieu thong tin", errors)
    
    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
        doc.append("process_logs", {
            "title": data["title"],
            "content": data["content"],
            "logged_at": data.get("logged_at", now()),
            "assignees": data.get("assignees", ""),
            "attachment": data.get("attachment", "")
        })
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Them log xu ly thanh cong")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi them log: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_process_log():
    """Cap nhat log xu ly"""
    check_crm_permission()
    data = get_request_data()
    
    issue_name = data.get("issue_name")
    log_idx = data.get("log_idx")
    
    if not issue_name:
        return validation_error_response("Thieu issue_name", {"issue_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Issue", issue_name):
        return not_found_response(f"Khong tim thay van de {issue_name}")
    
    try:
        doc = frappe.get_doc("CRM Issue", issue_name)
        
        if log_idx is not None and 0 <= int(log_idx) < len(doc.process_logs):
            log = doc.process_logs[int(log_idx)]
            for field in ["title", "content", "assignees", "attachment"]:
                if field in data:
                    setattr(log, field, data[field])
            
            doc.save(ignore_permissions=True)
            frappe.db.commit()
            return single_item_response(doc.as_dict(), "Cap nhat log thanh cong")
        
        return error_response("Khong tim thay log voi index da cho")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat log: {str(e)}")
