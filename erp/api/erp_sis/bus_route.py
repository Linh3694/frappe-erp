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

	# Create route student assignment
	route_student_doc = create_doc("SIS Bus Route Student", student_data)

	# Get route and student info for SIS Bus Student
	route_info = frappe.get_doc("SIS Bus Route", route_id)
	student_info = frappe.get_doc("CRM Student", student_id)

	# Find class_student_id from SIS Class Student
	class_student_id = frappe.db.get_value("SIS Class Student", {
		"student_id": student_id,
		"campus_id": route_info.campus_id,
		"school_year_id": route_info.school_year_id
	}, "name")

	if not class_student_id:
		frappe.throw(f"Không tìm thấy thông tin lớp của học sinh {student_info.full_name}")

	# Add class_student_id to route student data
	student_data["class_student_id"] = class_student_id

	# Create or update SIS Bus Student record
	bus_student_data = {
		"full_name": student_info.full_name,
		"student_code": student_info.student_code,
		"class_id": student_info.class_id,
		"route_id": route_id,
		"status": "Active",
		"campus_id": route_info.campus_id,
		"school_year_id": route_info.school_year_id
	}

	# Check if SIS Bus Student record already exists
	existing_bus_student = frappe.db.exists("SIS Bus Student", {
		"student_code": student_info.student_code,
		"route_id": route_id
	})

	if existing_bus_student:
		# Update existing record
		frappe.db.set_value("SIS Bus Student", existing_bus_student, bus_student_data)
	else:
		# Create new record
		bus_student_data["name"] = f"SIS_BUS_STU-{student_info.student_code}-{route_id}"
		create_doc("SIS Bus Student", bus_student_data)

	return route_student_doc

@frappe.whitelist()
def remove_student_from_route(route_student_id):
	"""Remove a student from a bus route"""
	# Get route student info before deletion
	route_student = frappe.get_doc("SIS Bus Route Student", route_student_id)

	# Delete from SIS Bus Route Student
	delete_doc("SIS Bus Route Student", route_student_id)

	# Remove from SIS Bus Student if exists
	existing_bus_student = frappe.db.exists("SIS Bus Student", {
		"student_code": route_student.student_id,
		"route_id": route_student.route_id
	})

	if existing_bus_student:
		frappe.delete_doc("SIS Bus Student", existing_bus_student)

	# Also remove class_student_id from route student data if needed
	# This will be handled automatically when the document is deleted

	return True

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
def get_bus_students(page=1, limit=20, **filters):
	"""Get all bus students with pagination - optimized lookup"""
	return get_list(
		"SIS Bus Student",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "full_name", "student_code", "class_id", "route_id",
			"status", "campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="full_name asc"
	)

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
def get_student_bus_route_by_student_id(student_id):
	"""Get bus route information for a specific student by student ID"""
	try:
		# First check SIS Bus Student table for optimized lookup
		bus_student = frappe.db.sql("""
			SELECT
				bs.name, bs.full_name, bs.student_code, bs.class_id, bs.route_id,
				bs.status, bs.campus_id, bs.school_year_id,
				r.route_name, r.vehicle_id, r.driver_id, r.monitor1_id, r.monitor2_id,
				v.vehicle_code, v.license_plate, v.vehicle_type,
				d.full_name as driver_name, d.phone_number as driver_phone,
				m1.full_name as monitor1_name, m1.phone_number as monitor1_phone,
				m2.full_name as monitor2_name, m2.phone_number as monitor2_phone
			FROM `tabSIS Bus Student` bs
			LEFT JOIN `tabSIS Bus Route` r ON bs.route_id = r.name
			LEFT JOIN `tabSIS Bus Transportation` v ON r.vehicle_id = v.name
			LEFT JOIN `tabSIS Bus Driver` d ON r.driver_id = d.name
			LEFT JOIN `tabSIS Bus Monitor` m1 ON r.monitor1_id = m1.name
			LEFT JOIN `tabSIS Bus Monitor` m2 ON r.monitor2_id = m2.name
			WHERE bs.student_code = %s AND bs.status = 'Active'
		""", (student_id,), as_dict=True)

		if bus_student:
			return bus_student[0]

		# Fallback to SIS Bus Route Student if not found in SIS Bus Student
		route_students = frappe.db.sql("""
			SELECT
				brs.name, brs.student_id, brs.route_id, brs.weekday, brs.trip_type,
				brs.pickup_order, brs.pickup_location, brs.drop_off_location, brs.notes,
				r.route_name, r.vehicle_id, r.driver_id, r.monitor1_id, r.monitor2_id,
				v.vehicle_code, v.license_plate, v.vehicle_type,
				d.full_name as driver_name, d.phone_number as driver_phone,
				m1.full_name as monitor1_name, m1.phone_number as monitor1_phone,
				m2.full_name as monitor2_name, m2.phone_number as monitor2_phone,
				s.full_name, s.student_code
			FROM `tabSIS Bus Route Student` brs
			LEFT JOIN `tabSIS Bus Route` r ON brs.route_id = r.name
			LEFT JOIN `tabSIS Bus Transportation` v ON r.vehicle_id = v.name
			LEFT JOIN `tabSIS Bus Driver` d ON r.driver_id = d.name
			LEFT JOIN `tabSIS Bus Monitor` m1 ON r.monitor1_id = m1.name
			LEFT JOIN `tabSIS Bus Monitor` m2 ON r.monitor2_id = m2.name
			LEFT JOIN `tabCRM Student` s ON brs.student_id = s.name
			WHERE brs.student_id = %s
		""", (student_id,), as_dict=True)

		return route_students if route_students else None

	except Exception as e:
		frappe.log_error(f"Error getting student bus route: {str(e)}")
		return None

