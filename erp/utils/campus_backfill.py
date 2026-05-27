"""
Tiện ích backfill campus_id cho Phase 2 multi-campus.
"""

from __future__ import annotations

import frappe

FALLBACK_CAMPUS = "CAMPUS-00001"


def _table(doctype: str) -> str:
	return f"tab{doctype}"


def backfill_from_join(
	doctype: str,
	link_field: str,
	parent_doctype: str,
	parent_campus_field: str = "campus_id",
) -> dict:
	"""Gán campus_id từ parent qua JOIN link field."""
	child = _table(doctype)
	parent = _table(parent_doctype)

	sql = f"""
		UPDATE `{child}` c
		INNER JOIN `{parent}` p ON c.`{link_field}` = p.name
		SET c.campus_id = p.`{parent_campus_field}`
		WHERE (c.campus_id IS NULL OR c.campus_id = '')
		  AND p.`{parent_campus_field}` IS NOT NULL
		  AND p.`{parent_campus_field}` != ''
	"""
	frappe.db.sql(sql)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_from_coalesce_joins(
	doctype: str,
	joins: list[tuple[str, str, str]],
) -> dict:
	"""Gán campus_id từ nhiều parent theo thứ tự ưu tiên (COALESCE)."""
	child = _table(doctype)
	set_parts = []
	where_parts = []

	for link_field, parent_doctype, parent_campus_field in joins:
		parent = _table(parent_doctype)
		alias = link_field.replace("_id", "").replace(".", "_")
		set_parts.append(
			f"COALESCE(c.campus_id, p_{alias}.`{parent_campus_field}`)"
		)
		where_parts.append(
			f"LEFT JOIN `{parent}` p_{alias} ON c.`{link_field}` = p_{alias}.name"
		)

	# Chạy từng join một (đơn giản, an toàn hơn COALESCE phức tạp)
	stats = {"doctype": doctype, "steps": []}
	for link_field, parent_doctype, parent_campus_field in joins:
		step = backfill_from_join(doctype, link_field, parent_doctype, parent_campus_field)
		stats["steps"].append(step)

	final = report_backfill(doctype)
	stats.update(final)
	return stats


