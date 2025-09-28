# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusRouteStudent(Document):
	def validate(self):
		self.validate_references_exist()
		self.validate_student_not_assigned()
		self.validate_pickup_order_unique()
		self.validate_student_assignment_unique()

	def validate_references_exist(self):
		"""Validate that route and student exist"""
		if self.route_id and not frappe.db.exists("SIS Bus Route", self.route_id):
			frappe.throw("Tuyến đường không tồn tại")

		if self.student_id and not frappe.db.exists("SIS Student", self.student_id):
			frappe.throw("Học sinh không tồn tại")

	def validate_student_not_assigned(self):
		"""Validate that student is not already assigned to another route"""
		if not self.route_id or not self.student_id:
			return

		existing_assignment = frappe.db.exists("SIS Bus Route Student", {
			"student_id": self.student_id,
			"route_id": ("!=", self.route_id),
			"name": ("!=", self.name)
		})

		if existing_assignment:
			frappe.throw("Học sinh đã được phân công cho tuyến khác")

	def validate_pickup_order_unique(self):
		"""Validate that pickup order is unique within the route for the same weekday and trip type"""
		if not self.route_id or not self.pickup_order or not self.weekday or not self.trip_type:
			return

		existing_order = frappe.db.exists("SIS Bus Route Student", {
			"route_id": self.route_id,
			"pickup_order": self.pickup_order,
			"weekday": self.weekday,
			"trip_type": self.trip_type,
			"name": ("!=", self.name)
		})

		if existing_order:
			frappe.throw(f"Thứ tự {self.pickup_order} đã tồn tại trong tuyến này cho {self.weekday} - {self.trip_type}")

	def validate_student_assignment_unique(self):
		"""Validate that a student is not assigned multiple times for the same route/weekday/trip_type"""
		if not self.route_id or not self.student_id or not self.weekday or not self.trip_type:
			return

		existing_assignment = frappe.db.exists("SIS Bus Route Student", {
			"route_id": self.route_id,
			"student_id": self.student_id,
			"weekday": self.weekday,
			"trip_type": self.trip_type,
			"name": ("!=", self.name)
		})

		if existing_assignment:
			frappe.throw(f"Học sinh đã được phân công cho tuyến này vào {self.weekday} - {self.trip_type}")
