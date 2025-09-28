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
			AND status = 'Hoạt động'
		""", (self.monitor1_id, self.monitor2_id, self.name))

		if existing_routes:
			route_names = [route[1] for route in existing_routes]
			frappe.throw(f"Monitor đã được phân công cho tuyến: {', '.join(route_names)}")
