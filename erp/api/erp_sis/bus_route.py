

import json
import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context

def add_student_to_daily_trips(route_id, route_student_data):
	"""Add student to all corresponding daily trips"""
	logs = []
	try:
		# Get all daily trips for this route with matching weekday and trip_type
		daily_trips = frappe.get_all(
			"SIS Bus Daily Trip",
			filters={
				"route_id": route_id,
				"weekday": route_student_data['weekday'],
				"trip_type": route_student_data['trip_type']
			},
			fields=["name", "trip_date"]
		)

		logs.append(f"🔍 Tìm thấy {len(daily_trips)} daily trips cho route {route_id}, weekday={route_student_data['weekday']}, trip_type={route_student_data['trip_type']}")
		
		if len(daily_trips) == 0:
			logs.append(f"⚠️ KHÔNG có daily trips nào matching - có thể chưa tạo daily trips hoặc weekday/trip_type không khớp")
			return {"success": False, "logs": logs, "added_count": 0}

		# Get student info
		student = frappe.get_doc("CRM Student", route_student_data['student_id'])
		class_name = ""
		if route_student_data.get('class_student_id'):
			class_student = frappe.get_doc("SIS Class Student", route_student_data['class_student_id'])
			if class_student.class_id:
				class_doc = frappe.get_doc("SIS Class", class_student.class_id)
				class_name = class_doc.title or class_doc.name

		logs.append(f"👤 Student: {student.student_code} - {student.student_name} (Class: {class_name})")

		# Add student to each daily trip
		added_count = 0
		skipped_count = 0
		
		for daily_trip in daily_trips:
			# Check if student already exists in this daily trip
			existing = frappe.db.sql("""
				SELECT name FROM `tabSIS Bus Daily Trip Student`
				WHERE daily_trip_id = %s AND student_id = %s
				LIMIT 1
			""", (daily_trip.name, route_student_data['student_id']))
			existing = existing[0][0] if existing else None
			
			if existing:
				logs.append(f"   ⏭️ Bỏ qua {daily_trip.name} ({daily_trip.trip_date}) - student đã tồn tại")
				skipped_count += 1
			else:
				try:
					student_data = {
						"daily_trip_id": daily_trip.name,
						"student_id": route_student_data['student_id'],
						"class_student_id": route_student_data.get('class_student_id'),
						"student_image": "",
						"student_name": student.student_name,
						"student_code": student.student_code,
						"class_name": class_name,
						"pickup_order": route_student_data['pickup_order'],
						"pickup_location": route_student_data['pickup_location'],
						"drop_off_location": route_student_data['drop_off_location'],
						"student_status": "Not Boarded"
					}

					frappe.get_doc({
						"doctype": "SIS Bus Daily Trip Student",
						**student_data
					}).insert()
					
					logs.append(f"   ✅ Đã thêm vào {daily_trip.name} ({daily_trip.trip_date})")
					added_count += 1
					
				except Exception as trip_error:
					logs.append(f"   ❌ Lỗi thêm vào {daily_trip.name}: {str(trip_error)}")

		frappe.db.commit()
		logs.append(f"📊 Tổng kết: Đã thêm vào {added_count} daily trips, bỏ qua {skipped_count} trips")
		
		frappe.logger().info(f"Added student to {added_count} daily trips")
		return {"success": True, "logs": logs, "added_count": added_count}

	except Exception as e:
		logs.append(f"❌ LỖI: {str(e)}")
		frappe.log_error(f"Error adding student to daily trips: {str(e)}")
		return {"success": False, "logs": logs, "added_count": 0}

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
	logs = []
	try:
		logs.append("🔍 Starting get_bus_route")
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		logs.append(f"📋 Route name: {name}")
		
		if not name:
			return error_response("Bus route name is required", logs=logs)
		
		logs.append("🔄 Getting SIS Bus Route document...")
		doc = frappe.get_doc("SIS Bus Route", name)
		route_data = doc.as_dict()
		logs.append(f"✅ Got route document: {route_data.get('route_name')}")

		# Get related entity details
		if route_data.get('vehicle_id'):
			logs.append(f"🚌 Loading vehicle: {route_data.get('vehicle_id')}")
			vehicle = frappe.get_doc("SIS Bus Transportation", route_data['vehicle_id'])
			route_data.update({
				"vehicle_code": vehicle.vehicle_code,
				"vehicle_type": vehicle.vehicle_type,
				"license_plate": vehicle.license_plate
			})
			logs.append("✅ Vehicle loaded")

		if route_data.get('driver_id'):
			logs.append(f"👨‍✈️ Loading driver: {route_data.get('driver_id')}")
			driver = frappe.get_doc("SIS Bus Driver", route_data['driver_id'])
			route_data.update({
				"driver_name": driver.full_name,
				"driver_phone": driver.phone_number
			})
			logs.append("✅ Driver loaded")

		if route_data.get('monitor1_id'):
			logs.append(f"👤 Loading monitor1: {route_data.get('monitor1_id')}")
			monitor1 = frappe.get_doc("SIS Bus Monitor", route_data['monitor1_id'])
			route_data.update({
				"monitor1_name": monitor1.full_name,
				"monitor1_phone": monitor1.phone_number
			})
			logs.append("✅ Monitor1 loaded")

		if route_data.get('monitor2_id'):
			logs.append(f"👤 Loading monitor2: {route_data.get('monitor2_id')}")
			monitor2 = frappe.get_doc("SIS Bus Monitor", route_data['monitor2_id'])
			route_data.update({
				"monitor2_name": monitor2.full_name,
				"monitor2_phone": monitor2.phone_number
			})
			logs.append("✅ Monitor2 loaded")

		# Get route students - query separately since it's not a child table
		logs.append(f"👨‍🎓 Loading route students for route_id: {name}")
		students = frappe.get_all(
			"SIS Bus Route Student",
			filters={"route_id": name},
			fields=["name", "route_id", "student_id", "class_student_id", "weekday", 
					"trip_type", "pickup_order", "pickup_location", "drop_off_location", "notes"],
			order_by="weekday, trip_type, pickup_order"
		)
		logs.append(f"✅ Loaded {len(students)} route students")

		route_data.update({"route_students": students})
		logs.append("🎉 Success!")

		return success_response(
			data=route_data,
			message="Bus route retrieved successfully",
			logs=logs
		)
	except Exception as e:
		import traceback
		error_trace = traceback.format_exc()
		logs.append(f"❌ ERROR: {str(e)}")
		logs.append(f"📜 Traceback: {error_trace}")
		frappe.log_error(f"Error getting bus route: {str(e)}\n{error_trace}")
		return error_response(f"Bus route not found: {str(e)}", logs=logs)

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

		# Validate that monitors are different (only if both are provided)
		if data.get("monitor1_id") and data.get("monitor2_id") and data.get("monitor1_id") == data.get("monitor2_id"):
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
		
		# Log successful creation
		frappe.logger().info(f"✅ Bus route created successfully: {doc.name} - {doc.route_name}")

		return success_response(
			data=doc.as_dict(),
			message=f"Bus route created successfully: {doc.name}",
			logs=[f"Route {doc.name} created with status {doc.status}"]
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

		# Validate that monitors are different (only if both are provided)
		if data.get("monitor1_id") and data.get("monitor2_id") and data.get("monitor1_id") == data.get("monitor2_id"):
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
		force_delete = frappe.local.form_dict.get('force_delete') or frappe.request.args.get('force_delete')
		
		if not name:
			return error_response("Bus route name is required")
		
		# Check for linked student routes
		linked_students = frappe.db.sql("""
			SELECT 
				brs.name,
				brs.student_id,
				s.student_code,
				s.full_name as student_name
			FROM `tabSIS Bus Route Student` brs
			LEFT JOIN `tabCRM Student` s ON s.name = brs.student_id
			WHERE brs.route_id = %s
		""", name, as_dict=True)
		
		student_count = len(linked_students)
		
		# If there are linked students and no force delete confirmation
		if student_count > 0 and not force_delete:
			return {
				"success": False,
				"requires_confirmation": True,
				"message": f"This route has {student_count} student(s) assigned. Deleting this route will also remove all student assignments.",
				"student_count": student_count,
				"students": linked_students
			}
		
		# Delete linked student routes first
		if student_count > 0:
			for student in linked_students:
				frappe.delete_doc("SIS Bus Route Student", student.name, force=True)
		
		# Delete the bus route
		frappe.delete_doc("SIS Bus Route", name, force=True)
		frappe.db.commit()

		return success_response(
			message=f"Bus route deleted successfully. {student_count} student assignment(s) were also removed." if student_count > 0 else "Bus route deleted successfully",
			deleted_student_count=student_count
		)
	except Exception as e:
		frappe.db.rollback()
		error_msg = str(e)
		# Remove HTML tags from error message for cleaner display
		import re
		clean_msg = re.sub('<[^<]+?>', '', error_msg)
		return error_response(f"Failed to delete bus route: {clean_msg}")

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

		try:
			frappe.logger().info("🔍 STEP 1: Parsing request data...")
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
						frappe.logger().info(f"✅ Received JSON data for add_student_to_route: {data}")
					else:
						data = frappe.local.form_dict
						frappe.logger().info(f"✅ Received form data for add_student_to_route (empty JSON body): {data}")
				except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
					# If JSON parsing fails, use form_dict
					frappe.logger().error(f"❌ JSON parsing failed in add_student_to_route: {str(e)}")
					data = frappe.local.form_dict
					frappe.logger().info(f"✅ Using form data for add_student_to_route after JSON failure: {data}")
			else:
				# Fallback to form_dict
				data = frappe.local.form_dict
				frappe.logger().info(f"✅ No request data, using form_dict for add_student_to_route: {data}")
		except Exception as e:
			frappe.logger().error(f"❌ STEP 1 FAILED: {str(e)}")
			raise e

		try:
			frappe.logger().info("🔍 STEP 2: Validating required fields...")
			# Validate required fields
			required_fields = ['route_id', 'student_id', 'weekday', 'trip_type', 'pickup_order', 'pickup_location', 'drop_off_location']
			for field in required_fields:
				if not data.get(field):
					return error_response(f"Field '{field}' is required")
			frappe.logger().info("✅ All required fields validated")
		except Exception as e:
			frappe.logger().error(f"❌ STEP 2 FAILED: {str(e)}")
			raise e

		try:
			frappe.logger().info("🔍 STEP 3: Finding class_student_id...")
			# Find class_student_id for the student
			class_student_id = None
			if data.get('student_id'):
				result = frappe.db.sql("""
					SELECT name FROM `tabSIS Class Student`
					WHERE student_id = %s
					LIMIT 1
				""", (data['student_id'],))
				class_student_id = result[0][0] if result else None
			frappe.logger().info(f"✅ Found class_student_id: {class_student_id}")
		except Exception as e:
			frappe.logger().error(f"❌ STEP 3 FAILED - Error finding class_student_id: {str(e)}")
			raise e

		try:
			frappe.logger().info("🔍 STEP 4: Getting route document...")
			# Try different approaches to get route document
			
			# First, try basic existence check
			route_exists = frappe.db.sql("SELECT name FROM `tabSIS Bus Route` WHERE name = %s LIMIT 1", (data['route_id'],))
			if not route_exists:
				frappe.logger().error(f"❌ Route {data['route_id']} does not exist!")
				raise Exception(f"Route {data['route_id']} does not exist")
			
			frappe.logger().info(f"✅ Route exists: {data['route_id']}")
			
			# Try to get the document with minimal loading
			try:
				# Try with ignore_permissions=True to skip some validations
				frappe.logger().info("🔍 Attempting frappe.get_doc with ignore_permissions...")
				route_doc = frappe.get_doc("SIS Bus Route", data['route_id'], ignore_permissions=True)
				frappe.logger().info(f"✅ Got route document: {route_doc.name}")
			except Exception as get_doc_error:
				frappe.logger().error(f"❌ frappe.get_doc failed: {str(get_doc_error)}")
				frappe.logger().info("🔍 Trying alternative approach - using raw SQL to get route data...")
				
				# Alternative: Get route data via SQL and construct minimal doc
				try:
					route_data = frappe.db.sql("""
						SELECT name, route_name, vehicle_id, driver_id, monitor1_id, monitor2_id, 
							   status, campus_id, school_year_id, creation, modified, owner, modified_by
						FROM `tabSIS Bus Route` WHERE name = %s
					""", (data['route_id'],), as_dict=True)
					
					if not route_data:
						raise Exception(f"Route {data['route_id']} not found in database")
					
					route_info = route_data[0]
					frappe.logger().info(f"✅ Got route data via SQL: {route_info}")
					
					# Create a minimal document instance with all required fields
					route_doc = frappe.new_doc("SIS Bus Route")
					for key, value in route_info.items():
						setattr(route_doc, key, value)
					
					# Ensure required fields are set
					if not route_doc.campus_id:
						route_doc.campus_id = "campus-00001"  
					if not route_doc.school_year_id:
						route_doc.school_year_id = "2024-2025"  
					
					# Load existing students count for info (no longer needed in document)
					existing_students = frappe.db.sql("""
						SELECT COUNT(*) as count FROM `tabSIS Bus Route Student` 
						WHERE route_id = %s
					""", (data['route_id'],))[0][0]
					
					frappe.logger().info(f"✅ Found {existing_students} existing students for route")
					
					frappe.logger().info(f"✅ Created route doc from SQL data with {existing_students} students: {route_doc.name}")
					
				except Exception as sql_error:
					frappe.logger().error(f"❌ SQL approach also failed: {str(sql_error)}")
					raise sql_error
				
		except Exception as e:
			frappe.logger().error(f"❌ STEP 4 FAILED - Error getting route document: {str(e)}")
			raise e
		
		try:
			frappe.logger().info("🔍 STEP 5: Creating standalone route student document...")
			# Create standalone route student document (no longer child table)
			route_student_data = {
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
			}
			
			route_student = frappe.get_doc(route_student_data)
			route_student.insert()
			frappe.logger().info(f"✅ Created standalone route student document: {route_student.name}")
		except Exception as e:
			frappe.logger().error(f"❌ STEP 5 FAILED - Error creating route student document: {str(e)}")
			raise e
		
		try:
			frappe.logger().info("🔍 STEP 6: Committing changes...")
			# No need to save route doc anymore since we're using standalone documents
			frappe.db.commit()
			frappe.logger().info("✅ Changes committed successfully")
		except Exception as e:
			frappe.logger().error(f"❌ STEP 6 FAILED - Error committing changes: {str(e)}")
			raise e

		try:
			frappe.logger().info("🔍 STEP 7: Adding student to daily trips...")
			# Add student to corresponding daily trips
			daily_trips_result = add_student_to_daily_trips(data['route_id'], route_student.as_dict())
			frappe.logger().info("✅ Student added to daily trips")
		except Exception as e:
			frappe.logger().error(f"❌ STEP 7 FAILED - Error adding student to daily trips: {str(e)}")
			# Don't re-raise this error - route student was already saved
			daily_trips_result = {"success": False, "logs": [f"❌ Error: {str(e)}"]}

		# Prepare response with detailed logs
		response_logs = [
			f"✅ Đã thêm student {data['student_id']} vào route {data['route_id']}",
			f"📋 Weekday: {data['weekday']}, Trip Type: {data['trip_type']}"
		]
		if daily_trips_result and daily_trips_result.get('logs'):
			response_logs.extend(daily_trips_result.get('logs', []))
		
		message = "Student added to route successfully"
		if daily_trips_result and daily_trips_result.get('success'):
			added_count = daily_trips_result.get('added_count', 0)
			message += f" and added to {added_count} daily trips"
		else:
			message += " but failed to add to daily trips"

		frappe.logger().info("✅ ALL STEPS COMPLETED - Returning success response")
		return success_response(
			data=route_student.as_dict(),
			message=message,
			logs=response_logs
		)
	except Exception as e:
		frappe.log_error(f"Error adding student to route: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to add student to route: {str(e)}")

@frappe.whitelist()
def remove_student_from_route():
	"""Remove a student from a bus route schedule"""
	try:
		# Get route_student_id from query params (frontend sends this)
		route_student_id = frappe.local.form_dict.get('route_student_id') or frappe.request.args.get('route_student_id')

		if not route_student_id:
			return error_response("Route student ID is required")

		# Delete the SIS Bus Route Student document directly
		# (It's a standalone DocType, not a child table)
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
		# Get route_student_id from params (frontend sends this)
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

		# Get the SIS Bus Route Student document directly
		# (It's a standalone DocType, not a child table)
		student_doc = frappe.get_doc("SIS Bus Route Student", route_student_id)

		# Update fields
		for key, value in data.items():
			if hasattr(student_doc, key) and key not in ['name', 'route_student_id']:
				setattr(student_doc, key, value)

		# Save the document
		student_doc.save()
		frappe.db.commit()

		return success_response(
			data=student_doc.as_dict(),
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

		return success_response(
			data=students,
			message="Students retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting students by route: {str(e)}")
		return error_response(f"Failed to get students by route: {str(e)}")

@frappe.whitelist()
def create_daily_trip():
	"""Create a new daily trip"""
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
					frappe.logger().info(f"Received JSON data for create_daily_trip: {data}")
				else:
					data = frappe.local.form_dict
					frappe.logger().info(f"Received form data for create_daily_trip (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in create_daily_trip: {str(e)}")
				data = frappe.local.form_dict
				frappe.logger().info(f"Using form data for create_daily_trip after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			frappe.logger().info(f"No request data, using form_dict for create_daily_trip: {data}")

		# Validate required fields
		required_fields = ['route_id', 'trip_date', 'weekday', 'trip_type', 'vehicle_id', 'driver_id', 'monitor1_id', 'trip_status']
		for field in required_fields:
			if not data.get(field):
				return error_response(f"Field '{field}' is required")

		# Set campus_id and school_year_id if not provided
		if not data.get('campus_id'):
			campus_id = get_current_campus_from_context()
			if campus_id:
				data['campus_id'] = campus_id
				frappe.logger().info(f"Set campus_id to {campus_id} for daily trip")
			else:
				# Fallback to default campus
				data['campus_id'] = "campus-1"
				frappe.logger().info("No campus context found, using default campus-1")

		if not data.get('school_year_id'):
			# Get school_year_id from route if available
			route_doc = frappe.get_doc("SIS Bus Route", data['route_id'])
			if route_doc.school_year_id:
				data['school_year_id'] = route_doc.school_year_id
				frappe.logger().info(f"Set school_year_id to {data['school_year_id']} from route")

		# Check if daily trip already exists
		existing_trip = frappe.db.sql("""
			SELECT name FROM `tabSIS Bus Daily Trip`
			WHERE route_id = %s AND trip_date = %s 
			AND weekday = %s AND trip_type = %s
			LIMIT 1
		""", (data['route_id'], data['trip_date'], data['weekday'], data['trip_type']))
		existing_trip = existing_trip[0][0] if existing_trip else None

		if existing_trip:
			return error_response(f"Daily trip already exists for this route, date, weekday, and trip type")

		doc = frappe.get_doc({
			"doctype": "SIS Bus Daily Trip",
			**data
		})
		doc.insert()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Daily trip created successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error creating daily trip: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create daily trip: {str(e)}")

@frappe.whitelist()
def get_daily_trips():
	"""Get all daily trips with enriched information"""
	try:
		# Temporarily disable campus filtering for testing
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			# Fallback to default if no campus found
			campus_id = "campus-1"

		# Use raw SQL query to get daily trips (temporarily without campus filtering)
		daily_trips = frappe.db.sql("""
			SELECT
				name, route_id, trip_date, weekday, trip_type,
				vehicle_id, driver_id, monitor1_id, monitor2_id,
				trip_status, campus_id, school_year_id,
				creation, modified
			FROM `tabSIS Bus Daily Trip`
			ORDER BY trip_date DESC, route_id ASC
			LIMIT 100
		""", as_dict=True)

		# Map field names to correct format
		for trip in daily_trips:
			trip['created_at'] = trip.pop('creation')
			trip['updated_at'] = trip.pop('modified')

		# Enrich with related information using SQL queries instead of frappe.get_doc
		for trip in daily_trips:
			# Get route information
			if trip.route_id:
				route_data = frappe.db.sql("""
					SELECT route_name FROM `tabSIS Bus Route` WHERE name = %s
				""", (trip.route_id,), as_dict=True)
				if route_data:
					trip.update({
						"route_name": route_data[0].route_name
					})

			# Get vehicle information
			if trip.vehicle_id:
				vehicle_data = frappe.db.sql("""
					SELECT vehicle_code, license_plate, vehicle_type 
					FROM `tabSIS Bus Transportation` WHERE name = %s
				""", (trip.vehicle_id,), as_dict=True)
				if vehicle_data:
					trip.update({
						"vehicle_code": vehicle_data[0].vehicle_code,
						"license_plate": vehicle_data[0].license_plate,
						"vehicle_type": vehicle_data[0].vehicle_type
					})

			# Get driver information
			if trip.driver_id:
				driver_data = frappe.db.sql("""
					SELECT full_name, phone_number FROM `tabSIS Bus Driver` WHERE name = %s
				""", (trip.driver_id,), as_dict=True)
				if driver_data:
					trip.update({
						"driver_name": driver_data[0].full_name,
						"driver_phone": driver_data[0].phone_number
					})

			# Get monitor information
			if trip.monitor1_id:
				monitor1_data = frappe.db.sql("""
					SELECT full_name, phone_number FROM `tabSIS Bus Monitor` WHERE name = %s
				""", (trip.monitor1_id,), as_dict=True)
				if monitor1_data:
					trip.update({
						"monitor1_name": monitor1_data[0].full_name,
						"monitor1_phone": monitor1_data[0].phone_number
					})

			if trip.monitor2_id:
				monitor2_data = frappe.db.sql("""
					SELECT full_name, phone_number FROM `tabSIS Bus Monitor` WHERE name = %s
				""", (trip.monitor2_id,), as_dict=True)
				if monitor2_data:
					trip.update({
						"monitor2_name": monitor2_data[0].full_name,
						"monitor2_phone": monitor2_data[0].phone_number
					})

			# Get trip students count and details
			students = frappe.db.sql("""
				SELECT
					name, student_id, class_student_id, student_image,
					student_name, student_code, class_name, pickup_order,
					pickup_location, drop_off_location, student_status,
					boarding_time, drop_off_time, absent_reason, notes
				FROM `tabSIS Bus Daily Trip Student`
				WHERE daily_trip_id = %s
				ORDER BY pickup_order
			""", (trip.name,), as_dict=True)

			trip.update({
				"trip_students": students,
				"total_students": len(students)
			})

		return success_response(
			data=daily_trips,
			message="Daily trips retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting daily trips: {str(e)}")
		return error_response(f"Failed to get daily trips: {str(e)}")

@frappe.whitelist()
def get_daily_trip():
	"""Get a single daily trip by name"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		if not name:
			return error_response("Daily trip name is required")

		# Use raw SQL to get daily trip
		trip_data = frappe.db.sql("""
			SELECT
				name, route_id, trip_date, weekday, trip_type,
				vehicle_id, driver_id, monitor1_id, monitor2_id,
				trip_status, campus_id, school_year_id,
				creation, modified
			FROM `tabSIS Bus Daily Trip`
			WHERE name = %s
		""", (name,), as_dict=True)

		if not trip_data:
			return error_response("Daily trip not found")

		trip_data = trip_data[0]

		# Map field names to correct format
		trip_data['created_at'] = trip_data.pop('creation')
		trip_data['updated_at'] = trip_data.pop('modified')

		# Get related entity details using SQL queries instead of frappe.get_doc
		if trip_data.get('route_id'):
			route_data = frappe.db.sql("""
				SELECT route_name FROM `tabSIS Bus Route` WHERE name = %s
			""", (trip_data['route_id'],), as_dict=True)
			if route_data:
				trip_data.update({
					"route_name": route_data[0].route_name
				})

		if trip_data.get('vehicle_id'):
			vehicle_data = frappe.db.sql("""
				SELECT vehicle_code, vehicle_type, license_plate 
				FROM `tabSIS Bus Transportation` WHERE name = %s
			""", (trip_data['vehicle_id'],), as_dict=True)
			if vehicle_data:
				trip_data.update({
					"vehicle_code": vehicle_data[0].vehicle_code,
					"vehicle_type": vehicle_data[0].vehicle_type,
					"license_plate": vehicle_data[0].license_plate
				})

		if trip_data.get('driver_id'):
			driver_data = frappe.db.sql("""
				SELECT full_name, phone_number, citizen_id FROM `tabSIS Bus Driver` WHERE name = %s
			""", (trip_data['driver_id'],), as_dict=True)
			if driver_data:
				trip_data.update({
					"driver_name": driver_data[0].full_name,
					"driver_phone": driver_data[0].phone_number,
					"driver_can_cuoc": driver_data[0].citizen_id
				})

		if trip_data.get('monitor1_id'):
			monitor1_data = frappe.db.sql("""
				SELECT full_name, phone_number, citizen_id FROM `tabSIS Bus Monitor` WHERE name = %s
			""", (trip_data['monitor1_id'],), as_dict=True)
			if monitor1_data:
				trip_data.update({
					"monitor1_name": monitor1_data[0].full_name,
					"monitor1_phone": monitor1_data[0].phone_number,
					"monitor1_can_cuoc": monitor1_data[0].citizen_id
				})

		if trip_data.get('monitor2_id'):
			monitor2_data = frappe.db.sql("""
				SELECT full_name, phone_number, citizen_id FROM `tabSIS Bus Monitor` WHERE name = %s
			""", (trip_data['monitor2_id'],), as_dict=True)
			if monitor2_data:
				trip_data.update({
					"monitor2_name": monitor2_data[0].full_name,
					"monitor2_phone": monitor2_data[0].phone_number,
					"monitor2_can_cuoc": monitor2_data[0].citizen_id
				})

		# Get trip students
		students = frappe.db.sql("""
			SELECT
				name, student_id, class_student_id, student_image,
				student_name, student_code, class_name, pickup_order,
				pickup_location, drop_off_location, student_status,
				boarding_time, drop_off_time, absent_reason, notes
			FROM `tabSIS Bus Daily Trip Student`
			WHERE daily_trip_id = %s
			ORDER BY pickup_order
		""", (name,), as_dict=True)

		trip_data.update({
			"trip_students": students,
			"total_students": len(students)
		})

		return success_response(
			data=trip_data,
			message="Daily trip retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting daily trip: {str(e)}")
		return error_response(f"Daily trip not found: {str(e)}")

@frappe.whitelist()
def update_daily_trip():
	"""Update an existing daily trip"""
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
					frappe.logger().info(f"Received JSON data for update_daily_trip: {data}, name: {name}")
				else:
					data = frappe.local.form_dict
					name = data.get('name')
					data.pop('name', None)
					frappe.logger().info(f"Received form data for update_daily_trip (empty JSON body): {data}")
			except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
				# If JSON parsing fails, use form_dict
				frappe.logger().error(f"JSON parsing failed in update_daily_trip: {str(e)}")
				data = frappe.local.form_dict
				name = data.get('name')
				data.pop('name', None)
				frappe.logger().info(f"Using form data for update_daily_trip after JSON failure: {data}")
		else:
			# Fallback to form_dict
			data = frappe.local.form_dict
			name = data.get('name')
			data.pop('name', None)
			frappe.logger().info(f"No request data, using form_dict for update_daily_trip: {data}")

		# If name is still not found, try request args
		if not name:
			name = frappe.request.args.get('name')

		if not name:
			return error_response("Daily trip name is required")

		# Update daily trip using raw SQL
		update_fields = []
		update_values = []

		for key, value in data.items():
			update_fields.append(f"{key} = %s")
			update_values.append(value)

		update_values.append(name)

		if update_fields:
			query = f"""
				UPDATE `tabSIS Bus Daily Trip`
				SET {', '.join(update_fields)}
				WHERE name = %s
			"""
			frappe.db.sql(query, update_values)
			frappe.db.commit()

			# Get updated data
			updated_trip = frappe.db.sql("""
				SELECT * FROM `tabSIS Bus Daily Trip` WHERE name = %s
			""", (name,), as_dict=True)

			return success_response(
				data=updated_trip[0] if updated_trip else {},
				message="Daily trip updated successfully"
			)
		else:
			return error_response("No data to update")
	except Exception as e:
		frappe.log_error(f"Error updating daily trip: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update daily trip: {str(e)}")

@frappe.whitelist()
def delete_daily_trip():
	"""Delete a daily trip"""
	try:
		name = frappe.local.form_dict.get('name') or frappe.request.args.get('name')
		if not name:
			return error_response("Daily trip name is required")

		# Delete associated students first
		frappe.db.sql("DELETE FROM `tabSIS Bus Daily Trip Student` WHERE daily_trip_id = %s", (name,))

		# Delete the daily trip
		frappe.db.sql("DELETE FROM `tabSIS Bus Daily Trip` WHERE name = %s", (name,))
		frappe.db.commit()

		return success_response(
			message="Daily trip deleted successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error deleting daily trip: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete daily trip: {str(e)}")

@frappe.whitelist()
def get_daily_trips_by_date():
	"""Get daily trips by date and optionally campus/school year"""
	try:
		trip_date = frappe.local.form_dict.get('trip_date') or frappe.request.args.get('trip_date')
		if not trip_date:
			return error_response("Trip date is required")

		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()
		school_year_id = frappe.local.form_dict.get('school_year_id') or frappe.request.args.get('school_year_id')

		filters = {"trip_date": trip_date}
		if campus_id:
			filters["campus_id"] = campus_id
		if school_year_id:
			filters["school_year_id"] = school_year_id

		# Use raw SQL query to get daily trips for the specified date (temporarily without campus filtering)
		daily_trips = frappe.db.sql("""
			SELECT
				name, route_id, trip_date, weekday, trip_type,
				vehicle_id, driver_id, monitor1_id, monitor2_id,
				trip_status, campus_id, school_year_id
			FROM `tabSIS Bus Daily Trip`
			WHERE trip_date = %s
			ORDER BY route_id ASC, trip_type ASC
			LIMIT 100
		""", (trip_date,), as_dict=True)

		# Enrich with related information
		for trip in daily_trips:
			# Get route information
			if trip.route_id:
				route = frappe.get_doc("SIS Bus Route", trip.route_id)
				trip.update({
					"route_name": route.route_name
				})

			# Get vehicle information
			if trip.vehicle_id:
				vehicle = frappe.get_doc("SIS Bus Transportation", trip.vehicle_id)
				trip.update({
					"vehicle_code": vehicle.vehicle_code,
					"license_plate": vehicle.license_plate,
					"vehicle_type": vehicle.vehicle_type
				})

			# Get driver information
			if trip.driver_id:
				driver = frappe.get_doc("SIS Bus Driver", trip.driver_id)
				trip.update({
					"driver_name": driver.full_name,
					"driver_phone": driver.phone_number
				})

			# Get monitor information
			if trip.monitor1_id:
				monitor1 = frappe.get_doc("SIS Bus Monitor", trip.monitor1_id)
				trip.update({
					"monitor1_name": monitor1.full_name,
					"monitor1_phone": monitor1.phone_number
				})

			if trip.monitor2_id:
				monitor2 = frappe.get_doc("SIS Bus Monitor", trip.monitor2_id)
				trip.update({
					"monitor2_name": monitor2.full_name,
					"monitor2_phone": monitor2.phone_number
				})

			# Get trip students count
			student_count = frappe.db.sql("""
				SELECT COUNT(*) FROM `tabSIS Bus Daily Trip Student`
				WHERE daily_trip_id = %s
			""", (trip.name,))[0][0]
			trip.update({
				"total_students": student_count
			})

		return success_response(
			data=daily_trips,
			message=f"Daily trips for {trip_date} retrieved successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error getting daily trips by date: {str(e)}")
		return error_response(f"Failed to get daily trips by date: {str(e)}")

@frappe.whitelist()
def update_trip_status():
	"""Update daily trip status"""
	try:
		# Get data from request
		daily_trip_id = frappe.local.form_dict.get('daily_trip_id') or frappe.request.args.get('daily_trip_id')
		trip_status = frappe.local.form_dict.get('trip_status') or frappe.request.args.get('trip_status')
		notes = frappe.local.form_dict.get('notes') or frappe.request.args.get('notes')

		if not daily_trip_id:
			return error_response("Daily trip ID is required")
		if not trip_status:
			return error_response("Trip status is required")

		# Validate trip status
		valid_statuses = ['Not Started', 'In Progress', 'Completed']
		if trip_status not in valid_statuses:
			return error_response(f"Invalid trip status. Must be one of: {', '.join(valid_statuses)}")

		# Update trip status using raw SQL
		if notes:
			frappe.db.sql("""
				UPDATE `tabSIS Bus Daily Trip`
				SET trip_status = %s, notes = %s
				WHERE name = %s
			""", (trip_status, notes, daily_trip_id))
		else:
			frappe.db.sql("""
				UPDATE `tabSIS Bus Daily Trip`
				SET trip_status = %s
				WHERE name = %s
			""", (trip_status, daily_trip_id))

		frappe.db.commit()

		# Get updated data
		updated_trip = frappe.db.sql("""
			SELECT * FROM `tabSIS Bus Daily Trip` WHERE name = %s
		""", (daily_trip_id,), as_dict=True)

		return success_response(
			data=updated_trip[0] if updated_trip else {},
			message="Trip status updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating trip status: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update trip status: {str(e)}")

@frappe.whitelist()
def trigger_create_daily_trips():
	"""Manually trigger daily trips creation for a route"""
	try:
		route_id = frappe.local.form_dict.get('route_id') or frappe.request.args.get('route_id')
		if not route_id:
			return error_response("Route ID is required")
		
		# Get the route
		route = frappe.get_doc("SIS Bus Route", route_id)
		
		if route.status != "Active":
			return error_response("Route must be Active to create daily trips")
		
		# Create daily trips
		frappe.logger().info(f"📋 Starting manual daily trips creation for route {route_id}")
		route.create_daily_trips()
		frappe.db.commit()
		
		# Count created trips
		trips_count = frappe.db.sql("""
			SELECT COUNT(*) FROM `tabSIS Bus Daily Trip`
			WHERE route_id = %s
		""", (route_id,))[0][0]
		
		frappe.logger().info(f"✅ Manual daily trips creation completed for route {route_id}, total trips: {trips_count}")
		
		return success_response(
			data={"route_id": route_id, "trips_created": trips_count},
			message=f"Daily trips created successfully. Total trips: {trips_count}",
			logs=[
				f"Route: {route.route_name}",
				f"Total daily trips: {trips_count}"
			]
		)
	except Exception as e:
		frappe.log_error(f"Error triggering daily trips creation: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create daily trips: {str(e)}")

@frappe.whitelist()
def update_student_status_in_trip():
	"""Update student status in a daily trip"""
	try:
		# Get data from request
		daily_trip_student_id = frappe.local.form_dict.get('daily_trip_student_id') or frappe.request.args.get('daily_trip_student_id')
		student_status = frappe.local.form_dict.get('student_status') or frappe.request.args.get('student_status')
		boarding_time = frappe.local.form_dict.get('boarding_time') or frappe.request.args.get('boarding_time')
		drop_off_time = frappe.local.form_dict.get('drop_off_time') or frappe.request.args.get('drop_off_time')
		absent_reason = frappe.local.form_dict.get('absent_reason') or frappe.request.args.get('absent_reason')
		notes = frappe.local.form_dict.get('notes') or frappe.request.args.get('notes')

		if not daily_trip_student_id:
			return error_response("Daily trip student ID is required")
		if not student_status:
			return error_response("Student status is required")

		# Validate student status
		valid_statuses = ['Not Boarded', 'Boarded', 'Dropped Off', 'Absent']
		if student_status not in valid_statuses:
			return error_response(f"Invalid student status. Must be one of: {', '.join(valid_statuses)}")

		doc = frappe.get_doc("SIS Bus Daily Trip Student", daily_trip_student_id)

		# Update fields based on status
		if student_status == 'Boarded' and boarding_time:
			doc.boarding_time = boarding_time
		elif student_status == 'Dropped Off' and drop_off_time:
			doc.drop_off_time = drop_off_time
		elif student_status == 'Absent' and absent_reason:
			doc.absent_reason = absent_reason

		doc.student_status = student_status
		if notes:
			doc.notes = notes

		doc.save()
		frappe.db.commit()

		return success_response(
			data=doc.as_dict(),
			message="Student status updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating student status in trip: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update student status: {str(e)}")
