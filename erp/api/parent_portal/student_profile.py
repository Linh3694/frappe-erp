"""
Parent Portal — Hồ sơ CRM Lead (read-only) theo CRM Student.
Chỉ phụ huynh có CRM Family Relationship với access=1 mới xem được.
"""

import frappe
from erp.utils.api_response import success_response, error_response, validation_error_response
from erp.api.crm.lead import build_lead_family_payload, enrich_lead_dict_with_sibling_lead_links


# Các trường trên CRM Lead cần hiển thị tại Parent Portal (đồng bộ màn CRM StudentSection)
LEAD_SUBSET_FIELDNAMES = [
    "name",
    "step",
    "student_name",
    "student_gender",
    "student_dob",
    "student_personal_id_number",
    "student_code",
    "current_grade",
    "current_school",
    "target_grade",
    "target_academic_year",
    "target_semester",
    "student_place_of_birth",
    "student_nationality",
    "student_ethnicity",
    "student_religion",
    "registered_address_province",
    "registered_address_ward",
    "registered_address_street",
    "registered_address_detail",
    "current_address_province",
    "current_address_ward",
    "current_address_street",
    "current_address_detail",
    "student_health_insurance_card",
    "student_initial_medical_registration",
    "student_health_notes",
    "student_account_holder_relationship",
    "student_bank_account_name",
    "student_bank_account_number",
    "student_bank_name",
    "student_bank_branch",
    "student_study_interruption",
    "student_study_interruption_reason",
    "student_special_characteristics",
    "student_discipline_issues",
    "tuition_fee_pct",
    "service_fee_pct",
    "dev_fee_pct",
    "ksdv_pct",
    "linked_student",
    "linked_family",
    "campus_id",
]


def _get_current_parent():
    """Lấy document name CRM Guardian của phụ huynh đang đăng nhập (cùng pattern re_enrollment)."""
    user_email = frappe.session.user
    if user_email == "Guest":
        return None
    if "@parent.wellspring.edu.vn" not in user_email:
        return None
    guardian_id = user_email.split("@")[0]
    return frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")


def _json_safe_value(val):
    if val is None:
        return None
    if hasattr(val, "date") and hasattr(val, "hour"):  # datetime
        return str(val)
    if hasattr(val, "isoformat") and not isinstance(val, str):
        try:
            return val.isoformat()
        except Exception:
            return str(val)
    return val


def _serialize_lead_subset(doc):
    d = doc.as_dict()
    out = {}
    for k in LEAD_SUBSET_FIELDNAMES:
        out[k] = _json_safe_value(d.get(k))
    return out


def _enrich_target_academic_year(lead_dict):
    """Bổ sung label năm học (tương tự schoolYearService ở CRM)."""
    yid = (lead_dict.get("target_academic_year") or "").strip()
    if not yid:
        lead_dict["target_academic_year_label"] = None
        return lead_dict
    row = frappe.db.get_value(
        "SIS School Year",
        yid,
        ["title_vn", "title_en", "name"],
        as_dict=True,
    )
    if not row:
        lead_dict["target_academic_year_label"] = yid
        return lead_dict
    lead_dict["target_academic_year_label"] = (row.get("title_vn") or row.get("title_en") or yid).strip()
    return lead_dict


def _serialize_crm_student_min(student_id):
    doc = frappe.get_doc("CRM Student", student_id)
    d = doc.as_dict()
    return {
        "name": d.get("name"),
        "student_name": d.get("student_name"),
        "student_code": d.get("student_code"),
        "dob": _json_safe_value(d.get("dob")),
        "gender": d.get("gender"),
        "campus_id": d.get("campus_id"),
        "personal_id_number": d.get("personal_id_number"),
    }


@frappe.whitelist()
def get_student_profile():
    """
    Lấy hồ sơ Lead (read-only) + gia đình + anh chị em cho học sinh.

    Tham số: student_id (query hoặc form_dict) — tên document CRM Student.
    """
    student_id = frappe.form_dict.get("student_id")
    if not student_id and hasattr(frappe.request, "args") and frappe.request.args:
        student_id = frappe.request.args.get("student_id")
    if not student_id:
        return validation_error_response("Thiếu student_id", {"student_id": ["Bắt buộc"]})

    if not frappe.db.exists("CRM Student", student_id):
        return error_response(message="Không tìm thấy học sinh", code="STUDENT_NOT_FOUND")

    parent_id = _get_current_parent()
    if not parent_id:
        return error_response(message="Không tìm thấy thông tin phụ huynh", code="PARENT_NOT_FOUND")

    # Chỉ phụ huynh có quyền truy cập hồ sơ học sinh (access = 1)
    rel_ok = frappe.db.exists(
        "CRM Family Relationship",
        {"guardian": parent_id, "student": student_id, "access": 1},
    )
    if not rel_ok:
        return error_response(
            message="Bạn không có quyền xem thông tin học sinh này",
            code="FORBIDDEN",
        )

    lr = frappe.db.sql(
        """
        SELECT name FROM `tabCRM Lead`
        WHERE linked_student = %s
        ORDER BY modified DESC
        LIMIT 1
        """,
        (student_id,),
    )
    if not lr:
        return success_response(
            data={
                "has_lead": False,
                "lead": None,
                "family": None,
                "siblings": [],
                "learning_history": [],
                "promotions": [],
                "student": _serialize_crm_student_min(student_id),
            },
            message="Học sinh chưa có CRM Lead liên kết",
        )

    lead_name = lr[0][0]
    doc = frappe.get_doc("CRM Lead", lead_name)
    lead_dict = _serialize_lead_subset(doc)
    _enrich_target_academic_year(lead_dict)

    # Lịch sử học tập (bảng con)
    learning_history = []
    for r in doc.get("lead_learning_history") or []:
        learning_history.append(
            {
                "name": r.get("name"),
                "school_name": r.get("school_name"),
                "address": r.get("address"),
                "start_month_year": r.get("start_month_year"),
                "withdraw_month_year": r.get("withdraw_month_year"),
            }
        )

    lead_for_siblings = doc.as_dict()
    enrich_lead_dict_with_sibling_lead_links(lead_for_siblings)
    siblings = lead_for_siblings.get("lead_siblings") or []
    for s in siblings:
        if not isinstance(s, dict):
            continue
        for k, v in list(s.items()):
            s[k] = _json_safe_value(v)

    fam_payload = build_lead_family_payload(doc)
    family = {
        "members": fam_payload.get("members") or [],
        "family_code": fam_payload.get("family_code"),
        "linked_family": fam_payload.get("linked_family"),
    }

    return success_response(
        data={
            "has_lead": True,
            "lead": lead_dict,
            "family": family,
            "siblings": siblings,
            "learning_history": learning_history,
            "promotions": [],
            "student": _serialize_crm_student_min(student_id),
        },
        message="OK",
    )
