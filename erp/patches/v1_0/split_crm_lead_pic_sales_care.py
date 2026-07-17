# -*- coding: utf-8 -*-
"""Tach CRM Lead.pic -> pic_sales + pic_care (G1). Idempotent.

Chay o post_model_sync: doctype da sync nen bang co ca `pic` (du lieu cu) lan
`pic_sales`/`pic_care` (moi, rong).

QUAN TRONG — Frappe KHONG tu drop cot bi bo khoi doctype (chi
`frappe.model.delete_fields(..., delete=1)` moi drop, va no chi duoc goi boi 1 patch
legacy cua frappe). `rename_field` cung KHONG doi ten cot vat ly — no chi
`UPDATE ... SET pic_sales = pic`. Nghia la neu de nguyen, cot `pic` cu se nam lai
nhu cot mo coi con du lieu dong bang => moi SQL raw con sot `l.pic` van CHAY, tra
so lieu cu ma khong bao loi. Do la kieu hong nguy hiem nhat cho bao cao KPI.

=> Buoc 4 doi ten cot cu thanh `pic_legacy_backup`: SQL con sot se loi to
   (Unknown column 'pic') thay vi am tham sai, va du lieu cu van con de doi chieu.
"""

import frappe
from frappe.model.utils.rename_field import rename_field

# Role doi cham soc — khop _CARE_CANDIDATE_ROLES trong erp/api/crm/sales_care_team.py
_CARE_ROLES = ("SIS Sales Care", "SIS Sales Care Admin")
# Buoc da ban giao cho doi Care (quyet dinh #2: Care chi tu Enrolled tro di)
_HANDED_OVER_STEPS = ("Enrolled", "Nghi hoc")


def _log(msg: str) -> None:
    """In ra log migrate — de ops thay ket qua backfill ngay khi chay bench migrate."""
    print(f"[split_crm_lead_pic_sales_care] {msg}")
    frappe.logger().info(f"[split_crm_lead_pic_sales_care] {msg}")


def _add_index_if_missing(doctype: str, index_name: str, columns_sql: str) -> None:
    """Them index neu chua co. Idempotent.

    LUU Y: `frappe.db.table_exists()` TU THEM tien to 'tab' — phai truyen 'CRM Lead',
    KHONG phai 'tabCRM Lead'. Patch `add_crm_report_indexes` truyen sai ('tabCRM Lead'
    -> kiem 'tabtabCRM Lead' -> luon False) nen no la NO-OP: khong index nao duoc tao.
    """
    if not frappe.db.table_exists(doctype):
        return
    table = f"tab{doctype}"
    if frappe.db.sql(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", (index_name,)):
        return
    frappe.db.sql(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns_sql})")


def _care_user_names():
    """User co role doi Care."""
    rows = frappe.db.sql(
        """
        SELECT DISTINCT r.parent
        FROM `tabHas Role` r
        WHERE r.parenttype = 'User' AND r.role IN %(roles)s
        """,
        {"roles": _CARE_ROLES},
    )
    return [r[0] for r in rows] if rows else []


