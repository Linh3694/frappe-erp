# -*- coding: utf-8 -*-
"""
TKB requirements — expand backup khối×môn sang lớp×môn sau khi schema có class_id.
"""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.table_exists("_erp_tkb_req_grade_backup"):
		return
	if not frappe.db.has_column("SIS Timetable Generation Requirement", "class_id"):
		return

	rows = frappe.db.sql(
		"""
		SELECT session_id, education_grade_id, timetable_subject_id,
		       periods_per_week, max_periods_per_day, prefer_consecutive,
		       force_pair, room_type_required
		FROM `_erp_tkb_req_grade_backup`
		""",
		as_dict=True,
	)
	if not rows:
		frappe.db.sql_ddl("DROP TABLE IF EXISTS `_erp_tkb_req_grade_backup`")
		return

	# Xóa requirements cũ (có thể rỗng class_id sau model sync)
	frappe.db.sql("DELETE FROM `tabSIS Timetable Generation Requirement`")

	session_cache: dict[str, dict] = {}

	for row in rows:
		session_id = row["session_id"]
		if session_id not in session_cache:
			sess = frappe.get_doc("SIS Timetable Generation Session", session_id)
			session_cache[session_id] = {
				"campus_id": sess.campus_id,
				"school_year_id": sess.school_year_id,
			}

		meta = session_cache[session_id]
		classes = frappe.db.sql(
			"""
			SELECT name FROM `tabSIS Class`
			WHERE campus_id = %(campus_id)s
			  AND school_year_id = %(school_year_id)s
			  AND education_grade = %(grade_id)s
			""",
			{
				"campus_id": meta["campus_id"],
				"school_year_id": meta["school_year_id"],
				"grade_id": row["education_grade_id"],
			},
			as_dict=True,
		)

		for cls in classes:
			existing = frappe.db.exists(
				"SIS Timetable Generation Requirement",
				{
					"session_id": session_id,
					"class_id": cls["name"],
					"timetable_subject_id": row["timetable_subject_id"],
				},
			)
			if existing:
				doc = frappe.get_doc("SIS Timetable Generation Requirement", existing)
			else:
				doc = frappe.new_doc("SIS Timetable Generation Requirement")
				doc.session_id = session_id
				doc.class_id = cls["name"]
				doc.timetable_subject_id = row["timetable_subject_id"]

			doc.periods_per_week = row["periods_per_week"]
			doc.max_periods_per_day = row["max_periods_per_day"] or 2
			doc.prefer_consecutive = bool(row["prefer_consecutive"])
			doc.force_pair = bool(row.get("force_pair"))
			doc.room_type_required = row["room_type_required"] or ""
			doc.save(ignore_permissions=True)

	frappe.db.sql_ddl("DROP TABLE IF EXISTS `_erp_tkb_req_grade_backup`")
	frappe.db.commit()
