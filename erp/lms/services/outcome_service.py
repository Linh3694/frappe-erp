"""Outcomes — align SIS Sub Curriculum, import criteria."""

import frappe

from erp.lms.utils.permissions import require_lms_staff, user_enrolled_in_course, is_lms_staff


def create_outcome(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Outcome", **data})
	if not doc.campus_id and doc.course:
		doc.campus_id = frappe.db.get_value("LMS Course", doc.course, "campus_id")
	doc.insert()
	return doc.as_dict()


def list_outcomes(course_id: str, user: str | None = None) -> list:
	user = user or frappe.session.user
	if not is_lms_staff(user) and not user_enrolled_in_course(user, course_id):
		frappe.throw("Không có quyền", frappe.PermissionError)

	return frappe.get_all(
		"LMS Outcome",
		filters={"course": course_id},
		fields=[
			"name", "title", "mastery_points", "sis_sub_curriculum_id",
			"sis_criteria_id", "description",
		],
		order_by="title asc",
	)


def import_outcomes_from_sis(course_id: str, sis_sub_curriculum_id: str) -> list:
	"""
	Import tiêu chí từ SIS Sub Curriculum → LMS Outcome.
	Đọc SIS Sub Curriculum Evaluation → SIS Curriculum Evaluation Criteria.
	"""
	require_lms_staff()
	if not frappe.db.exists("SIS Sub Curriculum", sis_sub_curriculum_id):
		frappe.throw("SIS Sub Curriculum không tồn tại")

	campus_id = frappe.db.get_value("LMS Course", course_id, "campus_id")
	eval_ids = frappe.get_all(
		"SIS Sub Curriculum Evaluation",
		filters={"subcurriculum_id": sis_sub_curriculum_id},
		pluck="name",
	)
	if not eval_ids:
		frappe.throw("Không tìm thấy Sub Curriculum Evaluation cho sub curriculum này")

	criteria = frappe.get_all(
		"SIS Curriculum Evaluation Criteria",
		filters={"subcurriculum_evaluation_id": ["in", eval_ids]},
		fields=["name", "title", "value", "description"],
		order_by="title asc",
	)

	created = []
	for c in criteria:
		if frappe.db.exists(
			"LMS Outcome",
			{"course": course_id, "sis_criteria_id": c.name},
		):
			continue
		doc = frappe.get_doc(
			{
				"doctype": "LMS Outcome",
				"course": course_id,
				"title": c.title,
				"mastery_points": c.value or 1,
				"sis_sub_curriculum_id": sis_sub_curriculum_id,
				"sis_criteria_id": c.name,
				"description": c.description,
				"campus_id": campus_id,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.as_dict())
	return created


def align_outcome_to_course(outcome_id: str, course_id: str) -> dict:
	"""Gắn outcome có sẵn vào course (copy nếu khác course)."""
	require_lms_staff()
	src = frappe.get_doc("LMS Outcome", outcome_id)
	if src.course == course_id:
		return src.as_dict()

	doc = frappe.copy_doc(src)
	doc.course = course_id
	doc.campus_id = frappe.db.get_value("LMS Course", course_id, "campus_id")
	doc.sis_criteria_id = None
	doc.insert()
	return doc.as_dict()