def _column_type(table: str, column: str):
    rows = frappe.db.sql(
        """
        SELECT COLUMN_TYPE FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    return rows[0][0] if rows else None


def execute():
    if not frappe.db.table_exists("CRM Lead"):
        return

    has_legacy_pic = frappe.db.has_column("CRM Lead", "pic")

    # 1. pic -> pic_sales: copy du lieu + cap nhat Report / property setter / user settings.
    if has_legacy_pic and frappe.db.has_column("CRM Lead", "pic_sales"):
        rename_field("CRM Lead", "pic", "pic_sales")

    care_users = _care_user_names()

    # CANH BAO VAN HANH: toan bo viec tach Sales/Care duoi day dua vao `tabHas Role`
    # TAI THOI DIEM CHAY. Neu luc `bench migrate` chua ai duoc gan role Care thi
    # care_users = [] => backfill bi BO QUA, patch van duoc ghi "da chay" (tabPatch Log)
    # => KHONG tu chay lai o lan migrate sau. Log ro de ops phat hien va chay tay:
    #    bench execute erp.patches.v1_0.split_crm_lead_pic_sales_care.execute
    # (Patch idempotent — chay lai an toan.)
    _log(f"tim thay {len(care_users)} user co role Care {_CARE_ROLES}")
    if not care_users:
        _log(
            "!! CANH BAO: khong co user nao mang role Care -> BO QUA backfill pic_care "
            "va team='care'. Gan role Care cho nhan su roi chay tay lai patch nay."
        )

    # 2. Backfill pic_care — chi ho so DA ban giao va PIC hien tai co role Care.
    #    Quyet dinh #4: khong truy hoi tabVersion => lich su pic_sales cu coi nhu mat.
    #    Heuristic theo role KHONG chinh xac tuyet doi (nguoi Care van co the hop le
    #    giu pic_sales) — da chap nhan trong plan.
    if care_users and frappe.db.has_column("CRM Lead", "pic_care"):
        binds = {"steps": _HANDED_OVER_STEPS, "users": care_users}
        # `SET pic_care = pic_sales` dung TRUOC `SET pic_sales = NULL`: MySQL/MariaDB
        # danh gia SET trai-sang-phai nen pic_care nhan dung gia tri goc.
        cond = (
            "`step` IN %(steps)s "
            "AND IFNULL(`pic_sales`, '') != '' "
            "AND `pic_sales` IN %(users)s"
        )
        n = frappe.db.sql(f"SELECT COUNT(*) FROM `tabCRM Lead` WHERE {cond}", binds)[0][0]
        frappe.db.sql(
            f"UPDATE `tabCRM Lead` SET `pic_care` = `pic_sales`, `pic_sales` = NULL WHERE {cond}",
            binds,
        )
        _log(f"backfill pic_care: {n} ho so (pic_sales lich su -> NULL, chap nhan theo quyet dinh #4)")

    # 3. Backfill `team` cho CRM Admission Target Member — suy tu role cua chinh user do.
    #    Khong can set 'sales' cho dong cu: field `team` co "default": "sales" nen
    #    ADD COLUMN luc sync da dien san 'sales' cho toan bo dong hien huu.
    if care_users and frappe.db.table_exists("CRM Admission Target Member") and frappe.db.has_column(
        "CRM Admission Target Member", "team"
    ):
        n = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabCRM Admission Target Member` WHERE `pic` IN %(users)s",
            {"users": care_users},
        )[0][0]
        frappe.db.sql(
            "UPDATE `tabCRM Admission Target Member` SET `team` = 'care' "
            "WHERE `pic` IN %(users)s",
            {"users": care_users},
        )
        _log(f"backfill team=care: {n} dong target")

    # 4. Doi ten cot `pic` cu -> `pic_legacy_backup` (xem docstring dau file).
    #    Chi lam SAU khi da copy sang pic_sales o buoc 1.
    if has_legacy_pic and frappe.db.has_column("CRM Lead", "pic_sales"):
        if not frappe.db.has_column("CRM Lead", "pic_legacy_backup"):
            col_type = _column_type("tabCRM Lead", "pic") or "varchar(140)"
            frappe.db.commit()  # mariadb commit ngam truoc DDL — lam ro rang
            frappe.db.sql(
                f"ALTER TABLE `tabCRM Lead` "
                f"CHANGE COLUMN `pic` `pic_legacy_backup` {col_type}"
            )

    # 5. Index bao cao. Tao lai ca cac index ma `add_crm_report_indexes` dinh tao nhung
    #    khong tao duoc (no-op, xem docstring `_add_index_if_missing`), doi `pic` -> `pic_sales`.
    _add_index_if_missing(
        "CRM Lead",
        "crm_lead_report_creation",
        "`creation`, `campus_id`, `pic_sales`, `target_academic_year`, `target_grade`",
    )
    _add_index_if_missing("CRM Lead", "crm_lead_report_step_status", "`step`, `status`")
    _add_index_if_missing("CRM Lead", "crm_lead_report_enrollment_date", "`enrollment_date`")
    # KPI theo doi (1.1: team chon cot de group)
    _add_index_if_missing(
        "CRM Lead",
        "crm_lead_kpi_sales",
        "`target_academic_year`, `campus_id`, `pic_sales`, `step`",
    )
    _add_index_if_missing(
        "CRM Lead",
        "crm_lead_kpi_care",
        "`target_academic_year`, `campus_id`, `pic_care`, `step`",
    )
    _add_index_if_missing(
        "CRM Lead Step History",
        "crm_lead_hist_report_event",
        "`changed_at`, `new_step`, `new_status`",
    )
    _add_index_if_missing(
        "CRM Lead Step History", "crm_lead_hist_report_lead", "`lead`, `new_step`"
    )
