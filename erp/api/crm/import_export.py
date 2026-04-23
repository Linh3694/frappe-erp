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
    validate_phone_number, normalize_phone_number,
    STEP_STATUSES, CRM_STEPS
)
from erp.api.crm.pipeline import _log_step_change
from datetime import datetime, timedelta


# Cot xuat / cap nhat bulk — khoi thong tin hoc sinh (StudentSection) + PIC / buoc / trang thai
# Dong bo voi frappe-sis-frontend bulkUpdateStudentColumns.ts
_EXPORT_BULK_LEAD_FIELDS = [
    "name",
    "crm_code",
    "student_code",
    "student_name",
    "pic",
    "step",
    "status",
    "reject_reason",
    "reject_detail",
    "student_gender",
    "student_dob",
    "current_grade",
    "current_school",
    "target_grade",
    "target_academic_year",
    "student_place_of_birth",
    "student_nationality",
    "student_ethnicity",
    "student_religion",
    "student_health_insurance_card",
    "student_initial_medical_registration",
    "student_health_notes",
    "student_account_holder_relationship",
    "student_bank_account_name",
    "student_bank_account_number",
    "student_bank_name",
    "student_bank_branch",
    "registered_address_province",
    "registered_address_ward",
    "registered_address_street",
    "current_address_province",
    "current_address_ward",
    "current_address_street",
    "student_study_interruption",
    "student_study_interruption_reason",
    "student_special_characteristics",
    "student_discipline_issues",
]

_BULK_FLOAT_FIELDS = frozenset()


def _parse_bulk_cell(field, raw):
    """Chuan hoa gia tri tu Excel / JSON."""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    if field in _BULK_FLOAT_FIELDS:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if field == "student_dob" and raw is not None:
        if hasattr(raw, "strftime"):
            return raw.strftime("%Y-%m-%d")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            try:
                base = datetime(1899, 12, 30)
                d = base + timedelta(days=float(raw))
                return d.strftime("%Y-%m-%d")
            except Exception:
                pass
        s = str(raw).strip()
        return s or None
    s = str(raw).strip()
    return s if s else None


def _set_doc_field_if_changed(doc, field, new_val):
    """Tra ve True neu co thay doi."""
    old = doc.get(field)
    if field in _BULK_FLOAT_FIELDS:
        try:
            o = float(old) if old is not None else None
        except (TypeError, ValueError):
            o = None
        n = new_val
        if o is None and n is None:
            return False
        if o is None or n is None:
            doc.set(field, n)
            return True
        if abs(o - float(n)) < 1e-9:
            return False
        doc.set(field, n)
        return True
    if field == "student_dob":
        old_s = (str(old)[:10] if old else "").strip()
        new_s = (new_val or "").strip()[:10] if new_val else ""
        if old_s == new_s:
            return False
        doc.set(field, new_val or None)
        return True
    o = (old or "") if old is not None else ""
    n = (new_val or "") if new_val is not None else ""
    if o == n:
        return False
    doc.set(field, new_val or None)
    return True


def _apply_bulk_student_section_fields(doc, row):
    """Doc row dict: chi cap nhat neu key co trong row."""
    changed = False
    for field in _EXPORT_BULK_LEAD_FIELDS:
        if field in (
            "name",
            "crm_code",
            "step",
            "status",
            "pic",
            "reject_reason",
            "reject_detail",
        ):
            continue
        if field not in row:
            continue
        new_val = _parse_bulk_cell(field, row.get(field))
        if _set_doc_field_if_changed(doc, field, new_val):
            changed = True
    return changed


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


@frappe.whitelist()
def export_step_leads_for_update():
    """
    Xuat danh sach records cua 1 step de user cap nhat bang Excel.
    Gom PIC / buoc / trang thai va toan bo truong khoi thong tin hoc sinh (StudentSection).
    Dong bo voi bulkUpdateStudentColumns.ts (frontend). Khong gom chuong trinh uu dai (%).
    """
    check_crm_permission()

    step = frappe.request.args.get("step")
    if not step:
        return validation_error_response("Thieu tham so step", {"step": ["Bat buoc"]})

    filters = {"step": step}
    campus_id = frappe.request.args.get("campus_id")
    if campus_id:
        filters["campus_id"] = campus_id

    leads = frappe.get_all(
        "CRM Lead",
        filters=filters,
        fields=_EXPORT_BULK_LEAD_FIELDS,
        order_by="crm_code asc, creation asc",
        limit_page_length=0,
    )

    all_step_statuses = {s: STEP_STATUSES.get(s, []) for s in CRM_STEPS}

    return success_response({
        "leads": leads,
        "valid_statuses": STEP_STATUSES.get(step, []),
        "all_step_statuses": all_step_statuses,
        "steps": CRM_STEPS,
        "step": step,
    })


