# Analytics API — Phase 6

import frappe

from erp.lms.services import analytics_service
from erp.utils.api_response import error_response, success_response


@frappe.whitelist(methods=["GET"])
def get_course_analytics(section_id=None):
	try:
		section_id = section_id or frappe.form_dict.get("section_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		data = analytics_service.get_course_analytics(section_id)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_campus_analytics():
	try:
		data = analytics_service.get_campus_analytics()
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
