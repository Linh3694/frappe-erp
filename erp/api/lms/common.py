# Auth / context cho LMS Portal

import frappe

from erp.lms.utils.permissions import is_lms_staff
from erp.utils.api_response import single_item_response
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist(methods=["GET"])
def me():
	"""Thông tin user hiện tại + vai trò LMS."""
	user = frappe.session.user
	roles = frappe.get_roles(user)
	data = {
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name"),
		"email": frappe.db.get_value("User", user, "email"),
		"roles": roles,
		"is_lms_staff": is_lms_staff(user),
		"campus_id": get_current_campus_from_context(),
	}
	return single_item_response(data)
