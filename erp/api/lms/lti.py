# LTI API — Phase 6

import frappe

from erp.lms.services import lti_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def list_tools(course_id=None):
	try:
		course_id = course_id or frappe.form_dict.get("course_id")
		if not course_id:
			return error_response("course_id bắt buộc", code="VALIDATION_ERROR")
		rows = lti_service.list_tools(course_id)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def upsert_tool():
	try:
		data = frappe.request.json or frappe.form_dict
		result = lti_service.upsert_tool(data)
		return single_item_response(result, message="Tool saved")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def launch(tool_id=None, return_url=None):
	try:
		fd = frappe.form_dict
		tool_id = tool_id or fd.get("tool_id")
		return_url = return_url or fd.get("return_url")
		if not tool_id:
			return error_response("tool_id bắt buộc", code="VALIDATION_ERROR")
		data = lti_service.launch(tool_id, return_url=return_url)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
