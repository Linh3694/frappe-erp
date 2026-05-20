# Gradebook API

import frappe

from erp.lms.services import gradebook_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def get_gradebook(section_id=None):
	try:
		section_id = section_id or frappe.form_dict.get("section_id")
		data = gradebook_service.get_gradebook(section_id)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def upsert_grade_entry():
	try:
		data = frappe.request.json or frappe.form_dict
		result = gradebook_service.upsert_grade_entry(
			column_id=data.get("column_id"),
			student_id=data.get("student_id"),
			score=float(data.get("score", 0)),
			excused=int(data.get("excused") or 0),
		)
		return single_item_response(result, message="Grade saved")
	except Exception as exc:
		return error_response(str(exc))
