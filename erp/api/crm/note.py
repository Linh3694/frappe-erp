"""
CRM Note API - Ghi chu & cham soc ho so
"""

import frappe
from frappe import _
from frappe.utils import now
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


@frappe.whitelist()
def get_notes():
    """Lay danh sach ghi chu"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    category = frappe.request.args.get("category")
    
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    filters = {"lead": lead_name}
    if category:
        filters["category"] = category

    notes = frappe.get_all(
        "CRM Lead Note",
        filters=filters,
        fields=["*"],
        order_by="creation desc"
    )

    # Bổ sung assignee_name (full_name từ User) cho mỗi note
    for note in notes:
        if note.get("assignee"):
            full_name = frappe.db.get_value("User", note["assignee"], "full_name")
            note["assignee_name"] = full_name or note["assignee"]
        else:
            note["assignee_name"] = ""

    return list_response(notes)


@frappe.whitelist(methods=["POST"])
def create_note():
    """Tao ghi chu moi"""
    check_crm_permission()
    data = get_request_data()
    
    lead_name = data.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    # Nhiệm vụ: content + deadline tùy chọn; Logcall/Loại khác: vẫn bắt buộc nội dung
    errors = {}
    for field in ["title", "communication_method", "category"]:
        if not data.get(field):
            errors[field] = ["Bat buoc"]
    if data.get("category") and data.get("category") != "Nhiem vu":
        if not (data.get("content") or "").strip():
            errors["content"] = ["Bat buoc"]
    if errors:
        return validation_error_response("Thieu thong tin bat buoc", errors)
    
    try:
        doc = frappe.new_doc("CRM Lead Note")
        doc.lead = lead_name
        doc.category = data.get("category")
        doc.title = data.get("title")
        doc.content = data.get("content")
        doc.communication_method = data.get("communication_method")
        doc.assignee = data.get("assignee", frappe.session.user)
        doc.deadline = data.get("deadline")
        doc.is_completed = 0
        
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Tao ghi chu thanh cong")
    
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi tao ghi chu: {str(e)}")


@frappe.whitelist(methods=["POST"])
def update_note():
    """Cap nhat ghi chu"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead Note", name):
        return not_found_response(f"Khong tim thay ghi chu {name}")
    
    try:
        doc = frappe.get_doc("CRM Lead Note", name)
        
        updatable = ["title", "content", "communication_method", "assignee", "deadline", "category", "is_completed"]
        for field in updatable:
            if field in data:
                doc.set(field, data[field])
        
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(doc.as_dict(), "Cap nhat ghi chu thanh cong")
    
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi cap nhat ghi chu: {str(e)}")


@frappe.whitelist(methods=["POST"])
def complete_task():
    """Hoan thanh nhiem vu -> tu dong chuyen category thanh Lich su"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead Note", name):
        return not_found_response(f"Khong tim thay ghi chu {name}")
    
    doc = frappe.get_doc("CRM Lead Note", name)
    
    if doc.category != "Nhiem vu":
        return error_response("Chi co the hoan thanh ghi chu loai Nhiem vu")
    
    doc.is_completed = 1
    doc.category = "Lich su"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    return single_item_response(doc.as_dict(), "Da hoan thanh nhiem vu")


@frappe.whitelist(methods=["POST"])
def delete_note():
    """Xoa ghi chu"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead Note", name):
        return not_found_response(f"Khong tim thay ghi chu {name}")
    
    try:
        frappe.delete_doc("CRM Lead Note", name, ignore_permissions=True)
        frappe.db.commit()
        return success_response(message=f"Da xoa ghi chu {name}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi xoa ghi chu: {str(e)}")
