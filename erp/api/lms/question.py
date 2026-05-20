# Question bank & quiz builder API

import json

import frappe

from erp.lms.services import question_service
from erp.utils.api_response import error_response, paginated_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_question():
	try:
		data = frappe.request.json or frappe.form_dict
		result = question_service.create_question(data)
		return single_item_response(result, message="Question created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "PUT"])
def update_question():
	try:
		data = frappe.request.json or frappe.form_dict
		question_id = data.get("question_id") or data.get("name")
		if not question_id:
			return error_response("question_id bắt buộc", code="VALIDATION_ERROR")
		payload = {k: v for k, v in data.items() if k not in ("question_id", "name", "cmd")}
		result = question_service.update_question(question_id, payload)
		return single_item_response(result, message="Question updated")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def delete_question():
	try:
		data = frappe.request.json or frappe.form_dict
		question_id = data.get("question_id")
		if not question_id:
			return error_response("question_id bắt buộc", code="VALIDATION_ERROR")
		result = question_service.delete_question(question_id)
		return success_response(data=result, message="Question deleted")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_questions(bank_id=None):
	try:
		bank_id = bank_id or frappe.form_dict.get("bank_id")
		page = int(frappe.form_dict.get("page") or 1)
		per_page = int(frappe.form_dict.get("per_page") or 50)
		rows, total = question_service.list_questions(bank_id, page=page, per_page=per_page)
		return paginated_response(rows, page, total, per_page)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def link_quiz_question():
	try:
		data = frappe.request.json or frappe.form_dict
		result = question_service.link_quiz_question(data)
		return single_item_response(result, message="Question linked")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def unlink_quiz_question():
	try:
		data = frappe.request.json or frappe.form_dict
		quiz_question_id = data.get("quiz_question_id")
		if not quiz_question_id:
			return error_response("quiz_question_id bắt buộc", code="VALIDATION_ERROR")
		result = question_service.unlink_quiz_question(quiz_question_id)
		return success_response(data=result, message="Question unlinked")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def reorder_quiz_questions():
	try:
		data = frappe.request.json or frappe.form_dict
		order = data.get("order")
		if isinstance(order, str):
			order = json.loads(order)
		result = question_service.reorder_quiz_questions(data.get("quiz"), order)
		return success_response(data=result, message="Questions reordered")
	except Exception as exc:
		return error_response(str(exc))
