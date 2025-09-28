# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.api.utils import get_list, get_single, create_doc, update_doc, delete_doc

@frappe.whitelist()
def get_all_bus_routes(page=1, limit=20, **filters):
	"""Get all bus routes with pagination"""
	return get_list(
		"SIS Bus Route",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "route_name", "vehicle_id", "driver_id", "monitor1_id", "monitor2_id",
			"status", "campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="creation desc"
	)

@frappe.whitelist()
def get_bus_route(name):
	"""Get a single bus route by name with full details"""
	doc = get_single("SIS Bus Route", name)
	if doc:
		# Get related entity details
		if doc.vehicle_id:
			vehicle = frappe.get_doc("SIS Bus Transportation", doc.vehicle_id)
			doc.update({
				"vehicle_code": vehicle.vehicle_code,
				"vehicle_type": vehicle.vehicle_type,
				"license_plate": vehicle.license_plate
			})

		if doc.driver_id:
			driver = frappe.get_doc("SIS Bus Driver", doc.driver_id)
			doc.update({
				"driver_name": driver.full_name,
				"driver_phone": driver.phone_number
			})

		if doc.monitor1_id:
			monitor1 = frappe.get_doc("SIS Bus Monitor", doc.monitor1_id)
			doc.update({
				"monitor1_name": monitor1.full_name,
				"monitor1_phone": monitor1.phone_number
			})

		if doc.monitor2_id:
			monitor2 = frappe.get_doc("SIS Bus Monitor", doc.monitor2_id)
			doc.update({
				"monitor2_name": monitor2.full_name,
				"monitor2_phone": monitor2.phone_number
			})

		# Get route students
		students = frappe.db.sql("""
			SELECT
				name, student_id, weekday, trip_type, pickup_order,
				pickup_location, drop_off_location, notes
			FROM `tabSIS Bus Route Student`
			WHERE route_id = %s
			ORDER BY
				CASE weekday
					WHEN 'Thứ 2' THEN 1
					WHEN 'Thứ 3' THEN 2
					WHEN 'Thứ 4' THEN 3
					WHEN 'Thứ 5' THEN 4
					WHEN 'Thứ 6' THEN 5
					WHEN 'Thứ 7' THEN 6
					WHEN 'Chủ nhật' THEN 7
				END,
				CASE trip_type
					WHEN 'Đón' THEN 1
					WHEN 'Trả' THEN 2
				END,
				pickup_order
		""", (name,), as_dict=True)

		doc.update({"route_students": students})

	return doc

@frappe.whitelist()
def create_bus_route(**data):
	"""Create a new bus route"""
	# Validate that monitors are different
	if data.get("monitor1_id") == data.get("monitor2_id"):
		frappe.throw("Monitor 1 và Monitor 2 không được giống nhau")

	# Check if monitors are already assigned to other routes
	monitor1_id = data.get("monitor1_id")
	monitor2_id = data.get("monitor2_id")

	if monitor1_id:
		existing_routes = frappe.db.sql("""
			SELECT name, route_name
			FROM `tabSIS Bus Route`
			WHERE (monitor1_id = %s OR monitor2_id = %s)
			AND name != %s
			AND status = 'Hoạt động'
		""", (monitor1_id, monitor1_id, data.get("name", "")), as_dict=True)

		if existing_routes:
			route_names = [route.route_name for route in existing_routes]
			frappe.throw(f"Monitor 1 đã được phân công cho tuyến: {', '.join(route_names)}")

	if monitor2_id:
		existing_routes = frappe.db.sql("""
			SELECT name, route_name
			FROM `tabSIS Bus Route`
			WHERE (monitor1_id = %s OR monitor2_id = %s)
			AND name != %s
			AND status = 'Hoạt động'
		""", (monitor2_id, monitor2_id, data.get("name", "")), as_dict=True)

		if existing_routes:
			route_names = [route.route_name for route in existing_routes]
			frappe.throw(f"Monitor 2 đã được phân công cho tuyến: {', '.join(route_names)}")

	return create_doc("SIS Bus Route", data)

@frappe.whitelist()
def update_bus_route(name, **data):
	"""Update an existing bus route"""
	# Validate that monitors are different
	if data.get("monitor1_id") == data.get("monitor2_id"):
		frappe.throw("Monitor 1 và Monitor 2 không được giống nhau")

	# Check if monitors are already assigned to other routes
	monitor1_id = data.get("monitor1_id")
	monitor2_id = data.get("monitor2_id")

	if monitor1_id:
		existing_routes = frappe.db.sql("""
			SELECT name, route_name
			FROM `tabSIS Bus Route`
			WHERE (monitor1_id = %s OR monitor2_id = %s)
			AND name != %s
			AND status = 'Hoạt động'
		""", (monitor1_id, monitor1_id, name), as_dict=True)

		if existing_routes:
			route_names = [route.route_name for route in existing_routes]
			frappe.throw(f"Monitor 1 đã được phân công cho tuyến: {', '.join(route_names)}")

	if monitor2_id:
		existing_routes = frappe.db.sql("""
			SELECT name, route_name
			FROM `tabSIS Bus Route`
			WHERE (monitor1_id = %s OR monitor2_id = %s)
			AND name != %s
			AND status = 'Hoạt động'
		""", (monitor2_id, monitor2_id, name), as_dict=True)

		if existing_routes:
			route_names = [route.route_name for route in existing_routes]
			frappe.throw(f"Monitor 2 đã được phân công cho tuyến: {', '.join(route_names)}")

	return update_doc("SIS Bus Route", name, data)

