"""
CRM Enrollment API - Tao CRM Student/Guardian/Family tu CRM Lead khi enrollment
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate
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

# CRM Student bat buoc dob — lead co the chua nhap ngay sinh
_PLACEHOLDER_DOB = "1900-01-01"


def _coerce_student_name(lead_doc):
    """Ten hien thi — khong de trong (CRM Student.student_name reqd)."""
    n = (lead_doc.student_name or "").strip()
    if n:
        return n
    if (lead_doc.crm_code or "").strip():
        return f"Hoc sinh {lead_doc.crm_code.strip()}"
    return f"Hoc sinh {lead_doc.name}"


def _coerce_student_dob(lead_doc):
    """Ngay sinh — khong de trong (CRM Student.dob reqd)."""
    raw = (lead_doc.student_dob or "").strip()
    if not raw:
        return _PLACEHOLDER_DOB
    try:
        getdate(raw)
        return raw
    except Exception:
        return _PLACEHOLDER_DOB


def _coerce_student_gender(lead_doc):
    """Gioi tinh — CRM Student.gender reqd (male/female/others)."""
    g = GENDER_MAP.get(lead_doc.student_gender or "", "")
    return g if g else "others"


def _get_primary_phone(lead_doc):
    """Lay so dien thoai chinh tu lead"""
    if lead_doc.phone_numbers:
        for phone in lead_doc.phone_numbers:
            if cint(phone.is_primary):
                return phone.phone_number
        return lead_doc.phone_numbers[0].phone_number
    return lead_doc.primary_phone or ""


def _resolve_campus_id_for_new_student(lead_doc):
    """
    CRM Student bat buoc co campus_id hop le: get_all_students / search_students
    loc theo campus nguoi dung — neu lead de trong thi lay campus hien tai.
    """
    cid = (lead_doc.campus_id or "").strip()
    if cid:
        return cid
    try:
        from erp.utils.campus_utils import get_current_campus_from_context

        return get_current_campus_from_context() or "campus-1"
    except Exception:
        return "campus-1"


def _create_crm_student(lead_doc):
    """Tao CRM Student tu CRM Lead — dong bo bat buoc tren CRM Student."""
    student = frappe.get_doc({
        "doctype": "CRM Student",
        "student_name": _coerce_student_name(lead_doc),
        "student_code": (lead_doc.student_code or "").strip(),
        "dob": _coerce_student_dob(lead_doc),
        "gender": _coerce_student_gender(lead_doc),
        "campus_id": _resolve_campus_id_for_new_student(lead_doc),
    })
    student.insert(ignore_permissions=True)
    return student


def _create_crm_guardian(lead_doc, family_code=""):
    """Tao CRM Guardian tu CRM Lead (family_code cap nhat sau khi co CRM Family)."""
    phone = _get_primary_phone(lead_doc)

    guardian = frappe.get_doc({
        "doctype": "CRM Guardian",
        "guardian_id": lead_doc.guardian_id_number or "",
        "guardian_name": lead_doc.guardian_name or "",
        "phone_number": phone,
        "email": lead_doc.guardian_email or "",
        "family_code": family_code or "",
    })
    guardian.insert(ignore_permissions=True)
    return guardian


def _create_crm_family_enrollment(student_name, guardian_docname, relationship_type):
    """
    Tao CRM Family giong erp.api.erp_sis.family.create_family:
    insert shell (bo qua mandatory family_code), gan family_code = name, roi them dong relationship du guardian.
    """
    family_doc = frappe.get_doc({
        "doctype": "CRM Family",
        "relationships": [],
    })
    family_doc.flags.ignore_validate = True
    family_doc.insert(ignore_permissions=True, ignore_mandatory=True)
    family_doc.family_code = family_doc.name
    family_doc.flags.ignore_validate = True
    family_doc.save(ignore_permissions=True)

    family_doc.append(
        "relationships",
        {
            "student": student_name,
            "guardian": guardian_docname,
            "relationship_type": relationship_type,
            "key_person": 1,
            "access": 1,
        },
    )
    family_doc.save(ignore_permissions=True)
    return family_doc


def run_create_enrollment_records(lead_name: str):
    """
    Tao CRM Student + CRM Guardian + CRM Family tu CRM Lead.
    Goi truc tiep tu pipeline (truyen lead_name) — khong phu thuoc JSON body / form_dict.
    """
    check_crm_permission()

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

    if not (lead_doc.student_code or "").strip():
        return error_response(
            "Ho so chua co ma hoc sinh. Vui long lam moi trang hoac lien he quan tri."
        )

    try:
        student = _create_crm_student(lead_doc)

        relationship_type = RELATIONSHIP_MAP.get(
            lead_doc.relationship or "", lead_doc.relationship or "Guardian"
        )

        # Guardian truoc (chua family_code), Family shell + relationship du guardian (bat buoc tren child table)
        guardian = _create_crm_guardian(lead_doc, "")
        family = _create_crm_family_enrollment(
            student.name, guardian.name, relationship_type
        )

        guardian_doc = frappe.get_doc("CRM Guardian", guardian.name)
        guardian_doc.family_code = family.family_code
        guardian_doc.flags.ignore_validate = True
        guardian_doc.save(ignore_permissions=True)

        student.family_code = family.family_code
        student.flags.ignore_validate = True
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


@frappe.whitelist(methods=["POST"])
def create_enrollment_records():
    """Tao CRM Student + CRM Guardian + CRM Family tu CRM Lead (API)"""
    data = get_request_data()
    # JSON POST: get_request_data() chi lay body — can them form_dict (pipeline cap nhat lead_name)
    lead_name = data.get("lead_name") or frappe.form_dict.get("lead_name")
    return run_create_enrollment_records(lead_name)


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
