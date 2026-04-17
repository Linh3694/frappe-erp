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
    get_valid_statuses_for_step, generate_crm_code, STEP_STATUSES,
    QLEAD_TEST_STATUSES, QLEAD_DEAL_STATUSES,
)
from erp.api.crm.lead import enrich_lead_dict_with_pic_info


def _lead_payload(doc):
    """Tra ve dict lead kem pic_info (avatar, ten, job_title) cho FE."""
    d = doc.as_dict()
    enrich_lead_dict_with_pic_info(d)
    return d


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


def _prepare_advance_step_doc(name, target_step, extra_data):
    """
    Load CRM Lead va ap dung toan bo thay doi advance_step.
    Goi lai ham nay sau khi reload khi save gap TimestampMismatch (cap nhat dong thoi).
    Tra ve ((doc, old_step, old_status), None) hoac (None, error_response dict).
    """
    doc = frappe.get_doc("CRM Lead", name)
    old_step = doc.step
    old_status = doc.status

    # Tu Draft: khong trung SDT voi ho so he thong -> Lead; trung -> Verify (status theo rule)
    verify_status_from_duplicate = None
    if old_step == "Draft" and target_step in ("Verify", "Lead"):
        from erp.api.crm.duplicate import resolve_draft_promotion

        effective_target, eff_status = resolve_draft_promotion(doc)
        target_step = effective_target
        if effective_target == "Verify":
            verify_status_from_duplicate = eff_status

    validate_step_transition(old_step, target_step)

    # QLead -> Enrolled: sinh ma HS (hoc sinh moi) + kiem tra trung Enrolled
    if old_step == "QLead" and target_step == "Enrolled":
        student_type = extra_data.get("student_type", "new")
        if student_type == "new":
            from erp.api.crm.student_code import _generate_code_internal

            if not doc.student_code:
                code = _generate_code_internal(
                    extra_data.get("campus_code", "WS1"),
                    extra_data.get("academic_year", ""),
                    extra_data.get("grade", doc.target_grade or "01"),
                )
                doc.student_code = code
        elif student_type == "existing":
            if extra_data.get("student_code"):
                doc.student_code = extra_data.get("student_code", "")
            if extra_data.get("linked_student"):
                doc.linked_student = extra_data.get("linked_student", "")

        if doc.linked_student:
            existing = frappe.db.exists(
                "CRM Lead",
                {
                    "linked_student": doc.linked_student,
                    "step": "Enrolled",
                    "name": ["!=", name],
                },
            )
            if existing:
                return None, error_response(
                    "Hoc sinh nay da co ho so o buoc Enrolled"
                )

    doc.step = target_step
    default_statuses = {
        "Verify": "Can kiem tra",
        "Lead": "Moi",
        "QLead": "Dang cham soc",
        "Enrolled": "Cho xep lop",
        "Nghi hoc": extra_data.get("initial_status") or "Chuyen truong",
    }
    doc.status = default_statuses.get(target_step, "")
    if target_step == "Nghi hoc":
        valid_nghi = get_valid_statuses_for_step("Nghi hoc")
        if doc.status not in valid_nghi:
            doc.status = valid_nghi[0] if valid_nghi else "Chuyen truong"
    if verify_status_from_duplicate:
        doc.status = verify_status_from_duplicate
    if target_step == "Verify" and old_step == "Lead":
        doc.status = "Da kiem tra - Trung hoc sinh"

    if target_step == "Lead" and not doc.crm_code:
        doc.crm_code = generate_crm_code()
    if old_step == "Draft" and target_step == "Verify" and not doc.crm_code:
        doc.crm_code = generate_crm_code()

    if target_step in ("Verify", "Lead") and not doc.pic:
        from erp.api.crm.assignment import assign_pic_sales_weight_balance

        pic = assign_pic_sales_weight_balance(doc.name, doc.campus_id)
        if pic:
            doc.pic = pic

    return (doc, old_step, old_status), None


