"""Gradebook grid."""

import frappe

from erp.lms.utils.enrollment import validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def get_gradebook(section_id: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	if is_lms_staff(user):
		require_lms_staff()
	else:
		validate_section_enrollment(section_id, user, min_role="student")

	columns = frappe.get_all(
		"LMS Grade Column",
		filters={"section": section_id},
		fields=[
			"name", "title", "position", "points_possible",
			"column_type", "muted", "assignment", "quiz", "discussion",
		],
		order_by="position asc",
	)
	if not is_lms_staff(user):
		columns = [c for c in columns if not c.muted]

	students = frappe.get_all(
		"LMS Enrollment",
		filters={"section": section_id, "role": "student", "status": "active"},
		fields=["student_id"],
	)
	student_ids = [s.student_id for s in students if s.student_id]

	entries = []
	if columns and student_ids:
		entries = frappe.get_all(
			"LMS Grade Entry",
			filters={"column": ["in", [c.name for c in columns]], "student_id": ["in", student_ids]},
			fields=["name", "column", "student_id", "score", "excused"],
		)

	entry_map = {}
	for e in entries:
		entry_map.setdefault(e.student_id, {})[e.column] = e

	rows = []
	for sid in student_ids:
		student_name = frappe.db.get_value("CRM Student", sid, "student_name")
		rows.append(
			{
				"student_id": sid,
				"student_name": student_name,
				"grades": entry_map.get(sid, {}),
			}
		)

	groups = frappe.get_all(
		"LMS Grade Group",
		filters={"section": section_id},
		fields=["name", "title", "weight", "drop_lowest"],
	)

	return {
		"section_id": section_id,
		"columns": columns,
		"groups": groups,
		"rows": rows,
	}


def upsert_grade_entry(column_id: str, student_id: str, score: float, excused: int = 0) -> dict:
	require_lms_staff()
	existing = frappe.db.get_value(
		"LMS Grade Entry",
		{"column": column_id, "student_id": student_id},
	)
	payload = {
		"score": score,
		"excused": excused,
		"entered_by": frappe.session.user,
	}
	if existing:
		doc = frappe.get_doc("LMS Grade Entry", existing)
		doc.update(payload)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "LMS Grade Entry",
				"column": column_id,
				"student_id": student_id,
				**payload,
			}
		)
		doc.insert(ignore_permissions=True)
	return doc.as_dict()
