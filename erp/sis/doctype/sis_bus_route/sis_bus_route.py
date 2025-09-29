# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusRoute(Document):
	def validate(self):
		self.validate_references_exist()
		self.validate_monitor_assignment()

	def validate_references_exist(self):
		"""Validate that all referenced entities exist"""
		if self.vehicle_id and not frappe.db.exists("SIS Bus Transportation", self.vehicle_id):
			frappe.throw("Xe không tồn tại")

		if self.driver_id and not frappe.db.exists("SIS Bus Driver", self.driver_id):
			frappe.throw("Tài xế không tồn tại")

		if self.monitor1_id and not frappe.db.exists("SIS Bus Monitor", self.monitor1_id):
			frappe.throw("Monitor 1 không tồn tại")

		if self.monitor2_id and not frappe.db.exists("SIS Bus Monitor", self.monitor2_id):
			frappe.throw("Monitor 2 không tồn tại")

	def validate_monitor_assignment(self):
		"""Validate that monitors are not assigned to multiple routes"""
		if self.monitor1_id == self.monitor2_id:
			frappe.throw("Monitor 1 và Monitor 2 không được giống nhau")

		# Check if monitors are already assigned to other routes
		existing_routes = frappe.db.sql("""
			SELECT name, route_name
			FROM `tabSIS Bus Route`
			WHERE (monitor1_id = %s OR monitor2_id = %s)
			AND name != %s
			AND status = 'Active'
		""", (self.monitor1_id, self.monitor2_id, self.name))

		if existing_routes:
			route_names = [route[1] for route in existing_routes]
			frappe.throw(f"Monitor đã được phân công cho tuyến: {', '.join(route_names)}")

	def after_insert(self):
		"""Create daily trips when route is created"""
		if self.status == "Active":
			self.create_daily_trips()

	def on_update(self):
		"""Create daily trips when route is created or updated"""
		if self.has_value_changed("status") and self.status == "Active":
			self.create_daily_trips()

	def create_daily_trips(self):
		"""Create daily trips for the next 30 days (weekdays only)"""
		from datetime import datetime, timedelta

		start_date = datetime.now().date()
		end_date = start_date + timedelta(days=30)

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

		frappe.logger().info(f"Creating daily trips for route {self.name} from {start_date} to {end_date}")

		while current_date <= end_date:
			weekday_num = current_date.weekday()
			
			# Only create for weekdays (Monday-Friday: 0-4)
			if weekday_num <= 4:  # Monday to Friday only
				weekday = weekdays_map[weekday_num]
				
				# Create daily trips for both trip types
				for trip_type in ["Đón", "Trả"]:
					try:
						created = self.create_daily_trip_for_date(current_date, weekday, trip_type)
						if created:
							total_created += 1
					except Exception as e:
						error_msg = f"Failed to create daily trip for {current_date} {weekday} {trip_type}: {str(e)}"
						errors.append(error_msg)
						frappe.logger().error(error_msg)
						# Continue with other trips instead of stopping

			current_date += timedelta(days=1)

		frappe.logger().info(f"Created {total_created} daily trips for route {self.name}")
		
		if errors:
			frappe.logger().warning(f"Encountered {len(errors)} errors while creating daily trips: {errors[:5]}")  # Log first 5 errors

	def create_daily_trip_for_date(self, trip_date, weekday, trip_type):
		"""Create a daily trip for specific date and trip type"""
		try:
			# Check if daily trip already exists
			existing_trip = frappe.db.exists("SIS Bus Daily Trip", {
				"route_id": self.name,
				"trip_date": trip_date,
				"weekday": weekday,
				"trip_type": trip_type
			})

			if existing_trip:
				frappe.logger().debug(f"Daily trip already exists: {self.name} - {trip_date} - {weekday} - {trip_type}")
				return False  # Skip if already exists

			# Get students for this route, weekday, and trip type with full student info
			# Since route_students is a child table, get students directly from the route's child table
			students = []
			if hasattr(self, 'route_students') and self.route_students:
				for student in self.route_students:
					if student.weekday == weekday and student.trip_type == trip_type:
						# Get student details
						student_doc = frappe.get_doc("CRM Student", student.student_id)
						class_name = ""
						if student.class_student_id:
							class_student = frappe.get_doc("SIS Class Student", student.class_student_id)
							if class_student.class_id:
								class_doc = frappe.get_doc("SIS Class", class_student.class_id)
								class_name = class_doc.title or class_doc.name

						students.append({
							'student_id': student.student_id,
							'class_student_id': student.class_student_id,
							'pickup_order': student.pickup_order,
							'pickup_location': student.pickup_location,
							'drop_off_location': student.drop_off_location,
							'notes': student.notes,
							'student_name': student_doc.student_name,
							'student_code': student_doc.student_code,
							'class_name': class_name
						})

			# Sort by pickup_order
			students.sort(key=lambda x: x['pickup_order'])

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
			daily_trip.insert()
			
			students_added = 0
			
			# Add students to daily trip with full information (if any)
			if students:
				for student in students:
					try:
						student_data = {
							"daily_trip_id": daily_trip.name,
							"student_id": student.student_id,
							"class_student_id": student.class_student_id,
							"student_image": "",
							"student_name": student.student_name,
							"student_code": student.student_code,
							"class_name": student.class_name or "",
							"pickup_order": student.pickup_order,
							"pickup_location": student.pickup_location,
							"drop_off_location": student.drop_off_location,
							"notes": student.notes or "",
							"student_status": "Not Boarded"
						}

						frappe.get_doc({
							"doctype": "SIS Bus Daily Trip Student",
							**student_data
						}).insert()
						
						students_added += 1
						
					except Exception as e:
						frappe.logger().error(f"Failed to add student {student.student_id} to daily trip {daily_trip.name}: {str(e)}")
						# Continue with other students

			frappe.logger().info(f"Created daily trip {daily_trip.name} for {trip_date} {weekday} {trip_type} with {students_added} students")
			
			# Commit after successful creation
			frappe.db.commit()
			return True
			
		except Exception as e:
			frappe.logger().error(f"Error creating daily trip for {self.name} - {trip_date} - {weekday} - {trip_type}: {str(e)}")
			frappe.db.rollback()
			raise e
