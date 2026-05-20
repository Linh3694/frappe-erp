# Discussion API — Phase 4

import frappe

from erp.lms.services import discussion_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_discussion():
	try:
		data = frappe.request.json or frappe.form_dict
		result = discussion_service.create_discussion(data)
		return single_item_response(result, message="Discussion created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_discussions():
	try:
		fd = frappe.form_dict
		rows = discussion_service.list_discussions(
			course_id=fd.get("course_id"),
			section_id=fd.get("section_id"),
		)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_discussion():
	try:
		fd = frappe.form_dict
		result = discussion_service.get_discussion(fd.get("discussion_id"))
		return single_item_response(result)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "PUT"])
def update_discussion():
	try:
		data = frappe.request.json or frappe.form_dict
		discussion_id = data.pop("discussion_id", None) or data.pop("name", None)
		result = discussion_service.update_discussion(discussion_id, data)
		return single_item_response(result, message="Discussion updated")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def post_entry():
	try:
		data = frappe.request.json or frappe.form_dict
		result = discussion_service.post_entry(
			discussion_id=data.get("discussion_id"),
			body=data.get("body"),
			parent_entry=data.get("parent_entry"),
		)
		return single_item_response(result, message="Entry posted")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_entries():
	"""Danh sách bài trong discussion (threads)."""
	try:
		fd = frappe.form_dict
		rows = discussion_service.list_entries(fd.get("discussion_id"))
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_threads():
	"""Alias — cùng list_entries."""
	return list_entries()


@frappe.whitelist(methods=["POST"])
def pin_entry():
	try:
		data = frappe.request.json or frappe.form_dict
		result = discussion_service.pin_entry(
			data.get("entry_id"),
			pinned=bool(int(data.get("pinned", 1))),
		)
		return single_item_response(result)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def hide_entry():
	try:
		data = frappe.request.json or frappe.form_dict
		result = discussion_service.hide_entry(
			data.get("entry_id"),
			hidden=bool(int(data.get("hidden", 1))),
		)
		return single_item_response(result)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def grade_participation():
	try:
		data = frappe.request.json or frappe.form_dict
		result = discussion_service.grade_discussion_participation(
			discussion_id=data.get("discussion_id"),
			student_id=data.get("student_id"),
			score=float(data.get("score", 0)),
		)
		return single_item_response(result, message="Graded")
	except Exception as exc:
		return error_response(str(exc))
