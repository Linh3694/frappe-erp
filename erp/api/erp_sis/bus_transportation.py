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
	logs = []
	def log_info(msg):
		logs.append(f"INFO: {msg}")
		frappe.logger().info(msg)
	def log_error(msg):
		logs.append(f"ERROR: {msg}")
		frappe.logger().error(msg)

	try:
		# Debug: Check if we have form data
		log_info(f"All received data: {dict(frappe.form_dict)}")
		log_info(f"Method data: {data}")
		log_info(f"Local data: {frappe.local.form_dict}")

		# Get data from form_dict if data is empty
		if not data or data.get('cmd'):
			form_data = dict(frappe.form_dict)
			# Remove cmd and other metadata
			form_data.pop('cmd', None)
			data = form_data
			log_info(f"Using form data instead: {data}")

		log_info(f"Creating bus transportation with data: {data}")

		# Enrich with driver information
		if data.get("driver_id"):
			log_info(f"Looking up driver: {data['driver_id']}")

			# Check if driver exists first
			if not frappe.db.exists("SIS Bus Driver", data["driver_id"]):
				log_error(f"Driver {data['driver_id']} does not exist in database")
				return error_response(f"Driver not found: {data['driver_id']}", logs=logs)

			try:
				driver = frappe.get_doc("SIS Bus Driver", data["driver_id"])
				log_info(f"Found driver: {driver.name} - {driver.full_name}")
				data.update({
					"driver_name": driver.full_name,
					"driver_phone": driver.phone_number
				})
			except Exception as driver_error:
				log_error(f"Error finding driver {data['driver_id']}: {str(driver_error)}")
				return error_response(f"Driver not found: {data['driver_id']} - {str(driver_error)}", logs=logs)

		log_info(f"Final data before creating doc: {data}")

		# Create document step by step to debug field mapping
		doc = frappe.new_doc("SIS Bus Transportation")

		# Set fields explicitly
		doc.vehicle_code = data.get("vehicle_code")
		doc.license_plate = data.get("license_plate")
		doc.vehicle_type = data.get("vehicle_type")
		doc.driver_id = data.get("driver_id")
		doc.status = data.get("status", "Active")
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
		WHERE status = 'Active'
		ORDER BY vehicle_code
	""", as_dict=True)
