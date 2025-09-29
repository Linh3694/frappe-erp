# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context

@frappe.whitelist()
def get_all_bus_routes():
	"""Get all bus routes without pagination - always returns full dataset"""
	try:
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			# Fallback to default if no campus found
			campus_id = "campus-1"

		# Apply campus filtering for data isolation
		filters = {"campus_id": campus_id}

		# Get all bus routes
		routes = frappe.get_list(
			"SIS Bus Route",
			filters=filters,
			fields=[
				"name", "route_name", "vehicle_id", "driver_id", "monitor1_id", "monitor2_id",
				"status", "campus_id", "school_year_id", "creation", "modified"
			],
			order_by="route_name asc"
		)

		# Map field names to correct format
		for route in routes:
			route['created_at'] = route.pop('creation')
			route['updated_at'] = route.pop('modified')

		# Enrich with related information
		for route in routes:
			# Get vehicle information
			if route.vehicle_id:
				vehicle = frappe.get_doc("SIS Bus Transportation", route.vehicle_id)
				route.update({
					"vehicle_code": vehicle.vehicle_code,
					"license_plate": vehicle.license_plate,
					"vehicle_type": vehicle.vehicle_type
				})

			# Get driver information
			if route.driver_id:
				driver = frappe.get_doc("SIS Bus Driver", route.driver_id)
				route.update({
					"driver_name": driver.full_name,
					"driver_phone": driver.phone_number
				})

			# Get monitor information
			if route.monitor1_id:
				monitor1 = frappe.get_doc("SIS Bus Monitor", route.monitor1_id)
				route.update({
					"monitor1_name": monitor1.full_name,
					"monitor1_phone": monitor1.phone_number
				})

			if route.monitor2_id:
				monitor2 = frappe.get_doc("SIS Bus Monitor", route.monitor2_id)
				route.update({
					"monitor2_name": monitor2.full_name,
					"monitor2_phone": monitor2.phone_number
				})

		return success_response(
			data=routes,
			message="Bus routes retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting bus routes: {str(e)}")
		return error_response(f"Failed to get bus routes: {str(e)}")

@frappe.whitelist()
def get_bus_route():
	"""Get a single bus route by name"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		if not name:
			return error_response("Bus route name is required")
			
		doc = frappe.get_doc("SIS Bus Route", name)
		route_data = doc.as_dict()

		# Get related entity details
		if route_data.get('vehicle_id'):
			vehicle = frappe.get_doc("SIS Bus Transportation", route_data['vehicle_id'])
			route_data.update({
				"vehicle_code": vehicle.vehicle_code,
				"vehicle_type": vehicle.vehicle_type,
				"license_plate": vehicle.license_plate
			})

		if route_data.get('driver_id'):
			driver = frappe.get_doc("SIS Bus Driver", route_data['driver_id'])
			route_data.update({
				"driver_name": driver.full_name,
				"driver_phone": driver.phone_number
			})

		if route_data.get('monitor1_id'):
			monitor1 = frappe.get_doc("SIS Bus Monitor", route_data['monitor1_id'])
			route_data.update({
				"monitor1_name": monitor1.full_name,
				"monitor1_phone": monitor1.phone_number
			})

		if route_data.get('monitor2_id'):
			monitor2 = frappe.get_doc("SIS Bus Monitor", route_data['monitor2_id'])
			route_data.update({
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
					WHEN 'Monday' THEN 1
					WHEN 'Tuesday' THEN 2
					WHEN 'Wednesday' THEN 3
					WHEN 'Thursday' THEN 4
					WHEN 'Friday' THEN 5
					WHEN 'Saturday' THEN 6
					WHEN 'Sunday' THEN 7
				END,
				CASE trip_type
					WHEN 'Pickup' THEN 1
					WHEN 'Drop-off' THEN 2
				END,
				pickup_order
		""", (name,), as_dict=True)

		route_data.update({"route_students": students})

		return success_response(
			data=route_data,
			message="Bus route retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting bus route: {str(e)}")
		return error_response(f"Bus route not found: {str(e)}")

