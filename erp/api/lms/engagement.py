# Engagement API — Phase 6

import frappe

from erp.lms.services import engagement_service
from erp.utils.api_response import error_response, success_response


@frappe.whitelist(methods=["GET"])
def get_score(section_id=None, student_id=None):
	try:
		fd = frappe.form_dict
		section_id = section_id or fd.get("section_id")
		student_id = student_id or fd.get("student_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		data = engagement_service.get_score(section_id, student_id=student_id)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def async_attendance(section_id=None, week=None):
	try:
		fd = frappe.form_dict
		section_id = section_id or fd.get("section_id")
		week = week or fd.get("week")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		data = engagement_service.async_attendance(section_id, week=week)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