def _log_step_change(lead_name, old_step, new_step, old_status, new_status,
                     reject_reason=None, reject_detail=None):
    """Ghi nhan lich su chuyen buoc. Khi new_status=Lost thi luu reject_reason, reject_detail."""
    try:
        doc_data = {
            "doctype": "CRM Lead Step History",
            "lead": lead_name,
            "old_step": old_step,
            "new_step": new_step,
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": frappe.session.user,
            "changed_at": now()
        }
        # Lost (trang thai chinh) hoac Tu choi o test_status/deal_status (ghi trong new_status dang field:val)
        if new_status == "Lost" or (
            reject_reason and new_status and "Tu choi" in str(new_status)
        ):
            if reject_reason is not None:
                doc_data["reject_reason"] = reject_reason
            if reject_detail is not None:
                doc_data["reject_detail"] = reject_detail
        frappe.get_doc(doc_data).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Loi ghi log chuyen buoc: {str(e)}")


def _run_create_enrollment_for_lead(lead_name: str, context: str):
    """
    Tao CRM Student tu lead. Phai truyen lead_name truc tiep: request JSON
    khi advance_step khong co lead_name trong body, nen create_enrollment_records() tung that bai.
    """
    try:
        from erp.api.crm.enrollment import run_create_enrollment_records

        res = run_create_enrollment_records(lead_name)
        if not res.get("success"):
            frappe.log_error(
                title=f"Loi tao enrollment ({context})",
                message=f"lead={lead_name}: {res.get('message', '')}",
            )
    except Exception as e:
        frappe.log_error(f"Loi tao enrollment ({context}): {str(e)}")


@frappe.whitelist(methods=["POST"])
def change_status():
    """Chuyen trang thai trong cung 1 step. Khi chuyen sang Lost co the truyen reject_reason, reject_detail."""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    new_status = data.get("new_status")
    reject_reason = data.get("reject_reason", "")
    reject_detail = data.get("reject_detail", "")
    
    if not name or not new_status:
        return validation_error_response(
            "Thieu tham so",
            {"name": ["Bat buoc"] if not name else [], "new_status": ["Bat buoc"] if not new_status else []}
        )
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", name)
        valid_statuses = get_valid_statuses_for_step(doc.step)

        if new_status not in valid_statuses:
            return error_response(
                f"Trang thai '{new_status}' khong hop le cho buoc {doc.step}. "
                f"Cac trang thai hop le: {', '.join(valid_statuses)}"
            )

        old_status = doc.status
        doc.status = new_status
        if new_status == "Lost":
            doc.reject_reason = reject_reason
            doc.reject_detail = reject_detail
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()
    
    _log_step_change(name, doc.step, doc.step, old_status, new_status,
                     reject_reason=reject_reason if new_status == "Lost" else None,
                     reject_detail=reject_detail if new_status == "Lost" else None)
    
    return single_item_response(_lead_payload(doc), f"Da chuyen trang thai sang {new_status}")


