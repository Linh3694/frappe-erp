"""Mastery path — conditional unlock module sau quiz/outcome."""

import json

import frappe

from erp.lms.utils.enrollment import get_student_id_for_user
from erp.lms.utils.permissions import is_lms_staff, require_lms_staff


def create_mastery_rule(data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc({"doctype": "LMS Mastery Rule", **data})
	if not doc.campus_id and doc.course:
		doc.campus_id = frappe.db.get_value("LMS Course", doc.course, "campus_id")
	doc.insert()
	return doc.as_dict()


def list_mastery_rules(course_id: str = None, section_id: str = None) -> list:
	filters = {}
	if course_id:
		filters["course"] = course_id
	if section_id:
		filters["section"] = section_id
	if not filters:
		frappe.throw("course_id hoặc section_id bắt buộc")
	require_lms_staff()
	return frappe.get_all(
		"LMS Mastery Rule",
		filters=filters,
		fields=[
			"name", "course", "section", "module", "outcome", "quiz",
			"mastery_threshold", "next_module",
		],
		order_by="module asc",
	)


def evaluate_unlock(
	student_id: str = None,
	quiz_id: str = None,
	attempt_id: str = None,
	section_id: str = None,
) -> dict:
	"""
	Đánh giá mastery sau quiz submit.
	Trả về danh sách module vừa unlock cho học sinh.
	"""
	if attempt_id:
		attempt = frappe.get_doc("LMS Quiz Attempt", attempt_id)
		student_id = attempt.student_id
		quiz_id = attempt.quiz
		score = float(attempt.score or 0)
	elif quiz_id and student_id:
		attempts = frappe.get_all(
			"LMS Quiz Attempt",
			filters={"quiz": quiz_id, "student_id": student_id, "workflow_state": "graded"},
			fields=["name", "score"],
			order_by="finished_at desc",
			limit=1,
		)
		if not attempts:
			return {"unlocked_modules": [], "message": "Chưa có attempt graded"}
		score = float(attempts[0].score or 0)
	else:
		frappe.throw("Cần attempt_id hoặc (quiz_id + student_id)")

	rules = frappe.get_all(
		"LMS Mastery Rule",
		filters={"quiz": quiz_id},
		fields=["name", "module", "next_module", "mastery_threshold", "course", "section"],
	)
	if section_id:
		rules = [r for r in rules if not r.section or r.section == section_id]

	unlocked = []
	for rule in rules:
		threshold = float(rule.mastery_threshold or 80)
		if score >= threshold:
			if _unlock_module_for_student(student_id, rule.section, rule.next_module):
				unlocked.append(rule.next_module)

	return {"student_id": student_id, "quiz_id": quiz_id, "score": score, "unlocked_modules": unlocked}


def is_module_visible_for_student(module_id: str, student_id: str, section_id: str) -> bool:
	"""HS có thể xem module (unlock_at, mastery unlock, hoặc module đầu)."""
	mod = frappe.db.get_value(
		"LMS Module",
		module_id,
		["unlock_at", "course", "position"],
		as_dict=True,
	)
	if not mod:
		return True

	from frappe.utils import get_datetime, now_datetime

	if mod.unlock_at and get_datetime(now_datetime()) < get_datetime(mod.unlock_at):
		return False

	if module_id in _get_student_unlocked_modules(student_id, section_id):
		return True

	first = frappe.get_all(
		"LMS Module",
		filters={"course": mod.course},
		fields=["name"],
		order_by="position asc",
		limit=1,
	)
	if first and first[0].name == module_id:
		return True

	# Có mastery rule trỏ tới module này → cần unlock qua quiz
	if frappe.db.exists("LMS Mastery Rule", {"next_module": module_id}):
		return False

	return True


def is_module_unlocked_for_student(module_id: str, student_id: str, section_id: str) -> bool:
	"""Alias — module đã được unlock (mastery json hoặc unlock_at đã qua)."""
	return is_module_visible_for_student(module_id, student_id, section_id)


def _unlock_module_for_student(student_id: str, section_id: str | None, module_id: str) -> bool:
	if not section_id:
		course = frappe.db.get_value("LMS Module", module_id, "course")
		section_id = frappe.db.get_value("LMS Course Section", {"course": course}, "name")
	if not section_id:
		return False

	unlocked = _get_student_unlocked_modules(student_id, section_id)
	if module_id in unlocked:
		return False
	unlocked.append(module_id)
	_save_student_unlocked_modules(student_id, section_id, unlocked)
	return True


def _get_student_unlocked_modules(student_id: str, section_id: str) -> list:
	row = frappe.db.get_value(
		"LMS Course Progress",
		{"student_id": student_id, "section": section_id},
		"mastery_unlocked_modules_json",
	)
	if not row:
		return []
	if isinstance(row, list):
		return row
	try:
		return json.loads(row) if row else []
	except (TypeError, json.JSONDecodeError):
		return []


def _save_student_unlocked_modules(student_id: str, section_id: str, modules: list):
	existing = frappe.db.get_value(
		"LMS Course Progress",
		{"student_id": student_id, "section": section_id},
	)
	payload = {"mastery_unlocked_modules_json": json.dumps(modules)}
	if existing:
		frappe.db.set_value("LMS Course Progress", existing, payload)
	else:
		frappe.get_doc(
			{
				"doctype": "LMS Course Progress",
				"student_id": student_id,
				"section": section_id,
				"percent_complete": 0,
				**payload,
			}
		).insert(ignore_permissions=True)