@frappe.whitelist()
def create_bus_route():
	"""Create a new bus route"""
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
					frappe.logger().info(f"Received JSON data for create_bus_route: {data}")
				else:
					data = frappe.local.form_dict
					frappe.logger().info(f"Received form data for create_bus_route (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in create_bus_route: {str(e)}")
				data = frappe.local.form_dict
				frappe.logger().info(f"Using form data for create_bus_route after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			frappe.logger().info(f"No request data, using form_dict for create_bus_route: {data}")

		# Set campus_id if not provided
		if not data.get('campus_id'):
			campus_id = get_current_campus_from_context()
			if campus_id:
				data['campus_id'] = campus_id
				frappe.logger().info(f"Set campus_id to {campus_id} for bus route")
			else:
				# Fallback to default campus
				data['campus_id'] = "campus-1"
				frappe.logger().info("No campus context found, using default campus-1")

		# Validate that monitors are different
		if data.get("monitor1_id") == data.get("monitor2_id"):
			return error_response("Monitor 1 và Monitor 2 không được giống nhau")

		# Check if monitors are already assigned to other routes
		monitor1_id = data.get("monitor1_id")
		monitor2_id = data.get("monitor2_id")

		if monitor1_id:
			existing_routes = frappe.db.sql("""
				SELECT name, route_name
				FROM `tabSIS Bus Route`
				WHERE (monitor1_id = %s OR monitor2_id = %s)
				AND status = 'Active'
			""", (monitor1_id, monitor1_id), as_dict=True)

			if existing_routes:
				route_names = [route.route_name for route in existing_routes]
				return error_response(f"Monitor 1 đã được phân công cho tuyến: {', '.join(route_names)}")

		if monitor2_id:
			existing_routes = frappe.db.sql("""
				SELECT name, route_name
				FROM `tabSIS Bus Route`
				WHERE (monitor1_id = %s OR monitor2_id = %s)
				AND status = 'Active'
			""", (monitor2_id, monitor2_id), as_dict=True)

			if existing_routes:
				route_names = [route.route_name for route in existing_routes]
				return error_response(f"Monitor 2 đã được phân công cho tuyến: {', '.join(route_names)}")

		doc = frappe.get_doc({
			"doctype": "SIS Bus Route",
			**data
		})
		doc.insert()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus route created successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error creating bus route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus route: {str(e)}")

@frappe.whitelist()
def update_bus_route():
	"""Update an existing bus route"""
	try:
		# Get update data from request
		data = {}
		name = None

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
					# Extract name from data if it exists
					name = data.pop('name', None)
					frappe.logger().info(f"Received JSON data for update_bus_route: {data}, name: {name}")
				else:
					data = frappe.local.form_dict
					name = data.get('name')
					data.pop('name', None)
					frappe.logger().info(f"Received form data for update_bus_route (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in update_bus_route: {str(e)}")
				data = frappe.local.form_dict
				name = data.get('name')
				data.pop('name', None)
				frappe.logger().info(f"Using form data for update_bus_route after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			name = data.get('name')
			data.pop('name', None)
			frappe.logger().info(f"No request data, using form_dict for update_bus_route: {data}")

		# If name is still not found, try request args
		if not name:
			name = frappe.request.args.get('name')

		if not name:
			return error_response("Bus route name is required")

		# Validate that monitors are different
		if data.get("monitor1_id") == data.get("monitor2_id"):
			return error_response("Monitor 1 và Monitor 2 không được giống nhau")

		# Check if monitors are already assigned to other routes
		monitor1_id = data.get("monitor1_id")
		monitor2_id = data.get("monitor2_id")

		if monitor1_id:
			existing_routes = frappe.db.sql("""
				SELECT name, route_name
				FROM `tabSIS Bus Route`
				WHERE (monitor1_id = %s OR monitor2_id = %s)
				AND name != %s
				AND status = 'Active'
			""", (monitor1_id, monitor1_id, name), as_dict=True)

			if existing_routes:
				route_names = [route.route_name for route in existing_routes]
				return error_response(f"Monitor 1 đã được phân công cho tuyến: {', '.join(route_names)}")

		if monitor2_id:
			existing_routes = frappe.db.sql("""
				SELECT name, route_name
				FROM `tabSIS Bus Route`
				WHERE (monitor1_id = %s OR monitor2_id = %s)
				AND name != %s
				AND status = 'Active'
			""", (monitor2_id, monitor2_id, name), as_dict=True)

			if existing_routes:
				route_names = [route.route_name for route in existing_routes]
				return error_response(f"Monitor 2 đã được phân công cho tuyến: {', '.join(route_names)}")

		doc = frappe.get_doc("SIS Bus Route", name)
		doc.update(data)
		doc.save()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Bus route updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating bus route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update bus route: {str(e)}")

@frappe.whitelist()
def delete_bus_route():
	"""Delete a bus route"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		if not name:
			return error_response("Bus route name is required")
			
		frappe.delete_doc("SIS Bus Route", name)
		frappe.db.commit()

		return success_response(
			message="Bus route deleted successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error deleting bus route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete bus route: {str(e)}")

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

@frappe.whitelist()
def add_student_to_route():
	"""Add a student to a bus route schedule"""
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
					frappe.logger().info(f"Received JSON data for add_student_to_route: {data}")
				else:
					data = frappe.local.form_dict
					frappe.logger().info(f"Received form data for add_student_to_route (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in add_student_to_route: {str(e)}")
				data = frappe.local.form_dict
				frappe.logger().info(f"Using form data for add_student_to_route after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			frappe.logger().info(f"No request data, using form_dict for add_student_to_route: {data}")

		# Validate required fields
		required_fields = ['route_id', 'student_id', 'weekday', 'trip_type', 'pickup_order', 'pickup_location', 'drop_off_location']
		for field in required_fields:
			if not data.get(field):
				return error_response(f"Field '{field}' is required")

		# Find class_student_id for the student
		class_student_id = None
		if data.get('student_id'):
			class_student = frappe.db.get_value(
				"SIS Class Student",
				{"student_id": data['student_id']},
				"name",
				order_by="creation desc",
				limit=1
			)
			if class_student:
				class_student_id = class_student[0]

		# Create bus route student record
		route_student = frappe.get_doc({
			"doctype": "SIS Bus Route Student",
			"route_id": data['route_id'],
			"student_id": data['student_id'],
			"class_student_id": class_student_id,
			"weekday": data['weekday'],
			"trip_type": data['trip_type'],
			"pickup_order": int(data['pickup_order']),
			"pickup_location": data['pickup_location'],
			"drop_off_location": data['drop_off_location'],
			"notes": data.get('notes', '')
		})
		route_student.insert()
		frappe.db.commit()

		return success_response(
			data=route_student.as_dict(),
			message="Student added to route successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error adding student to route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to add student to route: {str(e)}")

@frappe.whitelist()
def remove_student_from_route():
	"""Remove a student from a bus route schedule"""
	try:
		route_student_id = frappe.local.form_dict.get('route_student_id') or frappe.request.args.get('route_student_id')
		if not route_student_id:
			return error_response("Route student ID is required")

		frappe.delete_doc("SIS Bus Route Student", route_student_id)
		frappe.db.commit()

		return success_response(
			message="Student removed from route successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error removing student from route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to remove student from route: {str(e)}")

@frappe.whitelist()
def update_student_in_route():
	"""Update a student in a bus route schedule"""
	try:
		route_student_id = frappe.local.form_dict.get('route_student_id') or frappe.request.args.get('route_student_id')
		if not route_student_id:
			return error_response("Route student ID is required")

		# Get update data
		data = {}
		if frappe.request.data:
			try:
				if isinstance(frappe.request.data, bytes):
					json_data = json.loads(frappe.request.data.decode('utf-8'))
				else:
					json_data = json.loads(frappe.request.data)
				if json_data:
					data = json_data
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
				data = frappe.local.form_dict
		else:
			data = frappe.local.form_dict

		doc = frappe.get_doc("SIS Bus Route Student", route_student_id)
		doc.update(data)
		doc.save()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Student updated in route successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating student in route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update student in route: {str(e)}")

@frappe.whitelist()
def get_students_by_route():
	"""Get all students assigned to a bus route"""
	try:
		route_id = frappe.local.form_dict.get('route_id') or frappe.request.args.get('route_id')
		if not route_id:
			return error_response("Route ID is required")

		students = frappe.db.sql("""
			SELECT
				name, route_id, student_id, weekday, trip_type, pickup_order,
				pickup_location, drop_off_location, notes
			FROM `tabSIS Bus Route Student`
			WHERE route_id = %s
			ORDER BY
				CASE weekday
					WHEN 'Monday' THEN 1
					WHEN 'Tuesday' THEN 2
					WHEN 'Wednesday' THEN 3
					WHEN 'Thursday' THEN 4
					WHEN 'Friday' THEN 5
					WHEN 'Saturday' THEN 6
					WHEN 'Sunday' THEN 7
				END,
				CASE trip_type
					WHEN 'Pickup' THEN 1
					WHEN 'Drop-off' THEN 2
				END,
				pickup_order
		""", (route_id,), as_dict=True)

		return success_response(
			data=students,
			message="Students retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting students by route: {str(e)}")
		return error_response(f"Failed to get students by route: {str(e)}")
