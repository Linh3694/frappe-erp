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
    QLEAD_TEST_STATUSES,
)
from erp.api.crm.lead import enrich_lead_dict_with_pic_info
from erp.api.crm.assignment import (
    assign_pic_sales_weight_balance,
    assign_pic_sales_care_weight_balance,
)
from erp.utils.campus_utils import get_current_campus_from_context


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

    # Ma hoc sinh (student_code) khong con sinh khi Lead->QLead — chuyen sang sinh khi
    # QLead status = Khao sat/Dat coc/Dong phi (xem ensure_student_code_for_qlead_status
    # trong change_status). QLead->Enrolled ben duoi van sinh (fallback neu chua co).

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
        # Nghi hoc: luu thong tin nghi hoc cho moi loai nghi (khong bat buoc,
        # khong con gioi han chi khi Chuyen truong)
        for f in (
            "withdraw_reason_group",
            "withdraw_transfer_school",
            "withdraw_transfer_school_address",
            "withdraw_transfer_reason",
        ):
            val = extra_data.get(f)
            if val is not None:
                doc.set(f, val)
    if verify_status_from_duplicate:
        doc.status = verify_status_from_duplicate
    if target_step == "Verify" and old_step == "Lead":
        doc.status = "Da kiem tra - Trung hoc sinh"

    if target_step == "Lead" and not doc.crm_code:
        doc.crm_code = generate_crm_code()
    if old_step == "Draft" and target_step == "Verify" and not doc.crm_code:
        doc.crm_code = generate_crm_code()

    if target_step in ("Verify", "Lead") and not doc.pic_sales:
        pic = assign_pic_sales_weight_balance(doc.name, doc.campus_id)
        if pic:
            doc.pic_sales = pic

    # QLead -> Enrolled: gan them PIC team cham soc (SIS Sales Care, can bang tai).
    # KHONG dung Nghi hoc -> Enrolled. `pic_sales` GIU NGUYEN — truoc day bi ghi de o day
    # nen mat lich su ai chot deal, keo theo KPI Sales sai.
    if old_step == "QLead" and target_step == "Enrolled":
        pic_care = assign_pic_sales_care_weight_balance(doc.name, doc.campus_id)
        if pic_care:
            doc.pic_care = pic_care

    # Chuyen sang buoc Enrolled: ghi nhan Ngay nhap hoc (Tuyen sinh co the sua lai sau).
    if target_step == "Enrolled" and old_step != "Enrolled":
        doc.enrollment_date = nowdate()

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
        # Tu choi (trang thai chinh) hoac Tu choi o test_status (ghi trong new_status dang field:val)
        if new_status == "Tu choi" or (
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
    """Chuyen trang thai trong cung 1 step. Khi chuyen sang Tu choi co the truyen reject_reason, reject_detail."""
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
        # Sinh ma hoc sinh khi vao QLead status Khao sat/Dat coc/Dong phi (neu chua co)
        from erp.api.crm.student_code import ensure_student_code_for_qlead_status
        ensure_student_code_for_qlead_status(doc)
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

    _log_step_change(name, doc.step, doc.step, old_status, new_status,
                     reject_reason=reject_reason if new_status == "Tu choi" else None,
                     reject_detail=reject_detail if new_status == "Tu choi" else None)
    
    return single_item_response(_lead_payload(doc), f"Da chuyen trang thai sang {new_status}")


@frappe.whitelist(methods=["POST"])
def change_sub_status():
    """Doi test_status khi buoc QLead. Tu choi: luu reject_reason/reject_detail."""
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

    if field != "test_status":
        return error_response("field phai la test_status")

    valid = QLEAD_TEST_STATUSES
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
        doc.enrollment_date = nowdate()
        # Sinh ma HS neu chua co (dong bo logic QLead -> Enrolled trong advance_step)
        if not doc.student_code and not doc.linked_student:
            from erp.api.crm.student_code import _generate_code_internal

            doc.student_code = _generate_code_internal(
                "WS1",
                doc.target_academic_year or "",
                doc.target_grade or "01",
            )
        pic_care = assign_pic_sales_care_weight_balance(doc.name, doc.campus_id)
        if pic_care:
            doc.pic_care = pic_care
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


# --- Chuyen hang loat hoc sinh chinh thuc sang Nghi hoc -----------------------------

# Khoi cuoi cap — hoc sinh dang hoc khoi nay chuyen sang Nghi hoc / Tot nghiep.
_GRADUATING_GRADE = "12"

# Thao tac dien rong (ghi hang loat, kho hoan tac tung ho so) nen chi mo cho cap quan ly,
# khong mo cho toan bo ALLOWED_ROLES nhu cac API pipeline don le.
_BULK_WITHDRAW_ROLES = [
    "System Manager",
    "SIS Manager",
    "SIS Sales Admin",
    "SIS Sales Care Admin",
]


def _re_enrollment_decision_by_student(student_ids, campus_id):
    """Map linked_student -> decision cua don tai ghi danh dang xet.

    CUNG dinh nghia voi erp.api.crm.lead.enrich_lead_dict_with_re_enrollment (hang
    "Trang thai Tai ghi danh" tren sidebar ho so): don thuoc dot co
    source_school_year_id = nam active cua campus, khong co thi lui ve dot nam truoc.
    Sua o day thi phai sua ca ben do, neu khong UI va hanh dong hang loat se lech nhau.

    Tra ve {} khi thieu du lieu (khong co nam hoc) — KHONG doan bua.
    """
    from erp.api.crm.lead import _enrollment_class_years

    out = {}
    sids = [s for s in (student_ids or []) if s]
    if not sids:
        return out

    current, previous = _enrollment_class_years(campus_id)
    candidates = [y["name"] for y in (current, previous) if y]
    if not candidates:
        return out

    rows = frappe.db.sql(
        """
        SELECT r.`student_id`, r.`decision`,
               cfg.`source_school_year_id` AS src_year
        FROM `tabSIS Re-enrollment` r
        INNER JOIN `tabSIS Re-enrollment Config` cfg ON cfg.`name` = r.`config_id`
        LEFT  JOIN `tabSIS School Year` ty ON ty.`name` = cfg.`school_year_id`
        WHERE r.`student_id` IN %(sids)s
          AND cfg.`source_school_year_id` IN %(years)s
        ORDER BY ty.`start_date` DESC, r.`modified` DESC
        """,
        {"sids": sids, "years": candidates},
        as_dict=True,
    )

    # ORDER BY ... DESC -> ban ghi dau tien cua moi (student, nam nguon) la moi nhat
    by_student_year = {}
    for r in rows:
        by_student_year.setdefault((r["student_id"], r["src_year"]), r)

    for sid in sids:
        for year_name in candidates:  # nam active truoc, roi nam truoc
            row = by_student_year.get((sid, year_name))
            if row:
                out[sid] = str(row.get("decision") or "")
                break
    return out


def _collect_withdraw_candidates(campus_id=None):
    """Tim hoc sinh chinh thuc du dieu kien chuyen sang Nghi hoc.

    Chi xet ho so o buoc 'Enrolled' VA trang thai 'Dang hoc'.
      Nhom 1 — current_grade = '12'                     -> Nghi hoc / Tot nghiep
      Nhom 2 — khoi khac + tai ghi danh 'not_re_enroll' -> Nghi hoc / Chuyen truong

    Khoi lop lay THANG tu SIS (grade_by_student_from_sis) cho MOI ho so, khong tin
    `CRM Lead.current_grade` da denormalize: field do chi duoc sync o vai thoi diem
    (promote_leads_to_dang_hoc_if_class_assigned) va KHONG BAO GIO bi xoa, nen rat de cu.
    `current_grade` chi con la fallback khi SIS khong tra ra khoi nao.

    Ham SIS lay lop Regular MOI NHAT theo start_date, KHONG loc theo nam hoc — chinh la
    dieu can cho tinh huong chuyen nam: nam active da la 26-27 nhung hoc sinh chua co lop
    26-27, lop that con o 25-26, van phai nhan dung la khoi 12 cua 25-26.

    KHONG dung `target_grade` (khoi dang ky luc tuyen sinh, da cu voi HS hoc nhieu nam).

    Tra ve (graduate_rows, transfer_rows) — moi phan tu la dict lead, da duoc gan
    `current_grade` = khoi da giai quyet (de danh sach xem truoc hien dung khoi that).
    """
    filters = {"step": "Enrolled", "status": "Dang hoc"}
    if campus_id:
        filters["campus_id"] = campus_id

    leads = frappe.get_all(
        "CRM Lead",
        filters=filters,
        fields=[
            "name", "student_name", "student_code",
            "current_grade", "linked_student", "campus_id",
        ],
        order_by="student_name asc",
    )

    # Import trong ham: tranh import vong pipeline <-> enrolled_class_sync
    # (module kia goi nguoc _log_step_change cua file nay)
    from erp.api.crm.enrolled_class_sync import grade_by_student_from_sis

    # Tra SIS cho TAT CA ho so (1 query), khong chi ho so thieu current_grade:
    # current_grade co the dang giu gia tri cu tu nam truoc.
    sis_grades = grade_by_student_from_sis(
        [lead["linked_student"] for lead in leads if lead.get("linked_student")]
    )

    graduate = []
    others = []
    for lead in leads:
        # SIS thang; current_grade chi dung khi SIS khong co lop nao cho hoc sinh
        grade = sis_grades.get(lead.get("linked_student")) or str(
            lead.get("current_grade") or ""
        ).strip()
        # Ghi nguoc vao row de danh sach xem truoc hien dung khoi da giai quyet
        lead["current_grade"] = grade
        if grade == _GRADUATING_GRADE:
            graduate.append(lead)
        elif lead.get("linked_student"):
            # Khong co linked_student thi khong tra duoc don tai ghi danh -> bo qua
            others.append(lead)

    # Gom theo campus: nam hoc active duoc xac dinh RIENG cho tung campus
    by_campus = {}
    for lead in others:
        by_campus.setdefault(lead.get("campus_id"), []).append(lead)

    transfer = []
    for cid, rows in by_campus.items():
        decisions = _re_enrollment_decision_by_student(
            [r["linked_student"] for r in rows], cid
        )
        transfer.extend(
            r for r in rows if decisions.get(r["linked_student"]) == "not_re_enroll"
        )

    return graduate, transfer


def _withdraw_one_lead(lead_name, new_status):
    """Chuyen 1 lead Enrolled/Dang hoc -> Nghi hoc voi status chi dinh.

    Doc lai tu DB moi lan thu: danh sach ung vien duoc tinh truoc do co the da cu
    (nguoi khac vua doi buoc/trang thai). Raise neu that bai — caller gom vao errors.
    """
    old_step = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", lead_name)
        if doc.step != "Enrolled" or doc.status != "Dang hoc":
            raise frappe.ValidationError(
                f"Ho so khong con o Enrolled/Dang hoc (hien tai: {doc.step}/{doc.status})"
            )
        validate_step_transition(doc.step, "Nghi hoc")

        old_step = doc.step
        old_status = doc.status
        doc.step = "Nghi hoc"
        doc.status = new_status

        # Bo qua kiem tra truong bat buoc.
        # `CRM Lead.phone_numbers` la child table `reqd: 1` nhung CRM Lead KHONG co field
        # SDT phang de bootstrap nhu CRM Guardian, nen ho so cu khong co dong nao se lam
        # `doc.save()` throw MandatoryError "Du lieu bi mat trong bang: Phone Numbers".
        # Da chay patch backfill_crm_lead_phone_from_guardian (lay SDT tu guardian qua
        # lead_guardians / CRM Family Relationship) va van con 1731 ho so khong co nguon
        # SDT nao — tuc rang buoc reqd nay khong phan anh dung du lieu thuc te.
        # Chan chuyen buoc vi ly do do la sai; ta chi ghi step/status nen khong lam hong
        # them du lieu nao.
        doc.flags.ignore_mandatory = True
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                raise

    _log_step_change(lead_name, old_step, "Nghi hoc", old_status, new_status)


@frappe.whitelist(methods=["POST"])
def bulk_withdraw_enrolled_students():
    """Chuyen hang loat hoc sinh chinh thuc sang buoc Nghi hoc.

    Hai nhom (xem _collect_withdraw_candidates):
      - Khoi 12 dang hoc                                  -> Nghi hoc / Tot nghiep
      - Khoi khac dang hoc + "Khong tai ghi danh"         -> Nghi hoc / Chuyen truong

    Tham so (body JSON):
      dry_run   : "1"/true -> CHI dem, khong ghi gi (man xac nhan tren UI)
      campus_id : mac dinh lay tu context nguoi dung

    Khong dung bulk_advance_step duoc vi ham do truyen extra_data={} cung nen moi ho so
    se roi vao cung mot status mac dinh, khong tach duoc Tot nghiep / Chuyen truong.

    Luu y tac dung phu (dung y do): moi doc.save() kich hoat CRM Lead.on_update ->
    lead_student_sync -> CRM Student.enrollment_status = 'Nghi hoc' -> hoc sinh khong
    con duoc xep lop moi.
    """
    check_crm_permission(_BULK_WITHDRAW_ROLES)
    data = get_request_data()

    campus_id = data.get("campus_id") or get_current_campus_from_context()
    raw_dry = data.get("dry_run")
    dry_run = str(raw_dry).strip().lower() in ("1", "true", "yes") if raw_dry is not None else False

    graduate, transfer = _collect_withdraw_candidates(campus_id)

    def _sample(rows):
        return [
            {
                "name": r["name"],
                "student_name": r.get("student_name"),
                "student_code": r.get("student_code"),
                "current_grade": r.get("current_grade"),
            }
            for r in rows[:20]
        ]

    if dry_run:
        return success_response(
            {
                "graduate_count": len(graduate),
                "transfer_count": len(transfer),
                "total": len(graduate) + len(transfer),
                "graduate_samples": _sample(graduate),
                "transfer_samples": _sample(transfer),
            },
            f"Se chuyen {len(graduate) + len(transfer)} ho so sang buoc Nghi hoc",
        )

    results = {"graduated": 0, "transferred": 0, "errors": []}
    for rows, new_status, counter in (
        (graduate, "Tot nghiep", "graduated"),
        (transfer, "Chuyen truong", "transferred"),
    ):
        for row in rows:
            try:
                _withdraw_one_lead(row["name"], new_status)
                results[counter] += 1
            except Exception as e:
                # Kem ten/ma hoc sinh: chi co docname CRM-LEAD-xxx thi ops khong tra ra ai
                results["errors"].append(
                    {
                        "name": row["name"],
                        "student_name": row.get("student_name"),
                        "student_code": row.get("student_code"),
                        "error": str(e),
                    }
                )

    frappe.db.commit()

    return success_response(
        results,
        f"Da chuyen {results['graduated']} ho so sang Tot nghiep, "
        f"{results['transferred']} ho so sang Chuyen truong, "
        f"{len(results['errors'])} loi",
    )


# --- Chuyen hang loat ho so da nop phi sang Hoc sinh chinh thuc --------------------

# Chi ho so DA NOP PHI moi duoc chuyen hang loat. "Dat coc" van phai chuyen tay
# (enroll_lead) vi chua chac chan nhap hoc.
_BULK_ENROLL_STATUSES = ("Dong phi",)

# Cung nhom quyen voi chuyen hang loat sang Nghi hoc: ghi hang loat, kho hoan tac tung ho so.
_BULK_ENROLL_ROLES = _BULK_WITHDRAW_ROLES


def _enroll_one_lead(lead_name, allowed_statuses, context):
    """Chuyen 1 ho so QLead (status thuoc allowed_statuses) -> Enrolled / Cho xep lop.

    Doc lai tu DB moi lan thu: danh sach ung vien duoc tinh truoc do co the da cu
    (nguoi khac vua doi buoc/trang thai).

    Tra ve True neu da chuyen, False neu BO QUA (khong con du dieu kien, hoac hoc sinh
    da co ho so khac o buoc Enrolled). Raise neu that bai — caller gom vao errors.
    KHONG commit: caller commit mot lan sau vong lap.
    """
    doc = None
    old_step = None
    old_status = None
    for attempt in range(2):
        doc = frappe.get_doc("CRM Lead", lead_name)
        if doc.step != "QLead" or (doc.status or "") not in allowed_statuses:
            return False
        if doc.linked_student and frappe.db.exists(
            "CRM Lead",
            {
                "linked_student": doc.linked_student,
                "step": "Enrolled",
                "name": ["!=", doc.name],
            },
        ):
            return False

        validate_step_transition(doc.step, "Enrolled")

        old_step = doc.step
        old_status = doc.status
        doc.step = "Enrolled"
        doc.status = "Cho xep lop"
        doc.enrollment_date = nowdate()
        # Sinh ma HS neu chua co — dong bo enroll_lead / _prepare_advance_step_doc.
        # Ho so nop phi thuong da co ma (ensure_student_code_for_qlead_status trong
        # change_status), nhung ho so import/backfill thi chua.
        if not doc.student_code and not doc.linked_student:
            from erp.api.crm.student_code import _generate_code_internal

            doc.student_code = _generate_code_internal(
                "WS1",
                doc.target_academic_year or "",
                doc.target_grade or "01",
            )
        pic_care = assign_pic_sales_care_weight_balance(doc.name, doc.campus_id)
        if pic_care:
            doc.pic_care = pic_care
        try:
            doc.save(ignore_permissions=True)
            break
        except frappe.TimestampMismatchError:
            if attempt == 1:
                raise

    _log_step_change(lead_name, old_step, "Enrolled", old_status, "Cho xep lop")
    _sync_lead_guardians_to_family_if_needed(doc)

    if not doc.linked_student:
        _run_create_enrollment_for_lead(lead_name, context)
    else:
        try:
            from erp.api.crm.enrolled_class_sync import (
                promote_leads_to_dang_hoc_if_class_assigned,
            )

            promote_leads_to_dang_hoc_if_class_assigned(doc.linked_student)
        except Exception as e:
            frappe.log_error(f"Loi dong bo trang thai enrolled ({context}): {str(e)}")

    return True


def _collect_enroll_candidates(campus_id=None):
    """Tim ho so QLead da nop phi du dieu kien chuyen sang Hoc sinh chinh thuc.

    Tra ve (linked_rows, new_rows, skipped_rows):
      linked_rows  — da co linked_student            -> chi chuyen buoc
      new_rows     — chua co linked_student          -> se tao ho so hoc sinh moi
      skipped_rows — hoc sinh da co ho so khac o buoc Enrolled -> bo qua

    Nhom "da co ho so Enrolled" tra bang MOT query (thay vi db.exists tung ho so) —
    danh sach nop phi co the hang tram dong. Ung vien deu dang o QLead nen khong the
    tu nam trong tap Enrolled, khong can loai tru chinh no.
    """
    filters = {"step": "QLead", "status": ["in", list(_BULK_ENROLL_STATUSES)]}
    if campus_id:
        filters["campus_id"] = campus_id

    leads = frappe.get_all(
        "CRM Lead",
        filters=filters,
        fields=[
            "name", "student_name", "student_code",
            "target_grade", "linked_student", "campus_id",
        ],
        order_by="student_name asc",
    )

    linked_ids = [lead["linked_student"] for lead in leads if lead.get("linked_student")]
    already_enrolled = set()
    if linked_ids:
        already_enrolled = {
            sid
            for sid in frappe.get_all(
                "CRM Lead",
                filters={"linked_student": ["in", linked_ids], "step": "Enrolled"},
                pluck="linked_student",
            )
            if sid
        }

    linked, new_students, skipped = [], [], []
    for lead in leads:
        sid = lead.get("linked_student")
        if sid and sid in already_enrolled:
            skipped.append(lead)
        elif sid:
            linked.append(lead)
        else:
            new_students.append(lead)

    return linked, new_students, skipped


@frappe.whitelist(methods=["POST"])
def bulk_enroll_paid_leads():
    """Chuyen hang loat ho so da nop phi sang buoc Hoc sinh chinh thuc.

    Chi xet ho so o buoc 'QLead' VA trang thai 'Dong phi' (Nop phi) — xem
    _collect_enroll_candidates.

    Tham so (body JSON):
      dry_run   : "1"/true -> CHI dem, khong ghi gi (man xac nhan tren UI)
      campus_id : mac dinh lay tu context nguoi dung

    Luu y tac dung phu (dung y do): moi ho so chuyen buoc se sinh ma hoc sinh (neu chua
    co), tao ho so hoc sinh + gia dinh, gan PIC cham soc va dong bo trang thai lop.
    """
    check_crm_permission(_BULK_ENROLL_ROLES)
    data = get_request_data()

    campus_id = data.get("campus_id") or get_current_campus_from_context()
    raw_dry = data.get("dry_run")
    dry_run = str(raw_dry).strip().lower() in ("1", "true", "yes") if raw_dry is not None else False

    linked, new_students, skipped = _collect_enroll_candidates(campus_id)

    def _sample(rows):
        return [
            {
                "name": r["name"],
                "student_name": r.get("student_name"),
                "student_code": r.get("student_code"),
                "target_grade": r.get("target_grade"),
            }
            for r in rows[:20]
        ]

    if dry_run:
        total = len(linked) + len(new_students)
        return success_response(
            {
                "linked_count": len(linked),
                "new_student_count": len(new_students),
                "skipped_count": len(skipped),
                "total": total,
                "linked_samples": _sample(linked),
                "new_student_samples": _sample(new_students),
                "skipped_samples": _sample(skipped),
            },
            f"Se chuyen {total} ho so sang buoc Hoc sinh chinh thuc",
        )

    results = {"enrolled": 0, "skipped": len(skipped), "errors": []}
    for row in linked + new_students:
        try:
            if _enroll_one_lead(row["name"], _BULK_ENROLL_STATUSES, "bulk_enroll_paid_leads"):
                results["enrolled"] += 1
            else:
                results["skipped"] += 1
        except Exception as e:
            # Kem ten/ma hoc sinh: chi co docname CRM-LEAD-xxx thi ops khong tra ra ai
            results["errors"].append(
                {
                    "name": row["name"],
                    "student_name": row.get("student_name"),
                    "student_code": row.get("student_code"),
                    "error": str(e),
                }
            )

    frappe.db.commit()

    return success_response(
        results,
        f"Da chuyen {results['enrolled']} ho so sang Hoc sinh chinh thuc, "
        f"{results['skipped']} ho so bo qua, {len(results['errors'])} loi",
    )


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
        doc.enrollment_date = nowdate()
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
    
    # Buoc QLead: da dong phi / dat coc (status chinh, sau khi gop deal_status)
    filters = {
        "step": "QLead",
        "status": ["in", ["Dong phi", "Dat coc"]],
    }
    if academic_year:
        filters["target_academic_year"] = academic_year
    
    leads = frappe.get_all("CRM Lead", filters=filters, fields=["name"])

    enrolled_count = 0
    errors = []
    for lead in leads:
        try:
            # Dung chung _enroll_one_lead voi bulk_enroll_paid_leads — khac moi tap status
            if _enroll_one_lead(
                lead["name"], ("Dong phi", "Dat coc"), "auto_enroll_paid_leads"
            ):
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
