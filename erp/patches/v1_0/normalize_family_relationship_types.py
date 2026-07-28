# -*- coding: utf-8 -*-
"""Chuan hoa quan he gia dinh ve ma EN lowercase.

Truoc day relationship_type la Data tu do, moi luong ghi dung mot bo tu vung rieng:
  - enrollment:   "Father" / "Mother" / "Guardian"
  - import Excel: "dad" / "mom" / "grandparent" / "uncle_aunt" / "foster_parent"
  - migration:    "Bo" / "Me" / "Nguoi giam ho" / "Ong" / "Ba"
  - nguoi dung go tay: "Bo" / "Me" / "Nguoi giam ho" / "Ba noi"...
Hau qua: cung mot phu huynh hien "Mother" o Ho so hoc sinh nhung "Me" o ho so CRM.

Patch gom tat ca ve ma chuan (xem erp/utils/relationship_types.py). Ap dung cho:
  - CRM Family Relationship.relationship_type  (child dung o 3 parent:
    CRM Family.relationships / CRM Student.family_relationships /
    CRM Guardian.student_relationships -> chay theo doctype la phu ca 3)
  - CRM Lead Guardian.relationship_type
  - CRM Lead Sibling.relationship_type
  - CRM Lead.relationship

Gia tri KHONG nhan dien duoc -> GIU NGUYEN (khong ep ve "other" de khoi mat du lieu),
va duoc thong ke lai de doi van hanh ra soat tay.
Idempotent: normalize(ma chuan) = chinh no, chay lai khong doi ket qua.
"""

import frappe

from erp.utils.relationship_types import is_known_code, normalize


def _normalize_column(doctype: str, fieldname: str) -> dict:
	if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, fieldname):
		frappe.logger().info(
			f"normalize_family_relationship_types: bo qua {doctype}.{fieldname} (khong ton tai)"
		)
		return {}

	rows = frappe.db.get_all(doctype, fields=["name", fieldname])
	converted = 0
	unknown = {}

	for row in rows:
		old = (row.get(fieldname) or "").strip()
		if not old:
			continue
		new = normalize(old)
		if not is_known_code(new):
			# Khong map duoc -> giu nguyen, chi ghi nhan de bao cao
			unknown[old] = unknown.get(old, 0) + 1
			continue
		if new == old:
			continue
		frappe.db.set_value(doctype, row["name"], fieldname, new, update_modified=False)
		converted += 1

	frappe.logger().info(
		f"normalize_family_relationship_types: {doctype}.{fieldname} -> {converted} doi, "
		f"{len(unknown)} gia tri ngoai danh muc"
	)
	return unknown


def execute():
	targets = (
		("CRM Family Relationship", "relationship_type"),
		("CRM Lead Guardian", "relationship_type"),
		("CRM Lead Sibling", "relationship_type"),
		("CRM Lead", "relationship"),
	)

	report = []
	for doctype, fieldname in targets:
		unknown = _normalize_column(doctype, fieldname)
		for value, count in sorted(unknown.items(), key=lambda item: -item[1]):
			report.append(f"{doctype}.{fieldname}: {value!r} x{count}")

	frappe.db.commit()

	if report:
		# Title <= 140 ky tu (gioi han CharacterLength cua Error Log)
		frappe.log_error(
			title="Quan he ngoai danh muc sau chuan hoa",
			message=(
				"Cac gia tri relationship_type khong map duoc ve danh muc chuan da "
				"GIU NGUYEN, can doi van hanh sua tay:\n\n" + "\n".join(report)
			),
		)