def backfill_copy_field(doctype: str, source_field: str = "campus") -> dict:
	"""Copy campus → campus_id (Đợt 6 rename)."""
	child = _table(doctype)
	frappe.db.sql(
		f"""
		UPDATE `{child}`
		SET campus_id = `{source_field}`
		WHERE (campus_id IS NULL OR campus_id = '')
		  AND `{source_field}` IS NOT NULL
		  AND `{source_field}` != ''
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_from_assignment_chain(
	doctype: str,
	assignment_field: str,
	assignment_doctype: str,
	section_field: str = "course_section",
) -> dict:
	"""LMS: assignment → section → campus_id."""
	child = _table(doctype)
	assign = _table(assignment_doctype)
	section = _table("LMS Course Section")

	frappe.db.sql(
		f"""
		UPDATE `{child}` c
		INNER JOIN `{assign}` a ON c.`{assignment_field}` = a.name
		INNER JOIN `{section}` s ON a.`{section_field}` = s.name
		SET c.campus_id = s.campus_id
		WHERE (c.campus_id IS NULL OR c.campus_id = '')
		  AND s.campus_id IS NOT NULL AND s.campus_id != ''
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_from_student_code(doctype: str, student_code_field: str = "student_code") -> dict:
	"""Thư viện: match student_code → CRM Student.campus_id."""
	child = _table(doctype)
	student = _table("CRM Student")

	frappe.db.sql(
		f"""
		UPDATE `{child}` c
		INNER JOIN `{student}` s ON c.`{student_code_field}` = s.student_code
		SET c.campus_id = s.campus_id
		WHERE (c.campus_id IS NULL OR c.campus_id = '')
		  AND c.`{student_code_field}` IS NOT NULL AND c.`{student_code_field}` != ''
		  AND s.campus_id IS NOT NULL AND s.campus_id != ''
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_guardian_from_family(doctype: str = "CRM Guardian") -> dict:
	"""CRM Guardian: campus từ student liên kết (relationship child table)."""
	child = _table(doctype)
	frappe.db.sql(
		f"""
		UPDATE `{child}` g
		INNER JOIN (
			SELECT fr.guardian, s.campus_id, COUNT(*) AS cnt
			FROM `tabCRM Family Relationship` fr
			INNER JOIN `tabCRM Student` s ON fr.student = s.name
			WHERE s.campus_id IS NOT NULL AND s.campus_id != ''
			GROUP BY fr.guardian, s.campus_id
		) ranked
		INNER JOIN (
			SELECT guardian, MAX(cnt) AS max_cnt
			FROM (
				SELECT fr.guardian, s.campus_id, COUNT(*) AS cnt
				FROM `tabCRM Family Relationship` fr
				INNER JOIN `tabCRM Student` s ON fr.student = s.name
				WHERE s.campus_id IS NOT NULL AND s.campus_id != ''
				GROUP BY fr.guardian, s.campus_id
			) x
			GROUP BY guardian
		) best_cnt ON ranked.guardian = best_cnt.guardian AND ranked.cnt = best_cnt.max_cnt
		SET g.campus_id = ranked.campus_id
		WHERE g.name = ranked.guardian
		  AND (g.campus_id IS NULL OR g.campus_id = '')
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_crm_family(doctype: str = "CRM Family") -> dict:
	"""CRM Family: campus từ student trong child table relationships."""
	child = _table(doctype)
	frappe.db.sql(
		f"""
		UPDATE `{child}` f
		INNER JOIN (
			SELECT fr.parent AS family_id, s.campus_id, COUNT(*) AS cnt
			FROM `tabCRM Family Relationship` fr
			INNER JOIN `tabCRM Student` s ON fr.student = s.name
			WHERE fr.parenttype = 'CRM Family'
			  AND s.campus_id IS NOT NULL AND s.campus_id != ''
			GROUP BY fr.parent, s.campus_id
		) ranked
		INNER JOIN (
			SELECT family_id, MAX(cnt) AS max_cnt
			FROM (
				SELECT fr.parent AS family_id, s.campus_id, COUNT(*) AS cnt
				FROM `tabCRM Family Relationship` fr
				INNER JOIN `tabCRM Student` s ON fr.student = s.name
				WHERE fr.parenttype = 'CRM Family'
				  AND s.campus_id IS NOT NULL AND s.campus_id != ''
				GROUP BY fr.parent, s.campus_id
			) x
			GROUP BY family_id
		) best_cnt ON ranked.family_id = best_cnt.family_id AND ranked.cnt = best_cnt.max_cnt
		SET f.campus_id = ranked.campus_id
		WHERE f.name = ranked.family_id
		  AND (f.campus_id IS NULL OR f.campus_id = '')
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_lms_quiz_attempt(doctype: str = "LMS Quiz Attempt") -> dict:
	"""LMS Quiz Attempt: quiz → section/course campus."""
	child = _table(doctype)
	quiz = _table("LMS Quiz")
	section = _table("LMS Course Section")
	course = _table("LMS Course")

	frappe.db.sql(
		f"""
		UPDATE `{child}` a
		INNER JOIN `{quiz}` q ON a.quiz = q.name
		INNER JOIN `{section}` s ON q.section = s.name
		SET a.campus_id = s.campus_id
		WHERE (a.campus_id IS NULL OR a.campus_id = '')
		  AND s.campus_id IS NOT NULL AND s.campus_id != ''
		"""
	)
	frappe.db.sql(
		f"""
		UPDATE `{child}` a
		INNER JOIN `{quiz}` q ON a.quiz = q.name
		INNER JOIN `{course}` c ON q.course = c.name
		SET a.campus_id = c.campus_id
		WHERE (a.campus_id IS NULL OR a.campus_id = '')
		  AND c.campus_id IS NOT NULL AND c.campus_id != ''
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def backfill_it_ticket_from_creator(doctype: str = "ERP IT Support Ticket") -> dict:
	"""IT Ticket: campus từ User Permission của owner."""
	child = _table(doctype)
	frappe.db.sql(
		f"""
		UPDATE `{child}` t
		INNER JOIN `tabUser Permission` up
			ON up.user = t.owner AND up.allow = 'SIS Campus'
		SET t.campus_id = up.for_value
		WHERE (t.campus_id IS NULL OR t.campus_id = '')
		  AND up.for_value IS NOT NULL AND up.for_value != ''
		"""
	)
	frappe.db.commit()
	return report_backfill(doctype)


def apply_fallback(doctype: str, fallback: str = FALLBACK_CAMPUS) -> int:
	"""Gán campus fallback cho row còn trống."""
	child = _table(doctype)
	count = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `{child}`
		WHERE campus_id IS NULL OR campus_id = ''
		"""
	)[0][0]
	if count:
		frappe.db.sql(
			f"""
			UPDATE `{child}`
			SET campus_id = %s
			WHERE campus_id IS NULL OR campus_id = ''
			""",
			fallback,
		)
		frappe.db.commit()
		frappe.log_error(
			title=f"campus_backfill_fallback_{doctype}",
			message=f"{doctype}: {count} row dùng fallback {fallback}",
		)
	return count


def report_backfill(doctype: str) -> dict:
	"""Báo cáo số row còn thiếu campus_id."""
	child = _table(doctype)
	total = frappe.db.count(doctype)
	missing = frappe.db.sql(
		f"SELECT COUNT(*) FROM `{child}` WHERE campus_id IS NULL OR campus_id = ''"
	)[0][0]
	filled = total - missing
	return {
		"doctype": doctype,
		"total": total,
		"filled": filled,
		"missing": missing,
	}
