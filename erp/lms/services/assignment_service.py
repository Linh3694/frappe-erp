"""Assignment & submission."""

import json

import frappe
from frappe.utils import now_datetime

from erp.lms.constants import (
	SUBMISSION_STATE_GRADED,
	SUBMISSION_STATE_SUBMITTED,
)
from erp.lms.utils.enrollment import get_student_id_for_user, validate_section_enrollment
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def create_assignment(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Assignment", **data})
	if not doc.campus_id and doc.course:
		doc.campus_id = frappe.db.get_value("LMS Course", doc.course, "campus_id")
	doc.insert()
	_ensure_grade_column_for_assignment(doc)
	return doc.as_dict()


def submit_assignment(assignment_id: str, body=None, attachments=None, user: str | None = None) -> dict:
	user = user or frappe.session.user
	student_id = get_student_id_for_user(user)
	if not student_id:
		frappe.throw("Chỉ học sinh mới nộp bài")

	assignment = frappe.get_doc("LMS Assignment", assignment_id)
	if assignment.lock_at and now_datetime() > assignment.lock_at:
		frappe.throw("Đã quá hạn nộp bài")

	if assignment.section:
		validate_section_enrollment(assignment.section, user, min_role="student")
	elif assignment.course:
		from erp.lms.utils.permissions import user_enrolled_in_course
		if not user_enrolled_in_course(user, assignment.course):
			frappe.throw("Không enrolled", frappe.PermissionError)

	existing = frappe.db.get_value(
		"LMS Submission",
		{"assignment": assignment_id, "student_id": student_id},
	)
	payload = {
		"body": body,
		"attachments_json": json.dumps(attachments or []),
		"submitted_at": now_datetime(),
		"workflow_state": SUBMISSION_STATE_SUBMITTED,
	}
	if existing:
		doc = frappe.get_doc("LMS Submission", existing)
		doc.update(payload)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "LMS Submission",
				"assignment": assignment_id,
				"student_id": student_id,
				**payload,
			}
		)
		doc.insert(ignore_permissions=True)
	return doc.as_dict()


def grade_submission(submission_id: str, score: float, feedback: str | None = None) -> dict:
	require_lms_staff()
	doc = frappe.get_doc("LMS Submission", submission_id)
	doc.score = score
	doc.graded_at = now_datetime()
	doc.grader = frappe.session.user
	doc.workflow_state = SUBMISSION_STATE_GRADED
	if feedback:
		doc.body = (doc.body or "") + f"\n\n---\nFeedback: {feedback}"
	doc.save(ignore_permissions=True)
	_sync_submission_to_grade_entry(doc)
	return doc.as_dict()


def list_assignments(section_id: str, user: str | None = None) -> list:
	"""Danh sách bài tập theo section — kèm trạng thái nộp của học sinh."""
	user = user or frappe.session.user
	validate_section_enrollment(section_id, user, min_role="observer")

	rows = frappe.get_all(
		"LMS Assignment",
		filters={"section": section_id},
		fields=[
			"name",
			"title",
			"points_possible",
			"due_at",
			"lock_at",
			"modified",
		],
		order_by="due_at asc, modified desc",
	)

	student_id = get_student_id_for_user(user)
	if student_id and not is_lms_staff(user):
		for row in rows:
			sub = frappe.db.get_value(
				"LMS Submission",
				{"assignment": row.name, "student_id": student_id},
				["name", "workflow_state", "score", "submitted_at", "graded_at"],
				as_dict=True,
			)
			row["my_submission"] = sub

	return rows


def get_assignment(assignment_id: str, user: str | None = None) -> dict:
	"""Chi tiết bài tập + submission của học sinh hiện tại."""
	user = user or frappe.session.user
	doc = frappe.get_doc("LMS Assignment", assignment_id)

	if doc.section:
		validate_section_enrollment(doc.section, user, min_role="observer")
	elif doc.course:
		from erp.lms.utils.permissions import user_enrolled_in_course
		if not is_lms_staff(user) and not user_enrolled_in_course(user, doc.course):
			frappe.throw("Không có quyền", frappe.PermissionError)

	result = doc.as_dict()
	student_id = get_student_id_for_user(user)
	if student_id:
		sub = frappe.db.get_value(
			"LMS Submission",
			{"assignment": assignment_id, "student_id": student_id},
			[
				"name",
				"workflow_state",
				"score",
				"submitted_at",
				"graded_at",
				"body",
				"attachments_json",
			],
			as_dict=True,
		)
		if sub and sub.get("attachments_json"):
			try:
				sub["attachments"] = json.loads(sub.attachments_json)
			except (TypeError, json.JSONDecodeError):
				sub["attachments"] = []
		result["my_submission"] = sub

	return result


def list_submissions(assignment_id: str) -> list:
	require_lms_staff()
	rows = frappe.get_all(
		"LMS Submission",
		filters={"assignment": assignment_id},
		fields=[
			"name",
			"student_id",
			"submitted_at",
			"score",
			"workflow_state",
			"graded_at",
			"grader",
			"body",
		],
		order_by="modified desc",
	)
	for row in rows:
		row["student_name"] = frappe.db.get_value(
			"CRM Student", row.student_id, "student_name"
		)
	return rows


def _ensure_grade_column_for_assignment(assignment):
	"""Tạo grade column nếu chưa có (section bắt buộc)."""
	if not assignment.section:
		return
	if frappe.db.exists("LMS Grade Column", {"assignment": assignment.name}):
		return
	frappe.get_doc(
		{
			"doctype": "LMS Grade Column",
			"section": assignment.section,
			"title": assignment.title,
			"points_possible": assignment.points_possible or 100,
			"column_type": "assignment",
			"assignment": assignment.name,
			"campus_id": assignment.campus_id,
		}
	).insert(ignore_permissions=True)


def _sync_submission_to_grade_entry(submission):
	assignment = frappe.get_doc("LMS Assignment", submission.assignment)
	if not assignment.section:
		return
	column = frappe.db.get_value("LMS Grade Column", {"assignment": assignment.name})
	if not column:
		return
	existing = frappe.db.get_value(
		"LMS Grade Entry",
		{"column": column, "student_id": submission.student_id},
	)
	payload = {
		"score": submission.score,
		"entered_by": frappe.session.user,
	}
	if existing:
		frappe.db.set_value("LMS Grade Entry", existing, payload)
	else:
		frappe.get_doc(
			{
				"doctype": "LMS Grade Entry",
				"column": column,
				"student_id": submission.student_id,
				**payload,
			}
		).insert(ignore_permissions=True)
