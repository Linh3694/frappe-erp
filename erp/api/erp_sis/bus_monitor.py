# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context

@frappe.whitelist()
def get_all_bus_monitors():
	"""Get all bus monitors without pagination - always returns full dataset"""
	try:
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			# Fallback to default if no campus found
			campus_id = "campus-1"

		# Apply campus filtering for data isolation
		filters = {"campus_id": campus_id}

		# Get all bus monitors
		monitors = frappe.get_list(
			"SIS Bus Monitor",
			filters=filters,
			fields=[
				"name", "full_name", "monitor_code", "gender", "citizen_id",
				"phone_number", "contractor", "address", "status",
				"campus_id", "school_year_id", "creation", "modified"
			],
			order_by="full_name asc"
		)

		# Map field names to correct format
		for monitor in monitors:
			monitor['created_at'] = monitor.pop('creation')
			monitor['updated_at'] = monitor.pop('modified')

		return success_response(
			data=monitors,
			message="Bus monitors retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting bus monitors: {str(e)}")
		return error_response(f"Failed to get bus monitors: {str(e)}")

@frappe.whitelist()
def get_bus_monitor(name):
	"""Get a single bus monitor by name"""
	try:
		doc = frappe.get_doc("SIS Bus Monitor", name)
		return success_response(
			data=doc.as_dict(),
			message="Bus monitor retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting bus monitor: {str(e)}")
		return error_response(f"Bus monitor not found: {str(e)}")

@frappe.whitelist()
def create_bus_monitor(**data):
	"""Create a new bus monitor"""
	try:
		doc = frappe.get_doc({
			"doctype": "SIS Bus Monitor",
			**data
		})
		doc.insert()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus monitor created successfully"
		)
	except Exception as e:
		error_msg = str(e)
		# Truncate error message if too long for logging
		if len(error_msg) > 100:
			error_msg = error_msg[:100] + "..."
		frappe.log_error(f"Error creating bus monitor: {error_msg}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus monitor: {str(e)}")

@frappe.whitelist()
def update_bus_monitor(name, **data):
	"""Update an existing bus monitor"""
	try:
		doc = frappe.get_doc("SIS Bus Monitor", name)
		doc.update(data)
		doc.save()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus monitor updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating bus monitor: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update bus monitor: {str(e)}")

@frappe.whitelist()
def delete_bus_monitor(name):
	"""Delete a bus monitor"""
	try:
		frappe.delete_doc("SIS Bus Monitor", name)
		frappe.db.commit()

		return success_response(
			message="Bus monitor deleted successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error deleting bus monitor: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete bus monitor: {str(e)}")

@frappe.whitelist()
def get_available_monitors():
	"""Get available monitors (not assigned to active routes)"""
	assigned_monitors = frappe.db.sql("""
		SELECT DISTINCT monitor1_id, monitor2_id
		FROM `tabSIS Bus Route`
		WHERE status = 'Active'
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
			WHERE status = 'Active'
			ORDER BY full_name
		""", as_dict=True)
	else:
		# Return monitors not in assigned_ids
		placeholders = ','.join(['%s'] * len(assigned_ids))
		return frappe.db.sql(f"""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Monitor`
			WHERE status = 'Active'
			AND name NOT IN ({placeholders})
			ORDER BY full_name
		""", assigned_ids, as_dict=True)