@frappe.whitelist(methods=["POST"])
def change_sub_status():
    """Doi test_status hoac deal_status khi buoc QLead. Tu choi: luu reject_reason/reject_detail."""
    check_crm_permission()
    data = get_request_data()

    name = data.get("name")
    field = data.get("field")
    new_status = data.get("new_status")
    reject_reason = data.get("reject_reason", "")
    reject_detail = data.get("reject_detail", "")

    if not name or not field or new_status is None or new_status == "":
        return validation_error_response(
            "Thieu tham so",
            {
                "name": ["Bat buoc"] if not name else [],
                "field": ["Bat buoc"] if not field else [],
                "new_status": ["Bat buoc"] if not new_status else [],
            },
        )

    if field not in ("test_status", "deal_status"):
        return error_response("field phai la test_status hoac deal_status")

    valid = QLEAD_TEST_STATUSES if field == "test_status" else QLEAD_DEAL_STATUSES
    if new_status not in valid:
        return error_response(
            f"Trang thai '{new_status}' khong hop le. Cac gia tri hop le: {', '.join(valid)}"
        )

    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = None
    old_val = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", name)
        if doc.step != "QLead":
            return error_response(
                f"Chi co the doi sub-status khi buoc QLead. Hien tai: {doc.step}"
            )

        old_val = getattr(doc, field) or ""
        setattr(doc, field, new_status)
        if new_status == "Tu choi":
            doc.reject_reason = reject_reason
            doc.reject_detail = reject_detail
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()

    _log_step_change(
        name,
        doc.step,
        doc.step,
        f"{field}:{old_val}",
        f"{field}:{new_status}",
        reject_reason=reject_reason if new_status == "Tu choi" else None,
        reject_detail=reject_detail if new_status == "Tu choi" else None,
    )

    return single_item_response(_lead_payload(doc), f"Da cap nhat {field}")


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

    doc = None
    old_step = None
    old_status = None
    for attempt in range(2):
        prepared, prep_err = _prepare_advance_step_doc(name, target_step, extra_data)
        if prep_err is not None:
            return prep_err
        doc, old_step, old_status = prepared
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()

    _log_step_change(name, old_step, doc.step, old_status, doc.status)
    
    # QLead -> Enrolled: dong bo CRM Family + tao CRM Student / enrollment
    if old_step == "QLead" and doc.step == "Enrolled":
        _sync_lead_guardians_to_family_if_needed(doc)
        if not doc.linked_student:
            _run_create_enrollment_for_lead(name, "advance_step")
        else:
            try:
                from erp.api.crm.enrolled_class_sync import (
                    promote_leads_to_dang_hoc_if_class_assigned,
                )

                promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
                frappe.db.commit()
            except Exception as e:
                frappe.log_error(
                    f"Loi dong bo trang thai enrolled (advance_step): {str(e)}"
                )

    # Tai load tu DB: sau enrollment linked_student + CRM Student da cap nhat, doc trong RAM con cu
    doc = frappe.get_doc("CRM Lead", name)

    return single_item_response(_lead_payload(doc), f"Da chuyen ho so sang buoc {doc.step}")


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

            doc = None
            old_step = None
            old_status = None
            for attempt in range(2):
                prepared, prep_err = _prepare_advance_step_doc(lead_name, target_step, {})
                if prep_err is not None:
                    results["errors"].append({
                        "name": lead_name,
                        "error": prep_err.get("message", "Loi chuyen buoc"),
                    })
                    doc = None
                    break
                doc, old_step, old_status = prepared
                try:
                    doc.save(ignore_permissions=True)
                    break
                except frappe.TimestampMismatchError:
                    if attempt == 1:
                        raise

            if doc is None:
                continue

            _log_step_change(lead_name, old_step, doc.step, old_status, doc.status)
            # QLead -> Enrolled: enrollment (giong advance_step)
            if old_step == "QLead" and doc.step == "Enrolled":
                _sync_lead_guardians_to_family_if_needed(doc)
                if not doc.linked_student:
                    _run_create_enrollment_for_lead(lead_name, "bulk_advance_step")
                else:
                    try:
                        from erp.api.crm.enrolled_class_sync import (
                            promote_leads_to_dang_hoc_if_class_assigned,
                        )

                        promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
                    except Exception as e:
                        frappe.log_error(
                            f"Loi dong bo enrolled (bulk_advance): {str(e)}"
                        )
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

    doc = None
    old_step = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", name)

        if doc.step != "QLead":
            return error_response(
                f"Chi co the nhap hoc tu buoc QLead. Ho so hien tai o buoc {doc.step}"
            )

        old_step = doc.step
        old_status = doc.status
        doc.step = "Enrolled"
        doc.status = "Cho xep lop"
        # Sinh ma HS neu chua co (dong bo logic QLead -> Enrolled trong advance_step)
        if not doc.student_code and not doc.linked_student:
            from erp.api.crm.student_code import _generate_code_internal

            doc.student_code = _generate_code_internal(
                "WS1",
                doc.target_academic_year or "",
                doc.target_grade or "01",
            )
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()
    
    _log_step_change(name, old_step, "Enrolled", old_status, "Cho xep lop")
    
    _sync_lead_guardians_to_family_if_needed(doc)

    if not doc.linked_student:
        _run_create_enrollment_for_lead(name, "enroll_lead")
    else:
        try:
            from erp.api.crm.enrolled_class_sync import (
                promote_leads_to_dang_hoc_if_class_assigned,
            )

            promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Loi dong bo trang thai enrolled (enroll_lead): {str(e)}")

    doc = frappe.get_doc("CRM Lead", name)
    return single_item_response(_lead_payload(doc), "Da nhap hoc thanh cong")


