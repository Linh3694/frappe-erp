"""
Dong bo truong hoc sinh tu CRM Lead sang CRM Student.

Quy tac nghiep vu: Sau khi Lead co linked_student (nhap hoc / lien ket),
cac truong ho so hoc sinh co ban tren CRM Lead duoc coi la nguon cap nhat
cho ban ghi CRM Student (man Hoc sinh SIS). Cac thay doi qua CRM, bulk Excel
hoac Parent Portal (ghi Lead) se cap nhat CRM Student tu dong.

Chi dong bo cac cot ton tai tren DocType CRM Student; khong ghi de bang rong
cac truong bat buoc (ten, ma, dob, gender) neu Lead de trong — tranh lam hai du lieu Student.

Module nay cung la nguon duy nhat tinh CRM Student.enrollment_status (trang thai hoc)
— xem compute_enrollment_status. Trang thai duoc suy tu TAT CA Lead tro vao Student,
va la dieu kien de duoc xep lop moi (erp.api.crm.enrolled_class_sync.can_assign_student_to_class).
"""

from __future__ import annotations

from datetime import date

import frappe
from frappe.utils import getdate

from erp.api.crm.enrollment import GENDER_MAP

# Gia tri CRM Student.enrollment_status — PHAI khop options trong crm_student.json
ENROLLMENT_STATUS_STUDYING = "Dang hoc"
ENROLLMENT_STATUS_WITHDRAWN = "Nghi hoc"
ENROLLMENT_STATUS_NOT_YET = "Chua nhap hoc"