@frappe.whitelist()
def delete_bus_route(name):
	"""Delete a bus route"""
	return delete_doc("SIS Bus Route", name)

@frappe.whitelist()
def add_student_to_route(route_id, student_id, weekday, trip_type, pickup_order, pickup_location, drop_off_location, notes=None):
	"""Add a student to a bus route"""
	student_data = {
		"route_id": route_id,
		"student_id": student_id,
		"weekday": weekday,
		"trip_type": trip_type,
		"pickup_order": pickup_order,
		"pickup_location": pickup_location,
		"drop_off_location": drop_off_location
	}

	if notes:
		student_data["notes"] = notes

	# Check if student is already assigned to another route for same weekday/trip_type
	existing_assignment = frappe.db.exists("SIS Bus Route Student", {
		"student_id": student_id,
		"route_id": ("!=", route_id)
	})

	if existing_assignment:
		frappe.throw("Học sinh đã được phân công cho tuyến khác")

	# Check if pickup order is unique within the route for same weekday/trip_type
	existing_order = frappe.db.exists("SIS Bus Route Student", {
		"route_id": route_id,
		"pickup_order": pickup_order,
		"weekday": weekday,
		"trip_type": trip_type
	})

	if existing_order:
		frappe.throw(f"Thứ tự {pickup_order} đã tồn tại trong tuyến này cho {weekday} - {trip_type}")

	# Check if student is already assigned for this weekday/trip_type in the same route
	existing_student_assignment = frappe.db.exists("SIS Bus Route Student", {
		"route_id": route_id,
		"student_id": student_id,
		"weekday": weekday,
		"trip_type": trip_type
	})

	if existing_student_assignment:
		frappe.throw(f"Học sinh đã được phân công cho tuyến này vào {weekday} - {trip_type}")

	return create_doc("SIS Bus Route Student", student_data)

@frappe.whitelist()
def remove_student_from_route(route_student_id):
	"""Remove a student from a bus route"""
	return delete_doc("SIS Bus Route Student", route_student_id)

@frappe.whitelist()
def update_student_in_route(route_student_id, **data):
	"""Update a student in a bus route"""
	return update_doc("SIS Bus Route Student", route_student_id, data)

@frappe.whitelist()
def get_students_by_route(route_id):
	"""Get all students assigned to a specific route"""
	return frappe.db.sql("""
		SELECT
			name, student_id, weekday, trip_type, pickup_order,
			pickup_location, drop_off_location, notes
		FROM `tabSIS Bus Route Student`
		WHERE route_id = %s
		ORDER BY
			CASE weekday
				WHEN 'Thứ 2' THEN 1
				WHEN 'Thứ 3' THEN 2
				WHEN 'Thứ 4' THEN 3
				WHEN 'Thứ 5' THEN 4
				WHEN 'Thứ 6' THEN 5
				WHEN 'Thứ 7' THEN 6
				WHEN 'Chủ nhật' THEN 7
			END,
			CASE trip_type
				WHEN 'Đón' THEN 1
				WHEN 'Trả' THEN 2
			END,
			pickup_order
	""", (route_id,), as_dict=True)

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

@frappe.whitelist()
def get_available_students(campus_id=None, school_year_id=None):
	"""Get students not assigned to any bus route"""
	conditions = []
	params = []

	if campus_id:
		conditions.append("s.campus_id = %s")
		params.append(campus_id)

	if school_year_id:
		conditions.append("s.school_year_id = %s")
		params.append(school_year_id)

	where_clause = " AND ".join(conditions) if conditions else "1=1"

	return frappe.db.sql(f"""
		SELECT s.name, s.full_name, s.student_code, c.class_name
		FROM `tabSIS Student` s
		LEFT JOIN `tabSIS Class` c ON s.class_id = c.name
		WHERE s.status = 'Active'
		AND s.name NOT IN (
			SELECT DISTINCT student_id
			FROM `tabSIS Bus Route Student`
			WHERE student_id IS NOT NULL
		)
		AND {where_clause}
		ORDER BY s.full_name
	""", params, as_dict=True)
