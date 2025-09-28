# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context

@frappe.whitelist()
def get_all_bus_transportation():
	"""Get all bus transportation without pagination - always returns full dataset"""
	try:
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			# Fallback to default if no campus found
			campus_id = "campus-1"

		# Apply campus filtering for data isolation
		filters = {"campus_id": campus_id}

		# Get all bus transportation
		transportation = frappe.get_list(
			"SIS Bus Transportation",
			filters=filters,
			fields=[
				"name", "vehicle_code", "license_plate", "vehicle_type",
				"driver_id", "status", "campus_id", "school_year_id",
				"creation", "modified"
			],
			order_by="vehicle_code asc"
		)

		# Map field names to correct format
		for item in transportation:
			item['created_at'] = item.pop('creation')
			item['updated_at'] = item.pop('modified')

		# Enrich with driver information
		for item in transportation:
			if item.driver_id:
				driver = frappe.get_doc("SIS Bus Driver", item.driver_id)
				item.update({
					"driver_name": driver.full_name,
					"driver_phone": driver.phone_number
				})

		return success_response(
			data=transportation,
			message="Bus transportation retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting bus transportation: {str(e)}")
		return error_response(f"Failed to get bus transportation: {str(e)}")

@frappe.whitelist()
def get_bus_transportation(name):
	"""Get a single bus transportation by name"""
	try:
		doc = frappe.get_doc("SIS Bus Transportation", name)

		# Enrich with driver information
		if doc.driver_id:
			driver = frappe.get_doc("SIS Bus Driver", doc.driver_id)
			doc.update({
				"driver_name": driver.full_name,
				"driver_phone": driver.phone_number
			})

		return success_response(
			data=doc.as_dict(),
			message="Bus transportation retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting bus transportation: {str(e)}")
		return error_response(f"Bus transportation not found: {str(e)}")

@frappe.whitelist()
def create_bus_transportation(**data):
	"""Create a new bus transportation"""
	try:
		# Enrich with driver information
		if data.get("driver_id"):
			driver = frappe.get_doc("SIS Bus Driver", data["driver_id"])
			data.update({
				"driver_name": driver.full_name,
				"driver_phone": driver.phone_number
			})

		doc = frappe.get_doc({
			"doctype": "SIS Bus Transportation",
			**data
		})
		doc.insert()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus transportation created successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error creating bus transportation: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus transportation: {str(e)}")

@frappe.whitelist()
def update_bus_transportation(name, **data):
	"""Update an existing bus transportation"""
	try:
		# Enrich with driver information
		if data.get("driver_id"):
			driver = frappe.get_doc("SIS Bus Driver", data["driver_id"])
			data.update({
				"driver_name": driver.full_name,
				"driver_phone": driver.phone_number
			})

		doc = frappe.get_doc("SIS Bus Transportation", name)
		doc.update(data)
		doc.save()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus transportation updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating bus transportation: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update bus transportation: {str(e)}")

@frappe.whitelist()
def delete_bus_transportation(name):
	"""Delete a bus transportation"""
	try:
		frappe.delete_doc("SIS Bus Transportation", name)
		frappe.db.commit()

		return success_response(
			message="Bus transportation deleted successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error deleting bus transportation: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete bus transportation: {str(e)}")

@frappe.whitelist()
def get_available_vehicles():
	"""Get all available vehicles"""
	return frappe.db.sql("""
		SELECT name, vehicle_code, license_plate, vehicle_type
		FROM `tabSIS Bus Transportation`
		WHERE status = 'Hoạt động'
		ORDER BY vehicle_code
	""", as_dict=True)
