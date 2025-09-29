# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import json
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
				"status", "campus_id", "school_year_id",
				"creation", "modified"
			],
			order_by="vehicle_code asc"
		)

		# Map field names to correct format
		for item in transportation:
			item['created_at'] = item.pop('creation')
			item['updated_at'] = item.pop('modified')

		return success_response(
			data=transportation,
			message="Bus transportation retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting bus transportation: {str(e)}")
		return error_response(f"Failed to get bus transportation: {str(e)}")

@frappe.whitelist()
def get_bus_transportation():
	"""Get a single bus transportation by name"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		if not name:
			return error_response("Bus transportation name is required")
			
		doc = frappe.get_doc("SIS Bus Transportation", name)

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
	logs = []
	def log_info(msg):
		logs.append(f"INFO: {msg}")
		frappe.logger().info(msg)
	def log_error(msg):
		logs.append(f"ERROR: {msg}")
		frappe.logger().error(msg)

	try:
		# Parse request body if it contains URL-encoded data
		if not data or data.get('cmd'):
			if frappe.request.data and isinstance(frappe.request.data, bytes):
				try:
					# Parse URL-encoded data from request body
					from urllib.parse import unquote_plus
					body_string = frappe.request.data.decode('utf-8')
					
					# Parse URL-encoded data
					parsed_data = {}
					for pair in body_string.split('&'):
						if '=' in pair:
							key, value = pair.split('=', 1)
							parsed_data[unquote_plus(key)] = unquote_plus(value)
					
					data = parsed_data
				except Exception as parse_error:
					log_error(f"Failed to parse request body: {str(parse_error)}")
					# Fallback to form_dict
					form_data = dict(frappe.form_dict)
					form_data.pop('cmd', None)
					data = form_data
			else:
				# Fallback to form_dict
				form_data = dict(frappe.form_dict)
				form_data.pop('cmd', None)
				data = form_data

		# No driver information needed in Bus Transportation

		log_info(f"Final data before creating doc: {data}")

		# Create document step by step to debug field mapping
		doc = frappe.new_doc("SIS Bus Transportation")

		# Set fields explicitly
		doc.vehicle_code = data.get("vehicle_code")
		doc.license_plate = data.get("license_plate")
		doc.vehicle_type = data.get("vehicle_type")
		# Map frontend status (lowercase) to backend status (capitalized)
		status = data.get("status", "active")
		doc.status = "Active" if status == "active" else "Inactive"
		doc.campus_id = data.get("campus_id")
		doc.school_year_id = data.get("school_year_id")

		log_info(f"Document before insert: {doc.as_dict()}")

		# Validate document before insert
		try:
			doc.validate()
			log_info("Document validation passed")
		except Exception as validation_error:
			log_error(f"Document validation failed: {str(validation_error)}")
			return error_response(f"Validation failed: {str(validation_error)}", logs=logs)

		doc.insert()
		log_info(f"Document after insert: {doc.as_dict()}")
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus transportation created successfully",
			logs=logs
		)
	except Exception as e:
		log_error(f"Error creating bus transportation: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus transportation: {str(e)}", logs=logs)

@frappe.whitelist()
def update_bus_transportation(**data):
	"""Update an existing bus transportation"""
	try:
		# Get name from data (sent by frontend as part of data object)
		name = data.get('name')
		if not name:
			return error_response("Bus transportation name is required")
			
		# Remove name from data before updating document
		data.pop('name', None)
		
		# Map frontend status (lowercase) to backend status (capitalized) if present
		if data.get("status"):
			status = data.get("status")
			data["status"] = "Active" if status == "active" else "Inactive"

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
def delete_bus_transportation():
	"""Delete a bus transportation"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		if not name:
			return error_response("Bus transportation name is required")
			
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
		WHERE status = 'Active'
		ORDER BY vehicle_code
	""", as_dict=True)
