# Assignment API

import frappe

from erp.lms.services import assignment_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_assignment():
	try:
		data = frappe.request.json or frappe.form_dict
		result = assignment_service.create_assignment(data)
		return single_item_response(result, message="Assignment created")
	except Exception as exc:
		frappe.log_error(title="LMS create_assignment", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def submit_assignment():
	try:
		data = frappe.request.json or frappe.form_dict
		result = assignment_service.submit_assignment(
			assignment_id=data.get("assignment_id"),
			body=data.get("body"),
			attachments=data.get("attachments"),
		)
		return single_item_response(result, message="Submitted")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def grade_submission():
	try:
		data = frappe.request.json or frappe.form_dict
		result = assignment_service.grade_submission(
			submission_id=data.get("submission_id"),
			score=float(data.get("score", 0)),
			feedback=data.get("feedback"),
		)
		return single_item_response(result, message="Graded")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_assignments(section_id=None):
	try:
		section_id = section_id or frappe.form_dict.get("section_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		rows = assignment_service.list_assignments(section_id)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_assignment(assignment_id=None):
	try:
		assignment_id = assignment_id or frappe.form_dict.get("assignment_id")
		if not assignment_id:
			return error_response("assignment_id bắt buộc", code="VALIDATION_ERROR")
		data = assignment_service.get_assignment(assignment_id)
		return single_item_response(data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_submissions(assignment_id=None):
	try:
		assignment_id = assignment_id or frappe.form_dict.get("assignment_id")
		rows = assignment_service.list_submissions(assignment_id)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))
