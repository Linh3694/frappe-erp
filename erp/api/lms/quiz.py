# Quiz API

import json

import frappe

from erp.lms.services import quiz_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def list_quizzes(section_id=None):
	try:
		section_id = section_id or frappe.form_dict.get("section_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		rows = quiz_service.list_quizzes(section_id)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_quiz(quiz_id=None):
	try:
		quiz_id = quiz_id or frappe.form_dict.get("quiz_id")
		if not quiz_id:
			return error_response("quiz_id bắt buộc", code="VALIDATION_ERROR")
		data = quiz_service.get_quiz(quiz_id)
		return single_item_response(data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_quiz():
	try:
		data = frappe.request.json or frappe.form_dict
		result = quiz_service.create_quiz(data)
		return single_item_response(result, message="Quiz created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def start_attempt():
	try:
		data = frappe.request.json or frappe.form_dict
		result = quiz_service.start_attempt(quiz_id=data.get("quiz_id"))
		return success_response(data=result, message="Attempt started")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def submit_attempt():
	try:
		data = frappe.request.json or frappe.form_dict
		result = quiz_service.submit_attempt(
			attempt_id=data.get("attempt_id"),
			responses=data.get("responses"),
		)
		return single_item_response(result, message="Attempt submitted")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def grade_attempt():
	"""GV chấm attempt có câu essay/short_answer."""
	try:
		data = frappe.request.json or frappe.form_dict
		result = quiz_service.grade_attempt(
			attempt_id=data.get("attempt_id"),
			question_scores=data.get("question_scores"),
			overall_score=data.get("overall_score"),
			feedback=data.get("feedback"),
		)
		return single_item_response(result, message="Attempt graded")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_attempts(quiz_id=None, section_id=None):
	"""Danh sách attempt theo quiz — staff."""
	try:
		quiz_id = quiz_id or frappe.form_dict.get("quiz_id")
		if not quiz_id:
			return error_response("quiz_id bắt buộc", code="VALIDATION_ERROR")
		section_id = section_id or frappe.form_dict.get("section_id")
		rows = quiz_service.list_quiz_attempts(quiz_id, section_id=section_id)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))
