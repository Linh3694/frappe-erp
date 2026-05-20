# Announcement API

import frappe

from erp.lms.services import announcement_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def post_announcement():
	try:
		data = frappe.request.json or frappe.form_dict
		result = announcement_service.post_announcement(data)
		return single_item_response(result, message="Announcement posted")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_announcements():
	try:
		fd = frappe.form_dict
		rows = announcement_service.list_announcements(
			course_id=fd.get("course_id"),
			section_id=fd.get("section_id"),
		)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
