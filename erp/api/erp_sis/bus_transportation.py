# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.api.utils import get_list, get_single, create_doc, update_doc, delete_doc

@frappe.whitelist()
def get_all_bus_transportation(page=1, limit=20, **filters):
	"""Get all bus transportation with pagination"""
	return get_list(
		"SIS Bus Transportation",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "vehicle_code", "license_plate", "vehicle_type",
			"driver_id", "driver_name", "driver_phone", "status",
			"campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="creation desc"
	)

@frappe.whitelist()
def get_bus_transportation(name):
	"""Get a single bus transportation by name"""
	doc = get_single("SIS Bus Transportation", name)
	if doc and doc.driver_id:
		# Get driver details
		driver = frappe.get_doc("SIS Bus Driver", doc.driver_id)
		doc.update({
			"driver_name": driver.full_name,
			"driver_phone": driver.phone_number
		})
	return doc

@frappe.whitelist()
def create_bus_transportation(**data):
	"""Create a new bus transportation"""
	if data.get("driver_id"):
		driver = frappe.get_doc("SIS Bus Driver", data["driver_id"])
		data.update({
			"driver_name": driver.full_name,
			"driver_phone": driver.phone_number
		})
	return create_doc("SIS Bus Transportation", data)

@frappe.whitelist()
def update_bus_transportation(name, **data):
	"""Update an existing bus transportation"""
	if data.get("driver_id"):
		driver = frappe.get_doc("SIS Bus Driver", data["driver_id"])
		data.update({
			"driver_name": driver.full_name,
			"driver_phone": driver.phone_number
		})
	return update_doc("SIS Bus Transportation", name, data)

@frappe.whitelist()
def delete_bus_transportation(name):
	"""Delete a bus transportation"""
	return delete_doc("SIS Bus Transportation", name)

@frappe.whitelist()
def get_available_vehicles():
	"""Get all available vehicles"""
	return frappe.db.sql("""
		SELECT name, vehicle_code, license_plate, vehicle_type
		FROM `tabSIS Bus Transportation`
		WHERE status = 'Hoạt động'
		ORDER BY vehicle_code
	""", as_dict=True)
