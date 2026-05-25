# Copyright (c) 2026, Wellspring International School
# API phòng — proxy ERP Administrative Room cho FE inventory

import frappe
from frappe import _

from erp.utils.api_response import error_response, list_response
from erp.utils.campus_utils import get_current_campus_from_context
from erp.api.erp_inventory.inventory_helpers import room_to_fe


@frappe.whitelist(allow_guest=False)
def get_all_rooms():
	"""Danh sách phòng từ Frappe — thay Mongo Room collection."""
	try:
		campus_id = get_current_campus_from_context()
		filters = {}
		if campus_id:
			filters["campus_id"] = campus_id

		rows = frappe.get_all(
			"ERP Administrative Room",
			filters=filters,
			fields=["name"],
			order_by="physical_code asc",
			limit=5000,
		)
		rooms = [room_to_fe(r.name) for r in rows if room_to_fe(r.name)]
		return {"rooms": rooms, "data": rooms}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.get_all_rooms")
		return error_response(str(e))
