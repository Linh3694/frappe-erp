# -*- coding: utf-8 -*-
"""Chuan hoa Quoc tich CRM ve ten Country chuan (tieng Anh).

Truoc day quoc tich luu lan lon: "Vietnam" / "Viet Nam" / "Việt Nam" / rong / text tu do,
do field hien thi la o text tu do (frontend) va backend bo qua validate Link.
Gom ve ten record `Country` chuan (vd "Vietnam") de dropdown hien thi nhat quan
va loc/thong ke theo quoc gia chinh xac. Ap dung cho:
  - CRM Lead.student_nationality   (Data)
  - CRM Lead.guardian_nationality  (Link -> Country)
  - CRM Guardian.nationality       (Link -> Country)

Cac field deu la Link -> Country, nen gia tri khong nhan dien duoc -> dua ve RONG
(policy da chot: sai thi de rong), tranh LinkValidationError ve sau. Co ghi log
nhung gia tri bi xoa de ra soat.
Idempotent: chay lai khong lam hong gia tri da chuan hoa.
"""

import frappe

from erp.utils.country import to_country_or_blank


def _normalize_column(doctype: str, fieldname: str) -> None:
	if not frappe.db.has_column(doctype, fieldname):
		return

	rows = frappe.db.get_all(doctype, fields=["name", fieldname])
	converted = 0
	blanked = set()

	for row in rows:
		old = (row.get(fieldname) or "").strip()
		if not old:
			continue
		new = to_country_or_blank(old)
		if new == old:
			continue
		frappe.db.set_value(doctype, row["name"], fieldname, new, update_modified=False)
		converted += 1
		if not new:
			blanked.add(old)

	frappe.logger().info(
		f"normalize_crm_nationalities: {doctype}.{fieldname} -> {converted} doi, "
		f"{len(blanked)} gia tri dua ve rong: {sorted(blanked)[:50]}"
	)


def execute():
	_normalize_column("CRM Lead", "student_nationality")
	_normalize_column("CRM Lead", "guardian_nationality")
	_normalize_column("CRM Guardian", "nationality")
	frappe.db.commit()
