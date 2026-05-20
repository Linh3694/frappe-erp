# Program & Section CRUD

import frappe

from erp.lms.utils.permissions import require_lms_staff
from erp.utils.api_response import error_response, single_item_response, success_response
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist(methods=["GET"])
def list_programs():
	try:
		campus_id = get_current_campus_from_context()
		filters = {"is_active": 1}
		if campus_id:
			filters["campus_id"] = campus_id
		rows = frappe.get_all(
			"LMS Program",
			filters=filters,
			fields=["name", "title", "campus_id", "school_year_id"],
			order_by="modified desc",
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_program():
	try:
		require_lms_staff()
		data = frappe.request.json or frappe.form_dict
		if not data.get("campus_id"):
			data["campus_id"] = get_current_campus_from_context()
		doc = frappe.get_doc({"doctype": "LMS Program", **data})
		doc.insert()
		return single_item_response(doc.as_dict(), message="Program created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_section():
	try:
		require_lms_staff()
		data = frappe.request.json or frappe.form_dict
		doc = frappe.get_doc({"doctype": "LMS Course Section", **data})
		doc.insert()
		return single_item_response(doc.as_dict(), message="Section created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_sections(course_id=None):
	try:
		course_id = course_id or frappe.form_dict.get("course_id")
		rows = frappe.get_all(
			"LMS Course Section",
			filters={"course": course_id},
			fields=["name", "section_name", "sis_class_id", "auto_sync_enrollment"],
			order_by="section_name asc",
		)
		return success_response(data=rows)
	except Exception as exc:
		return error_response(str(exc))
