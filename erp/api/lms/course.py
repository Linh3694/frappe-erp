# LMS Course — CRUD & detail

import json

import frappe

from erp.lms.services import course_service
from erp.utils.api_response import error_response, paginated_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def list_courses():
	try:
		page = int(frappe.form_dict.get("page") or 1)
		per_page = int(frappe.form_dict.get("per_page") or 20)
		rows, total = course_service.list_courses(
			page=page,
			per_page=per_page,
			course_state=frappe.form_dict.get("course_state"),
			program=frappe.form_dict.get("program"),
		)
		return paginated_response(rows, page, total, per_page)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_course(course_id=None):
	try:
		course_id = course_id or frappe.form_dict.get("course_id")
		if not course_id:
			return error_response("course_id bắt buộc", code="VALIDATION_ERROR")
		data = course_service.get_course_detail(course_id)
		return single_item_response(data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_course():
	try:
		data = frappe.request.json or frappe.form_dict
		if isinstance(data.get("data"), str):
			data = json.loads(data["data"])
		result = course_service.create_course(data)
		return single_item_response(result, message="Course created")
	except Exception as exc:
		frappe.log_error(title="LMS create_course", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "PUT"])
def update_course():
	try:
		data = frappe.request.json or frappe.form_dict
		course_id = data.get("course_id") or data.get("name")
		if not course_id:
			return error_response("course_id bắt buộc", code="VALIDATION_ERROR")
		payload = {k: v for k, v in data.items() if k not in ("course_id", "name", "cmd")}
		result = course_service.update_course(course_id, payload)
		return single_item_response(result, message="Course updated")
	except Exception as exc:
		return error_response(str(exc))
