# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt
"""Backfill force_pair_mode 3 nấc từ checkbox force_pair legacy.

force_pair=1 (đang tick) → mode='hard' để giữ nguyên hành vi cứng hiện tại.
Idempotent: chỉ set khi mode còn rỗng; mọi đường đọc cũng có fallback runtime
(`force_pair_mode or ('hard' if force_pair else '')`) nên chạy trước/sau đều đúng.
"""

import frappe


def execute():
	for table in (
		"tabSIS Timetable Generation Requirement",
		"tabSIS Timetable Rule Set Requirement",
	):
		if not frappe.db.table_exists(table[3:]):
			continue
		if not frappe.db.has_column(table[3:], "force_pair_mode"):
			continue
		frappe.db.sql(
			f"""
			UPDATE `{table}`
			SET force_pair_mode = 'hard'
			WHERE COALESCE(force_pair, 0) = 1
			  AND COALESCE(force_pair_mode, '') = ''
			"""
		)
	frappe.db.commit()
