# -*- coding: utf-8 -*-
"""Gan target_academic_year = nam hoc 2025-2026 cho ho so migrate. Idempotent.

Ho so migrate = hoc sinh cu duoc nap thang vao buoc cuoi, chua tung di qua pheu.
Nhan dien dong thoi 3 dau hieu (khop `_exclude_migrated_leads_sql` trong
erp/api/crm/reports.py — sua o day thi phai sua ca ben do):
  1. step IN ('Enrolled', 'Nghi hoc')
  2. enrollment_date IS NULL   — chi pipeline.py set khi chot that
  3. khong co dong CRM Lead Step History nao

Ho so chot qua pipeline luon co du (2) va (3) nen khong bao gio bi dung toi;
create_lead chi tao duoc o Verify/Lead nen cung nam ngoai. Chi `bulk_import_leads`
(erp/api/crm/import_export.py, cho `doc.step = target_step`) moi tao ra hinh dang nay
— va no KHONG map `target_academic_year`, nen dam ho so nay dang de trong truong do.

QUAN TRONG — `SIS School Year` co `campus_id` va autoname la
`format:SIS_SCHOOL_YEAR-{#####}`. Nghia la:
  - `target_academic_year` luu DOCNAME (vd 'SIS_SCHOOL_YEAR-00007'), KHONG phai chuoi
    '2025-2026'. Gan thang chuoi la hong Link, bao cao loc theo nam se ra 0.
  - Moi campus co mot ban ghi 2025-2026 RIENG. Phai map theo tung campus, khong the
    gan mot gia tri cung cho tat ca.

Chi ghi len ho so dang de TRONG `target_academic_year` — khong de len gia tri co san.
Nho do chay lai lan 2 la no-op.
"""

import frappe

# Nam hoc dich — khop theo title_vn/title_en cua SIS School Year
_TARGET_YEAR_LABEL = "2025-2026"

_MIGRATED_STEPS = ("Enrolled", "Nghi hoc")

# Loc phu: ho so co campus / khong co campus
_HAS_CAMPUS = "AND l.`campus_id` = %(campus)s"
_NO_CAMPUS = "AND IFNULL(TRIM(l.`campus_id`), '') = ''"


def _log(msg: str) -> None:
    """In ra log migrate — de ops thay ket qua backfill ngay khi chay bench migrate."""
    print(f"[set_target_year_for_migrated_leads] {msg}")
    frappe.logger().info(f"[set_target_year_for_migrated_leads] {msg}")


def _migrated_where(extra: str = "") -> str:
    """Dieu kien nhan dien ho so migrate con de trong nam hoc muc tieu."""
    return f"""
        IFNULL(TRIM(l.`target_academic_year`), '') = ''
        AND l.`step` IN {_MIGRATED_STEPS}
        AND l.`enrollment_date` IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM `tabCRM Lead Step History` h WHERE h.`lead` = l.`name`
        )
        {extra}
    """


def _count_migrated(extra: str = "", binds=None) -> int:
    return int(
        frappe.db.sql(
            f"SELECT COUNT(*) FROM `tabCRM Lead` l WHERE {_migrated_where(extra)}",
            binds or {},
        )[0][0]
    )


def _assign(year_name: str, extra: str, binds: dict) -> None:
    frappe.db.sql(
        f"""
        UPDATE `tabCRM Lead` l
        SET l.`target_academic_year` = %(year)s
        WHERE {_migrated_where(extra)}
        """,
        {"year": year_name, **binds},
    )


def _school_years_2025_2026():
    """Ban ghi SIS School Year 2025-2026 — list dict(name, campus_id)."""
    return frappe.db.sql(
        """
        SELECT y.`name`, IFNULL(TRIM(y.`campus_id`), '') AS campus_id
        FROM `tabSIS School Year` y
        WHERE y.`title_vn` LIKE %(lbl)s OR y.`title_en` LIKE %(lbl)s
        """,
        {"lbl": f"%{_TARGET_YEAR_LABEL}%"},
        as_dict=True,
    )


def execute():
    if not frappe.db.table_exists("CRM Lead"):
        _log("Bo qua — chua co bang CRM Lead")
        return

    total = _count_migrated()
    if not total:
        _log("Khong co ho so migrate nao con trong target_academic_year — no-op")
        return

    years = _school_years_2025_2026()
    if not years:
        _log(
            f"DUNG — khong tim thay SIS School Year nao co title chua "
            f"'{_TARGET_YEAR_LABEL}'. {total} ho so migrate giu nguyen. "
            f"Tao nam hoc roi chay lai patch."
        )
        return

    year_by_campus = {y["campus_id"]: y["name"] for y in years if y["campus_id"]}
    _log(f"Tim thay {len(years)} ban ghi nam hoc {_TARGET_YEAR_LABEL}: {year_by_campus}")

    updated = 0

    # 1. Ho so co campus — gan theo dung nam hoc cua campus do
    for campus_id, year_name in year_by_campus.items():
        binds = {"campus": campus_id}
        n = _count_migrated(_HAS_CAMPUS, binds)
        if not n:
            continue
        _assign(year_name, _HAS_CAMPUS, binds)
        _log(f"campus {campus_id}: gan {n} ho so -> {year_name}")
        updated += n

    # 2. Ho so khong co campus — chi gan duoc khi 2025-2026 co DUY NHAT 1 ban ghi;
    #    nhieu hon thi khong doan duoc campus nao => bo qua, de ops xu ly tay.
    orphan = _count_migrated(_NO_CAMPUS)
    if orphan:
        if len(years) == 1:
            _assign(years[0]["name"], _NO_CAMPUS, {})
            _log(f"gan {orphan} ho so khong co campus -> {years[0]['name']} (chi co 1 nam hoc)")
            updated += orphan
        else:
            _log(
                f"CANH BAO — {orphan} ho so migrate khong co campus_id, ma co {len(years)} "
                f"ban ghi nam hoc {_TARGET_YEAR_LABEL}. Khong doan duoc campus => BO QUA. "
                f"Ops can dien campus_id roi chay lai patch."
            )

    frappe.db.commit()
    _log(f"Xong: tong {total} ho so migrate, da gan {updated}, con lai {_count_migrated()}")
