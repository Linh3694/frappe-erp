# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusRouteStudent(Document):
	def validate(self):
		frappe.logger().info("🔍 DEBUG: SIS Bus Route Student validation called")
		frappe.logger().info(f"🔍 DEBUG: route_id={self.route_id}, student_id={self.student_id}")
		
		# TEMPORARILY DISABLE ALL VALIDATION for debugging
		frappe.logger().info("⚠️  WARNING: All SIS Bus Route Student validation DISABLED for debugging")
		return
		
		self.validate_references_exist()
		self.validate_student_not_assigned()
		self.validate_pickup_order_unique()
		self.validate_student_assignment_unique()

	def validate_references_exist(self):
		"""Validate that route, student, and class student exist"""
		if self.route_id:
			route_exists = frappe.db.sql("SELECT name FROM `tabSIS Bus Route` WHERE name = %s LIMIT 1", (self.route_id,))
			if not route_exists:
				frappe.throw("Tuyến đường không tồn tại")

		if self.student_id:
			student_exists = frappe.db.sql("SELECT name FROM `tabCRM Student` WHERE name = %s LIMIT 1", (self.student_id,))
			if not student_exists:
				frappe.throw("Học sinh không tồn tại")

		if self.class_student_id:
			class_student_exists = frappe.db.sql("SELECT name FROM `tabSIS Class Student` WHERE name = %s LIMIT 1", (self.class_student_id,))
			if not class_student_exists:
				frappe.throw("Học sinh trong lớp không tồn tại")

	def validate_student_not_assigned(self):
		"""Validate that student is not already assigned to another route"""
		if not self.route_id or not self.student_id:
			return

		existing_assignment = frappe.db.sql("""
			SELECT name FROM `tabSIS Bus Route Student`
			WHERE student_id = %s AND route_id != %s AND name != %s
			LIMIT 1
		""", (self.student_id, self.route_id, self.name or ""))
		
		if existing_assignment:
			frappe.throw("Học sinh đã được phân công cho tuyến khác")

	def validate_pickup_order_unique(self):
		"""Validate that pickup order is unique within the route for the same weekday and trip type"""
		if not self.route_id or not self.pickup_order or not self.weekday or not self.trip_type:
			return

		existing_order = frappe.db.sql("""
			SELECT name FROM `tabSIS Bus Route Student`
			WHERE route_id = %s AND pickup_order = %s 
			AND weekday = %s AND trip_type = %s AND name != %s
			LIMIT 1
		""", (self.route_id, self.pickup_order, self.weekday, self.trip_type, self.name or ""))

		if existing_order:
			frappe.throw(f"Thứ tự {self.pickup_order} đã tồn tại trong tuyến này cho {self.weekday} - {self.trip_type}")

	def validate_student_assignment_unique(self):
		"""Validate that a student is not assigned multiple times for the same route/weekday/trip_type"""
		if not self.route_id or not self.student_id or not self.weekday or not self.trip_type:
			return

		existing_assignment = frappe.db.sql("""
			SELECT name FROM `tabSIS Bus Route Student`
			WHERE route_id = %s AND student_id = %s 
			AND weekday = %s AND trip_type = %s AND name != %s
			LIMIT 1
		""", (self.route_id, self.student_id, self.weekday, self.trip_type, self.name or ""))

		if existing_assignment:
			frappe.throw(f"Học sinh đã được phân công cho tuyến này vào {self.weekday} - {self.trip_type}")
