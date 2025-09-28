# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.api.utils import get_list, get_single, create_doc, update_doc, delete_doc

@frappe.whitelist()
def get_all_bus_students(page=1, limit=20, **filters):
	"""Get all bus students with pagination"""
	return get_list(
		"SIS Bus Student",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "full_name", "student_code", "class_name", "route_name",
			"status", "campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="creation desc"
	)

@frappe.whitelist()
def get_bus_student(name):
	"""Get a single bus student by name"""
	return get_single("SIS Bus Student", name)

@frappe.whitelist()
def create_bus_student(**data):
	"""Create a new bus student"""
	return create_doc("SIS Bus Student", data)

@frappe.whitelist()
def update_bus_student(name, **data):
	"""Update an existing bus student"""
	return update_doc("SIS Bus Student", name, data)

@frappe.whitelist()
def delete_bus_student(name):
	"""Delete a bus student"""
	return delete_doc("SIS Bus Student", name)

@frappe.whitelist()
def get_available_classes():
	"""Get available classes"""
	return frappe.db.sql("""
		SELECT name, class_name
		FROM `tabSIS Class`
		WHERE status = 'Active'
		ORDER BY class_name
	""", as_dict=True)

@frappe.whitelist()
def get_available_routes():
	"""Get available routes"""
	return frappe.db.sql("""
		SELECT name, route_name
		FROM `tabSIS Bus Route`
		WHERE status = 'Hoạt động'
		ORDER BY route_name
	""", as_dict=True)
