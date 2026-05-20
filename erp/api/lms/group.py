# Group API — Phase 4

import frappe

from erp.lms.services import group_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_group():
	try:
		data = frappe.request.json or frappe.form_dict
		result = group_service.create_group(data)
		return single_item_response(result, message="Group created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_groups():
	try:
		fd = frappe.form_dict
		rows = group_service.list_groups(fd.get("section_id"))
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def assign_members():
	try:
		data = frappe.request.json or frappe.form_dict
		result = group_service.assign_members(
			data.get("group_id"),
			data.get("student_ids") or data.get("students"),
		)
		return success_response(data=result, message="Members assigned")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def random_split():
	try:
		data = frappe.request.json or frappe.form_dict
		rows = group_service.random_split(
			section_id=data.get("section_id"),
			group_count=int(data["group_count"]) if data.get("group_count") else None,
			max_members=int(data.get("max_members") or 4),
		)
		return success_response(data=rows, message="Groups created")
	except Exception as exc:
		return error_response(str(exc))
