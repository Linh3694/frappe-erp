"""
CRM Pipeline API - Quan ly luong chuyen buoc va trang thai
"""

import frappe
from frappe import _
from frappe.utils import now, getdate, add_years, nowdate
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    validation_error_response, not_found_response, list_response
)
from erp.api.crm.utils import (
    check_crm_permission, get_request_data, validate_step_transition,
    get_valid_statuses_for_step, generate_crm_code, STEP_STATUSES
)


def _sync_lead_guardians_to_family_if_needed(doc):
    """Tao CRM Family tu lead_guardians khi lead co linked_student nhung chua co linked_family."""
    if not getattr(doc, "linked_student", None):
        return
    if getattr(doc, "linked_family", None):
        return
    lead_guardians = getattr(doc, "lead_guardians", None) or []
    if not lead_guardians:
        return
    try:
        from erp.api.erp_sis.family import create_family
        guardians = [lg.guardian for lg in lead_guardians if lg.get("guardian")]
        if not guardians:
            return
        relationships = []
        for i, lg in enumerate(lead_guardians):
            if not lg.get("guardian"):
                continue
            relationships.append({
                "student": doc.linked_student,
                "guardian": lg.guardian,
                "relationship_type": lg.get("relationship_type") or "other",
                "key_person": 1 if lg.get("is_primary_contact") else 0,
                "access": 1,
            })
        frappe.local.form_dict = {
            "students": [doc.linked_student],
            "guardians": guardians,
            "relationships": relationships,
        }
        res = create_family()
        if res.get("success") and res.get("data", {}).get("family_code"):
            family_code = res["data"]["family_code"]
            if frappe.db.exists("CRM Family", family_code):
                doc.linked_family = family_code
                doc.flags.ignore_validate = True
                doc.save(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Loi sync lead_guardians sang CRM Family: {str(e)}")


def _log_step_change(lead_name, old_step, new_step, old_status, new_status):
    """Ghi nhan lich su chuyen buoc"""
    try:
        frappe.get_doc({
            "doctype": "CRM Lead Step History",
            "lead": lead_name,
            "old_step": old_step,
            "new_step": new_step,
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": frappe.session.user,
            "changed_at": now()
        }).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Loi ghi log chuyen buoc: {str(e)}")


@frappe.whitelist(methods=["POST"])
def change_status():
    """Chuyen trang thai trong cung 1 step"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    new_status = data.get("new_status")
    
    if not name or not new_status:
        return validation_error_response(
            "Thieu tham so",
            {"name": ["Bat buoc"] if not name else [], "new_status": ["Bat buoc"] if not new_status else []}
        )
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    valid_statuses = get_valid_statuses_for_step(doc.step)
    
    if new_status not in valid_statuses:
        return error_response(
            f"Trang thai '{new_status}' khong hop le cho buoc {doc.step}. "
            f"Cac trang thai hop le: {', '.join(valid_statuses)}"
        )
    
    old_status = doc.status
    doc.status = new_status
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    _log_step_change(name, doc.step, doc.step, old_status, new_status)
    
    return single_item_response(doc.as_dict(), f"Da chuyen trang thai sang {new_status}")


@frappe.whitelist(methods=["POST"])
def advance_step():
    """Chuyen buoc don le"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    target_step = data.get("target_step")
    extra_data = data.get("extra_data", {})
    
    if not name or not target_step:
        return validation_error_response(
            "Thieu tham so",
            {"name": ["Bat buoc"] if not name else [], "target_step": ["Bat buoc"] if not target_step else []}
        )
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    old_step = doc.step
    old_status = doc.status
    
    # Validate chuyen buoc
    validate_step_transition(old_step, target_step)
    
    # Xu ly dac biet khi chuyen QLead -> Test
    if old_step == "QLead" and target_step == "Test":
        student_type = extra_data.get("student_type", "new")
        if student_type == "new":
            from erp.api.crm.student_code import _generate_code_internal
            code = _generate_code_internal(
                extra_data.get("campus_code", "WS1"),
                extra_data.get("academic_year", ""),
                extra_data.get("grade", doc.target_grade or "01")
            )
            doc.student_code = code
        elif student_type == "existing":
            doc.student_code = extra_data.get("student_code", "")
            doc.linked_student = extra_data.get("linked_student", "")
    
    # Xu ly khi chuyen Deal -> Enrolled
    if old_step == "Deal" and target_step == "Enrolled":
        if doc.status not in ["Paid", "Deposit"]:
            return error_response("Chi co the nhap hoc ho so co trang thai Paid hoac Deposit")
        # Kiem tra khong cho Enroll 2 ho so cung 1 hoc sinh
        if doc.linked_student:
            existing = frappe.db.exists("CRM Lead", {
                "linked_student": doc.linked_student,
                "step": "Enrolled",
                "name": ["!=", name]
            })
            if existing:
                return error_response("Hoc sinh nay da co ho so o buoc Enrolled")
    
    # Cap nhat step va status mac dinh
    doc.step = target_step
    default_statuses = {
        "Verify": "Can kiem tra",
        "Lead": "Moi",
        "QLead": "Moi",
        "Test": "Pre-test",
        "Deal": "Booked",
        "Enrolled": "Dang hoc",
        "Re-Enroll": "Unpaid",
        "Withdraw": "Chuyen truong",
        "Graduated": "Tot nghiep"
    }
    doc.status = default_statuses.get(target_step, "")
    
    # Sinh crm_code khi chuyen sang Lead
    if target_step == "Lead" and not doc.crm_code:
        doc.crm_code = generate_crm_code()
    
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    _log_step_change(name, old_step, target_step, old_status, doc.status)
    
    # Tao CRM Family tu lead_guardians khi chuyen Deal -> Enrolled (co linked_student)
    if old_step == "Deal" and target_step == "Enrolled":
        _sync_lead_guardians_to_family_if_needed(doc)
    
    # Tu dong tao enrollment records khi chuyen Deal -> Enrolled
    if old_step == "Deal" and target_step == "Enrolled" and not doc.linked_student:
        try:
            from erp.api.crm.enrollment import create_enrollment_records
            frappe.form_dict.update({"lead_name": name})
            create_enrollment_records()
        except Exception as e:
            frappe.log_error(f"Loi tu dong tao enrollment records: {str(e)}")
    
    return single_item_response(doc.as_dict(), f"Da chuyen ho so sang buoc {target_step}")


@frappe.whitelist(methods=["POST"])
def bulk_advance_step():
    """Chuyen buoc hang loat (Draft -> Lead)"""
    check_crm_permission()
    data = get_request_data()
    
    names = data.get("names", [])
    target_step = data.get("target_step")
    
    if not names or not target_step:
        return validation_error_response("Thieu tham so", {"names": ["Bat buoc"], "target_step": ["Bat buoc"]})
    
    results = {"success": [], "errors": []}
    
    for lead_name in names:
        try:
            if not frappe.db.exists("CRM Lead", lead_name):
                results["errors"].append({"name": lead_name, "error": "Khong tim thay"})
                continue
            
            doc = frappe.get_doc("CRM Lead", lead_name)
            old_step = doc.step
            old_status = doc.status
            
            validate_step_transition(old_step, target_step)
            
            doc.step = target_step
            default_statuses = {
                "Verify": "Can kiem tra",
                "Lead": "Moi",
                "QLead": "Moi",
                "Test": "Pre-test",
                "Deal": "Booked",
                "Enrolled": "Dang hoc",
                "Re-Enroll": "Unpaid",
                "Withdraw": "Chuyen truong",
                "Graduated": "Tot nghiep"
            }
            doc.status = default_statuses.get(target_step, "")
            
            if target_step == "Lead" and not doc.crm_code:
                doc.crm_code = generate_crm_code()
            
            doc.save(ignore_permissions=True)
            
            _log_step_change(lead_name, old_step, target_step, old_status, doc.status)
            results["success"].append(lead_name)
        
        except Exception as e:
            results["errors"].append({"name": lead_name, "error": str(e)})
    
    frappe.db.commit()
    
    return success_response(results, f"Da chuyen {len(results['success'])} ho so, {len(results['errors'])} loi")


@frappe.whitelist(methods=["POST"])
def enroll_lead():
    """Nhap hoc thu cong (giua chung)"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    
    if doc.step != "Deal":
        return error_response(f"Chi co the nhap hoc tu buoc Deal. Ho so hien tai o buoc {doc.step}")
    if doc.status not in ["Paid", "Deposit"]:
        return error_response("Chi co the nhap hoc ho so co trang thai Paid hoac Deposit")
    
    old_step = doc.step
    old_status = doc.status
    doc.step = "Enrolled"
    doc.status = "Dang hoc"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    _log_step_change(name, old_step, "Enrolled", old_status, "Dang hoc")
    
    _sync_lead_guardians_to_family_if_needed(doc)
    
    return single_item_response(doc.as_dict(), "Da nhap hoc thanh cong")


@frappe.whitelist(methods=["POST"])
def transfer_to_withdraw():
    """Chuyen truong - tu Enrolled sang Withdraw"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    reason = data.get("reason", "")
    
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    if doc.step != "Enrolled":
        return error_response("Chi co the chuyen truong tu buoc Enrolled")
    
    old_step = doc.step
    old_status = doc.status
    doc.step = "Withdraw"
    doc.status = "Chuyen truong"
    if reason:
        doc.reject_reason = reason
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    _log_step_change(name, old_step, "Withdraw", old_status, "Chuyen truong")
    
    return single_item_response(doc.as_dict(), "Da chuyen sang Withdraw")


@frappe.whitelist(methods=["POST"])
def reserve_enrollment():
    """Bao luu -> Re-Enroll"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    if doc.step != "Enrolled":
        return error_response("Chi co the bao luu tu buoc Enrolled")
    
    old_step = doc.step
    old_status = doc.status
    doc.step = "Re-Enroll"
    doc.status = "Unpaid"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    _log_step_change(name, old_step, "Re-Enroll", old_status, "Unpaid")
    
    return single_item_response(doc.as_dict(), "Da bao luu thanh cong")


@frappe.whitelist(methods=["POST"])
def move_back_to_reenroll():
    """Lop 12 khong dat -> quay lai Re-Enroll"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")
    
    doc = frappe.get_doc("CRM Lead", name)
    if doc.step != "Graduated":
        return error_response("Chi co the chuyen tu Graduated ve Re-Enroll")
    
    old_step = doc.step
    old_status = doc.status
    doc.step = "Re-Enroll"
    doc.status = "Unpaid"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    _log_step_change(name, old_step, "Re-Enroll", old_status, "Unpaid")
    
    return single_item_response(doc.as_dict(), "Da chuyen ve Re-Enroll")


