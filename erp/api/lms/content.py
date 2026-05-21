# Content — module tree, pages, progress

import frappe

from erp.lms.services import content_service
from erp.utils.api_response import error_response, single_item_response, success_response


def _normalize_id(value) -> str | None:
	"""Chuẩn hóa query param — bỏ chuỗi rỗng."""
	if value is None:
		return None
	if isinstance(value, (list, tuple)):
		for item in value:
			n = _normalize_id(item)
			if n:
				return n
		return None
	text = str(value).strip()
	return text or None


def _safe_json_body() -> dict:
	"""Chỉ parse JSON khi Content-Type đúng — tránh 415 trên GET."""
	req = getattr(frappe.local, "request", None)
	if not req or not getattr(req, "is_json", False):
		return {}
	try:
		data = req.get_json(silent=True)
	except Exception:
		return {}
	return data if isinstance(data, dict) else {}


def _first_param(*keys: str, kwarg: str | None = None) -> str | None:
	"""Đọc param từ kwargs, form_dict, JSON body, request.args (GET đôi khi lệch form_dict)."""
	n = _normalize_id(kwarg)
	if n:
		return n
	sources = []
	if frappe.form_dict:
		sources.append(frappe.form_dict)
	if getattr(frappe.local, "request", None) and getattr(frappe.request, "args", None):
		sources.append(frappe.request.args)
	body = _safe_json_body()
	if body:
		sources.append(body)
	for key in keys:
		for src in sources:
			try:
				val = src.get(key) if hasattr(src, "get") else None
			except Exception:
				val = None
			n = _normalize_id(val)
			if n:
				return n
	return None


@frappe.whitelist(methods=["GET", "POST"])
def get_module_tree(section_id=None, course_id=None):
	try:
		section_id = _first_param("section_id", "sectionId", kwarg=section_id)
		course_id = _first_param("course_id", "course", "courseId", kwarg=course_id)
		# :sectionId trên portal có thể là LMS Course id (blueprint)
		if section_id and not course_id and frappe.db.exists("LMS Course", section_id):
			course_id = section_id
		if not section_id and not course_id:
			return error_response(
				"section_id hoặc course_id bắt buộc",
				code="VALIDATION_ERROR",
			)
		data = content_service.get_module_tree(
			section_id or "",
			course_id=course_id,
		)
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


@frappe.whitelist(methods=["POST", "PUT"])
def update_page():
	try:
		data = frappe.request.json or frappe.form_dict
		page_id = data.get("page_id") or data.get("name")
		if not page_id:
			return error_response("page_id bắt buộc", code="VALIDATION_ERROR")
		result = content_service.update_page(page_id, data)
		return single_item_response(result, message="Page updated")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "DELETE"])
def delete_page():
	try:
		data = frappe.request.json or frappe.form_dict
		page_id = data.get("page_id") or data.get("name") or frappe.form_dict.get("page_id")
		if not page_id:
			return error_response("page_id bắt buộc", code="VALIDATION_ERROR")
		result = content_service.delete_page(page_id)
		return success_response(data=result, message="Page deleted")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_page(page_id=None):
	try:
		page_id = _first_param("page_id", "pageId", kwarg=page_id)
		if not page_id:
			return error_response("page_id bắt buộc", code="VALIDATION_ERROR")
		result = content_service.get_page(page_id)
		return single_item_response(result)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
