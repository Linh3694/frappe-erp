# LMS Enrollment

import json

import frappe

from erp.lms.utils.permissions import require_lms_staff
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def list_enrollments(section=None):
	try:
		require_lms_staff()
		filters = {"status": "active"}
		if section:
			filters["section"] = section
		rows = frappe.get_all(
			"LMS Enrollment",
			filters=filters,
			fields=[
				"name",
				"section",
				"student_id",
				"user",
				"role",
				"status",
				"modified",
			],
			order_by="modified desc",
			limit=500,
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_enrollment():
	try:
		require_lms_staff()
		data = frappe.request.json or frappe.form_dict
		doc = frappe.get_doc({"doctype": "LMS Enrollment", **data})
		doc.insert()
		return single_item_response(doc.as_dict(), message="Enrollment created")
	except Exception as exc:
		frappe.log_error(title="LMS create_enrollment", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def delete_enrollment(enrollment_id=None):
	try:
		require_lms_staff()
		enrollment_id = enrollment_id or (frappe.request.json or frappe.form_dict).get("enrollment_id")
		if not enrollment_id:
			return error_response("enrollment_id bắt buộc", code="VALIDATION_ERROR")
		frappe.delete_doc("LMS Enrollment", enrollment_id)
		return success_response(message="Enrollment deleted")
	except Exception as exc:
		return error_response(str(exc))