@frappe.whitelist(methods=["POST"])
def auto_enroll_paid_leads():
    """Scheduler: Tu dong chuyen Paid/Deposit sang Enrolled"""
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()
    
    academic_year = data.get("academic_year")
    
    filters = {
        "step": "Deal",
        "status": ["in", ["Paid", "Deposit"]]
    }
    if academic_year:
        filters["target_academic_year"] = academic_year
    
    leads = frappe.get_all("CRM Lead", filters=filters, fields=["name"])
    
    enrolled_count = 0
    errors = []
    for lead in leads:
        try:
            doc = frappe.get_doc("CRM Lead", lead["name"])
            # Kiem tra khong enroll 2 ho so cung 1 hoc sinh
            if doc.linked_student:
                existing = frappe.db.exists("CRM Lead", {
                    "linked_student": doc.linked_student,
                    "step": "Enrolled",
                    "name": ["!=", doc.name]
                })
                if existing:
                    continue
            
            old_step = doc.step
            old_status = doc.status
            doc.step = "Enrolled"
            doc.status = "Dang hoc"
            doc.save(ignore_permissions=True)
            _log_step_change(doc.name, old_step, "Enrolled", old_status, "Dang hoc")
            _sync_lead_guardians_to_family_if_needed(doc)
            enrolled_count += 1
        except Exception as e:
            errors.append({"name": lead["name"], "error": str(e)})
    
    frappe.db.commit()
    return success_response(
        {"enrolled": enrolled_count, "errors": errors},
        f"Da tu dong nhap hoc {enrolled_count} ho so"
    )


