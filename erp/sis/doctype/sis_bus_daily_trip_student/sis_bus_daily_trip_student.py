# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusDailyTripStudent(Document):
	def validate(self):
		self.validate_references_exist()

	def validate_references_exist(self):
		"""Validate that all referenced entities exist"""
		if self.daily_trip_id and not frappe.db.exists("SIS Bus Daily Trip", self.daily_trip_id):
			frappe.throw("Chuyến xe không tồn tại")

		if self.student_id and not frappe.db.exists("CRM Student", self.student_id):
			frappe.throw("Học sinh không tồn tại")

		if self.class_student_id and not frappe.db.exists("SIS Class Student", self.class_student_id):
			frappe.throw("Học sinh trong lớp không tồn tại")
