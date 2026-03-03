"""
CRM Duplicate Check API - Kiem tra trung lap ho so
Business rules phuc tap theo SRS
"""

import frappe
from frappe.utils import now, getdate, add_years, add_months, date_diff
from erp.utils.api_response import (
    success_response, error_response, validation_error_response
)
from erp.api.crm.utils import (
    check_crm_permission, get_request_data, normalize_phone_number
)


def _find_matching_leads(phone_numbers, student_name=None, guardian_name=None, exclude_draft=False):
    """Tim ho so trung dua tren SDT, ten HS, ten PH"""
    matches = []
    
    normalized_phones = [normalize_phone_number(p) for p in phone_numbers if p]
    if not normalized_phones:
        return matches
    
    # Tim theo SDT
    phone_placeholders = ", ".join(["%s"] * len(normalized_phones))
    
    base_query = """
        SELECT DISTINCT cl.name, cl.step, cl.status, cl.student_name, cl.guardian_name,
               cl.modified, cl.pic, cl.campus_id
        FROM `tabCRM Lead` cl
        INNER JOIN `tabCRM Lead Phone` clp ON clp.parent = cl.name
        WHERE clp.phone_number IN ({placeholders})
    """.format(placeholders=phone_placeholders)
    
    if exclude_draft:
        base_query += " AND cl.step != 'Draft'"
    
    phone_matches = frappe.db.sql(base_query, normalized_phones, as_dict=True)
    
    for match in phone_matches:
        match["matched_fields"] = ["phone_number"]
        
        # Kiem tra them ten HS
        if student_name and match.get("student_name"):
            if student_name.strip().lower() == match["student_name"].strip().lower():
                match["matched_fields"].append("student_name")
        
        # Kiem tra them ten PH
        if guardian_name and match.get("guardian_name"):
            if guardian_name.strip().lower() == match["guardian_name"].strip().lower():
                match["matched_fields"].append("guardian_name")
        
        matches.append(match)
    
    return matches


def _evaluate_duplicate_rules(matched_lead, exclude_draft=False):
    """
    Ap dung business rules de xac dinh buoc va trang thai cho ho so moi.
    
    Rules:
    - TH1: Khong trung hoac chi trung 1 truong (ten PH hoac ten HS) -> Verify/Can kiem tra
    - TH2: Trung >= 2 truong -> Verify/Trung
    - TH3: Chi trung SDT -> kiem tra step va thoi gian
    """
    matched_fields = matched_lead.get("matched_fields", [])
    num_matched = len(matched_fields)
    old_step = matched_lead.get("step", "")
    modified = matched_lead.get("modified")
    
    # Tinh so ngay tu lan cap nhat gan nhat
    days_since_update = 0
    if modified:
        days_since_update = date_diff(now(), modified)
    
    # TH2: Trung >= 2 truong
    if num_matched >= 2 and not (num_matched == 1 and "phone_number" not in matched_fields):
        non_phone_fields = [f for f in matched_fields if f != "phone_number"]
        if len(non_phone_fields) >= 1 and "phone_number" in matched_fields:
            return {
                "is_duplicate": True,
                "duplicate_type": "multi_field",
                "recommended_step": "Verify",
                "recommended_status": "Trung",
                "reason": f"Trung {num_matched} truong: {', '.join(matched_fields)}"
            }
    
    # TH3: Chi trung SDT
    if matched_fields == ["phone_number"]:
        one_year_days = 365
        two_year_days = 730
        
        # TH3.1: Ho so bi trung o buoc Lead
        if old_step == "Lead":
            if days_since_update > one_year_days:
                return {
                    "is_duplicate": False,
                    "duplicate_type": "phone_only_expired",
                    "recommended_step": "Verify",
                    "recommended_status": "Can kiem tra",
                    "reason": f"Trung SDT, ho so cu o Lead > 1 nam"
                }
            else:
                return {
                    "is_duplicate": True,
                    "duplicate_type": "phone_only_recent",
                    "recommended_step": "Verify",
                    "recommended_status": "Trung",
                    "reason": f"Trung SDT, ho so cu o Lead <= 1 nam"
                }
        
        # TH3.2: Ho so bi trung o buoc QLead
        if old_step == "QLead":
            if days_since_update > two_year_days:
                return {
                    "is_duplicate": False,
                    "duplicate_type": "phone_only_expired",
                    "recommended_step": "Verify",
                    "recommended_status": "Can kiem tra",
                    "reason": f"Trung SDT, ho so cu o QLead > 2 nam"
                }
            else:
                return {
                    "is_duplicate": True,
                    "duplicate_type": "phone_only_recent",
                    "recommended_step": "Verify",
                    "recommended_status": "Trung",
                    "reason": f"Trung SDT, ho so cu o QLead <= 2 nam"
                }
        
        # TH3.3: Test, Deal, Enrolled, Re-enrolled, Withdraw, Graduated
        if old_step in ["Test", "Deal", "Enrolled", "Re-Enroll", "Withdraw", "Graduated"]:
            if days_since_update > one_year_days:
                return {
                    "is_duplicate": False,
                    "duplicate_type": "phone_only_expired",
                    "recommended_step": "Verify",
                    "recommended_status": "Can kiem tra",
                    "reason": f"Trung SDT, ho so cu o {old_step} > 1 nam"
                }
            else:
                return {
                    "is_duplicate": True,
                    "duplicate_type": "phone_only_recent",
                    "recommended_step": "Verify",
                    "recommended_status": "Trung",
                    "reason": f"Trung SDT, ho so cu o {old_step} <= 1 nam"
                }
    
    # TH1: Khong trung hoac chi trung 1 truong khong phai SDT
    return {
        "is_duplicate": False,
        "duplicate_type": "none",
        "recommended_step": "Verify",
        "recommended_status": "Can kiem tra",
        "reason": "Khong trung hoac chi trung 1 truong"
    }


