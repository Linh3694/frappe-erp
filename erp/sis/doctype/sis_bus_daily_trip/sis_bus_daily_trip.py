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
		"""Validate that monitors are not assigned to multiple trips on same date"""
		if self.monitor1_id == self.monitor2_id:
			frappe.throw("Monitor 1 và Monitor 2 không được giống nhau")

		# Check if monitors are already assigned to other trips on same date
		existing_trips = frappe.db.sql("""
			SELECT name, route_id
			FROM `tabSIS Bus Daily Trip`
			WHERE trip_date = %s
			AND (monitor1_id = %s OR monitor2_id = %s OR monitor1_id = %s OR monitor2_id = %s)
			AND name != %s
		""", (self.trip_date, self.monitor1_id, self.monitor1_id, self.monitor2_id, self.monitor2_id, self.name), as_dict=True)

		if existing_trips:
			route_names = [trip.route_id for trip in existing_trips]
			frappe.throw(f"Monitor đã được phân công cho chuyến khác trong ngày: {', '.join(set(route_names))}")

	def on_update(self):
		"""Update trip status based on current time"""
		if self.trip_status == "Chưa xuất phát" and self.trip_date == datetime.now().date():
			# Auto update to "Đã xuất phát" if current time is past start time
			# This could be enhanced with actual start time logic
			pass
