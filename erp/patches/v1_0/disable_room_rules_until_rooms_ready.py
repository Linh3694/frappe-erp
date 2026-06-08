"""Tắt rule phòng trên rule set DB — campus chưa định nghĩa phòng đầy đủ.

Bật lại room_no_overlap + room_type_match khi module phòng sẵn sàng (G1).
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.table_exists("SIS Timetable Rule Set"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabSIS Timetable Rule`
		SET enabled = 0
		WHERE rule_id IN ('room_no_overlap', 'room_type_match')
		  AND parenttype = 'SIS Timetable Rule Set'
		"""
	)
	frappe.db.commit()