def _lead_student_dob_to_iso(lead_doc) -> str | None:
    """Tra ve YYYY-MM-DD neu Lead co ngay sinh hop le; khong thi None."""
    raw = getattr(lead_doc, "student_dob", None)
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return getdate(raw).strftime("%Y-%m-%d")
    s = str(raw).strip()
    if not s:
        return None
    try:
        return getdate(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def _lead_gender_to_student_select(lead_doc) -> str | None:
    """Map student_gender Lead (Nam/Nu) -> CRM Student Select; khong map duoc thi None."""
    raw = str(getattr(lead_doc, "student_gender", None) or "").strip()
    if not raw:
        return None
    g = GENDER_MAP.get(raw, "")
    return g if g else None


def compute_enrollment_status(crm_student_name: str) -> str:
    """Tinh trang thai hoc cua 1 CRM Student tu TAT CA CRM Lead tro vao no.

    Mot CRM Student co the bi NHIEU CRM Lead tro vao (nghi hoc roi nhap hoc lai),
    nen khong duoc suy trang thai tu mot lead don le.

    Thu tu uu tien (PHAI khop nguyen ban voi patch
    erp/patches/v1_0/backfill_crm_student_enrollment_status.py):
      1. Co >=1 Lead o step 'Enrolled'                 -> 'Dang hoc'
      2. Co Lead va TAT CA Lead o step 'Nghi hoc'      -> 'Nghi hoc'
      3. Da co lop Regular (SIS Class Student)         -> 'Dang hoc'  (grandfather)
      4. Con lai, co Lead                              -> 'Chua nhap hoc'
      5. Khong Lead, khong lop                         -> ''  (chua lien ket ho so)

    Buoc 1-2 chi 1 aggregate query tren index (linked_student, step).
    Buoc 3 chi chay o nhanh HIEM (khong co lead Enrolled va khong toan bo Nghi hoc).
    """
    if not crm_student_name:
        return ""

    row = frappe.db.sql(
        """
        SELECT
            SUM(CASE WHEN `step` = 'Enrolled' THEN 1 ELSE 0 END) AS enrolled_cnt,
            SUM(CASE WHEN `step` = 'Nghi hoc' THEN 1 ELSE 0 END) AS withdrawn_cnt,
            COUNT(*) AS total_cnt
        FROM `tabCRM Lead`
        WHERE `linked_student` = %s
        """,
        (crm_student_name,),
        as_dict=True,
    )[0]

    total = int(row.get("total_cnt") or 0)
    if int(row.get("enrolled_cnt") or 0):
        return ENROLLMENT_STATUS_STUDYING
    if total and int(row.get("withdrawn_cnt") or 0) == total:
        return ENROLLMENT_STATUS_WITHDRAWN

    # Grandfather: HS dang co lop that nhung ho so CRM chua/khong len Enrolled.
    # Tranh chan oan HS dang hoc that (import Excel cu, Lead con o QLead).
    from erp.api.crm.enrolled_class_sync import has_regular_class_assignment

    if has_regular_class_assignment(crm_student_name):
        return ENROLLMENT_STATUS_STUDYING

    return ENROLLMENT_STATUS_NOT_YET if total else ""


def sync_enrollment_status_for_student(crm_student_name: str) -> bool:
    """Tinh lai + ghi enrollment_status cho 1 CRM Student. Tra ve True neu co ghi.

    Dung cho cac diem goi NGOAI luong sync_linked_crm_student_from_lead:
    xoa Lead, doi linked_student sang HS khac, va sua tay bang `bench execute`.
    Ghi bang frappe.db.set_value (khong chay hook Document, khong doi `modified`).

    Khong raise — loi chi log, de tranh chan luong xoa/merge Lead.
    """
    try:
        if not crm_student_name or not frappe.db.exists("CRM Student", crm_student_name):
            return False

        new_status = compute_enrollment_status(crm_student_name)
        cur = str(
            frappe.db.get_value("CRM Student", crm_student_name, "enrollment_status") or ""
        ).strip()
        if new_status == cur:
            return False

        frappe.db.set_value(
            "CRM Student",
            crm_student_name,
            "enrollment_status",
            new_status,
            update_modified=False,
        )
        return True
    except Exception as e:
        frappe.log_error(
            f"Loi tinh enrollment_status cho student {crm_student_name}: {str(e)}"
        )
        return False


def _should_recompute_enrollment_status(lead_doc, student) -> bool:
    """Gate cho aggregate query.

    sync_linked_crm_student_from_lead chay o MOI CRM Lead.on_update nen khong duoc
    them query vo dieu kien. Chi tinh lai khi thuc su co the doi ket qua.
    """
    # Chua co gia tri -> luon tinh (tu heal du lieu cu / HS moi duoc lien ket)
    if not str(getattr(student, "enrollment_status", None) or "").strip():
        return True
    # after_insert: chua co _doc_before_save
    if not lead_doc.get_doc_before_save():
        return True
    return bool(
        lead_doc.has_value_changed("step") or lead_doc.has_value_changed("linked_student")
    )


def sync_linked_crm_student_from_lead(lead_doc) -> None:
    """
    Cap nhat CRM Student neu Lead co linked_student va ton tai Student tuong ung.
    Khong raise neu khong lien ket — chi return som.
    Raise neu Student.save loi (rollback transaction Lead).
    """
    sid = getattr(lead_doc, "linked_student", None)
    if not sid:
        return
    sid = str(sid).strip()
    if not sid or not frappe.db.exists("CRM Student", sid):
        return

    student = frappe.get_doc("CRM Student", sid)
    changed = False

    ln = str(getattr(lead_doc, "student_name", None) or "").strip()
    if ln and ln != str(student.student_name or "").strip():
        student.student_name = ln
        changed = True

    code = str(getattr(lead_doc, "student_code", None) or "").strip()
    if code and code != str(student.student_code or "").strip():
        student.student_code = code
        changed = True

    dob_str = _lead_student_dob_to_iso(lead_doc)
    if dob_str and dob_str != str(student.dob or "").strip():
        student.dob = dob_str
        changed = True

    g = _lead_gender_to_student_select(lead_doc)
    if g and g != str(student.gender or "").strip():
        student.gender = g
        changed = True

    pid = str(getattr(lead_doc, "student_personal_id_number", None) or "").strip()
    cur_pid = str(student.personal_id_number or "").strip()
    if pid != cur_pid:
        student.personal_id_number = pid or ""
        changed = True

    cid = str(getattr(lead_doc, "campus_id", None) or "").strip()
    if cid and cid != str(student.campus_id or "").strip():
        student.campus_id = cid
        changed = True

    # Trang thai hoc: tinh tu TAT CA Lead cua student, khong chi lead dang save
    # (1 HS co the bi nhieu Lead tro vao — nghi hoc roi nhap hoc lai).
    # Di chung student.save() ben duoi nen khong them write nao.
    if _should_recompute_enrollment_status(lead_doc, student):
        new_status = compute_enrollment_status(sid)
        if new_status != str(student.enrollment_status or "").strip():
            student.enrollment_status = new_status
            changed = True

    if not changed:
        return

    student.save(ignore_permissions=True)
