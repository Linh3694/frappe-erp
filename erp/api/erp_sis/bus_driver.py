# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.api.utils import get_list, get_single, create_doc, update_doc, delete_doc

@frappe.whitelist()
def get_all_bus_drivers(page=1, limit=20, **filters):
	"""Get all bus drivers with pagination"""
	return get_list(
		"SIS Bus Driver",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "full_name", "driver_code", "gender", "citizen_id",
			"phone_number", "contractor", "address", "status",
			"campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="creation desc"
	)

@frappe.whitelist()
def get_bus_driver(name):
	"""Get a single bus driver by name"""
	return get_single("SIS Bus Driver", name)

@frappe.whitelist()
def create_bus_driver(**data):
	"""Create a new bus driver"""
	return create_doc("SIS Bus Driver", data)

@frappe.whitelist()
def update_bus_driver(name, **data):
	"""Update an existing bus driver"""
	return update_doc("SIS Bus Driver", name, data)

@frappe.whitelist()
def delete_bus_driver(name):
	"""Delete a bus driver"""
	return delete_doc("SIS Bus Driver", name)

@frappe.whitelist()
def get_available_drivers():
	"""Get available drivers (not assigned to active transportation)"""
	assigned_drivers = frappe.db.sql("""
		SELECT DISTINCT driver_id
		FROM `tabSIS Bus Transportation`
		WHERE status = 'Hoạt động'
	""", as_dict=True)

	assigned_ids = [assignment.driver_id for assignment in assigned_drivers if assignment.driver_id]

	if not assigned_ids:
		# Return all active drivers
		return frappe.db.sql("""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Driver`
			WHERE status = 'Hoạt động'
			ORDER BY full_name
		""", as_dict=True)
	else:
		# Return drivers not in assigned_ids
		placeholders = ','.join(['%s'] * len(assigned_ids))
		return frappe.db.sql(f"""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Driver`
			WHERE status = 'Hoạt động'
			AND name NOT IN ({placeholders})
			ORDER BY full_name
		""", assigned_ids, as_dict=True)
