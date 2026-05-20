# Calendar API — Phase 4

import frappe

from erp.lms.services import calendar_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_calendar_event():
	try:
		data = frappe.request.json or frappe.form_dict
		result = calendar_service.create_calendar_event(data)
		return single_item_response(result, message="Event created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_calendar_events():
	try:
		fd = frappe.form_dict
		rows = calendar_service.list_calendar_events(
			course_id=fd.get("course_id"),
			section_id=fd.get("section_id"),
			start=fd.get("start"),
			end=fd.get("end"),
		)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_merged_calendar():
	try:
		fd = frappe.form_dict
		result = calendar_service.get_merged_calendar(
			week_start=fd.get("week_start"),
			week_end=fd.get("week_end"),
			section_id=fd.get("section_id"),
			student_id=fd.get("student_id"),
		)
		return success_response(data=result)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
