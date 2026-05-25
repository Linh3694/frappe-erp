# Copyright (c) 2026, Wellspring International School and contributors
# Backfill student_code / employee_code cho phiếu mượn thư viện cũ

import frappe


def execute():
	if not frappe.db.exists("DocType", "SIS Library Transaction"):
		return

	from erp.api.erp_sis.library import TRANSACTION_DTYPE, _get_user_employee_code

	rows = frappe.get_all(
		TRANSACTION_DTYPE,
		fields=["name", "borrower_id", "borrower_type", "student_code", "employee_code"],
	)

	updated = 0
	for row in rows:
		updates = {}
		if row.borrower_type == "student" and not (row.student_code or "").strip():
			code = frappe.db.get_value("CRM Student", row.borrower_id, "student_code")
			if code:
				updates["student_code"] = code
		elif row.borrower_type == "staff" and not (row.employee_code or "").strip():
			user_id = row.borrower_id
			if frappe.db.exists("SIS Teacher", row.borrower_id):
				user_id = frappe.db.get_value("SIS Teacher", row.borrower_id, "user_id") or user_id
			code = _get_user_employee_code(user_id)
			if code:
				updates["employee_code"] = code

		if updates:
			frappe.db.set_value(TRANSACTION_DTYPE, row.name, updates, update_modified=False)
			updated += 1

	frappe.db.commit()
	frappe.logger().info(
		f"backfill_library_transaction_borrower_codes: updated {updated} transactions"
	)
