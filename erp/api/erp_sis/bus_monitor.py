# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.api.utils import get_list, get_single, create_doc, update_doc, delete_doc

@frappe.whitelist()
def get_all_bus_monitors(page=1, limit=20, **filters):
	"""Get all bus monitors with pagination"""
	return get_list(
		"SIS Bus Monitor",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "full_name", "monitor_code", "gender", "citizen_id",
			"phone_number", "contractor", "address", "status",
			"campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="creation desc"
	)

@frappe.whitelist()
def get_bus_monitor(name):
	"""Get a single bus monitor by name"""
	return get_single("SIS Bus Monitor", name)

@frappe.whitelist()
def create_bus_monitor(**data):
	"""Create a new bus monitor"""
	return create_doc("SIS Bus Monitor", data)

@frappe.whitelist()
def update_bus_monitor(name, **data):
	"""Update an existing bus monitor"""
	return update_doc("SIS Bus Monitor", name, data)

@frappe.whitelist()
def delete_bus_monitor(name):
	"""Delete a bus monitor"""
	return delete_doc("SIS Bus Monitor", name)

@frappe.whitelist()
def get_available_monitors():
	"""Get available monitors (not assigned to active routes)"""
	assigned_monitors = frappe.db.sql("""
		SELECT DISTINCT monitor1_id, monitor2_id
		FROM `tabSIS Bus Route`
		WHERE status = 'Hoạt động'
	""", as_dict=True)

	assigned_ids = []
	for assignment in assigned_monitors:
		if assignment.monitor1_id:
			assigned_ids.append(assignment.monitor1_id)
		if assignment.monitor2_id:
			assigned_ids.append(assignment.monitor2_id)

	if not assigned_ids:
		# Return all active monitors
		return frappe.db.sql("""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Monitor`
			WHERE status = 'Hoạt động'
			ORDER BY full_name
		""", as_dict=True)
	else:
		# Return monitors not in assigned_ids
		placeholders = ','.join(['%s'] * len(assigned_ids))
		return frappe.db.sql(f"""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Monitor`
			WHERE status = 'Hoạt động'
			AND name NOT IN ({placeholders})
			ORDER BY full_name
		""", assigned_ids, as_dict=True)
