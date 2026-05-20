# Content — module tree, pages, progress

import frappe

from erp.lms.services import content_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def get_module_tree(section_id=None):
	try:
		section_id = section_id or frappe.form_dict.get("section_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		data = content_service.get_module_tree(section_id)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def mark_item_complete():
	try:
		data = frappe.request.json or frappe.form_dict
		result = content_service.mark_item_complete(
			module_item_id=data.get("module_item_id"),
			last_position=data.get("last_position") or 0,
			section_id=data.get("section_id"),
		)
		return single_item_response(result, message="Marked complete")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_page():
	try:
		data = frappe.request.json or frappe.form_dict
		result = content_service.create_page(data)
		return single_item_response(result, message="Page created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_page(page_id=None):
	try:
		page_id = page_id or frappe.form_dict.get("page_id")
		result = content_service.get_page(page_id)
		return single_item_response(result)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
