"""
CRM Migration API - Dong bo du lieu tu CRM Student/Guardian/Family cu sang CRM Lead
Giup hien thi ho so da co trong pipeline CRM moi (buoc Enrolled) ma KHONG thay doi
bat ky logic nao cua he thong cu (SIS, Parent Portal).
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate
from erp.utils.api_response import (
    success_response, error_response, single_item_response,
    paginated_response, list_response, validation_error_response
)
from erp.api.crm.utils import check_crm_permission, get_request_data, generate_crm_code


REVERSE_GENDER_MAP = {
    "male": "Nam",
    "female": "Nu",
    "others": "",
}

REVERSE_RELATIONSHIP_MAP = {
    "Father": "Bo",
    "Mother": "Me",
    "Guardian": "Nguoi giam ho",
    "Grandfather": "Ong",
    "Grandmother": "Ba",
}

# Trung voi add_lead_sibling (mode=existing) trong lead.py
DEFAULT_SIBLING_SCHOOL = "Wellspring Hà Nội"


def _resolve_linked_family_via_shared_guardians(student_doc):
    """
    Fallback: HS chi co dong quan he duoi CRM Student — tim CRM Family khac co cung guardian.
    """
    rels = frappe.get_all(
        "CRM Family Relationship",
        filters={"student": student_doc.name},
        fields=["guardian"],
        limit_page_length=0,
    )
    seen_g = set()
    for r in rels:
        gid = r.get("guardian")
        if not gid or gid in seen_g:
            continue
        seen_g.add(gid)
        families = frappe.db.sql(
            """
            SELECT DISTINCT parent FROM `tabCRM Family Relationship`
            WHERE guardian = %s AND parenttype = 'CRM Family'
            LIMIT 5
            """,
            (gid,),
        )
        for (fam_name,) in families:
            if fam_name and frappe.db.exists("CRM Family", fam_name):
                return fam_name
    return None


def _resolve_linked_family_for_student(student_doc):
    """
    Tim ten document CRM Family tu CRM Student:
    - family_code (trung name hoac trung cot family_code)
    - hoac dong CRM Family Relationship co parenttype = CRM Family
    - fallback: guardian dung chung voi bang tren CRM Family
    """
    code = (getattr(student_doc, "family_code", None) or "").strip()
    if code:
        if frappe.db.exists("CRM Family", code):
            return code
        fam_name = frappe.db.get_value("CRM Family", {"family_code": code}, "name")
        if fam_name:
            return fam_name

    rels = frappe.get_all(
        "CRM Family Relationship",
        filters={"student": student_doc.name},
        fields=["parent", "parenttype"],
        limit_page_length=0,
    )
    for r in rels:
        if r.get("parenttype") == "CRM Family" and r.get("parent"):
            pname = r["parent"]
            if frappe.db.exists("CRM Family", pname):
                return pname
    return _resolve_linked_family_via_shared_guardians(student_doc)


def _sibling_relationship_label(current_doc, other_doc):
    """Uoc luong Anh / Chi / Em dua tren dob + gender (CRM Student)."""
    if not getattr(current_doc, "dob", None) or not getattr(other_doc, "dob", None):
        return ""
    d0 = getdate(current_doc.dob)
    d1 = getdate(other_doc.dob)
    if d1 < d0:
        if other_doc.gender == "male":
            return "Anh"
        if other_doc.gender == "female":
            return "Chi"
        return "Anh/Chị"
    if d1 > d0:
        if other_doc.gender == "male":
            return "Em trai"
        if other_doc.gender == "female":
            return "Em gai"
        return "Em"
    return "Cùng ngày sinh"


def _distinct_sibling_student_ids(family_name, exclude_student_name):
    """Cac CRM Student khac trong cung CRM Family (relationships tren document CRM Family)."""
    rel_rows = frappe.get_all(
        "CRM Family Relationship",
        filters={"parent": family_name},
        fields=["student"],
        limit_page_length=0,
    )
    seen = set()
    out = []
    for r in rel_rows:
        sid = r.get("student")
        if not sid or sid == exclude_student_name or sid in seen:
            continue
        if not frappe.db.exists("CRM Student", sid):
            continue
        seen.add(sid)
        out.append(sid)
    return out


def _distinct_sibling_student_ids_via_shared_guardians(exclude_student_name):
    """
    HS khac cung it nhat mot PH (qua bat ky dong CRM Family Relationship),
    khi khong co document CRM Family de gom nhom.
    """
    rels = frappe.get_all(
        "CRM Family Relationship",
        filters={"student": exclude_student_name},
        fields=["guardian"],
        limit_page_length=0,
    )
    gids = {r["guardian"] for r in rels if r.get("guardian")}
    if not gids:
        return []
    seen = set()
    out = []
    for gid in gids:
        others = frappe.get_all(
            "CRM Family Relationship",
            filters={"guardian": gid, "student": ["!=", exclude_student_name]},
            fields=["student"],
            limit_page_length=0,
        )
        for o in others:
            sid = o.get("student")
            if not sid or sid == exclude_student_name or sid in seen:
                continue
            if not frappe.db.exists("CRM Student", sid):
                continue
            seen.add(sid)
            out.append(sid)
    return out


def _lead_sibling_rows_for_student(student_doc, family_name=None):
    """
    Neu co family_name: siblings trong CRM Family.
    Neu khong: suy qua guardian dung chung (du lieu cu chi co bang duoi CRM Student).
    """
    if family_name:
        sibling_ids = _distinct_sibling_student_ids(family_name, student_doc.name)
    else:
        sibling_ids = _distinct_sibling_student_ids_via_shared_guardians(student_doc.name)
    if not sibling_ids:
        return []
    siblings = [frappe.get_doc("CRM Student", sid) for sid in sibling_ids]
    siblings.sort(key=lambda d: (d.dob or "", d.student_name or ""))
    rows = []
    for other in siblings:
        rows.append({
            "sibling_name": other.student_name,
            "student_code": other.student_code or "",
            "relationship_type": _sibling_relationship_label(student_doc, other),
            "dob": str(other.dob) if other.dob else None,
            "school": DEFAULT_SIBLING_SCHOOL,
        })
    return rows


def _find_key_guardian_for_student(student_name):
    """
    Tim guardian chinh cua student thong qua CRM Family Relationship.
    Uu tien: key_person=1, hoac lay row dau tien.
    """
    rels = frappe.get_all(
        "CRM Family Relationship",
        filters={"student": student_name},
        fields=["guardian", "relationship_type", "key_person"],
        order_by="key_person desc, idx asc",
        limit_page_length=0,
    )

    if not rels:
        return None, None

    best = rels[0]
    guardian_doc = None
    if best.get("guardian") and frappe.db.exists("CRM Guardian", best["guardian"]):
        guardian_doc = frappe.get_doc("CRM Guardian", best["guardian"])

    return guardian_doc, best.get("relationship_type", "")


def _build_lead_from_student(
    student_doc,
    guardian_doc,
    relationship_type,
    linked_family=None,
    lead_sibling_rows=None,
):
    """Tao dict data cho CRM Lead tu CRM Student + CRM Guardian; tuy chon linked_family + lead_siblings."""
    lead_data = {
        "doctype": "CRM Lead",
        "step": "Enrolled",
        "status": "Dang hoc",
        "data_source": "Offline",
        "student_name": student_doc.student_name,
        "student_code": student_doc.student_code,
        "student_dob": student_doc.dob,
        "student_gender": REVERSE_GENDER_MAP.get(student_doc.gender or "", ""),
        "campus_id": student_doc.campus_id,
        "linked_student": student_doc.name,
    }

    if linked_family:
        lead_data["linked_family"] = linked_family
    if lead_sibling_rows:
        lead_data["lead_siblings"] = lead_sibling_rows

    if guardian_doc:
        lead_data["guardian_name"] = guardian_doc.guardian_name or ""
        lead_data["guardian_email"] = guardian_doc.email or ""
        # CCCD thuc te nam o field id_number; guardian_id la ma unique cua doc (vd GRD-00001)
        lead_data["guardian_id_number"] = getattr(guardian_doc, "id_number", "") or ""
        lead_data["relationship"] = REVERSE_RELATIONSHIP_MAP.get(
            relationship_type, relationship_type or ""
        )

        if guardian_doc.phone_number:
            lead_data["phone_numbers"] = [{
                "phone_number": guardian_doc.phone_number,
                "is_primary": 1,
            }]
            # Khong gan primary_phone: khong phai field DocType CRM Lead, chi enrich dong o API list

    return lead_data


@frappe.whitelist(methods=["GET"])
def get_unlinked_students():
    """
    Lay danh sach CRM Student chua co CRM Lead lien ket.
    Dung de xem truoc truoc khi chay migration.
    """
    check_crm_permission(["System Manager", "SIS Manager"])

    page = cint(frappe.form_dict.get("page", 1))
    per_page = cint(frappe.form_dict.get("per_page", 50))
    campus_id = frappe.form_dict.get("campus_id")

    # Lay tat ca CRM Student da co lead lien ket
    linked_students = frappe.get_all(
        "CRM Lead",
        filters={"linked_student": ["is", "set"]},
        fields=["linked_student"],
        limit_page_length=0,
    )
    linked_set = {r["linked_student"] for r in linked_students}

    # Lay tat ca CRM Student
    student_filters = {}
    if campus_id:
        student_filters["campus_id"] = campus_id

    all_students = frappe.get_all(
        "CRM Student",
        filters=student_filters,
        fields=["name", "student_name", "student_code", "dob", "gender", "campus_id", "family_code"],
        order_by="creation asc",
        limit_page_length=0,
    )

    # Loc ra nhung student chua co lead
    unlinked = [s for s in all_students if s["name"] not in linked_set]
    total = len(unlinked)

    start = (page - 1) * per_page
    page_data = unlinked[start:start + per_page]

    # Bo sung guardian info cho moi student
    for student in page_data:
        guardian_doc, rel_type = _find_key_guardian_for_student(student["name"])
        student["guardian_name"] = guardian_doc.guardian_name if guardian_doc else ""
        student["guardian_phone"] = guardian_doc.phone_number if guardian_doc else ""
        student["relationship_type"] = rel_type

    return paginated_response(page_data, page, total, per_page, f"Tim thay {total} student chua co CRM Lead")


@frappe.whitelist(methods=["POST"])
def sync_existing_students():
    """
    Tao CRM Lead (buoc Enrolled) cho tat ca CRM Student chua co lead lien ket.
    Chi tao moi, KHONG chinh sua bat ky du lieu nao cua CRM Student/Guardian/Family.

    Params (JSON body):
      - campus_id (optional): Chi sync students cua campus nay
      - dry_run (optional, bool): Neu True chi tra ve preview, ko tao thuc te
      - student_names (optional, list): Chi sync cac student cu the (thay vi tat ca)
      - include_family_siblings (optional, bool, default 1): Neu 1 thi gan linked_family +
        lead_siblings tu CRM Family / CRM Family Relationship (anh chi em cung ho)
    """
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()

    campus_id = data.get("campus_id")
    dry_run = cint(data.get("dry_run", 0))
    specific_students = data.get("student_names", [])
    include_family_siblings = cint(data.get("include_family_siblings", 1))

    # Tim CRM Students chua co lead
    linked_students = frappe.get_all(
        "CRM Lead",
        filters={"linked_student": ["is", "set"]},
        fields=["linked_student"],
        limit_page_length=0,
    )
    linked_set = {r["linked_student"] for r in linked_students}

    student_filters = {}
    if campus_id:
        student_filters["campus_id"] = campus_id
    if specific_students:
        student_filters["name"] = ["in", specific_students]

    all_students = frappe.get_all(
        "CRM Student",
        filters=student_filters,
        fields=["name"],
        order_by="creation asc",
        limit_page_length=0,
    )

    to_migrate = [s for s in all_students if s["name"] not in linked_set]

    if dry_run:
        preview = []
        for s in to_migrate[:100]:
            student_doc = frappe.get_doc("CRM Student", s["name"])
            guardian_doc, rel_type = _find_key_guardian_for_student(s["name"])
            linked_family = None
            sibling_rows = []
            if include_family_siblings:
                linked_family = _resolve_linked_family_for_student(student_doc)
                sibling_rows = _lead_sibling_rows_for_student(student_doc, linked_family)
            preview.append({
                "student": s["name"],
                "student_name": student_doc.student_name,
                "student_code": student_doc.student_code,
                "campus_id": student_doc.campus_id,
                "guardian_name": guardian_doc.guardian_name if guardian_doc else "",
                "guardian_phone": guardian_doc.phone_number if guardian_doc else "",
                "linked_family": linked_family,
                "siblings_count": len(sibling_rows),
                "siblings_preview": [
                    {"sibling_name": r.get("sibling_name"), "student_code": r.get("student_code")}
                    for r in sibling_rows[:8]
                ],
            })
        return success_response({
            "total_to_migrate": len(to_migrate),
            "preview": preview,
            "dry_run": True,
            "include_family_siblings": bool(include_family_siblings),
        }, f"Preview: {len(to_migrate)} students can dong bo")

    # Thuc hien migration
    results = {"created": 0, "skipped": 0, "errors": [], "leads_created": []}
    batch_size = cint(data.get("batch_size", 100)) or 100

    for idx, s in enumerate(to_migrate, start=1):
        # Moi record chay trong 1 savepoint rieng de co the rollback ma khong anh huong
        # cac record truoc da insert thanh cong trong cung transaction.
        savepoint = f"crm_mig_{idx}"
        try:
            frappe.db.savepoint(savepoint)

            # Kiem tra lai ngay truoc khi insert de tranh race condition
            # (vd: admin khac dang chay cung thao tac, hoac vua chay backfill)
            if frappe.db.exists("CRM Lead", {"linked_student": s["name"]}):
                results["skipped"] += 1
                continue

            student_doc = frappe.get_doc("CRM Student", s["name"])
            guardian_doc, rel_type = _find_key_guardian_for_student(s["name"])

            linked_family = None
            sibling_rows = []
            if include_family_siblings:
                linked_family = _resolve_linked_family_for_student(student_doc)
                sibling_rows = _lead_sibling_rows_for_student(student_doc, linked_family)

            lead_data = _build_lead_from_student(
                student_doc,
                guardian_doc,
                rel_type,
                linked_family=linked_family,
                lead_sibling_rows=sibling_rows,
            )
            lead_data["crm_code"] = generate_crm_code()
            lead_doc = frappe.get_doc(lead_data)
            # Bypass mandatory validation cho phone_numbers vi du lieu cu co the khong co SDT
            lead_doc.flags.ignore_validate = True
            lead_doc.flags.ignore_mandatory = True
            lead_doc.insert(ignore_permissions=True)

            results["created"] += 1
            results["leads_created"].append({
                "lead": lead_doc.name,
                "student": s["name"],
                "student_name": student_doc.student_name,
            })

        except Exception as e:
            # Rollback chi savepoint nay; cac record truoc van giu nguyen
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                pass
            error_msg = str(e)
            results["errors"].append({
                "student": s["name"],
                "error": error_msg,
            })
            # Ghi log vinh vien de trace sau migration
            frappe.log_error(
                message=frappe.get_traceback() or error_msg,
                title=f"CRM Migration sync_existing_students - {s['name']}",
            )

        # Commit theo batch de tranh mat tien do khi process bi kill giua chung
        if idx % batch_size == 0:
            frappe.db.commit()

    frappe.db.commit()

    return success_response(
        results,
        f"Da tao {results['created']} CRM Lead tu {len(to_migrate)} students. "
        f"Bo qua (da co lead): {results['skipped']}. Loi: {len(results['errors'])}"
    )


def _run_migration_in_background(job_id: str, method: str, params: dict, user: str = None):
    """
    Chay sync/backfill o background job, luu ket qua vao cache de client poll qua
    `get_migration_job_status`.

    - job_id: key cache de theo doi.
    - method: dotted path cua whitelisted function (vd erp.api.crm.migration.sync_existing_students).
    - params: dict params (campus_id, include_family_siblings, ...).
    - user: session user goc (de check_crm_permission hoat dong dung).
    """
    cache_key = f"crm_migration_result:{job_id}"
    cache = frappe.cache()
    try:
        if user:
            frappe.set_user(user)
        cache.set_value(
            cache_key,
            {"status": "running", "method": method, "params": params},
            expires_in_sec=86400,
        )
        # Gia lap form_dict de get_request_data() trong target function nhan duoc params
        frappe.local.form_dict = frappe._dict(params or {})
        fn = frappe.get_attr(method)
        result = fn()
        cache.set_value(
            cache_key,
            {"status": "completed", "method": method, "result": result},
            expires_in_sec=86400,
        )
    except Exception as e:
        frappe.log_error(
            message=frappe.get_traceback() or str(e),
            title=f"CRM Migration Worker - {method} - {job_id}",
        )
        cache.set_value(
            cache_key,
            {
                "status": "failed",
                "method": method,
                "error": str(e),
                "traceback": frappe.get_traceback(),
            },
            expires_in_sec=86400,
        )


def _enqueue_migration(method: str) -> dict:
    """Helper chung de enqueue 1 migration method va tra ve job_id."""
    data = get_request_data()
    job_id = f"crm_mig_{frappe.generate_hash(length=10)}"
    frappe.enqueue(
        "erp.api.crm.migration._run_migration_in_background",
        queue="long",
        timeout=36000,
        job_name=job_id,
        job_id=job_id,
        method=method,
        params=dict(data or {}),
        user=frappe.session.user,
    )
    return {"job_id": job_id, "status": "queued", "method": method}


@frappe.whitelist(methods=["POST"])
def enqueue_sync_existing_students():
    """
    Enqueue `sync_existing_students` chay background (queue=long, timeout=36000s).
    Tra ve job_id de client poll qua `get_migration_job_status`.
    Nhan cung tham so nhu `sync_existing_students`.
    """
    check_crm_permission(["System Manager", "SIS Manager"])
    result = _enqueue_migration("erp.api.crm.migration.sync_existing_students")
    return success_response(result, f"Da queue sync_existing_students (job_id={result['job_id']})")


@frappe.whitelist(methods=["POST"])
def enqueue_backfill_lead_family_siblings():
    """
    Enqueue `backfill_lead_family_siblings` chay background.
    Tra ve job_id de poll qua `get_migration_job_status`.
    """
    check_crm_permission(["System Manager", "SIS Manager"])
    result = _enqueue_migration("erp.api.crm.migration.backfill_lead_family_siblings")
    return success_response(result, f"Da queue backfill (job_id={result['job_id']})")


@frappe.whitelist(methods=["GET"])
def get_migration_job_status():
    """
    Kiem tra trang thai cua migration job da enqueue.
    Params: job_id (required).
    Tra ve: {status: queued|running|completed|failed, result?, error?}.
    """
    check_crm_permission(["System Manager", "SIS Manager"])
    job_id = frappe.form_dict.get("job_id")
    if not job_id:
        return error_response("Thieu job_id")
    cache_val = frappe.cache().get_value(f"crm_migration_result:{job_id}")
    if not cache_val:
        # Co the job chua start hoac da het TTL
        return single_item_response(
            {"job_id": job_id, "status": "unknown"},
            "Khong tim thay job (chua start hoac da het han cache)",
        )
    cache_val["job_id"] = job_id
    return single_item_response(cache_val, f"Trang thai job {job_id}")


def _lead_needs_family_backfill(lead_doc, force):
    """force=0: chi lead thieu linked_family hoac chua co dong lead_siblings."""
    if force:
        return True
    if not getattr(lead_doc, "linked_family", None):
        return True
    siblings = getattr(lead_doc, "lead_siblings", None) or []
    return len(siblings) == 0


@frappe.whitelist(methods=["POST"])
def backfill_lead_family_siblings():
    """
    Cap nhat linked_family + lead_siblings cho CRM Lead DA CO linked_student
    (dong bo lai sau khi migrate cu thieu anh/chi/em).

    Params (JSON body):
      - dry_run (optional): 1 = chi tra preview
      - force (optional, default 0): 0 = chi lead dang thieu linked_family hoac lead_siblings rong;
        1 = ghi de tu CRM Family cho moi lead co linked_student
      - campus_id (optional): loc theo campus_id tren CRM Lead
      - linked_students (optional, list): chi cac CRM Student name
    """
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()

    dry_run = cint(data.get("dry_run", 0))
    force = cint(data.get("force", 0))
    campus_id = data.get("campus_id")
    linked_students_filter = data.get("linked_students") or []

    lead_filters = {"linked_student": ["is", "set"]}
    if campus_id:
        lead_filters["campus_id"] = campus_id
    if linked_students_filter:
        lead_filters["linked_student"] = ["in", linked_students_filter]

    leads = frappe.get_all(
        "CRM Lead",
        filters=lead_filters,
        fields=["name", "linked_student"],
        order_by="modified desc",
        limit_page_length=0,
    )

    to_process = []
    for row in leads:
        lead_doc = frappe.get_doc("CRM Lead", row["name"])
        if not lead_doc.linked_student:
            continue
        if not frappe.db.exists("CRM Student", lead_doc.linked_student):
            continue
        if not _lead_needs_family_backfill(lead_doc, force):
            continue
        to_process.append(lead_doc)

    if dry_run:
        preview = []
        for lead_doc in to_process[:150]:
            student_doc = frappe.get_doc("CRM Student", lead_doc.linked_student)
            fam = _resolve_linked_family_for_student(student_doc)
            sib_rows = _lead_sibling_rows_for_student(student_doc, fam)
            preview.append({
                "lead": lead_doc.name,
                "linked_student": lead_doc.linked_student,
                "student_name": student_doc.student_name,
                "resolved_linked_family": fam,
                "siblings_count": len(sib_rows),
                "siblings_preview": [
                    {"sibling_name": r.get("sibling_name"), "student_code": r.get("student_code")}
                    for r in sib_rows[:8]
                ],
            })
        return success_response({
            "total_leads": len(leads),
            "to_update": len(to_process),
            "preview": preview,
            "dry_run": True,
            "force": bool(force),
        }, f"Preview: {len(to_process)} lead can cap nhat family/siblings")

    results = {"updated": 0, "skipped_no_family_or_siblings": 0, "errors": [], "details": []}
    batch_size = cint(data.get("batch_size", 100)) or 100

    for idx, lead_doc in enumerate(to_process, start=1):
        savepoint = f"crm_backfill_{idx}"
        try:
            frappe.db.savepoint(savepoint)

            student_doc = frappe.get_doc("CRM Student", lead_doc.linked_student)
            fam = _resolve_linked_family_for_student(student_doc)
            sib_rows = _lead_sibling_rows_for_student(student_doc, fam)
            if not fam and not sib_rows:
                results["skipped_no_family_or_siblings"] += 1
                results["details"].append({
                    "lead": lead_doc.name,
                    "linked_student": lead_doc.linked_student,
                    "status": "skipped_no_crm_family_or_siblings",
                })
                continue

            if fam:
                lead_doc.linked_family = fam
            lead_doc.set("lead_siblings", [])
            for r in sib_rows:
                lead_doc.append("lead_siblings", r)

            lead_doc.flags.ignore_validate = True
            lead_doc.flags.ignore_mandatory = True
            lead_doc.save(ignore_permissions=True)

            results["updated"] += 1
            results["details"].append({
                "lead": lead_doc.name,
                "linked_student": lead_doc.linked_student,
                "linked_family": fam,
                "siblings_count": len(sib_rows),
                "status": "updated",
            })
        except Exception as e:
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                pass
            error_msg = str(e)
            results["errors"].append({
                "lead": lead_doc.name,
                "linked_student": getattr(lead_doc, "linked_student", None),
                "error": error_msg,
            })
            frappe.log_error(
                message=frappe.get_traceback() or error_msg,
                title=f"CRM Migration backfill - {lead_doc.name}",
            )

        if idx % batch_size == 0:
            frappe.db.commit()

    frappe.db.commit()

    return success_response(
        results,
        f"Da cap nhat {results['updated']} lead. Bo qua (khong co CRM Family va khong suy ra anh/chi/em): "
        f"{results['skipped_no_family_or_siblings']}. Loi: {len(results['errors'])}",
    )


@frappe.whitelist(methods=["GET"])
def get_migration_stats():
    """Thong ke tong quan de hien thi tren UI truoc khi chay migration"""
    check_crm_permission(["System Manager", "SIS Manager"])

    campus_id = frappe.form_dict.get("campus_id")

    student_filters = {}
    if campus_id:
        student_filters["campus_id"] = campus_id

    total_students = frappe.db.count("CRM Student", filters=student_filters)

    # Dem so student da co lead
    linked_filters = {"linked_student": ["is", "set"]}
    if campus_id:
        linked_filters["campus_id"] = campus_id
    linked_count = frappe.db.count("CRM Lead", filters=linked_filters)

    total_guardians = frappe.db.count("CRM Guardian")
    total_families = frappe.db.count("CRM Family")

    return single_item_response({
        "total_students": total_students,
        "already_linked": linked_count,
        "unlinked": total_students - linked_count,
        "total_guardians": total_guardians,
        "total_families": total_families,
    }, "Thong ke migration")


@frappe.whitelist(methods=["POST"])
def fix_migrated_statuses():
    """
    Cap nhat status cu khong con hop le sang status moi.
    Chuyen cac records co status bi loi do thay doi step/status mapping.

    Params (JSON body):
      - dry_run (optional, bool): Neu 1 chi dem + tra ve chi tiet, KHONG UPDATE
    """
    check_crm_permission(["System Manager", "SIS Manager"])
    data = get_request_data()
    dry_run = cint(data.get("dry_run", 0))

    # (step, old_status, new_status) — Nghi hoc co 2 mapping legacy Withdraw/Graduated
    STATUS_FIXES = [
        ("Enrolled", "Enrolled", "Dang hoc"),
        ("Nghi hoc", "Withdraw", "Chuyen truong"),
        ("Nghi hoc", "Graduated", "Tot nghiep"),
    ]

    OLD_STATUS_MAP = {
        "New": {"Verify": "Can kiem tra"},
        "KNM": {"Lead": "Khong nghe may"},
        "HGL": {"Lead": "Hen gap lai"},
        "KNM nhieu lan": {"Lead": "Khong nghe may nhieu lan"},
        "KCNC": {"Lead": "Khong co nhu cau"},
        "Sai thong tin": {"Lead": "Sau thong tin"},
        "Follow up": {"QLead": "Follow Up"},
        "Pre-school tour": {"QLead": "Pre-school Tour/ School Tour"},
        "School tour": {"QLead": "Pre-school Tour/ School Tour"},
        "Fail": {"QLead": "Lost"},
    }

    results = {"updated": 0, "details": [], "dry_run": bool(dry_run)}

    # Helper dem truoc, log va update (bo qua update neu dry_run)
    def _apply_status_fix(step, old_status, new_status):
        count = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabCRM Lead` WHERE step = %(step)s AND status = %(old)s",
            {"step": step, "old": old_status},
        )[0][0]
        if not count:
            return
        detail = f"{step}: {old_status} -> {new_status} ({count} records)"
        results["updated"] += count
        results["details"].append(detail)
        if not dry_run:
            frappe.db.sql(
                "UPDATE `tabCRM Lead` SET status = %(new)s WHERE step = %(step)s AND status = %(old)s",
                {"new": new_status, "step": step, "old": old_status},
            )
            frappe.logger("crm_migration").info(f"[fix_migrated_statuses] {detail}")

    for step, old_status, new_status in STATUS_FIXES:
        _apply_status_fix(step, old_status, new_status)

    for old_status, step_map in OLD_STATUS_MAP.items():
        for step, new_status in step_map.items():
            _apply_status_fix(step, old_status, new_status)

    # Fix Draft records co status != '' -> status rong
    draft_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabCRM Lead` WHERE step = 'Draft' AND status != ''",
    )[0][0]
    if draft_count:
        detail = f"Draft: cleared status ({draft_count} records)"
        results["updated"] += draft_count
        results["details"].append(detail)
        if not dry_run:
            frappe.db.sql("UPDATE `tabCRM Lead` SET status = '' WHERE step = 'Draft' AND status != ''")
            frappe.logger("crm_migration").info(f"[fix_migrated_statuses] {detail}")

    if dry_run:
        return success_response(
            results,
            f"Dry-run: {results['updated']} records se duoc cap nhat. KHONG co thay doi DB.",
        )

    frappe.db.commit()

    return success_response(results, f"Da cap nhat {results['updated']} records")
