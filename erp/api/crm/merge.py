"""
CRM Merge API - Gop ho so trung lap
"""

import frappe
from frappe import _
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    list_response, validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data, generate_crm_code


@frappe.whitelist()
def get_merge_candidates():
    """Lay danh sach ho so trung co the gop"""
    check_crm_permission()
    
    lead_name = frappe.request.args.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    doc = frappe.get_doc("CRM Lead", lead_name)

    from erp.api.crm.duplicate import _find_matching_leads, _find_matching_leads_by_names

    candidates = []

    def _merge_or_append(full_dict, matched_fields):
        """Gop candidate: neu trung name thi gop matched_fields."""
        name = full_dict.get("name")
        if name == lead_name:
            return
        for c in candidates:
            if c.get("name") == name:
                mf = set(c.get("matched_fields") or [])
                mf.update(matched_fields or [])
                c["matched_fields"] = list(mf)
                return
        full_dict["matched_fields"] = list(matched_fields or [])
        candidates.append(full_dict)

    # Tim ho so trung theo duplicate_lead
    if doc.duplicate_lead:
        dup_doc = frappe.get_doc("CRM Lead", doc.duplicate_lead)
        d = dup_doc.as_dict()
        _merge_or_append(d, d.get("matched_fields") or [])

    # Tim theo SDT (check voi ho so trong he thong, khong lay ban ghi Verify khac)
    phones = [p.phone_number for p in doc.phone_numbers]
    if phones:
        matches = _find_matching_leads(
            phones, doc.student_name, doc.guardian_name,
            exclude_draft=True, exclude_verify=True
        )
        for match in matches:
            if match["name"] == lead_name:
                continue
            full_doc = frappe.get_doc("CRM Lead", match["name"]).as_dict()
            _merge_or_append(full_doc, match.get("matched_fields", []))

    # Tim theo cap ten PH + ten HS (bo sung ngoai SĐT)
    name_matches = _find_matching_leads_by_names(
        doc.student_name, doc.guardian_name,
        exclude_draft=True, exclude_verify=True
    )
    for match in name_matches:
        if match["name"] == lead_name:
            continue
        full_doc = frappe.get_doc("CRM Lead", match["name"]).as_dict()
        _merge_or_append(full_doc, match.get("matched_fields", []))

    return list_response(candidates)


@frappe.whitelist(methods=["POST"])
def merge_leads():
    """Gop ho so: giu thong tin primary, hop nhat lich su"""
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()
    
    primary_lead = data.get("primary_lead")
    secondary_leads = data.get("secondary_leads", [])
    
    if not primary_lead or not secondary_leads:
        return validation_error_response("Thieu tham so", {
            "primary_lead": ["Bat buoc"] if not primary_lead else [],
            "secondary_leads": ["Bat buoc"] if not secondary_leads else []
        })
    
    if not frappe.db.exists("CRM Lead", primary_lead):
        return not_found_response(f"Khong tim thay ho so chinh {primary_lead}")
    
    try:
        primary_doc = frappe.get_doc("CRM Lead", primary_lead)
        
        for sec_name in secondary_leads:
            if not frappe.db.exists("CRM Lead", sec_name):
                continue
            
            sec_doc = frappe.get_doc("CRM Lead", sec_name)
            
            # Hop nhat phone numbers (khong trung)
            existing_phones = [p.phone_number for p in primary_doc.phone_numbers]
            for phone in sec_doc.phone_numbers:
                if phone.phone_number not in existing_phones:
                    primary_doc.append("phone_numbers", {
                        "phone_number": phone.phone_number,
                        "is_primary": 0
                    })
            
            # Chuyen notes tu secondary sang primary
            sec_notes = frappe.get_all("CRM Lead Note", filters={"lead": sec_name}, fields=["name"])
            for note in sec_notes:
                frappe.db.set_value("CRM Lead Note", note["name"], "lead", primary_lead)
            
            # Chuyen step history
            sec_histories = frappe.get_all("CRM Lead Step History", filters={"lead": sec_name}, fields=["name"])
            for hist in sec_histories:
                frappe.db.set_value("CRM Lead Step History", hist["name"], "lead", primary_lead)
            
            # Xoa ho so phu
            frappe.delete_doc("CRM Lead", sec_name, ignore_permissions=True)
        
        # Chuyen sang Lead va sinh crm_code sau khi gop
        if primary_doc.step in ("Draft", "Verify"):
            primary_doc.step = "Lead"
            primary_doc.status = "Moi"
            if not primary_doc.crm_code:
                primary_doc.crm_code = generate_crm_code()
            primary_doc.duplicate_lead = ""
            primary_doc.duplicate_fields = ""

        if primary_doc.step == "Lead" and not primary_doc.pic:
            from erp.api.crm.assignment import assign_pic_sales_weight_balance

            pic = assign_pic_sales_weight_balance(primary_doc.name, primary_doc.campus_id)
            if pic:
                primary_doc.pic = pic

        primary_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return single_item_response(primary_doc.as_dict(), "Gop ho so thanh cong")
    
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Loi gop ho so: {str(e)}")


@frappe.whitelist(methods=["POST"])
def skip_merge():
    """Khong gop, chuyen lead sang buoc tiep theo"""
    check_crm_permission()
    data = get_request_data()
    
    lead_name = data.get("lead_name")
    if not lead_name:
        return validation_error_response("Thieu lead_name", {"lead_name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")
    
    doc = frappe.get_doc("CRM Lead", lead_name)
    
    if doc.step == "Verify":
        doc.step = "Lead"
        doc.status = "Moi"
        if not doc.crm_code:
            doc.crm_code = generate_crm_code()
        doc.duplicate_lead = ""
        doc.duplicate_fields = ""
        if not doc.pic:
            from erp.api.crm.assignment import assign_pic_sales_weight_balance

            pic = assign_pic_sales_weight_balance(doc.name, doc.campus_id)
            if pic:
                doc.pic = pic
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    
    return single_item_response(doc.as_dict(), "Da bo qua gop va chuyen sang Lead")