@frappe.whitelist(methods=["POST"])
def check_duplicate():
    """Kiem tra trung lap toan he thong (tru Draft)"""
    check_crm_permission()
    data = get_request_data()
    
    phone_numbers = data.get("phone_numbers", [])
    student_name = data.get("student_name", "")
    guardian_name = data.get("guardian_name", "")
    exclude_lead = data.get("exclude_lead", "")
    
    if not phone_numbers:
        return validation_error_response("Thieu SDT", {"phone_numbers": ["Bat buoc"]})
    
    # Tim ho so trung (tru Draft)
    matches = _find_matching_leads(phone_numbers, student_name, guardian_name, exclude_draft=True)
    
    # Loai bo ho so dang kiem tra
    if exclude_lead:
        matches = [m for m in matches if m["name"] != exclude_lead]
    
    if not matches:
        return success_response({
            "is_duplicate": False,
            "matches": [],
            "recommended_step": "Verify",
            "recommended_status": "Can kiem tra"
        })
    
    # Sap xep theo thoi gian cap nhat gan nhat
    matches.sort(key=lambda x: x.get("modified", ""), reverse=True)
    most_recent = matches[0]
    
    result = _evaluate_duplicate_rules(most_recent)
    result["duplicate_lead"] = most_recent["name"]
    result["matches"] = matches
    
    return success_response(result)


@frappe.whitelist(methods=["POST"])
def check_draft_duplicate():
    """Kiem tra trung trong Draft (chi SDT)"""
    check_crm_permission()
    data = get_request_data()
    
    phone_numbers = data.get("phone_numbers", [])
    exclude_lead = data.get("exclude_lead", "")
    
    if not phone_numbers:
        return validation_error_response("Thieu SDT", {"phone_numbers": ["Bat buoc"]})
    
    normalized_phones = [normalize_phone_number(p) for p in phone_numbers if p]
    
    if not normalized_phones:
        return success_response({"is_duplicate": False, "matches": []})
    
    phone_placeholders = ", ".join(["%s"] * len(normalized_phones))
    
    query = """
        SELECT DISTINCT cl.name, cl.student_name, cl.guardian_name, cl.modified
        FROM `tabCRM Lead` cl
        INNER JOIN `tabCRM Lead Phone` clp ON clp.parent = cl.name
        WHERE cl.step = 'Draft'
        AND clp.phone_number IN ({placeholders})
    """.format(placeholders=phone_placeholders)
    
    if exclude_lead:
        query += f" AND cl.name != '{frappe.db.escape(exclude_lead)}'"
    
    matches = frappe.db.sql(query, normalized_phones, as_dict=True)
    
    return success_response({
        "is_duplicate": len(matches) > 0,
        "matches": matches
    })
