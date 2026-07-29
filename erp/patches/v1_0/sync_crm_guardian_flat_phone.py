# -*- coding: utf-8 -*-
"""Dong bo CRM Guardian.phone_number voi row is_primary trong CRM Guardian Phone.

Child table phone_numbers la nguon su that; field phang phone_number chi la ban mirror
de list / filter / dedup doc nhanh ma khong phai join. Cac endpoint thao tac tung so
(add_guardian_phone, remove_guardian_phone, set_guardian_primary_phone) truoc day khong
ghi lai field phang, va deu save voi flags.ignore_validate nen CRMGuardian.validate()
cung bi bo qua — hau qua la field phang dung im o gia tri luc tao guardian trong khi
child table da doi.

Code da duoc sua de sync tu bay gio, nhung ban ghi lech san trong DB thi khong tu khoi.
Patch nay va lai, va chua duoc cho tat ca noi doc field phang cung luc — ke ca cac module
ngoai CRM truy van thang bang raw SQL nen khong the fallback sang child: scholarship,
re_enrollment, feedback, family. Hai cho check trung SDT guardian (add_lead_guardian va
add_guardian_phone trong api/crm/lead.py) cung so tren field phang nay: lech thi so cu da
xoa van chan oan guardian khac dang ky.

Chon gia tri dung bang chinh _derive_primary_phone_from_rows ma runtime dung, thay vi
viet lai luat bang SQL, de patch va code khong the lech ngu nghia (uu tien row is_primary,
khong co row nao danh dau thi lay row idx nho nhat).

Chi dung toi guardian DA co it nhat mot row trong CRM Guardian Phone. Guardian cu chua
migrate (chi co field phang, child rong) khong xuat hien trong vong lap nen giu nguyen —
ghi de se xoa mat so duy nhat cua ho.

Idempotent: chay lai tren du lieu da dong bo khong ghi gi them.
"""

import frappe

from erp.api.erp_sis.guardian import _derive_primary_phone_from_rows


def execute():
    # Doc thang bang raw SQL nhu patch anh em backfill_crm_lead_phone_from_guardian.
    # ORDER BY idx de thu tu row giong het luc runtime doc g_doc.phone_numbers, nho vay
    # nhanh fallback "row dau tien" cua helper cho ra cung ket qua.
    rows = frappe.db.sql(
        """
        SELECT gp.`parent` AS guardian, gp.`phone_number`, gp.`is_primary`
        FROM `tabCRM Guardian Phone` gp
        WHERE gp.`parenttype` = 'CRM Guardian'
        ORDER BY gp.`parent` ASC, gp.`idx` ASC
        """,
        as_dict=True,
    )
    if not rows:
        print("sync_crm_guardian_flat_phone: khong co CRM Guardian Phone nao")
        return

    rows_by_guardian = {}
    for row in rows:
        rows_by_guardian.setdefault(row["guardian"], []).append(row)

    flat_by_guardian = {
        g["name"]: g["phone_number"]
        for g in frappe.get_all("CRM Guardian", fields=["name", "phone_number"])
    }

    fixed = 0
    for guardian, guardian_rows in rows_by_guardian.items():
        # Row mo coi (guardian da bi xoa) thi bo qua.
        if guardian not in flat_by_guardian:
            continue
        correct = _derive_primary_phone_from_rows(guardian_rows) or ""
        if (flat_by_guardian[guardian] or "") == correct:
            continue
        frappe.db.set_value(
            "CRM Guardian", guardian, "phone_number", correct, update_modified=False
        )
        fixed += 1

    frappe.db.commit()

    msg = f"sync_crm_guardian_flat_phone: da dong bo {fixed}/{len(rows_by_guardian)} CRM Guardian"
    frappe.logger().info(msg)
    print(msg)
