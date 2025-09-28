# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context

@frappe.whitelist()
def get_all_bus_drivers():
	"""Get all bus drivers without pagination - always returns full dataset"""
	try:
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			# Fallback to default if no campus found
			campus_id = "campus-1"

		# Apply campus filtering for data isolation
		filters = {"campus_id": campus_id}

		# Get all bus drivers
		drivers = frappe.get_list(
			"SIS Bus Driver",
			filters=filters,
			fields=[
				"name", "full_name", "driver_code", "gender", "citizen_id",
				"phone_number", "contractor", "address", "status",
				"campus_id", "school_year_id", "creation", "modified"
			],
			order_by="full_name asc"
		)

		# Map field names to correct format
		for driver in drivers:
			driver['created_at'] = driver.pop('creation')
			driver['updated_at'] = driver.pop('modified')

		return success_response(
			data=drivers,
			message="Bus drivers retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting bus drivers: {str(e)}")
		return error_response(f"Failed to get bus drivers: {str(e)}")

@frappe.whitelist()
def get_bus_driver():
	"""Get a single bus driver by name"""
	try:
		name = frappe.local.form_dict.get('name')
		if not name:
			return error_response("Bus driver name is required")

		doc = frappe.get_doc("SIS Bus Driver", name)
		return success_response(
			data=doc.as_dict(),
			message="Bus driver retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting bus driver: {str(e)}")
		return error_response(f"Bus driver not found: {str(e)}")

@frappe.whitelist()
def create_bus_driver():
	"""Create a new bus driver"""
	try:
		# Get data from request
		data = {}

		# First try to get JSON data from request body
		if frappe.request.data:
			try:
				# Support both bytes and string payloads
				if isinstance(frappe.request.data, bytes):
					json_data = json.loads(frappe.request.data.decode('utf-8'))
				else:
					json_data = json.loads(frappe.request.data)

				if json_data:
					data = json_data
					frappe.logger().info(f"Received JSON data for create_bus_driver: {data}")
				else:
					data = frappe.local.form_dict
					frappe.logger().info(f"Received form data for create_bus_driver (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in create_bus_driver: {str(e)}")
				data = frappe.local.form_dict
				frappe.logger().info(f"Using form data for create_bus_driver after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			frappe.logger().info(f"No request data, using form_dict for create_bus_driver: {data}")

		doc = frappe.get_doc({
			"doctype": "SIS Bus Driver",
			**data
		})
		doc.insert()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus driver created successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error creating bus driver: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus driver: {str(e)}")

@frappe.whitelist()
def update_bus_driver():
	"""Update an existing bus driver"""
	try:
		name = frappe.local.form_dict.get('name')
		if not name:
			return error_response("Bus driver name is required")

		# Get update data from request
		data = {}

		# First try to get JSON data from request body
		if frappe.request.data:
			try:
				# Support both bytes and string payloads
				if isinstance(frappe.request.data, bytes):
					json_data = json.loads(frappe.request.data.decode('utf-8'))
				else:
					json_data = json.loads(frappe.request.data)

				if json_data:
					data = json_data
					# Remove name from data if it exists
					data.pop('name', None)
					frappe.logger().info(f"Received JSON data for update_bus_driver: {data}")
				else:
					data = frappe.local.form_dict
					# Remove name from data
					data.pop('name', None)
					frappe.logger().info(f"Received form data for update_bus_driver (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in update_bus_driver: {str(e)}")
				data = frappe.local.form_dict
				data.pop('name', None)
				frappe.logger().info(f"Using form data for update_bus_driver after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			data.pop('name', None)
			frappe.logger().info(f"No request data, using form_dict for update_bus_driver: {data}")

		doc = frappe.get_doc("SIS Bus Driver", name)
		doc.update(data)
		doc.save()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus driver updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating bus driver: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update bus driver: {str(e)}")

@frappe.whitelist()
def delete_bus_driver():
	"""Delete a bus driver"""
	try:
		name = frappe.local.form_dict.get('name')
		if not name:
			return error_response("Bus driver name is required")

		frappe.delete_doc("SIS Bus Driver", name)
		frappe.db.commit()

		return success_response(
			message="Bus driver deleted successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error deleting bus driver: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete bus driver: {str(e)}")

@frappe.whitelist()
def get_available_drivers():
	"""Get available drivers (not assigned to active transportation)"""
	assigned_drivers = frappe.db.sql("""
		SELECT DISTINCT driver_id
		FROM `tabSIS Bus Transportation`
		WHERE status = 'Active'
	""", as_dict=True)

	assigned_ids = [assignment.driver_id for assignment in assigned_drivers if assignment.driver_id]

	if not assigned_ids:
		# Return all active drivers
		return frappe.db.sql("""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Driver`
			WHERE status = 'Active'
			ORDER BY full_name
		""", as_dict=True)
	else:
		# Return drivers not in assigned_ids
		placeholders = ','.join(['%s'] * len(assigned_ids))
		return frappe.db.sql(f"""
			SELECT name, full_name, phone_number, citizen_id
			FROM `tabSIS Bus Driver`
			WHERE status = 'Active'
			AND name NOT IN ({placeholders})
			ORDER BY full_name
		""", assigned_ids, as_dict=True)
