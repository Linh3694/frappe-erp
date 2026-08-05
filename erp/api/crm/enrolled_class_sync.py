"""
Dong bo trang thai CRM Lead (buoc Enrolled) khi hoc sinh duoc gan lop Regular
(tu bang SIS Class Student + SIS Class).

Ngoai ra dong bo "Lop dang hoc" (current_grade) tren cac CRM Lead lien ket:
khi hoc sinh da co lop Regular trong SIS, khoi lop that (SIS Education Grade)
duoc ghi nguoc ve field current_grade cua lead (Select: K, 1-12).
"""

import re

import frappe


def _normalize_grade_to_lead_select(grade_code: str | None, grade_title_vn: str | None) -> str | None:
    """
    Chuan hoa khoi lop tu SIS Education Grade ve options Select current_grade
    tren CRM Lead ("K", "1".."12"). Khong map duoc thi tra None (khong ghi de).
    Ho tro cac dinh dang grade_code: "1".."12", "K", "K1".."K12" (ma kieu K10),
    fallback theo title_vn dang "Khối 10".
    """
    for raw in (grade_code, grade_title_vn):
        s = str(raw or "").strip().upper()
        if not s:
            continue
        if s in ("K", "MN"):  # Mau giao / Kindergarten
            return "K"
        # "Khối 10" -> "10"
        if s.startswith("KHỐI"):
            s = s[len("KHỐI"):].strip()
        # "K10" -> "10"
        elif s.startswith("K") and s[1:].strip().isdigit():
            s = s[1:].strip()
        if s.isdigit() and 1 <= int(s) <= 12:
            return str(int(s))
    return None


def _get_current_grade_from_sis(crm_student_name: str) -> str | None:
    """
    Lay khoi lop hien tai cua hoc sinh tu lop Regular trong SIS,
    uu tien nam hoc moi nhat (start_date), sau do ban ghi gan lop moi nhat.
    """
    rows = frappe.db.sql(
        """
        SELECT eg.grade_code, eg.title_vn
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
        LEFT JOIN `tabSIS School Year` sy ON cs.school_year_id = sy.name
        WHERE cs.student_id = %s
          AND (IFNULL(NULLIF(TRIM(c.class_type), ''), 'regular') = 'regular')
        ORDER BY sy.start_date DESC, cs.modified DESC
        LIMIT 1
        """,
        (crm_student_name,),
        as_dict=True,
    )
    if not rows:
        return None
    return _normalize_grade_to_lead_select(rows[0].get("grade_code"), rows[0].get("title_vn"))


def grade_by_student_from_sis(student_ids) -> dict:
    """Ban BULK cua _get_current_grade_from_sis — map crm_student -> khoi lop ("K", "1".."12").

    Cung quy tac chon: lop Regular, uu tien NAM HOC MOI NHAT (start_date), sau do ban ghi
    gan lop moi nhat. Nghia la hoc sinh chua co lop nam nay se tu dong lay lop nam gan
    nhat truoc do — khong can lop cua dung nam hien tai.

    Hoc sinh khong map duoc khoi nao thi KHONG co trong dict tra ve (khong doan bua).
    """
    out: dict = {}
    sids = [s for s in (student_ids or []) if s]
    if not sids:
        return out

    rows = frappe.db.sql(
        """
        SELECT cs.student_id, eg.grade_code, eg.title_vn
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
        LEFT JOIN `tabSIS School Year` sy ON cs.school_year_id = sy.name
        WHERE cs.student_id IN %(sids)s
          AND (IFNULL(NULLIF(TRIM(c.class_type), ''), 'regular') = 'regular')
        ORDER BY sy.start_date DESC, cs.modified DESC
        """,
        {"sids": sids},
        as_dict=True,
    )
    # ORDER BY ... DESC -> cac dong cua moi hoc sinh xep tu lop moi nhat den cu nhat.
    # Lay dong dau tien MAP DUOC khoi, khong dung lai o dong dau: grade_code la du lieu
    # nhap tay nen co the la ma la; bo qua no de lay lop ke tiep van dung hon la coi nhu
    # hoc sinh khong xac dinh duoc khoi (se bi bo sot khoi danh sach).
    for r in rows:
        sid = r.get("student_id")
        if sid in out:
            continue
        grade = _normalize_grade_to_lead_select(r.get("grade_code"), r.get("title_vn"))
        if grade:
            out[sid] = grade
    return out


def sync_current_grade_for_linked_leads(crm_student_name: str) -> None:
    """
    Ghi khoi lop that tu SIS ve field current_grade ("Lop dang hoc")
    cua tat ca CRM Lead co linked_student = hoc sinh nay.
    Chi cap nhat khi map duoc khoi hop le va gia tri thay doi.
    Khong raise — loi chi log, tranh chan luong xep lop / pipeline.
    """
    if not crm_student_name:
        return
    try:
        grade = _get_current_grade_from_sis(crm_student_name)
        if not grade:
            return
        leads = frappe.get_all(
            "CRM Lead",
            filters={"linked_student": crm_student_name},
            fields=["name", "current_grade"],
        )
        for lead in leads:
            if str(lead.current_grade or "").strip() == grade:
                continue
            # db.set_value: tranh chay lai toan bo hook save cua Lead (vong lap sync Lead -> Student)
            frappe.db.set_value("CRM Lead", lead.name, "current_grade", grade)
    except Exception as e:
        frappe.log_error(f"Loi dong bo current_grade tu SIS cho student {crm_student_name}: {str(e)}")


