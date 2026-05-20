# Mastery path API — Phase 4

import frappe

from erp.lms.services import mastery_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_mastery_rule():
	try:
		data = frappe.request.json or frappe.form_dict
		result = mastery_service.create_mastery_rule(data)
		return single_item_response(result, message="Mastery rule created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_mastery_rules():
	try:
		fd = frappe.form_dict
		rows = mastery_service.list_mastery_rules(
			course_id=fd.get("course_id"),
			section_id=fd.get("section_id"),
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def evaluate_unlock():
	"""Job sau quiz submit — có thể gọi thủ công."""
	try:
		data = frappe.request.json or frappe.form_dict
		result = mastery_service.evaluate_unlock(
			student_id=data.get("student_id"),
			quiz_id=data.get("quiz_id"),
			attempt_id=data.get("attempt_id"),
			section_id=data.get("section_id"),
		)
		return success_response(data=result)
	except Exception as exc:
		return error_response(str(exc))
