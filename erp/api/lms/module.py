# LMS Module & Module Item

import frappe

from erp.lms.services import module_service
from erp.lms.utils.permissions import require_lms_staff
from erp.utils.api_response import error_response, single_item_response, success_response


def _json_body() -> dict:
	return dict(frappe.request.json or frappe.form_dict or {})


@frappe.whitelist(methods=["POST"])
def create_module():
	try:
		result = module_service.create_module(_json_body())
		return single_item_response(result, message="Module created")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "PUT"])
def update_module():
	try:
		data = _json_body()
		module_id = data.get("module_id") or data.get("name")
		if not module_id:
			return error_response("module_id bắt buộc", code="VALIDATION_ERROR")
		result = module_service.update_module(module_id, data)
		return single_item_response(result, message="Module updated")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "DELETE"])
def delete_module():
	try:
		data = _json_body()
		module_id = data.get("module_id") or data.get("name") or frappe.form_dict.get("module_id")
		if not module_id:
			return error_response("module_id bắt buộc", code="VALIDATION_ERROR")
		result = module_service.delete_module(module_id)
		return success_response(data=result, message="Module deleted")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_module_item():
	try:
		result = module_service.create_module_item(_json_body())
		return single_item_response(result, message="Module item created")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "PUT"])
def update_module_item():
	try:
		data = _json_body()
		item_id = data.get("name") or data.get("item_id")
		if not item_id:
			return error_response("item_id bắt buộc", code="VALIDATION_ERROR")
		result = module_service.update_module_item(item_id, data)
		return single_item_response(result, message="Module item updated")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "DELETE"])
def delete_module_item():
	try:
		data = _json_body()
		item_id = data.get("item_id") or data.get("name") or frappe.form_dict.get("item_id")
		if not item_id:
			return error_response("item_id bắt buộc", code="VALIDATION_ERROR")
		result = module_service.delete_module_item(item_id)
		return success_response(data=result, message="Module item deleted")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def move_module_item():
	try:
		data = _json_body()
		item_id = data.get("item_id") or data.get("name")
		target_module = data.get("target_module") or data.get("module")
		if not item_id or not target_module:
			return error_response("item_id và target_module bắt buộc", code="VALIDATION_ERROR")
		result = module_service.move_module_item(
			item_id,
			target_module,
			position=data.get("position"),
		)
		return single_item_response(result, message="Module item moved")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def reorder_modules():
	try:
		data = _json_body()
		course = data.get("course") or data.get("course_id")
		order = data.get("order")
		if not course or not order:
			return error_response("course và order bắt buộc", code="VALIDATION_ERROR")
		result = module_service.reorder_modules(course, order)
		return success_response(data=result, message="Modules reordered")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def reorder_module_items():
	try:
		data = _json_body()
		module = data.get("module") or data.get("module_id")
		order = data.get("order")
		if not module or not order:
			return error_response("module và order bắt buộc", code="VALIDATION_ERROR")
		result = module_service.reorder_module_items(module, order)
		return success_response(data=result, message="Module items reordered")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
