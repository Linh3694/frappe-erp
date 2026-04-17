"""
CRM Enrollment API - Tao CRM Student/Guardian/Family tu CRM Lead khi enrollment
"""

import frappe
from frappe import _
from frappe.utils import now, cint
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    validation_error_response, not_found_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data


RELATIONSHIP_MAP = {
    "Bo": "Father",
    "Me": "Mother",
    "Nguoi giam ho": "Guardian",
}

GENDER_MAP = {
    "Nam": "male",
    "Nu": "female",
}


def _get_primary_phone(lead_doc):
    """Lay so dien thoai chinh tu lead"""
    if lead_doc.phone_numbers:
        for phone in lead_doc.phone_numbers:
            if cint(phone.is_primary):
                return phone.phone_number
        return lead_doc.phone_numbers[0].phone_number
    return lead_doc.primary_phone or ""


def _create_crm_student(lead_doc):
    """Tao CRM Student tu CRM Lead"""
    student = frappe.get_doc({
        "doctype": "CRM Student",
        "student_name": lead_doc.student_name,
        "student_code": lead_doc.student_code or "",
        "dob": lead_doc.student_dob or "",
        "gender": GENDER_MAP.get(lead_doc.student_gender or "", ""),
        "campus_id": lead_doc.campus_id or "",
    })
    student.insert(ignore_permissions=True)
    return student


def _create_crm_guardian(lead_doc, family_code=""):
    """Tao CRM Guardian tu CRM Lead"""
    phone = _get_primary_phone(lead_doc)

    guardian = frappe.get_doc({
        "doctype": "CRM Guardian",
        "guardian_id": lead_doc.guardian_id_number or "",
        "guardian_name": lead_doc.guardian_name or "",
        "phone_number": phone,
        "email": lead_doc.guardian_email or "",
        "family_code": family_code,
    })
    guardian.insert(ignore_permissions=True)
    return guardian


def _create_crm_family(student_name, guardian_name, relationship_type):
    """Tao CRM Family voi relationship giua student va guardian"""
    family = frappe.get_doc({
        "doctype": "CRM Family",
        "family_code": "",
        "relationships": [{
            "student": student_name,
            "guardian": guardian_name,
            "relationship_type": relationship_type,
            "key_person": 1,
            "access": 1,
        }]
    })
    family.insert(ignore_permissions=True)
    return family


@frappe.whitelist(methods=["POST"])
def create_enrollment_records():
    """Tao CRM Student + CRM Guardian + CRM Family tu CRM Lead"""
    check_crm_permission()
    data = get_request_data()

    lead_name = data.get("lead_name")
    if not lead_name:
        return validation_error_response(
            "Thieu tham so lead_name", {"lead_name": ["Bat buoc"]}
        )

    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")

    lead_doc = frappe.get_doc("CRM Lead", lead_name)

    if lead_doc.linked_student:
        return error_response("Ho so nay da duoc lien ket voi CRM Student")

    if lead_doc.step not in ("Enrolled", "QLead"):
        return error_response(
            f"Chi co the tao enrollment records tu buoc QLead hoac Enrolled. "
            f"Hien tai: {lead_doc.step}"
        )

    try:
        student = _create_crm_student(lead_doc)

        relationship_type = RELATIONSHIP_MAP.get(
            lead_doc.relationship or "", lead_doc.relationship or "Guardian"
        )

        family = _create_crm_family(
            student.name, None, relationship_type
        )

        guardian = _create_crm_guardian(lead_doc, family.family_code)

        # Cap nhat family relationship voi guardian name
        if family.relationships:
            family.relationships[0].guardian = guardian.name
            family.save(ignore_permissions=True)

        # Cap nhat student family_code
        student.family_code = family.family_code
        student.save(ignore_permissions=True)

        # Lien ket lead voi student
        lead_doc.linked_student = student.name
        lead_doc.save(ignore_permissions=True)

        # Neu da co gan lop Regular (SIS Class Student) thi nang len Dang hoc ngay
        from erp.api.crm.enrolled_class_sync import (
            promote_leads_to_dang_hoc_if_class_assigned,
        )

        promote_leads_to_dang_hoc_if_class_assigned(student.name)

        frappe.db.commit()

        return success_response({
            "student": student.name,
            "guardian": guardian.name,
            "family": family.name,
            "family_code": family.family_code,
        }, "Da tao enrollment records thanh cong")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Loi tao enrollment records cho {lead_name}: {str(e)}")
        return error_response(f"Loi tao enrollment records: {str(e)}")


@frappe.whitelist(methods=["GET"])
def get_enrollment_status():
    """Kiem tra trang thai enrollment cua lead"""
    check_crm_permission()
    lead_name = frappe.form_dict.get("lead_name")

    if not lead_name:
        return validation_error_response(
            "Thieu tham so lead_name", {"lead_name": ["Bat buoc"]}
        )

    if not frappe.db.exists("CRM Lead", lead_name):
        return not_found_response(f"Khong tim thay ho so {lead_name}")

    lead_doc = frappe.get_doc("CRM Lead", lead_name)

    result = {
        "lead_name": lead_name,
        "step": lead_doc.step,
        "linked_student": lead_doc.linked_student or None,
        "has_enrollment": bool(lead_doc.linked_student),
    }

    if lead_doc.linked_student and frappe.db.exists("CRM Student", lead_doc.linked_student):
        student = frappe.get_doc("CRM Student", lead_doc.linked_student)
        result["student"] = {
            "name": student.name,
            "student_name": student.student_name,
            "student_code": student.student_code,
            "family_code": student.family_code or "",
        }

    return single_item_response(result, "Trang thai enrollment")
