# -*- coding: utf-8 -*-
"""Backfill CRM Student.enrollment_status tu CRM Lead + SIS Class Student. Idempotent.

Bo sung cot trang thai hoc cho CRM Student (student master, Parent Portal cung dung).
Truoc day trang thai nghi hoc chi ton tai tren CRM Lead.step nen SIS khong biet ai da
nghi — HS da nghi van xep lop moi duoc.

Thu tu uu tien PHAI khop nguyen ban voi
`erp.api.crm.lead_student_sync.compute_enrollment_status` — sua o day thi phai sua ca
ben do (va nguoc lai). Nhom (c) la grandfather theo quyet dinh nghiep vu: HS dang co
lop that thi coi la dang hoc, du ho so CRM chua/khong len Enrolled, de khong chan oan
du lieu dang chay.

CHI ghi len ban ghi dang de TRONG enrollment_status -> chay lai lan 2 la no-op, va
KHONG ghi de gia tri runtime da tinh dung.
"""

import frappe

_STUDYING = "Dang hoc"
_WITHDRAWN = "Nghi hoc"
_NOT_YET = "Chua nhap hoc"

# Chuan hoa class_type — COPY nguyen ban tu
# erp/api/crm/enrolled_class_sync.py::has_regular_class_assignment
_HAS_REGULAR_CLASS = """
    EXISTS (
        SELECT 1 FROM `tabSIS Class Student` cs
        INNER JOIN `tabSIS Class` c ON c.`name` = cs.`class_id`
        WHERE cs.`student_id` = s.`name`
          AND IFNULL(NULLIF(TRIM(c.`class_type`), ''), 'regular') = 'regular'
    )
"""
_HAS_LEAD = "EXISTS (SELECT 1 FROM `tabCRM Lead` l WHERE l.`linked_student` = s.`name`)"
_HAS_ENROLLED_LEAD = (
    "EXISTS (SELECT 1 FROM `tabCRM Lead` l "
    "WHERE l.`linked_student` = s.`name` AND l.`step` = 'Enrolled')"
)
# Co Lead va KHONG Lead nao khac 'Nghi hoc' => tat ca Lead deu 'Nghi hoc'
_ALL_LEADS_WITHDRAWN = (
    f"{_HAS_LEAD} AND NOT EXISTS (SELECT 1 FROM `tabCRM Lead` l "
    "WHERE l.`linked_student` = s.`name` AND l.`step` <> 'Nghi hoc')"
)
_EMPTY = "IFNULL(TRIM(s.`enrollment_status`), '') = ''"


def _log(msg: str) -> None:
    """In ra log migrate — de ops thay ket qua backfill ngay khi chay bench migrate."""
    print(f"[backfill_crm_student_enrollment_status] {msg}")
    frappe.logger().info(f"[backfill_crm_student_enrollment_status] {msg}")


def _add_index_if_missing(doctype: str, index_name: str, columns_sql: str) -> None:
    """Them index neu chua co. Idempotent.

    LUU Y: `frappe.db.table_exists()` TU THEM tien to 'tab' — phai truyen 'CRM Lead',
    KHONG phai 'tabCRM Lead'. (Patch `add_crm_report_indexes` va
    `backfill_class_log_submitted` truyen sai nen la NO-OP — dung copy 2 file do.)
    """
    if not frappe.db.table_exists(doctype):
        return
    table = f"tab{doctype}"
    if frappe.db.sql(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", (index_name,)):
        return
    frappe.db.sql(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns_sql})")
    _log(f"da tao index {index_name} tren {table}")


def _count(where_sql: str) -> int:
    return int(
        frappe.db.sql(f"SELECT COUNT(*) FROM `tabCRM Student` s WHERE {where_sql}")[0][0]
    )


def _assign(status: str, where_sql: str) -> int:
    """Gan status cho cac CRM Student thoa where_sql VA dang de trong. Tra ve so dong."""
    n = _count(f"{_EMPTY} AND ({where_sql})")
    if not n:
        return 0
    frappe.db.sql(
        f"""
        UPDATE `tabCRM Student` s
        SET s.`enrollment_status` = %(st)s
        WHERE {_EMPTY} AND ({where_sql})
        """,
        {"st": status},
    )
    return n


def execute():
    for dt in ("CRM Student", "CRM Lead", "SIS Class Student", "SIS Class"):
        if not frappe.db.table_exists(dt):
            _log(f"Bo qua — chua co bang {dt}")
            return

    # Cot phai duoc schema sync tao truoc (patch nay o post_model_sync nen da co).
    if not frappe.db.has_column("CRM Student", "enrollment_status"):
        _log("Bo qua — cot enrollment_status chua ton tai (chay lai sau khi sync DocType)")
        return

    # 1) Index TRUOC backfill: cac correlated subquery ben duoi phu thuoc no.
    #    (linked_student, step) composite phuc vu ca compute_enrollment_status luc runtime,
    #    chay o moi CRM Lead.on_update — thieu index la full scan tabCRM Lead moi lan save.
    _add_index_if_missing(
        "CRM Lead", "crm_lead_linked_student_step", "`linked_student`, `step`"
    )
    #    SIS Class Student chi co index tren class_id -> student_id dang full-scan;
    #    index nay tang toc ca has_regular_class_assignment va
    #    validate_no_duplicate_regular_classes dang chay san.
    _add_index_if_missing(
        "SIS Class Student",
        "sis_class_student_student_year",
        "`student_id`, `school_year_id`",
    )
    #    get_lead enrich trang thai tai ghi danh join theo student_id — chua co index nao.
    if frappe.db.table_exists("SIS Re-enrollment"):
        _add_index_if_missing("SIS Re-enrollment", "sis_reenroll_student", "`student_id`")
    frappe.db.commit()

    total_empty = _count(_EMPTY)
    if not total_empty:
        _log("Khong con CRM Student nao trong enrollment_status — no-op")
        return
    _log(f"Bat dau: {total_empty} CRM Student dang trong enrollment_status")

    # 2) Backfill theo DUNG thu tu uu tien cua compute_enrollment_status.
    #    Guard `_EMPTY` trong tung UPDATE dam bao nhom truoc thang nhom sau.
    n_a = _assign(_STUDYING, _HAS_ENROLLED_LEAD)
    _log(f"(a) co Lead Enrolled -> {_STUDYING}: {n_a}")

    n_b1 = _assign(_WITHDRAWN, _ALL_LEADS_WITHDRAWN)
    _log(f"(b1) co Lead va TAT CA o Nghi hoc -> {_WITHDRAWN}: {n_b1}")

    # (c) GRANDFATHER — bao gom CA HAI nhom:
    #     - HS orphan (khong co Lead nao) nhung da co lop regular
    #     - HS co Lead con trong pheu (QLead...) nhung da co lop that
    n_c = _assign(_STUDYING, _HAS_REGULAR_CLASS)
    _log(f"(c) grandfather: da co lop Regular -> {_STUDYING}: {n_c}")

    n_b2 = _assign(_NOT_YET, _HAS_LEAD)
    _log(f"(b2) co Lead, chua Lead nao Enrolled -> {_NOT_YET}: {n_b2}")

    frappe.db.commit()

    # (d) con lai: khong Lead, khong lop -> de RONG (se bi chan xep lop, dung y do)
    remain = _count(_EMPTY)
    _log(
        f"Xong: {total_empty} ban ghi -> a={n_a}, b1={n_b1}, c={n_c}, b2={n_b2}; "
        f"con {remain} de rong (khong Lead, khong lop — se bi chan xep lop)"
    )
