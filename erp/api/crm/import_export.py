"""
CRM Import/Export API - Import/Export ho so hang loat
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, list_response, validation_error_response
)
from erp.api.crm.utils import (
    check_crm_permission, get_request_data,
    validate_phone_number, normalize_phone_number
)


@frappe.whitelist()
def download_lead_template():
    """Tai file Excel mau theo step"""
    check_crm_permission()
    
    step = frappe.request.args.get("step", "Draft")
    
    template_fields = [
        {"field": "student_name", "label": "Ten hoc sinh"},
        {"field": "student_gender", "label": "Gioi tinh (Nam/Nu)"},
        {"field": "student_dob", "label": "Ngay sinh (YYYY-MM-DD)"},
        {"field": "current_grade", "label": "Lop dang hoc"},
        {"field": "target_grade", "label": "Lop du tuyen"},
        {"field": "guardian_name", "label": "Ten phu huynh"},
        {"field": "relationship", "label": "Moi quan he (Bo/Me/Nguoi giam ho)"},
        {"field": "guardian_email", "label": "Email PH"},
        {"field": "phone_number", "label": "So dien thoai (bat buoc)"},
        {"field": "data_source", "label": "Nguon (Online/Offline/Doi tac)"},
    ]
    
    if step == "Lead":
        template_fields.extend([
            {"field": "current_school", "label": "Truong dang hoc"},
            {"field": "guardian_id_number", "label": "So CCCD/Ho chieu"},
        ])
    
    return success_response({"fields": template_fields, "step": step})


@frappe.whitelist(methods=["POST"])
def bulk_import_leads():
    """Import ho so tu Excel/data"""
    check_crm_permission()
    data = get_request_data()
    
    rows = data.get("rows", [])
    target_step = data.get("target_step", "Draft")
    
    if not rows:
        return validation_error_response("Khong co du lieu", {"rows": ["Bat buoc"]})
    
    results = {"success": 0, "duplicates": 0, "errors": []}
    
    for idx, row in enumerate(rows):
        phone = row.get("phone_number", "")
        
        if not phone or not validate_phone_number(phone):
            results["errors"].append({
                "row": idx + 1,
                "error": f"SDT khong hop le: {phone}"
            })
            continue
        
        normalized_phone = normalize_phone_number(phone)
        
        # Kiem tra trung
        if target_step == "Draft":
            from erp.api.crm.duplicate import _find_matching_leads
            draft_matches = frappe.db.sql("""
                SELECT cl.name FROM `tabCRM Lead` cl
                INNER JOIN `tabCRM Lead Phone` clp ON clp.parent = cl.name
                WHERE cl.step = 'Draft' AND clp.phone_number = %s
            """, normalized_phone)
            if draft_matches:
                results["duplicates"] += 1
                continue
        
        try:
            doc = frappe.new_doc("CRM Lead")
            doc.step = target_step
            doc.status = "New"
            
            field_map = [
                "student_name", "student_gender", "student_dob",
                "current_grade", "target_grade", "guardian_name",
                "relationship", "guardian_email", "data_source",
                "current_school", "guardian_id_number", "campus_id"
            ]
            for field in field_map:
                if row.get(field):
                    doc.set(field, row[field])
            
            doc.append("phone_numbers", {
                "phone_number": normalized_phone,
                "is_primary": 1
            })
            
            doc.insert(ignore_permissions=True)
            results["success"] += 1
        
        except Exception as e:
            results["errors"].append({"row": idx + 1, "error": str(e)})
    
    frappe.db.commit()
    return success_response(
        results,
        f"Import: {results['success']} thanh cong, {results['duplicates']} trung, {len(results['errors'])} loi"
    )


@frappe.whitelist()
def export_leads():
    """Xuat danh sach ho so"""
    check_crm_permission()
    
    step = frappe.request.args.get("step")
    status = frappe.request.args.get("status")
    campus_id = frappe.request.args.get("campus_id")
    
    filters = {}
    if step:
        filters["step"] = step
    if status:
        filters["status"] = status
    if campus_id:
        filters["campus_id"] = campus_id
    
    leads = frappe.get_all(
        "CRM Lead",
        filters=filters,
        fields=[
            "name", "step", "status", "student_name", "student_gender", "student_dob",
            "student_code", "current_grade", "target_grade", "guardian_name",
            "relationship", "guardian_email", "campus_id", "pic",
            "data_source", "creation", "modified"
        ],
        order_by="creation desc"
    )
    
    for lead in leads:
        phone = frappe.db.get_value(
            "CRM Lead Phone",
            {"parent": lead["name"], "is_primary": 1},
            "phone_number"
        ) or ""
        lead["primary_phone"] = phone
    
    return list_response(leads)
