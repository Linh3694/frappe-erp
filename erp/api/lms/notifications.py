# Notifications API — Phase 6

import frappe

from erp.lms.services import notifications_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["GET"])
def get_preferences():
	try:
		data = notifications_service.get_preferences()
		return success_response(data=data)
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def update_preferences():
	try:
		data = frappe.request.json or frappe.form_dict
		result = notifications_service.update_preferences(data)
		return single_item_response(result, message="Preferences updated")
	except Exception as exc:
		return error_response(str(exc))
