# -*- coding: utf-8 -*-
"""Chuan hoa SDT CRM ve dinh dang +84xxxxxxxxx.

Truoc day SDT luu lan lon (0xxxxxxxxx hoac +84...). Doi sang mot chuan duy nhat
+84xxxxxxxxx de dedup (so khop chinh xac trong CRM Lead Phone) va search hoat dong
nhat quan giua ban ghi cu va moi. Ap dung cho:
  - CRM Lead Phone.phone_number (SDT phu huynh / lien he)
  - CRM Referrer.phone        (SDT nguoi gioi thieu)

Idempotent: chay lai khong lam hong gia tri da chuan hoa.
"""

import frappe

from erp.api.crm.utils import normalize_phone_number


def _normalize_column(doctype: str, fieldname: str) -> None:
    if not frappe.db.has_column(doctype, fieldname):
        return
    rows = frappe.db.get_all(doctype, fields=["name", fieldname])
    for row in rows:
        old = (row.get(fieldname) or "").strip()
        if not old:
            continue
        new = normalize_phone_number(old)
        if new and new != old:
            frappe.db.set_value(
                doctype, row["name"], fieldname, new, update_modified=False
            )


def execute():
    _normalize_column("CRM Lead Phone", "phone_number")
    _normalize_column("CRM Referrer", "phone")
    frappe.db.commit()
