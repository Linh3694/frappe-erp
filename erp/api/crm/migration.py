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


def _resolve_linked_family_for_student(student_doc):
    """
    Tim ten document CRM Family tu CRM Student:
    - family_code (trung name hoac trung cot family_code)
    - hoac dong CRM Family Relationship co parenttype = CRM Family
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
    return None


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


def _lead_sibling_rows_from_family(student_doc, family_name):
    """Dong du lieu cho bang CRM Lead Sibling — check cheo CRM Family Relationship."""
    rows = []
    sibling_ids = _distinct_sibling_student_ids(family_name, student_doc.name)
    siblings = [frappe.get_doc("CRM Student", sid) for sid in sibling_ids]
    siblings.sort(key=lambda d: (d.dob or "", d.student_name or ""))
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
        lead_data["guardian_id_number"] = guardian_doc.guardian_id or ""
        lead_data["relationship"] = REVERSE_RELATIONSHIP_MAP.get(
            relationship_type, relationship_type or ""
        )

        if guardian_doc.phone_number:
            lead_data["phone_numbers"] = [{
                "phone_number": guardian_doc.phone_number,
                "is_primary": 1,
            }]
            lead_data["primary_phone"] = guardian_doc.phone_number

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
                if linked_family:
                    sibling_rows = _lead_sibling_rows_from_family(student_doc, linked_family)
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
    results = {"created": 0, "errors": [], "leads_created": []}

    for s in to_migrate:
        try:
            student_doc = frappe.get_doc("CRM Student", s["name"])
            guardian_doc, rel_type = _find_key_guardian_for_student(s["name"])

            linked_family = None
            sibling_rows = []
            if include_family_siblings:
                linked_family = _resolve_linked_family_for_student(student_doc)
                if linked_family:
                    sibling_rows = _lead_sibling_rows_from_family(student_doc, linked_family)

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
            results["errors"].append({
                "student": s["name"],
                "error": str(e),
            })

    frappe.db.commit()

    return success_response(
        results,
        f"Da tao {results['created']} CRM Lead tu {len(to_migrate)} students. "
        f"Loi: {len(results['errors'])}"
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
    """
    check_crm_permission(["System Manager", "SIS Manager"])

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

    results = {"updated": 0, "details": []}

    # Fix step-specific status renames
    for step, old_status, new_status in STATUS_FIXES:
        frappe.db.sql(
            "UPDATE `tabCRM Lead` SET status = %(new)s WHERE step = %(step)s AND status = %(old)s",
            {"new": new_status, "step": step, "old": old_status},
        )
        affected = frappe.db.sql("SELECT ROW_COUNT()")[0][0]
        if affected:
            results["updated"] += affected
            results["details"].append(f"{step}: {old_status} -> {new_status} ({affected} records)")

    # Fix old status names
    for old_status, step_map in OLD_STATUS_MAP.items():
        for step, new_status in step_map.items():
            affected_count = frappe.db.sql(
                "SELECT COUNT(*) FROM `tabCRM Lead` WHERE step = %(step)s AND status = %(old)s",
                {"step": step, "old": old_status}
            )[0][0]
            if affected_count:
                frappe.db.sql(
                    "UPDATE `tabCRM Lead` SET status = %(new)s WHERE step = %(step)s AND status = %(old)s",
                    {"new": new_status, "step": step, "old": old_status}
                )
                results["updated"] += affected_count
                results["details"].append(f"{step}: {old_status} -> {new_status} ({affected_count} records)")

    # Fix Draft records co status 'New' -> status rong
    draft_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabCRM Lead` WHERE step = 'Draft' AND status != ''",
    )[0][0]
    if draft_count:
        frappe.db.sql("UPDATE `tabCRM Lead` SET status = '' WHERE step = 'Draft' AND status != ''")
        results["updated"] += draft_count
        results["details"].append(f"Draft: cleared status ({draft_count} records)")

    frappe.db.commit()

    return success_response(results, f"Da cap nhat {results['updated']} records")
