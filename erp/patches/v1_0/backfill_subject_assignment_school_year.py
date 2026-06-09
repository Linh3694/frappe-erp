"""
Gán school_year_id cho phân công giảng dạy hiện có = năm học active theo từng campus.
"""

from __future__ import annotations

import frappe


def execute():
	"""Backfill school_year_id = năm học is_enable mới nhất theo campus."""
	campuses = frappe.db.sql(
		"""
		SELECT DISTINCT campus_id
		FROM `tabSIS Subject Assignment`
		WHERE campus_id IS NOT NULL AND campus_id != ''
		""",
		as_dict=True,
	)

	total_updated = 0
	missing_campuses: list[str] = []

	for row in campuses:
		campus_id = row.campus_id
		active_sy = frappe.db.get_value(
			"SIS School Year",
			{"is_enable": 1, "campus_id": campus_id},
			"name",
			order_by="start_date desc",
		)
		if not active_sy:
			missing_campuses.append(campus_id)
			frappe.logger().warning(
				f"subject_assignment_school_year: campus {campus_id} không có năm học active"
			)
			continue

		frappe.db.sql(
			"""
			UPDATE `tabSIS Subject Assignment`
			SET school_year_id = %s
			WHERE campus_id = %s
			  AND (school_year_id IS NULL OR school_year_id = '')
			""",
			(active_sy, campus_id),
		)
		count = frappe.db.sql(
			"""
			SELECT COUNT(*) FROM `tabSIS Subject Assignment`
			WHERE campus_id = %s AND school_year_id = %s
			""",
			(campus_id, active_sy),
		)[0][0]
		total_updated += count
		frappe.logger().info(
			f"subject_assignment_school_year: campus={campus_id} active={active_sy} count={count}"
		)

	# Báo cáo lệch class vs school_year (chỉ log, không auto-sửa)
	mismatch_count = frappe.db.sql(
		"""
		SELECT COUNT(*)
		FROM `tabSIS Subject Assignment` sa
		INNER JOIN `tabSIS Class` c ON sa.class_id = c.name
		WHERE sa.class_id IS NOT NULL
		  AND sa.school_year_id IS NOT NULL
		  AND sa.school_year_id != c.school_year_id
		"""
	)[0][0]

	frappe.db.commit()

	frappe.logger().info(
		f"subject_assignment_school_year: done total={total_updated} "
		f"mismatch_class_year={mismatch_count} missing_campuses={missing_campuses}"
	)

	if missing_campuses:
		frappe.log_error(
			title="Subject Assignment school_year backfill",
			message=f"Campus không có năm active: {', '.join(missing_campuses)}",
		)
