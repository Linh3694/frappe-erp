# Inbox API — Phase 6

import frappe

from erp.lms.services import inbox_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def list_conversations(course_id=None, section_id=None):
	try:
		fd = frappe.form_dict
		rows = inbox_service.list_conversations(
			course_id=course_id or fd.get("course_id"),
			section_id=section_id or fd.get("section_id"),
		)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_messages(conversation_id=None):
	try:
		conversation_id = conversation_id or frappe.form_dict.get("conversation_id")
		if not conversation_id:
			return error_response("conversation_id bắt buộc", code="VALIDATION_ERROR")
		rows = inbox_service.list_messages(conversation_id)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def send_message():
	try:
		data = frappe.request.json or frappe.form_dict
		conversation_id = data.get("conversation_id")
		body = data.get("body")
		if not conversation_id:
			return error_response("conversation_id bắt buộc", code="VALIDATION_ERROR")
		result = inbox_service.send_message(conversation_id, body)
		return single_item_response(result, message="Message sent")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
