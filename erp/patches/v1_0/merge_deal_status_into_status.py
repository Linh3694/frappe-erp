# -*- coding: utf-8 -*-
"""Gop deal_status (Thoa thuan) vao status chinh + chuan hoa code trang thai QLead.

Quy tac (chot voi user):
  - CHI ho so `status='Thoa thuan'` moi lay `deal_status`:
      + co deal_status (Dat cho/Dat coc/Dong phi/Hoan phi/Bao luu/Chuyen) -> status = deal_status
      + deal_status = 'Tu choi'                                           -> status = 'Tu choi'
      + deal_status rong                                                   -> status = 'Can nhac'
  - MOI `status='Lost'` (moi buoc) -> 'Tu choi'
  - Xoa `deal_status` toan bo sau khi gop.

Ho so co deal_status da chot ('Dong phi'/'Dat coc') nhung status != 'Thoa thuan'
se MAT tin hieu deal (theo quy tac tren) -> log_error de review truoc.

Idempotent: chay lai khong lam hong (khong con 'Thoa thuan'/'Lost'/deal_status).
Chay o [post_model_sync] (sau khi crm_lead.json them cac option moi).
"""

import frappe

_DEAL_VALUES = ("Dat cho", "Dat coc", "Dong phi", "Hoan phi", "Bao luu/Chuyen", "Tu choi")


def execute():
    if not frappe.db.has_column("CRM Lead", "deal_status"):
        return

    # 1) Pre-audit: deal da chot nhung status != Thoa thuan -> se mat tin hieu deal
    edge = frappe.db.sql(
        """
        SELECT name, step, status, deal_status
        FROM `tabCRM Lead`
        WHERE IFNULL(`deal_status`, '') IN ('Dong phi', 'Dat coc')
          AND IFNULL(`status`, '') != 'Thoa thuan'
        """,
        as_dict=True,
    )
    if edge:
        frappe.log_error(
            title="merge_deal_status: edge cases (deal da chot nhung status != Thoa thuan)",
            message=f"{len(edge)} ho so se mat tin hieu deal:\n"
            + "\n".join(
                f"{r['name']} step={r['step']} status={r['status']} deal={r['deal_status']}"
                for r in edge[:500]
            ),
        )

    # 2) status='Thoa thuan': co deal -> deal (Tu choi giu Tu choi); rong -> Can nhac
    for r in frappe.db.get_all(
        "CRM Lead", filters={"status": "Thoa thuan"}, fields=["name", "deal_status"]
    ):
        deal = (r.get("deal_status") or "").strip()
        new_status = deal if deal in _DEAL_VALUES else "Can nhac"
        frappe.db.set_value(
            "CRM Lead", r["name"], "status", new_status, update_modified=False
        )

    # 3) Lost -> Tu choi (toan he thong)
    frappe.db.sql("UPDATE `tabCRM Lead` SET `status` = 'Tu choi' WHERE `status` = 'Lost'")

    # 4) Xoa deal_status (da gop hoac bo theo quy tac)
    frappe.db.sql(
        "UPDATE `tabCRM Lead` SET `deal_status` = '' WHERE IFNULL(`deal_status`, '') != ''"
    )

    frappe.db.commit()
