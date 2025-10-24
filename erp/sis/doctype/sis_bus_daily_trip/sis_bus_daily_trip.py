# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import datetime

class SISBusDailyTrip(Document):
	def validate(self):
		self.validate_references_exist()
		self.validate_trip_date()
		self.validate_trip_assignment()

	def validate_references_exist(self):
		"""Validate that all referenced entities exist"""
		if self.route_id and not frappe.db.exists("SIS Bus Route", self.route_id):
			frappe.throw("Tuyến đường không tồn tại")

		if self.vehicle_id and not frappe.db.exists("SIS Bus Transportation", self.vehicle_id):
			frappe.throw("Xe không tồn tại")

		if self.driver_id and not frappe.db.exists("SIS Bus Driver", self.driver_id):
			frappe.throw("Tài xế không tồn tại")

		if self.monitor1_id and not frappe.db.exists("SIS Bus Monitor", self.monitor1_id):
			frappe.throw("Monitor 1 không tồn tại")

		if self.monitor2_id and not frappe.db.exists("SIS Bus Monitor", self.monitor2_id):
			frappe.throw("Monitor 2 không tồn tại")

	def validate_trip_date(self):
		"""Validate trip date is not in the past"""
		if self.trip_date and self.trip_date < datetime.now().date():
			frappe.throw("Ngày chạy không được là ngày trong quá khứ")

	def validate_trip_assignment(self):
		"""Validate that monitors, driver, and vehicle are not assigned to multiple trips on same date+trip_type from ACTIVE routes"""
		if self.monitor1_id == self.monitor2_id:
			frappe.throw("Monitor 1 và Monitor 2 không được giống nhau")

		# Check if resources (monitor, driver, vehicle) are already assigned to OTHER ACTIVE ROUTES' trips
		# on same date AND same trip_type (Đón hoặc Trả)
		# Allow same resources within same route for different trip types
		# Only check against Active routes to allow reusing resources from Inactive routes
		# Handle case where self.name might be None for new documents
		
		if self.name:
			# For existing documents, exclude current trip by name and route
			
			# Check monitors
			if self.monitor1_id or self.monitor2_id:
				monitor_conditions = []
				monitor_params = [self.trip_date, self.trip_type]
				
				if self.monitor1_id:
					monitor_conditions.append("dt.monitor1_id = %s OR dt.monitor2_id = %s")
					monitor_params.extend([self.monitor1_id, self.monitor1_id])
				if self.monitor2_id:
					monitor_conditions.append("dt.monitor1_id = %s OR dt.monitor2_id = %s")
					monitor_params.extend([self.monitor2_id, self.monitor2_id])
				
				monitor_params.extend([self.name, self.route_id])
				
				monitor_query = f"""
					SELECT dt.name, dt.route_id, br.route_name
					FROM `tabSIS Bus Daily Trip` dt
					INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
					WHERE dt.trip_date = %s AND dt.trip_type = %s
					AND ({' OR '.join(monitor_conditions)})
					AND dt.name != %s
					AND dt.route_id != %s
					AND br.status = 'Active'
				"""
				monitor_conflicts = frappe.db.sql(monitor_query, monitor_params, as_dict=True)
				
				if monitor_conflicts:
					route_names = [f"{t.route_name}" for t in monitor_conflicts]
					frappe.throw(f"Monitor đã phân công cho chuyến {self.trip_type} khác: {', '.join(set(route_names))}")
			
			# Check driver
			if self.driver_id:
				driver_query = """
					SELECT dt.name, dt.route_id, br.route_name
					FROM `tabSIS Bus Daily Trip` dt
					INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
					WHERE dt.trip_date = %s AND dt.trip_type = %s
					AND dt.driver_id = %s
					AND dt.name != %s
					AND dt.route_id != %s
					AND br.status = 'Active'
				"""
				driver_params = [self.trip_date, self.trip_type, self.driver_id, self.name, self.route_id]
				driver_conflicts = frappe.db.sql(driver_query, driver_params, as_dict=True)
				
				if driver_conflicts:
					route_names = [f"{t.route_name}" for t in driver_conflicts]
					frappe.throw(f"Tài xế đã phân công cho chuyến {self.trip_type} khác: {', '.join(set(route_names))}")
			
			# Check vehicle
			if self.vehicle_id:
				vehicle_query = """
					SELECT dt.name, dt.route_id, br.route_name
					FROM `tabSIS Bus Daily Trip` dt
					INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
					WHERE dt.trip_date = %s AND dt.trip_type = %s
					AND dt.vehicle_id = %s
					AND dt.name != %s
					AND dt.route_id != %s
					AND br.status = 'Active'
				"""
				vehicle_params = [self.trip_date, self.trip_type, self.vehicle_id, self.name, self.route_id]
				vehicle_conflicts = frappe.db.sql(vehicle_query, vehicle_params, as_dict=True)
				
				if vehicle_conflicts:
					route_names = [f"{t.route_name}" for t in vehicle_conflicts]
					frappe.throw(f"Xe đã phân công cho chuyến {self.trip_type} khác: {', '.join(set(route_names))}")
		
		else:
			# For new documents, only exclude by route_id
			
			# Check monitors
			if self.monitor1_id or self.monitor2_id:
				monitor_conditions = []
				monitor_params = [self.trip_date, self.trip_type]
				
				if self.monitor1_id:
					monitor_conditions.append("dt.monitor1_id = %s OR dt.monitor2_id = %s")
					monitor_params.extend([self.monitor1_id, self.monitor1_id])
				if self.monitor2_id:
					monitor_conditions.append("dt.monitor1_id = %s OR dt.monitor2_id = %s")
					monitor_params.extend([self.monitor2_id, self.monitor2_id])
				
				monitor_params.append(self.route_id)
				
				monitor_query = f"""
					SELECT dt.name, dt.route_id, br.route_name
					FROM `tabSIS Bus Daily Trip` dt
					INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
					WHERE dt.trip_date = %s AND dt.trip_type = %s
					AND ({' OR '.join(monitor_conditions)})
					AND dt.route_id != %s
					AND br.status = 'Active'
				"""
				monitor_conflicts = frappe.db.sql(monitor_query, monitor_params, as_dict=True)
				
				if monitor_conflicts:
					route_names = [f"{t.route_name}" for t in monitor_conflicts]
					frappe.throw(f"Monitor đã phân công cho chuyến {self.trip_type} khác: {', '.join(set(route_names))}")
			
			# Check driver
			if self.driver_id:
				driver_query = """
					SELECT dt.name, dt.route_id, br.route_name
					FROM `tabSIS Bus Daily Trip` dt
					INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
					WHERE dt.trip_date = %s AND dt.trip_type = %s
					AND dt.driver_id = %s
					AND dt.route_id != %s
					AND br.status = 'Active'
				"""
				driver_params = [self.trip_date, self.trip_type, self.driver_id, self.route_id]
				driver_conflicts = frappe.db.sql(driver_query, driver_params, as_dict=True)
				
				if driver_conflicts:
					route_names = [f"{t.route_name}" for t in driver_conflicts]
					frappe.throw(f"Tài xế đã phân công cho chuyến {self.trip_type} khác: {', '.join(set(route_names))}")
			
			# Check vehicle
			if self.vehicle_id:
				vehicle_query = """
					SELECT dt.name, dt.route_id, br.route_name
					FROM `tabSIS Bus Daily Trip` dt
					INNER JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
					WHERE dt.trip_date = %s AND dt.trip_type = %s
					AND dt.vehicle_id = %s
					AND dt.route_id != %s
					AND br.status = 'Active'
				"""
				vehicle_params = [self.trip_date, self.trip_type, self.vehicle_id, self.route_id]
				vehicle_conflicts = frappe.db.sql(vehicle_query, vehicle_params, as_dict=True)
				
				if vehicle_conflicts:
					route_names = [f"{t.route_name}" for t in vehicle_conflicts]
					frappe.throw(f"Xe đã phân công cho chuyến {self.trip_type} khác: {', '.join(set(route_names))}")

	def on_update(self):
		"""Update trip status based on current time"""
		if self.trip_status == "Not Started" and self.trip_date == datetime.now().date():
			# Auto update to "In Progress" if current time is past start time
			# This could be enhanced with actual start time logic
			pass
