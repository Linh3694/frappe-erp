"""CRUD câu hỏi và gắn câu vào quiz."""

import json

import frappe

from erp.lms.utils.permissions import require_lms_staff


def create_question(data: dict) -> dict:
	require_lms_staff()
	if isinstance(data.get("answers_json"), dict):
		data["answers_json"] = json.dumps(data["answers_json"])
	doc = frappe.get_doc({"doctype": "LMS Question", **data})
	if not doc.get("bank"):
		frappe.throw("bank bắt buộc")
	doc.insert()
	return doc.as_dict()


def update_question(question_id: str, data: dict) -> dict:
	require_lms_staff()
	doc = frappe.get_doc("LMS Question", question_id)
	payload = {k: v for k, v in data.items() if k not in ("question_id", "name", "cmd")}
	if isinstance(payload.get("answers_json"), dict):
		payload["answers_json"] = json.dumps(payload["answers_json"])
	doc.update(payload)
	doc.save()
	return doc.as_dict()


def delete_question(question_id: str) -> dict:
	require_lms_staff()
	linked = frappe.db.count("LMS Quiz Question", {"question": question_id})
	if linked:
		frappe.throw("Câu hỏi đang được gắn vào quiz, không thể xóa")
	frappe.delete_doc("LMS Question", question_id, ignore_permissions=True)
	return {"deleted": question_id}


def list_questions(bank_id: str, page: int = 1, per_page: int = 50) -> tuple[list, int]:
	require_lms_staff()
	if not bank_id:
		frappe.throw("bank_id bắt buộc")
	total = frappe.db.count("LMS Question", {"bank": bank_id})
	start = (page - 1) * per_page
	rows = frappe.get_all(
		"LMS Question",
		filters={"bank": bank_id},
		fields=["name", "bank", "question_type", "points", "prompt_html", "answers_json", "modified"],
		order_by="modified desc",
		start=start,
		page_length=per_page,
	)
	return rows, total


def link_quiz_question(data: dict) -> dict:
	require_lms_staff()
	quiz = data.get("quiz")
	question = data.get("question")
	if not quiz or not question:
		frappe.throw("quiz và question bắt buộc")

	position = data.get("position")
	if position is None:
		max_pos = frappe.db.sql(
			"""
			SELECT COALESCE(MAX(position), -1) FROM `tabLMS Quiz Question` WHERE quiz = %s
			""",
			quiz,
		)[0][0]
		position = int(max_pos) + 1

	if frappe.db.exists("LMS Quiz Question", {"quiz": quiz, "question": question}):
		frappe.throw("Câu hỏi đã được gắn vào quiz này")

	doc = frappe.get_doc(
		{
			"doctype": "LMS Quiz Question",
			"quiz": quiz,
			"question": question,
			"position": position,
			"points_override": data.get("points_override"),
		}
	)
	doc.insert()
	return doc.as_dict()


def unlink_quiz_question(quiz_question_id: str) -> dict:
	require_lms_staff()
	frappe.delete_doc("LMS Quiz Question", quiz_question_id, ignore_permissions=True)
	return {"deleted": quiz_question_id}


def reorder_quiz_questions(quiz: str, order: list) -> list:
	require_lms_staff()
	if isinstance(order, str):
		order = json.loads(order)
	if not quiz or not order:
		frappe.throw("quiz và order bắt buộc")

	for item in order:
		qq_id = item.get("quiz_question") or item.get("name")
		position = item.get("position")
		if qq_id is None or position is None:
			continue
		frappe.db.set_value("LMS Quiz Question", qq_id, "position", position)

	return frappe.get_all(
		"LMS Quiz Question",
		filters={"quiz": quiz},
		fields=["name", "question", "position", "points_override"],
		order_by="position asc",
	)
