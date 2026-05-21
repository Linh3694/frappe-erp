# LMS Module & Module Item

import frappe

from erp.lms.utils.permissions import require_lms_staff
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def create_module():
	try:
		require_lms_staff()
		data = dict(frappe.request.json or frappe.form_dict)
		course = data.get("course") or data.get("course_id")
		if not course:
			return error_response(
				"course hoặc course_id bắt buộc",
				code="VALIDATION_ERROR",
			)
		data["course"] = course
		data.pop("course_id", None)
		doc = frappe.get_doc({"doctype": "LMS Module", **data})
		doc.insert()
		return single_item_response(doc.as_dict(), message="Module created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_module_item():
	try:
		require_lms_staff()
		data = frappe.request.json or frappe.form_dict
		doc = frappe.get_doc({"doctype": "LMS Module Item", **data})
		doc.insert()
		return single_item_response(doc.as_dict(), message="Module item created")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST", "PUT"])
def update_module_item():
	try:
		require_lms_staff()
		data = frappe.request.json or frappe.form_dict
		item_id = data.get("name") or data.get("item_id")
		if not item_id:
			return error_response("item_id bắt buộc", code="VALIDATION_ERROR")
		doc = frappe.get_doc("LMS Module Item", item_id)
		doc.update({k: v for k, v in data.items() if k not in ("name", "item_id", "cmd")})
		doc.save()
		return single_item_response(doc.as_dict(), message="Module item updated")
	except Exception as exc:
		return error_response(str(exc))