@frappe.whitelist()
def get_student_bus_route_by_code(student_code):
	"""Get bus route information for a specific student by student code"""
	return get_student_bus_route_by_student_id(student_code)

@frappe.whitelist()
def get_daily_trips(page=1, limit=20, **filters):
	"""Get daily trips with pagination"""
	return get_list(
		"SIS Bus Daily Trip",
		page=page,
		limit=limit,
		filters=filters,
		fields=[
			"name", "route_id", "trip_date", "weekday", "trip_type",
			"vehicle_id", "driver_id", "monitor1_id", "monitor2_id",
			"trip_status", "campus_id", "school_year_id", "created_at", "updated_at"
		],
		order_by="trip_date desc, trip_type"
	)

@frappe.whitelist()
def get_daily_trip(name):
	"""Get a single daily trip with full details"""
	doc = get_single("SIS Bus Daily Trip", name)
	if doc:
		# Get related entity details
		if doc.vehicle_id:
			vehicle = frappe.get_doc("SIS Bus Transportation", doc.vehicle_id)
			doc.update({
				"vehicle_code": vehicle.vehicle_code,
				"license_plate": vehicle.license_plate,
				"vehicle_type": vehicle.vehicle_type
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

		# Get trip students with full information
		students = frappe.db.sql("""
			SELECT
				name, student_id, class_student_id, student_image, student_name,
				student_code, class_name, pickup_order, pickup_location,
				drop_off_location, student_status, boarding_time, drop_off_time,
				absent_reason, notes
			FROM `tabSIS Bus Daily Trip Student`
			WHERE daily_trip_id = %s
			ORDER BY pickup_order
		""", (name,), as_dict=True)

		# Students already have full information from the query

		doc.update({"trip_students": students})

	return doc

@frappe.whitelist()
def create_daily_trip(**data):
	"""Create a new daily trip"""
	# If students are provided, populate their information
	if data.get("trip_students"):
		students_data = data.pop("trip_students")

		# Create the daily trip first
		daily_trip = create_doc("SIS Bus Daily Trip", data)

		# Add students with full information
		for student_data in students_data:
			# Get student info from CRM Student
			student_info = frappe.get_doc("CRM Student", student_data.get("student_id"))
			class_info = frappe.get_doc("SIS Class", student_info.class_id) if student_info.class_id else None

			student_doc_data = {
				"daily_trip_id": daily_trip.name,
				"student_id": student_data.get("student_id"),
				"class_student_id": student_data.get("class_student_id"),
				"student_image": student_info.image,
				"student_name": student_info.full_name,
				"student_code": student_info.student_code,
				"class_name": class_info.class_name if class_info else "",
				"pickup_order": student_data.get("pickup_order", 0),
				"pickup_location": student_data.get("pickup_location", ""),
				"drop_off_location": student_data.get("drop_off_location", ""),
				"student_status": student_data.get("student_status", "Chưa lên xe")
			}

			frappe.get_doc({
				"doctype": "SIS Bus Daily Trip Student",
				**student_doc_data
			}).insert()

		frappe.db.commit()
		return daily_trip
	else:
		return create_doc("SIS Bus Daily Trip", data)

@frappe.whitelist()
def update_daily_trip(name, **data):
	"""Update an existing daily trip"""
	return update_doc("SIS Bus Daily Trip", name, data)

@frappe.whitelist()
def delete_daily_trip(name):
	"""Delete a daily trip"""
	return delete_doc("SIS Bus Daily Trip", name)

@frappe.whitelist()
def update_student_status_in_trip(daily_trip_student_id, student_status, boarding_time=None, drop_off_time=None, absent_reason=None, notes=None):
	"""Update student status in a daily trip"""
	data = {"student_status": student_status}

	if boarding_time:
		data["boarding_time"] = boarding_time
	if drop_off_time:
		data["drop_off_time"] = drop_off_time
	if absent_reason:
		data["absent_reason"] = absent_reason
	if notes:
		data["notes"] = notes

	return update_doc("SIS Bus Daily Trip Student", daily_trip_student_id, data)

@frappe.whitelist()
def update_trip_status(daily_trip_id, trip_status, notes=None):
	"""Update trip status"""
	data = {"trip_status": trip_status}
	if notes:
		data["notes"] = notes

	return update_doc("SIS Bus Daily Trip", daily_trip_id, data)

@frappe.whitelist()
def get_daily_trips_by_route(route_id, start_date=None, end_date=None):
	"""Get daily trips for a specific route and date range"""
	conditions = ["route_id = %s"]
	params = [route_id]

	if start_date:
		conditions.append("trip_date >= %s")
		params.append(start_date)

	if end_date:
		conditions.append("trip_date <= %s")
		params.append(end_date)

	where_clause = " AND ".join(conditions)

	return frappe.db.sql(f"""
		SELECT
			name, trip_date, weekday, trip_type, trip_status,
			vehicle_id, driver_id, monitor1_id, monitor2_id
		FROM `tabSIS Bus Daily Trip`
		WHERE {where_clause}
		ORDER BY trip_date, trip_type
	""", params, as_dict=True)

@frappe.whitelist()
def get_daily_trips_by_date(trip_date, campus_id=None, school_year_id=None):
	"""Get daily trips for a specific date"""
	conditions = ["trip_date = %s"]
	params = [trip_date]

	if campus_id:
		conditions.append("campus_id = %s")
		params.append(campus_id)

	if school_year_id:
		conditions.append("school_year_id = %s")
		params.append(school_year_id)

	where_clause = " AND ".join(conditions)

	return frappe.db.sql(f"""
		SELECT
			dt.name, dt.route_id, dt.trip_date, dt.weekday, dt.trip_type,
			dt.trip_status, dt.vehicle_id, dt.driver_id, dt.monitor1_id, dt.monitor2_id,
			r.route_name, v.vehicle_code, v.license_plate,
			d.full_name as driver_name, d.phone_number as driver_phone
		FROM `tabSIS Bus Daily Trip` dt
		LEFT JOIN `tabSIS Bus Route` r ON dt.route_id = r.name
		LEFT JOIN `tabSIS Bus Transportation` v ON dt.vehicle_id = v.name
		LEFT JOIN `tabSIS Bus Driver` d ON dt.driver_id = d.name
		WHERE {where_clause}
		ORDER BY dt.trip_type, r.route_name
	""", params, as_dict=True)

@frappe.whitelist()
def get_available_students(campus_id=None, school_year_id=None):
	"""Get students not assigned to any bus route"""
	conditions = []
	params = []

	if campus_id:
		conditions.append("cs.campus_id = %s")
		params.append(campus_id)

	if school_year_id:
		conditions.append("cs.school_year_id = %s")
		params.append(school_year_id)

	where_clause = " AND ".join(conditions) if conditions else "1=1"

	return frappe.db.sql(f"""
		SELECT cs.name, s.full_name, s.student_code, cl.class_name
		FROM `tabSIS Class Student` cs
		INNER JOIN `tabCRM Student` s ON cs.student_id = s.name
		LEFT JOIN `tabSIS Class` cl ON cs.class_id = cl.name
		WHERE cs.name NOT IN (
			SELECT DISTINCT student_id
			FROM `tabSIS Bus Route Student`
			WHERE student_id IS NOT NULL
		)
		AND {where_clause}
		ORDER BY s.full_name
	""", params, as_dict=True)
