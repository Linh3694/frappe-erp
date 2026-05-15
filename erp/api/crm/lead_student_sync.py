"""
Dong bo truong hoc sinh tu CRM Lead sang CRM Student.

Quy tac nghiep vu: Sau khi Lead co linked_student (nhap hoc / lien ket),
cac truong ho so hoc sinh co ban tren CRM Lead duoc coi la nguon cap nhat
cho ban ghi CRM Student (man Hoc sinh SIS). Cac thay doi qua CRM, bulk Excel
hoac Parent Portal (ghi Lead) se cap nhat CRM Student tu dong.

Chi dong bo cac cot ton tai tren DocType CRM Student; khong ghi de bang rong
cac truong bat buoc (ten, ma, dob, gender) neu Lead de trong — tranh lam hai du lieu Student.
"""

from __future__ import annotations

from datetime import date

import frappe
from frappe.utils import getdate

from erp.api.crm.enrollment import GENDER_MAP


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

    if not changed:
        return

    student.save(ignore_permissions=True)