@frappe.whitelist(methods=["POST"])
def transfer_to_withdraw():
    """Chuyen truong - tu Enrolled sang Nghi hoc (legacy API ten transfer_to_withdraw)"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    reason = data.get("reason", "")
    
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = None
    old_step = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", name)
        if doc.step != "Enrolled":
            return error_response("Chi co the chuyen truong tu buoc Enrolled")

        old_step = doc.step
        old_status = doc.status
        doc.step = "Nghi hoc"
        doc.status = "Chuyen truong"
        if reason:
            doc.reject_reason = reason
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()
    
    _log_step_change(name, old_step, "Nghi hoc", old_status, "Chuyen truong")
    
    return single_item_response(_lead_payload(doc), "Da chuyen sang Nghi hoc")


@frappe.whitelist(methods=["POST"])
def reserve_enrollment():
    """Bao luu: giu o buoc Enrolled (khong con buoc Re-Enroll trong pipeline)"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = None
    old_step = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", name)
        if doc.step != "Enrolled":
            return error_response("Chi co the bao luu tu buoc Enrolled")

        old_step = doc.step
        old_status = doc.status
        doc.step = "Enrolled"
        doc.status = "Cho xep lop"
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()

    # Chi ghi log khi co thay doi (tranh Enrolled -> Enrolled giong het)
    if old_step != doc.step or (old_status or "") != (doc.status or ""):
        _log_step_change(name, old_step, doc.step, old_status, doc.status)

    if doc.linked_student:
        try:
            from erp.api.crm.enrolled_class_sync import (
                promote_leads_to_dang_hoc_if_class_assigned,
            )

            promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Loi dong bo trang thai enrolled (reserve_enrollment): {str(e)}")

    return single_item_response(_lead_payload(doc), "Da bao luu thanh cong")


@frappe.whitelist(methods=["POST"])
def move_back_to_reenroll():
    """Tu Nghi hoc (Tot nghiep) -> Enrolled (API ten legacy move_back_to_reenroll)"""
    check_crm_permission()
    data = get_request_data()
    
    name = data.get("name")
    if not name:
        return validation_error_response("Thieu tham so name", {"name": ["Bat buoc"]})
    
    if not frappe.db.exists("CRM Lead", name):
        return not_found_response(f"Khong tim thay ho so {name}")

    doc = None
    old_step = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", name)
        if doc.step != "Nghi hoc" or doc.status != "Tot nghiep":
            return error_response("Chi co the chuyen tu Nghi hoc (Tot nghiep) ve Enrolled")

        old_step = doc.step
        old_status = doc.status
        doc.step = "Enrolled"
        doc.status = "Cho xep lop"
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                return error_response(
                    "Ho so da duoc cap nhat dong thoi. Vui long lam moi va thu lai."
                )

    frappe.db.commit()
    
    _log_step_change(name, old_step, "Enrolled", old_status, "Cho xep lop")

    if doc.linked_student:
        try:
            from erp.api.crm.enrolled_class_sync import (
                promote_leads_to_dang_hoc_if_class_assigned,
            )

            promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Loi dong bo trang thai enrolled (move_back_to_reenroll): {str(e)}")
    
    return single_item_response(_lead_payload(doc), "Da chuyen ve Nhap hoc")


