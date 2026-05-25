# Copyright (c) 2026, Wellspring International School and contributors
# Migration: tạo phiếu mượn retroactive cho bản sao đang mượn không có transaction item

import frappe
from frappe.utils import getdate, nowdate
from datetime import timedelta


def execute():
	if not frappe.db.exists("DocType", "SIS Library Transaction"):
		return

	from erp.api.erp_sis.library import (
		COPY_DTYPE,
		TRANSACTION_DTYPE,
		TRANSACTION_ITEM_DTYPE,
		_get_library_settings,
	)

	settings = _get_library_settings()
	loan_days = int(settings.get("default_loan_days") or 20)

	copies = frappe.get_all(
		COPY_DTYPE,
		filters={"status": ["in", ["borrowed", "overdue"]]},
		fields=[
			"name",
			"generated_code",
			"borrower_id",
			"borrower_name",
			"borrowed_date",
			"status",
			"overdue_days",
		],
	)

	created = 0
	for copy in copies:
		code = copy.generated_code
		if not code or not copy.borrower_id:
			continue

		open_item = frappe.db.sql(
			"""
			SELECT name FROM `tabSIS Library Transaction Item`
			WHERE book_copy_id = %s AND status IN ('borrowing', 'overdue')
			LIMIT 1
			""",
			(code,),
		)
		if open_item:
			continue

		borrow_date = copy.borrowed_date or nowdate()
		due_date = getdate(borrow_date) + timedelta(days=loan_days)
		item_status = "overdue" if copy.status == "overdue" else "borrowing"
		if item_status == "borrowing" and getdate(due_date) < getdate(nowdate()):
			item_status = "overdue"

		tx_status = "overdue" if item_status == "overdue" else "borrowing"

		try:
			tx = frappe.get_doc(
				{
					"doctype": TRANSACTION_DTYPE,
					"borrower_id": copy.borrower_id,
					"borrower_name": copy.borrower_name or copy.borrower_id,
					"borrower_type": "student",
					"borrow_date": borrow_date,
					"status": tx_status,
					"note": "Migration từ dữ liệu legacy",
					"items": [
						{
							"doctype": TRANSACTION_ITEM_DTYPE,
							"book_copy_id": code,
							"book_title": frappe.db.get_value(COPY_DTYPE, copy.name, "book_title") or "",
							"due_date": due_date,
							"status": item_status,
						}
					],
				}
			)
			tx.insert(ignore_permissions=True)
			created += 1
		except Exception as ex:
			frappe.log_error(f"migrate_legacy_borrows: copy {code} failed: {ex}")

	frappe.db.commit()
	frappe.logger().info(f"migrate_legacy_borrows_to_transactions: created {created} transactions")