@frappe.whitelist(methods=["POST"])
def bulk_update_leads():
    """
    Cap nhat hang loat records tu file Excel.
    Cap nhat: toan bo truong thong tin hoc sinh (StudentSection), pic, step, status, ly do tu choi (Lost).
    Cho phep chuyen buoc (step) — status se duoc validate theo buoc moi.
    Match bang truong 'name' (ID noi bo) hoac 'crm_code'.
    Chi ghi CRM Lead Step History khi step hoac status pipeline thay doi.

    Body JSON: { "rows": [ { ... }, ... ] } — key trung voi export_step_leads_for_update / bulkUpdateStudentColumns.ts
    """
    check_crm_permission()
    data = get_request_data()

    rows = data.get("rows", [])
    if not rows:
        return validation_error_response("Khong co du lieu", {"rows": ["Bat buoc"]})

    from erp.api.crm.utils import CRM_STEPS, generate_crm_code

    results = {"updated": 0, "skipped": 0, "errors": []}

    for idx, row in enumerate(rows):
        row_num = idx + 1
        lead_name = str(row.get("name", "")).strip()
        crm_code = str(row.get("crm_code", "")).strip()

        if not lead_name and not crm_code:
            results["errors"].append({"row": row_num, "error": "Thieu name hoac crm_code"})
            continue

        doc_name = None
        if lead_name and frappe.db.exists("CRM Lead", lead_name):
            doc_name = lead_name
        elif crm_code:
            doc_name = frappe.db.get_value("CRM Lead", {"crm_code": crm_code}, "name")

        if not doc_name:
            results["errors"].append({
                "row": row_num,
                "error": f"Khong tim thay ho so: name={lead_name}, crm_code={crm_code}"
            })
            continue

        try:
            doc = frappe.get_doc("CRM Lead", doc_name)
            snap_step = doc.step
            snap_status = doc.status

            changed = _apply_bulk_student_section_fields(doc, row)

            new_pic = str(row.get("pic", "")).strip()
            if new_pic and new_pic != (doc.pic or ""):
                doc.pic = new_pic
                changed = True

            new_step = str(row.get("step", "")).strip()
            new_status = str(row.get("status", "")).strip()
            reject_reason = str(row.get("reject_reason", "")).strip()
            reject_detail = str(row.get("reject_detail", "")).strip()

            # Validate step hop le
            if new_step and new_step != snap_step:
                if new_step not in CRM_STEPS:
                    results["errors"].append({
                        "row": row_num,
                        "error": f"Buoc '{new_step}' khong hop le. "
                                 f"Cho phep: {', '.join(CRM_STEPS)}"
                    })
                    continue
                doc.step = new_step
                changed = True

                # Gan crm_code khi chuyen vao Lead tro di ma chua co
                if not doc.crm_code and CRM_STEPS.index(new_step) >= CRM_STEPS.index("Lead"):
                    doc.crm_code = generate_crm_code()

            target_step = doc.step

            # Validate status theo step hien tai (sau khi doi buoc neu co)
            if new_status and new_status != (doc.status or ""):
                valid = STEP_STATUSES.get(target_step, [])
                if valid and new_status not in valid:
                    results["errors"].append({
                        "row": row_num,
                        "error": f"Status '{new_status}' khong hop le cho buoc {target_step}. "
                                 f"Cho phep: {', '.join(valid)}"
                    })
                    continue
                doc.status = new_status
                if new_status == "Lost":
                    doc.reject_reason = reject_reason
                    doc.reject_detail = reject_detail
                changed = True
            elif new_step and new_step != snap_step and not new_status:
                # Doi buoc nhung khong set status -> tu dong dat status mac dinh
                default_statuses = STEP_STATUSES.get(target_step, [])
                if default_statuses:
                    doc.status = default_statuses[0]
                else:
                    doc.status = ""
                changed = True

            if changed:
                doc.flags.ignore_validate = True
                doc.flags.ignore_mandatory = True
                doc.save(ignore_permissions=True)
                # Chi ghi log khi buoc hoac trang thai pipeline thay doi (tranh log khi chi sua thong tin HS)
                if doc.step != snap_step or doc.status != snap_status:
                    _log_step_change(
                        doc_name,
                        snap_step,
                        doc.step,
                        snap_status,
                        doc.status,
                        reject_reason=reject_reason if doc.status == "Lost" else None,
                        reject_detail=reject_detail if doc.status == "Lost" else None,
                    )
                results["updated"] += 1
            else:
                results["skipped"] += 1

        except Exception as e:
            results["errors"].append({"row": row_num, "error": str(e)})

    frappe.db.commit()

    return success_response(
        results,
        f"Cap nhat: {results['updated']} thanh cong, "
        f"{results['skipped']} khong thay doi, "
        f"{len(results['errors'])} loi"
    )