@frappe.whitelist(methods=["POST"])
def end_of_year_transition():
    """Scheduler: Cuoi nam hoc chuyen buoc"""
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()
    
    academic_year = data.get("academic_year")
    if not academic_year:
        return validation_error_response("Thieu nam hoc", {"academic_year": ["Bat buoc"]})
    
    enrolled_leads = frappe.get_all(
        "CRM Lead",
        filters={"step": "Enrolled", "target_academic_year": academic_year},
        fields=["name", "target_grade"]
    )
    
    results = {"re_enroll": 0, "graduated": 0, "errors": []}
    
    for lead in enrolled_leads:
        try:
            doc = frappe.get_doc("CRM Lead", lead["name"])
            old_step = doc.step
            old_status = doc.status
            
            if doc.target_grade == "12":
                doc.step = "Graduated"
                doc.status = "Tot nghiep"
                results["graduated"] += 1
            else:
                doc.step = "Re-Enroll"
                doc.status = "Unpaid"
                results["re_enroll"] += 1
            
            doc.save(ignore_permissions=True)
            _log_step_change(doc.name, old_step, doc.step, old_status, doc.status)
        
        except Exception as e:
            results["errors"].append({"name": lead["name"], "error": str(e)})
    
    frappe.db.commit()
    return success_response(results, "Da chuyen buoc cuoi nam hoc")
