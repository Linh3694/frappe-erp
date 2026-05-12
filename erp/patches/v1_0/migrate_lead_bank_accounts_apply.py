# -*- coding: utf-8 -*-
"""
CRM Lead — Nem du lieu tu bang backup vao child `bank_accounts`.

Chay trong [post_model_sync]: sau khi bang con `CRM Lead Bank Account` da ton tai.
"""

import frappe


def execute():
	if not frappe.db.has_table("_erp_crm_lead_bank_flat_backup"):
		return

	rows = frappe.db.sql(
		"""
		SELECT lead, student_account_holder_relationship, student_bank_account_name,
			   student_bank_account_number, student_bank_name, student_bank_branch
		FROM `_erp_crm_lead_bank_flat_backup`
		""",
		as_dict=True,
	)

	for row in rows or []:
		lead_name = (row.get("lead") or "").strip()
		if not lead_name or not frappe.db.exists("CRM Lead", lead_name):
			continue

		doc = frappe.get_doc("CRM Lead", lead_name)
		if getattr(doc, "bank_accounts", None):
			has_data = False
			for ba in doc.bank_accounts:
				if (
					(ba.account_holder_relationship or "").strip()
					or (ba.bank_account_name or "").strip()
					or (ba.bank_account_number or "").strip()
					or (ba.bank_name or "").strip()
					or (ba.bank_branch or "").strip()
				):
					has_data = True
					break
			if has_data:
				continue

		doc.append(
			"bank_accounts",
			{
				"account_holder_relationship": (row.get("student_account_holder_relationship") or "").strip(),
				"bank_account_name": (row.get("student_bank_account_name") or "").strip(),
				"bank_account_number": (row.get("student_bank_account_number") or "").strip(),
				"bank_name": (row.get("student_bank_name") or "").strip(),
				"bank_branch": (row.get("student_bank_branch") or "").strip(),
			},
		)
		doc.flags.ignore_permissions = True
		doc.save()

	frappe.db.sql_ddl("DROP TABLE IF EXISTS `_erp_crm_lead_bank_flat_backup`")
	frappe.db.commit()
