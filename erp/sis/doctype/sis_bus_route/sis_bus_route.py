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
		"""Create daily trips for the next 30 days"""
		from datetime import datetime, timedelta

		start_date = datetime.now().date()
		end_date = start_date + timedelta(days=30)

		current_date = start_date
		weekdays_map = {
			0: "Thứ 2",
			1: "Thứ 3",
			2: "Thứ 4",
			3: "Thứ 5",
			4: "Thứ 6",
			5: "Thứ 7",
			6: "Chủ nhật"
		}

		while current_date <= end_date:
			weekday = weekdays_map[current_date.weekday()]

			# Create daily trips for both trip types
			for trip_type in ["Đón", "Trả"]:
				self.create_daily_trip_for_date(current_date, weekday, trip_type)

			current_date += timedelta(days=1)

	def create_daily_trip_for_date(self, trip_date, weekday, trip_type):
		"""Create a daily trip for specific date and trip type"""
		# Check if daily trip already exists
		existing_trip = frappe.db.exists("SIS Bus Daily Trip", {
			"route_id": self.name,
			"trip_date": trip_date,
			"weekday": weekday,
			"trip_type": trip_type
		})

		if existing_trip:
			return  # Skip if already exists

		# Get students for this route, weekday, and trip type with full student info
		students = frappe.db.sql("""
			SELECT
				brs.student_id, brs.class_student_id, brs.pickup_order,
				brs.pickup_location, brs.drop_off_location,
				s.student_name, s.student_code,
				c.title as class_name
			FROM `tabSIS Bus Route Student` brs
			INNER JOIN `tabCRM Student` s ON brs.student_id = s.name
			LEFT JOIN `tabSIS Class Student` cs ON brs.class_student_id = cs.name
			LEFT JOIN `tabSIS Class` c ON cs.class_id = c.name
			WHERE brs.route_id = %s
			AND brs.weekday = %s
			AND brs.trip_type = %s
			ORDER BY brs.pickup_order
		""", (self.name, weekday, trip_type), as_dict=True)

		if not students:
			return  # No students for this route/weekday/trip_type

		# Create daily trip
		daily_trip_data = {
			"route_id": self.name,
			"trip_date": trip_date,
			"weekday": weekday,
			"trip_type": trip_type,
			"vehicle_id": self.vehicle_id,
			"driver_id": self.driver_id,
			"monitor1_id": self.monitor1_id,
			"monitor2_id": self.monitor2_id,
			"trip_status": "Chưa xuất phát",
			"campus_id": self.campus_id,
			"school_year_id": self.school_year_id
		}

		daily_trip = frappe.get_doc({
			"doctype": "SIS Bus Daily Trip",
			**daily_trip_data
		})

		daily_trip.insert()

		# Add students to daily trip with full information
		for student in students:
			student_data = {
				"daily_trip_id": daily_trip.name,
				"student_id": student.student_id,
				"class_student_id": student.class_student_id,
				"student_image": student.image,
				"student_name": student.student_name,
				"student_code": student.student_code,
				"class_name": student.class_name,
				"pickup_order": student.pickup_order,
				"pickup_location": student.pickup_location,
				"drop_off_location": student.drop_off_location,
				"student_status": "Chưa lên xe"
			}

			frappe.get_doc({
				"doctype": "SIS Bus Daily Trip Student",
				**student_data
			}).insert()

		frappe.db.commit()