def backfill_current_grade_for_all_linked_leads() -> dict:
    """
    Chay mot lan de dong bo current_grade cho toan bo lead da co linked_student
    (du lieu cu truoc khi co hook sync).
    Chay: bench --site <site> execute erp.api.crm.enrolled_class_sync.backfill_current_grade_for_all_linked_leads
    """
    student_ids = frappe.get_all(
        "CRM Lead",
        filters=[["linked_student", "is", "set"]],
        distinct=True,
        pluck="linked_student",
    )
    for sid in student_ids:
        sync_current_grade_for_linked_leads(sid)
    frappe.db.commit()
    return {"students_processed": len(student_ids)}


def has_regular_class_assignment(crm_student_name: str) -> bool:
    """Tra ve True neu CRM Student da co it nhat mot dong SIS Class Student thuoc lop Regular."""
    if not crm_student_name:
        return False
    r = frappe.db.sql(
        """
        SELECT cs.name
        FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
        WHERE cs.student_id = %s
          AND (IFNULL(NULLIF(TRIM(c.class_type), ''), 'regular') = 'regular')
        LIMIT 1
        """,
        (crm_student_name,),
    )
    return bool(r)


def promote_leads_to_dang_hoc_if_class_assigned(crm_student_name: str) -> None:
    """
    Neu lead dang Enrolled + Cho xep lop va da co lop Regular thi doi sang Dang hoc.
    Ghi nhan CRM Lead Step History (van buoc Enrolled).
    Dong thoi dong bo "Lop dang hoc" (current_grade) cho cac lead lien ket.
    """
    if not crm_student_name:
        return

    # Dong bo current_grade truoc — ap dung cho moi lead lien ket,
    # khong phu thuoc lead co dang o buoc Enrolled/Cho xep lop hay khong.
    sync_current_grade_for_linked_leads(crm_student_name)

    if not has_regular_class_assignment(crm_student_name):
        return

    # Tranh import vong pipeline <-> enrollment
    from erp.api.crm.pipeline import _log_step_change

    leads = frappe.get_all(
        "CRM Lead",
        filters={
            "linked_student": crm_student_name,
            "step": "Enrolled",
            "status": "Cho xep lop",
        },
        pluck="name",
    )
    for lead_name in leads:
        doc = frappe.get_doc("CRM Lead", lead_name)
        old_status = doc.status
        doc.status = "Dang hoc"
        doc.save(ignore_permissions=True)
        _log_step_change(lead_name, "Enrolled", "Enrolled", old_status, doc.status)


def _is_test_student_code(student_code) -> bool:
    """Ma hoc sinh test: WS0 + chu so (vd WS012345). Duoc mien kiem tra xep lop."""
    code = str(student_code or "").strip().upper()
    return bool(re.fullmatch(r"WS0\d+", code))


def can_assign_student_to_class(crm_student_name: str) -> tuple[bool, str]:
    """Kiem tra hoc sinh co duoc XEP LOP MOI khong.

    Dieu kien: CRM Student.enrollment_status == 'Dang hoc' (denormalize tu CRM Lead,
    tinh boi erp.api.crm.lead_student_sync.compute_enrollment_status).
    Day la ALLOWLIST — moi gia tri khac, KE CA rong, deu bi chan. Rong la trang thai
    mac dinh cua HS tao truc tiep qua form Hoc sinh / import Excel (khong co CRM Lead),
    nen dung denylist ('!= Nghi hoc') se de lot toan bo nhom do.

    Doc bang frappe.db.get_value (KHONG qua cache Redis cua batch_get_students)
    de khong bao gio quyet dinh tren gia tri stale.

    Tra ve (True, "") hoac (False, <thong bao tieng Viet cho end user>).

    LUU Y: guard nay chi bao phu cac duong di GOI no. Moi duong ghi
    `tabSIS Class Student` bang raw SQL / frappe.db.set_value se BO QUA guard —
    xem nhanh MOVE tai erp/api/erp_sis/class_student.py (frappe.db.set_value),
    da duoc chan o tang API truoc khi vao nhanh do.
    """
    sid = str(crm_student_name or "").strip()
    if not sid:
        return False, "Thieu ma hoc sinh."

    row = frappe.db.get_value(
        "CRM Student",
        sid,
        ["student_code", "student_name", "enrollment_status"],
        as_dict=True,
    )
    if not row:
        return False, f"Không tìm thấy hồ sơ học sinh {sid}."

    # Bypass cho hoc sinh TEST: student_code dang WS0xxxxx (prefix "WS0" + so).
    # Ho so test khong di qua luong CRM nen enrollment_status luon rong -> bi allowlist
    # chan; cho phep xep lop de QA/demo chay duoc.
    if _is_test_student_code(row.get("student_code")):
        return True, ""

    status = str(row.get("enrollment_status") or "").strip()
    if status == "Dang hoc":
        return True, ""

    who = f"{row.get('student_name') or ''} ({row.get('student_code') or sid})".strip()
    if status == "Nghi hoc":
        return False, (
            f"Học sinh {who} đang ở trạng thái Nghỉ học — không thể xếp lớp mới. "
            f"Nếu học sinh nhập học lại, hãy chuyển hồ sơ CRM về bước Nhập học (Enrolled) trước."
        )
    if status == "Chua nhap hoc":
        return False, (
            f"Học sinh {who} chưa có hồ sơ CRM ở bước Nhập học (Enrolled) — không thể xếp lớp. "
            f"Liên hệ Tuyển sinh để chốt hồ sơ trước khi phân lớp."
        )
    return False, (
        f"Học sinh {who} chưa được liên kết hồ sơ tuyển sinh (CRM Lead) — không thể xếp lớp. "
        f"Liên hệ Tuyển sinh để liên kết hồ sơ."
    )
