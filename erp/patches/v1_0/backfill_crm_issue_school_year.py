# -*- coding: utf-8 -*-
"""Gan school_year_id cho CRM Issue cu theo NGAY TAO. Idempotent.

Truong `school_year_id` moi them vao CRM Issue (form Tao van de bat buoc chon nam hoc,
cot "Hoc sinh lien quan" lay lop theo nam hoc nay). Van de tao truoc do de trong
=> danh sach roi ve nam hoc dang bat, lop hien thi co the sai voi van de cu.

Moc ngay dung de suy ra nam hoc: `occurred_at` (Ngay tiep nhan) — thieu thi lay
DATE(`creation`).

QUAN TRONG — `SIS School Year` co `campus_id`, moi campus mot ban ghi rieng cho
cung mot nien khoa, va autoname la `format:SIS_SCHOOL_YEAR-{#####}` nen truong
Link luu DOCNAME chu khong phai chuoi '2025-2026'. Vi vay phai map theo campus:
  1. Van de co campus_id -> chi khop nam hoc cung campus.
  2. Van de khong co campus_id -> chi gan khi khoang ngay do co DUY NHAT 1 ban ghi
     nam hoc; nhieu campus thi khong doan duoc => bo qua, log de ops xu ly tay.
  3. Ngay roi ngoai moi khoang (vd tao trong he) -> gan nam hoc GAN NHAT tinh theo
     so ngay lech toi [start_date, end_date], van theo dung campus.

Chi ghi len ban ghi dang de TRONG `school_year_id` => chay lai lan 2 la no-op.
"""

import frappe

# Ngay tham chieu: uu tien Ngay tiep nhan, thieu thi ngay tao ban ghi
_ISSUE_DATE_SQL = "COALESCE(i.`occurred_at`, DATE(i.`creation`))"

_EMPTY_YEAR = "IFNULL(TRIM(i.`school_year_id`), '') = ''"


def _log(msg: str) -> None:
    """In ra log migrate — de ops thay ket qua backfill ngay khi chay bench migrate."""
    print(f"[backfill_crm_issue_school_year] {msg}")
    frappe.logger().info(f"[backfill_crm_issue_school_year] {msg}")


def _count_empty() -> int:
    return int(
        frappe.db.sql(f"SELECT COUNT(*) FROM `tabCRM Issue` i WHERE {_EMPTY_YEAR}")[0][0]
    )


def _school_years():
    """SIS School Year — list dict(name, campus_id, start_date, end_date)."""
    return frappe.db.sql(
        """
        SELECT
            y.`name`,
            IFNULL(TRIM(y.`campus_id`), '') AS campus_id,
            y.`start_date`,
            y.`end_date`
        FROM `tabSIS School Year` y
        WHERE y.`start_date` IS NOT NULL AND y.`end_date` IS NOT NULL
        ORDER BY y.`start_date` ASC
        """,
        as_dict=True,
    )


def _assign_in_range(year, campus_condition: str, binds: dict) -> int:
    """Gan nam hoc cho cac van de con trong co ngay nam trong khoang nam hoc do."""
    where = f"""
        {_EMPTY_YEAR}
        AND {_ISSUE_DATE_SQL} BETWEEN %(start)s AND %(end)s
        {campus_condition}
    """
    params = {"start": year["start_date"], "end": year["end_date"], **binds}
    n = int(frappe.db.sql(f"SELECT COUNT(*) FROM `tabCRM Issue` i WHERE {where}", params)[0][0])
    if not n:
        return 0
    frappe.db.sql(
        f"UPDATE `tabCRM Issue` i SET i.`school_year_id` = %(year)s WHERE {where}",
        {"year": year["name"], **params},
    )
    return n


def _nearest_year(issue_date, campus_id, years_by_campus, all_years):
    """Nam hoc gan nhat theo so ngay lech toi [start_date, end_date] — cung campus."""
    candidates = years_by_campus.get(campus_id or "") or []
    if not candidates:
        # Van de khong co campus (hoac campus khong co nam hoc nao): chi doan duoc
        # khi toan he thong chi co mot bo nam hoc cua dung mot campus.
        campuses = {y["campus_id"] for y in all_years}
        if len(campuses) != 1:
            return None
        candidates = all_years

    def distance(y):
        if issue_date < y["start_date"]:
            return (y["start_date"] - issue_date).days
        if issue_date > y["end_date"]:
            return (issue_date - y["end_date"]).days
        return 0

    return min(candidates, key=distance)


def execute():
    if not frappe.db.table_exists("CRM Issue") or not frappe.db.table_exists("SIS School Year"):
        _log("Bo qua — chua co bang CRM Issue / SIS School Year")
        return
    if not frappe.db.has_column("CRM Issue", "school_year_id"):
        _log("Bo qua — CRM Issue chua co cot school_year_id (chay bench migrate truoc)")
        return

    total = _count_empty()
    if not total:
        _log("Khong co van de nao con trong school_year_id — no-op")
        return

    years = _school_years()
    if not years:
        _log(f"DUNG — khong co SIS School Year nao co start_date/end_date. {total} van de giu nguyen.")
        return

    years_by_campus = {}
    for y in years:
        years_by_campus.setdefault(y["campus_id"], []).append(y)
    _log(f"{total} van de can gan nam hoc; co {len(years)} ban ghi nam hoc")

    updated = 0

    # 1. Van de co campus — khop nam hoc cung campus, ngay nam trong khoang
    for campus_id, campus_years in years_by_campus.items():
        if not campus_id:
            continue
        for y in campus_years:
            n = _assign_in_range(y, "AND i.`campus_id` = %(campus)s", {"campus": campus_id})
            if n:
                _log(f"campus {campus_id}: gan {n} van de -> {y['name']} "
                     f"({y['start_date']} .. {y['end_date']})")
                updated += n

    # 2. Van de khong co campus — chi gan khi khoang ngay do co duy nhat 1 nam hoc
    no_campus = "AND IFNULL(TRIM(i.`campus_id`), '') = ''"
    for y in years:
        overlapping = [
            o
            for o in years
            if o["name"] != y["name"]
            and o["start_date"] <= y["end_date"]
            and o["end_date"] >= y["start_date"]
        ]
        if overlapping:
            continue
        n = _assign_in_range(y, no_campus, {})
        if n:
            _log(f"khong co campus: gan {n} van de -> {y['name']}")
            updated += n

    # 3. Con lai (ngay ngoai moi khoang nam hoc, vd tao trong he) -> nam hoc gan nhat
    leftovers = frappe.db.sql(
        f"""
        SELECT i.`name`, IFNULL(TRIM(i.`campus_id`), '') AS campus_id,
               {_ISSUE_DATE_SQL} AS issue_date
        FROM `tabCRM Issue` i
        WHERE {_EMPTY_YEAR}
        """,
        as_dict=True,
    )
    skipped = 0
    for row in leftovers or []:
        issue_date = row.get("issue_date")
        if not issue_date:
            skipped += 1
            continue
        y = _nearest_year(issue_date, row.get("campus_id"), years_by_campus, years)
        if not y:
            skipped += 1
            continue
        frappe.db.set_value(
            "CRM Issue", row["name"], "school_year_id", y["name"], update_modified=False
        )
        updated += 1
    if leftovers:
        _log(
            f"ngoai khoang nam hoc: gan {len(leftovers) - skipped} van de theo nam hoc gan nhat"
            + (f", bo qua {skipped} (khong doan duoc campus / thieu ngay)" if skipped else "")
        )

    frappe.db.commit()
    _log(f"Xong: tong {total} van de, da gan {updated}, con lai {_count_empty()}")
