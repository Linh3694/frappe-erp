# Grade sync API — Phase 5

import frappe

from erp.lms.services import grade_sync_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_sync_rule():
	try:
		data = frappe.request.json or frappe.form_dict
		result = grade_sync_service.create_sync_rule(data)
		return single_item_response(result, message="Sync rule created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_sync_rules():
	try:
		fd = frappe.form_dict
		rows = grade_sync_service.list_sync_rules(
			section_id=fd.get("section_id"),
			grade_column_id=fd.get("grade_column_id"),
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def finalize_column():
	try:
		data = frappe.request.json or frappe.form_dict
		result = grade_sync_service.finalize_grade_column(data.get("column_id"))
		return single_item_response(result, message="Column finalized")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def push_column():
	try:
		data = frappe.request.json or frappe.form_dict
		result = grade_sync_service.push_column(
			data.get("column_id"),
			force_override=bool(int(data.get("force_override", 0))),
		)
		return success_response(data=result, message="Push completed")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def approve():
	try:
		data = frappe.request.json or frappe.form_dict
		result = grade_sync_service.approve_sync_logs(
			data.get("log_ids") or data.get("log_id"),
			force_override=bool(int(data.get("force_override", 0))),
		)
		return success_response(data=result, message="Approved")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_logs():
	try:
		fd = frappe.form_dict
		rows = grade_sync_service.list_sync_logs(
			grade_column_id=fd.get("grade_column_id"),
			section_id=fd.get("section_id"),
			status=fd.get("status"),
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))
