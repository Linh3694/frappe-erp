# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

def create_daily_trips_for_route(route_name):
	"""Background job to create daily trips for a route"""
	try:
		route = frappe.get_doc("SIS Bus Route", route_name)
		route.create_daily_trips()
		frappe.db.commit()
		frappe.logger().info(f"✅ Successfully created daily trips for route {route_name}")
	except Exception as e:
		frappe.log_error(f"Error creating daily trips for route {route_name}: {str(e)}", "Bus Route Daily Trips Creation")
		frappe.logger().error(f"❌ Failed to create daily trips for route {route_name}: {str(e)}")
		frappe.db.rollback()

class SISBusRoute(Document):
	def validate(self):
		self.validate_references_exist()
		self.validate_monitor_assignment()

	def validate_references_exist(self):
		"""Validate that all referenced entities exist"""
		if self.vehicle_id:
			vehicle_exists = frappe.db.sql("SELECT name FROM `tabSIS Bus Transportation` WHERE name = %s LIMIT 1", (self.vehicle_id,))
			if not vehicle_exists:
				frappe.throw("Xe không tồn tại")

		if self.driver_id:
			driver_exists = frappe.db.sql("SELECT name FROM `tabSIS Bus Driver` WHERE name = %s LIMIT 1", (self.driver_id,))
			if not driver_exists:
				frappe.throw("Tài xế không tồn tại")

		if self.monitor1_id:
			monitor1_exists = frappe.db.sql("SELECT name FROM `tabSIS Bus Monitor` WHERE name = %s LIMIT 1", (self.monitor1_id,))
			if not monitor1_exists:
				frappe.throw("Monitor 1 không tồn tại")

		if self.monitor2_id:
			monitor2_exists = frappe.db.sql("SELECT name FROM `tabSIS Bus Monitor` WHERE name = %s LIMIT 1", (self.monitor2_id,))
			if not monitor2_exists:
				frappe.throw("Monitor 2 không tồn tại")

	def validate_monitor_assignment(self):
		"""Validate that monitors are not assigned to multiple routes or daily trips"""
		frappe.logger().info("🔍 DEBUG: validate_monitor_assignment called")
		frappe.logger().info(f"🔍 DEBUG: monitor1_id={self.monitor1_id}, monitor2_id={self.monitor2_id}, self.name={self.name}")
		
		if self.monitor1_id == self.monitor2_id:
			frappe.throw("Monitor 1 và Monitor 2 không được giống nhau")
		
		# Check if monitors are already assigned to other routes OR daily trips
		# Handle case where self.name might be None for new documents
		# Only check if monitor1_id or monitor2_id is provided
		monitors_to_check = []
		if self.monitor1_id:
			monitors_to_check.append(self.monitor1_id)
		if self.monitor2_id:
			monitors_to_check.append(self.monitor2_id)
		
		if not monitors_to_check:
			return  # No monitors to validate
		
		# Check active routes
		if self.name:
			# For existing documents, exclude current route
			placeholders = ','.join(['%s'] * len(monitors_to_check))
			query = f"""
				SELECT name, route_name, monitor1_id, monitor2_id
				FROM `tabSIS Bus Route`
				WHERE (monitor1_id IN ({placeholders}) OR monitor2_id IN ({placeholders}))
				AND name != %s
				AND status = 'Active'
			"""
			params = monitors_to_check + monitors_to_check + [self.name]
			existing_routes = frappe.db.sql(query, params, as_dict=True)
		else:
			# For new documents, check all routes
			placeholders = ','.join(['%s'] * len(monitors_to_check))
			query = f"""
				SELECT name, route_name, monitor1_id, monitor2_id
				FROM `tabSIS Bus Route`
				WHERE (monitor1_id IN ({placeholders}) OR monitor2_id IN ({placeholders}))
				AND status = 'Active'
			"""
			params = monitors_to_check + monitors_to_check
			existing_routes = frappe.db.sql(query, params, as_dict=True)

		if existing_routes:
			# Build detailed error message
			conflicts = []
			for route in existing_routes:
				if self.monitor1_id in [route.monitor1_id, route.monitor2_id]:
					conflicts.append(f"Monitor 1 đã ở tuyến Active {route.route_name}")
				if self.monitor2_id in [route.monitor1_id, route.monitor2_id]:
					conflicts.append(f"Monitor 2 đã ở tuyến Active {route.route_name}")
			frappe.throw(f"Trùng monitor: {'; '.join(set(conflicts))}")
		
		# Also check if resources (monitor, driver, vehicle) have future daily trips from OTHER ACTIVE routes
		# This ensures no resource conflicts when creating/updating route
		from datetime import datetime, timedelta
		today = datetime.now().date()
		future_date = today + timedelta(days=30)
		
		exclude_route = self.name if self.name else "NONE"
		
		# Check monitors
		if monitors_to_check:
			placeholders = ','.join(['%s'] * len(monitors_to_check))
			monitor_trips_query = f"""
				SELECT DISTINCT dt.route_id, dt.trip_date, dt.trip_type, br.route_name
				FROM `tabSIS Bus Daily Trip` dt
				INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
				WHERE (dt.monitor1_id IN ({placeholders}) OR dt.monitor2_id IN ({placeholders}))
				AND dt.trip_date BETWEEN %s AND %s
				AND dt.route_id != %s
				AND br.status = 'Active'
				LIMIT 3
			"""
			params = monitors_to_check + monitors_to_check + [today, future_date, exclude_route]
			monitor_conflicts = frappe.db.sql(monitor_trips_query, params, as_dict=True)
			
			if monitor_conflicts:
				trip_info = [f"{t.route_name} - {t.trip_type} ({t.trip_date})" for t in monitor_conflicts]
				frappe.throw(f"Monitor đã có lịch chạy xe: {', '.join(trip_info)}...")
		
		# Check driver
		if self.driver_id:
			driver_trips_query = """
				SELECT DISTINCT dt.route_id, dt.trip_date, dt.trip_type, br.route_name
				FROM `tabSIS Bus Daily Trip` dt
				INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
				WHERE dt.driver_id = %s
				AND dt.trip_date BETWEEN %s AND %s
				AND dt.route_id != %s
				AND br.status = 'Active'
				LIMIT 3
			"""
			driver_conflicts = frappe.db.sql(driver_trips_query, [self.driver_id, today, future_date, exclude_route], as_dict=True)
			
			if driver_conflicts:
				trip_info = [f"{t.route_name} - {t.trip_type} ({t.trip_date})" for t in driver_conflicts]
				frappe.throw(f"Tài xế đã có lịch chạy xe: {', '.join(trip_info)}...")
		
		# Check vehicle
		if self.vehicle_id:
			vehicle_trips_query = """
				SELECT DISTINCT dt.route_id, dt.trip_date, dt.trip_type, br.route_name
				FROM `tabSIS Bus Daily Trip` dt
				INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
				WHERE dt.vehicle_id = %s
				AND dt.trip_date BETWEEN %s AND %s
				AND dt.route_id != %s
				AND br.status = 'Active'
				LIMIT 3
			"""
			vehicle_conflicts = frappe.db.sql(vehicle_trips_query, [self.vehicle_id, today, future_date, exclude_route], as_dict=True)
			
			if vehicle_conflicts:
				trip_info = [f"{t.route_name} - {t.trip_type} ({t.trip_date})" for t in vehicle_conflicts]
				frappe.throw(f"Xe đã có lịch chạy: {', '.join(trip_info)}...")

	def after_insert(self):
		"""Create daily trips when route is created"""
		frappe.logger().info(f"📍 after_insert called for route {self.name}, status={self.status}")
		if self.status == "Active":
			try:
				frappe.logger().info(f"🚀 Starting daily trips creation for new route {self.name}")
				self.create_daily_trips()
				frappe.db.commit()  # Explicitly commit daily trips
				frappe.logger().info(f"✅ Daily trips creation completed and committed for route {self.name}")
			except Exception as e:
				# Log error but don't block route creation
				import traceback
				error_msg = f"❌ Failed to create daily trips for route {self.name}: {str(e)}\n{traceback.format_exc()}"
				frappe.log_error(error_msg, "Bus Route Daily Trips Creation Error")
				frappe.logger().error(error_msg)
				# Don't raise exception to avoid blocking route creation
		else:
			frappe.logger().info(f"⏭️ Skipping daily trips creation - route status is {self.status}")

	def on_update(self):
		"""Handle route updates - create daily trips or update existing ones"""
		from datetime import datetime
		
		# Case 1: Status changed to Active - create new daily trips
		if self.has_value_changed("status") and self.status == "Active":
			try:
				frappe.logger().info(f"🚀 Starting daily trips creation for updated route {self.name}")
				self.create_daily_trips()
				frappe.logger().info(f"✅ Daily trips creation completed for route {self.name}")
			except Exception as e:
				# Log error but don't block route update
				error_msg = f"❌ Failed to create daily trips for route {self.name}: {str(e)}"
				frappe.log_error(error_msg, "Bus Route Daily Trips Creation Error")
				frappe.logger().error(error_msg)
				# Don't raise exception to avoid blocking route update
		
		# Case 2: Personnel/vehicle changes - update future daily trips
		# Only update if the route is Active
		if self.status == "Active":
			personnel_changed = (
				self.has_value_changed("vehicle_id") or
				self.has_value_changed("driver_id") or
				self.has_value_changed("monitor1_id") or
				self.has_value_changed("monitor2_id")
			)
			
			if personnel_changed:
				try:
					self.update_future_daily_trips()
				except Exception as e:
					error_msg = f"❌ Failed to update future daily trips for route {self.name}: {str(e)}"
					frappe.log_error(error_msg, "Bus Route Daily Trips Update Error")
					frappe.logger().error(error_msg)
	
	def update_future_daily_trips(self):
		"""Update all future daily trips (from today onwards) with new personnel/vehicle"""
		from datetime import datetime
		
		today = datetime.now().date()
		
		frappe.logger().info(f"🔄 Updating future daily trips for route {self.name} from {today}")
		frappe.logger().info(f"📌 New values: vehicle={self.vehicle_id}, driver={self.driver_id}, monitor1={self.monitor1_id}, monitor2={self.monitor2_id}")
		
		# Get all future daily trips for this route
		future_trips = frappe.db.sql("""
			SELECT name, trip_date, trip_type
			FROM `tabSIS Bus Daily Trip`
			WHERE route_id = %s AND trip_date >= %s
			ORDER BY trip_date
		""", (self.name, today), as_dict=True)
		
		if not future_trips:
			frappe.logger().info(f"ℹ️ No future daily trips found for route {self.name}")
			return
		
		frappe.logger().info(f"📋 Found {len(future_trips)} future daily trips to update")
		
		updated_count = 0
		for trip in future_trips:
			try:
				frappe.db.sql("""
					UPDATE `tabSIS Bus Daily Trip`
					SET vehicle_id = %s, driver_id = %s, monitor1_id = %s, monitor2_id = %s, modified = NOW()
					WHERE name = %s
				""", (self.vehicle_id, self.driver_id, self.monitor1_id, self.monitor2_id, trip.name))
				updated_count += 1
			except Exception as e:
				frappe.logger().error(f"  ❌ Failed to update trip {trip.name}: {str(e)}")
		
		frappe.db.commit()
		frappe.logger().info(f"✅ Updated {updated_count}/{len(future_trips)} future daily trips for route {self.name}")

	def create_daily_trips(self):
		"""
		Create daily trips for the next 7 days (weekdays only).
		Giảm từ 30 ngày xuống 7 ngày để tối ưu performance.
		Scheduled job sẽ tự động extend thêm mỗi ngày.
		"""
		from datetime import datetime, timedelta

		start_date = datetime.now().date()
		end_date = start_date + timedelta(days=7)  # Chỉ tạo 7 ngày tới

		current_date = start_date
		weekdays_map = {
			0: "Thứ 2",    # Monday
			1: "Thứ 3",    # Tuesday  
			2: "Thứ 4",    # Wednesday
			3: "Thứ 5",    # Thursday
			4: "Thứ 6",    # Friday
			5: "Thứ 7",    # Saturday
			6: "Chủ nhật"  # Sunday
		}

		total_created = 0
		errors = []

		frappe.logger().info(f"📅 Creating daily trips for route {self.name} from {start_date} to {end_date}")
		frappe.logger().info(f"📌 Route info: vehicle={self.vehicle_id}, driver={self.driver_id}, monitor1={self.monitor1_id}, monitor2={self.monitor2_id}")

		# Check if route has any students assigned before creating trips
		total_route_students = frappe.db.sql("""
			SELECT COUNT(*) FROM `tabSIS Bus Route Student`
			WHERE route_id = %s
		""", (self.name,))[0][0]
		frappe.logger().info(f"📊 Route {self.name} has {total_route_students} total students assigned")

		if total_route_students == 0:
			frappe.logger().warning(f"⚠️  Route {self.name} has no students assigned - daily trips will be created but will be empty")

		while current_date <= end_date:
			weekday_num = current_date.weekday()

			# Only create for weekdays (Monday-Friday: 0-4)
			if weekday_num <= 4:  # Monday to Friday only
				weekday = weekdays_map[weekday_num]

				frappe.logger().info(f"📅 Processing {current_date} ({weekday})")

				# Create daily trips for both trip types
				for trip_type in ["Đón", "Trả"]:
					try:
						# Check if there are students for this specific weekday and trip_type
						students_for_trip = frappe.db.sql("""
							SELECT COUNT(*) FROM `tabSIS Bus Route Student`
							WHERE route_id = %s AND weekday = %s AND trip_type = %s
						""", (self.name, weekday, trip_type))[0][0]

						frappe.logger().info(f"  📋 {trip_type} trip: {students_for_trip} students assigned")

						created = self.create_daily_trip_for_date(current_date, weekday, trip_type)
						if created:
							total_created += 1
							frappe.logger().info(f"  ✅ Created {trip_type} trip for {current_date}")
						else:
							frappe.logger().info(f"  ⏭️  {trip_type} trip already exists for {current_date}")
					except Exception as e:
						error_msg = f"Failed to create daily trip for {current_date} {weekday} {trip_type}: {str(e)}"
						errors.append(error_msg)
						frappe.logger().error(f"  ❌ {error_msg}")
						# Continue with other trips instead of stopping

			current_date += timedelta(days=1)

		frappe.logger().info(f"✅ Created {total_created} daily trips for route {self.name}")

		if errors:
			frappe.logger().warning(f"⚠️ Encountered {len(errors)} errors while creating daily trips")
			for i, error in enumerate(errors[:5], 1):  # Log first 5 errors
				frappe.logger().error(f"  Error {i}: {error}")

		# Log to Error Log for visibility
		if total_created == 0:
			frappe.log_error(f"No daily trips were created for route {self.name}. Check if route has students assigned or if trips already exist.", "Daily Trips Creation Warning")
		elif errors:
			frappe.log_error(f"Created {total_created} trips with {len(errors)} errors for route {self.name}", "Daily Trips Creation Partial Success")
		else:
			frappe.logger().info(f"🎉 Successfully created all {total_created} daily trips for route {self.name} with no errors")

	def create_daily_trip_for_date(self, trip_date, weekday, trip_type):
		"""Create a daily trip for specific date and trip type"""
		try:
			frappe.logger().info(f"🔄 Creating daily trip: route={self.name}, date={trip_date}, weekday={weekday}, type={trip_type}")

			# Check if daily trip already exists
			existing_trip = frappe.db.sql("""
				SELECT name FROM `tabSIS Bus Daily Trip`
				WHERE route_id = %s AND trip_date = %s AND weekday = %s AND trip_type = %s
				LIMIT 1
			""", (self.name, trip_date, weekday, trip_type))
			existing_trip = existing_trip[0][0] if existing_trip else None

			if existing_trip:
				frappe.logger().debug(f"⏭️  Daily trip already exists: {self.name} - {trip_date} - {weekday} - {trip_type}")
				return False  # Skip if already exists

			# Get students for this route, weekday, and trip type with full student info
			frappe.logger().info(f"📝 Querying students for route {self.name}, weekday={weekday}, trip_type={trip_type}")

			# First, check if there are any route students for this route
			route_students_count = frappe.db.sql("""
				SELECT COUNT(*) FROM `tabSIS Bus Route Student`
				WHERE route_id = %s AND weekday = %s AND trip_type = %s
			""", (self.name, weekday, trip_type))[0][0]

			frappe.logger().info(f"📊 Found {route_students_count} route students for route {self.name}, weekday={weekday}, trip_type={trip_type}")

			if route_students_count == 0:
				frappe.logger().info(f"ℹ️  No students assigned for route {self.name} on {weekday} {trip_type} - will create empty trip")
				students = []
			else:
				students = frappe.db.sql("""
					SELECT
						brs.student_id, brs.class_student_id, brs.pickup_order,
						brs.pickup_location, brs.drop_off_location, brs.notes,
						s.student_name, s.student_code,
						COALESCE(c.title, cs.class_name, '') as class_name
					FROM `tabSIS Bus Route Student` brs
					INNER JOIN `tabCRM Student` s ON brs.student_id = s.name
					LEFT JOIN `tabSIS Class Student` cs ON brs.class_student_id = cs.name
					LEFT JOIN `tabSIS Class` c ON cs.class_id = c.name
					WHERE brs.route_id = %s
					AND brs.weekday = %s
					AND brs.trip_type = %s
					ORDER BY brs.pickup_order
				""", (self.name, weekday, trip_type), as_dict=True)

				frappe.logger().info(f"👥 Found {len(students)} students for this trip after query")

				# Log details of students found (or not found)
				if len(students) != route_students_count:
					frappe.logger().warning(f"⚠️  Mismatch: {route_students_count} route students but only {len(students)} valid students found")
					frappe.logger().warning("This might be due to missing student records or class information")

			# Create daily trip first (students can be added later)
			daily_trip_data = {
				"route_id": self.name,
				"trip_date": trip_date,
				"weekday": weekday,
				"trip_type": trip_type,
				"vehicle_id": self.vehicle_id,
				"driver_id": self.driver_id,
				"monitor1_id": self.monitor1_id,
				"monitor2_id": self.monitor2_id,
				"trip_status": "Not Started",
				"campus_id": self.campus_id,
				"school_year_id": self.school_year_id
			}

			daily_trip = frappe.get_doc({
				"doctype": "SIS Bus Daily Trip",
				**daily_trip_data
			})

			# Insert daily trip
			frappe.logger().info(f"💾 Inserting daily trip document...")
			daily_trip.insert()
			frappe.logger().info(f"✅ Daily trip inserted: {daily_trip.name}")
			
			students_added = 0
			
			# Add students to daily trip with full information (if any)
			if students:
				frappe.logger().info(f"📚 Adding {len(students)} students to daily trip {daily_trip.name}")
				for student in students:
					try:
						# Validate required fields before inserting
						if not student.student_id or not student.student_name:
							frappe.logger().error(f"  ❌ Invalid student data: missing student_id or student_name for {student.get('student_code', 'unknown')}")
							continue

						student_data = {
							"daily_trip_id": daily_trip.name,
							"student_id": student.student_id,
							"class_student_id": student.class_student_id or "",
							"student_image": "",
							"student_name": student.student_name,
							"student_code": student.student_code or "",
							"class_name": student.class_name or "",
							"pickup_order": student.pickup_order or 0,
							"pickup_location": student.pickup_location or "",
							"drop_off_location": student.drop_off_location or "",
							"notes": student.notes or "",
							"student_status": "Not Boarded"
						}

						frappe.get_doc({
							"doctype": "SIS Bus Daily Trip Student",
							**student_data
						}).insert()

						students_added += 1
						frappe.logger().debug(f"  ✓ Added student {student.student_code} - {student.student_name}")

					except Exception as e:
						frappe.logger().error(f"  ❌ Failed to add student {student.student_id} to daily trip {daily_trip.name}: {str(e)}")
						# Continue with other students
			else:
				frappe.logger().info(f"ℹ️  No students assigned for this trip schedule (route_students_count={route_students_count})")

			frappe.logger().info(f"✅ Created daily trip {daily_trip.name} for {trip_date} {weekday} {trip_type} with {students_added} students")
			
			return True
			
		except Exception as e:
			import traceback
			error_msg = f"❌ Error creating daily trip for {self.name} - {trip_date} - {weekday} - {trip_type}: {str(e)}"
			frappe.logger().error(error_msg)
			frappe.logger().error(f"Traceback: {traceback.format_exc()}")
			raise e
