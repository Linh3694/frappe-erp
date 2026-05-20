# Outcome API — Phase 4

import frappe

from erp.lms.services import outcome_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_outcome():
	try:
		data = frappe.request.json or frappe.form_dict
		result = outcome_service.create_outcome(data)
		return single_item_response(result, message="Outcome created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_outcomes():
	try:
		fd = frappe.form_dict
		rows = outcome_service.list_outcomes(fd.get("course_id"))
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def import_from_sis():
	try:
		data = frappe.request.json or frappe.form_dict
		rows = outcome_service.import_outcomes_from_sis(
			course_id=data.get("course_id"),
			sis_sub_curriculum_id=data.get("sis_sub_curriculum_id"),
		)
		return success_response(data=rows, message=f"Imported {len(rows)} outcomes")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def align_outcome():
	try:
		data = frappe.request.json or frappe.form_dict
		result = outcome_service.align_outcome_to_course(
			outcome_id=data.get("outcome_id"),
			course_id=data.get("course_id"),
		)
		return single_item_response(result, message="Outcome aligned")
	except Exception as exc:
		return error_response(str(exc))