@frappe.whitelist(methods=["POST"])
def auto_enroll_paid_leads():
    """Scheduler: Tu dong chuyen QLead (Dong phi / Dat coc) sang Enrolled"""
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()
    
    academic_year = data.get("academic_year")
    
    # Buoc QLead: thoa thuan da dong phi / dat coc
    filters = {
        "step": "QLead",
        "deal_status": ["in", ["Dong phi", "Dat coc"]],
    }
    if academic_year:
        filters["target_academic_year"] = academic_year
    
    leads = frappe.get_all("CRM Lead", filters=filters, fields=["name"])
    
    enrolled_count = 0
    errors = []
    for lead in leads:
        try:
            lead_name = lead["name"]
            skipped = False
            old_step = None
            old_status = None
            for attempt in range(2):
                doc = frappe.get_doc("CRM Lead", lead_name)
                if doc.linked_student:
                    existing = frappe.db.exists(
                        "CRM Lead",
                        {
                            "linked_student": doc.linked_student,
                            "step": "Enrolled",
                            "name": ["!=", doc.name],
                        },
                    )
                    if existing:
                        skipped = True
                        break
                if doc.step != "QLead" or (doc.deal_status or "") not in ("Dong phi", "Dat coc"):
                    skipped = True
                    break
                old_step = doc.step
                old_status = doc.status
                doc.step = "Enrolled"
                doc.status = "Cho xep lop"
                try:
                    doc.save(ignore_permissions=True)
                    break
                except frappe.TimestampMismatchError:
                    if attempt == 1:
                        raise
            if skipped or old_step is None:
                continue
            _log_step_change(doc.name, old_step, "Enrolled", old_status, "Cho xep lop")
            _sync_lead_guardians_to_family_if_needed(doc)
            if not doc.linked_student:
                _run_create_enrollment_for_lead(doc.name, "auto_enroll_paid_leads")
            else:
                try:
                    from erp.api.crm.enrolled_class_sync import (
                        promote_leads_to_dang_hoc_if_class_assigned,
                    )

                    promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
                except Exception as e:
                    frappe.log_error(f"Loi dong bo enrolled (auto_enroll): {str(e)}")
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
            lead_name = lead["name"]
            for attempt in range(2):
                doc = frappe.get_doc("CRM Lead", lead_name)
                old_step = doc.step
                old_status = doc.status

                if doc.target_grade == "12":
                    doc.step = "Nghi hoc"
                    doc.status = "Tot nghiep"
                    bump = "graduated"
                else:
                    doc.step = "Enrolled"
                    doc.status = "Cho xep lop"
                    bump = "re_enroll"
                try:
                    doc.save(ignore_permissions=True)
                    results[bump] += 1
                    _log_step_change(
                        doc.name, old_step, doc.step, old_status, doc.status
                    )
                    if bump == "re_enroll" and doc.linked_student:
                        try:
                            from erp.api.crm.enrolled_class_sync import (
                                promote_leads_to_dang_hoc_if_class_assigned,
                            )

                            promote_leads_to_dang_hoc_if_class_assigned(
                                doc.linked_student
                            )
                        except Exception as e:
                            frappe.log_error(
                                f"Loi dong bo enrolled (end_of_year): {str(e)}"
                            )
                    break
                except frappe.TimestampMismatchError:
                    if attempt == 1:
                        raise

        except Exception as e:
            results["errors"].append({"name": lead["name"], "error": str(e)})
    
    frappe.db.commit()
    return success_response(results, "Da chuyen buoc cuoi nam hoc")
