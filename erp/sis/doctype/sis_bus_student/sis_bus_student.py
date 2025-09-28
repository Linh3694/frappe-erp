# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusStudent(Document):
	def validate(self):
		self.validate_unique_fields()
		self.validate_references_exist()

	def validate_unique_fields(self):
		"""Validate unique fields"""
		if self.student_code:
			if frappe.db.exists("SIS Bus Student", {
				"student_code": self.student_code,
				"name": ("!=", self.name)
			}):
				frappe.throw("Mã học sinh đã tồn tại")

	def validate_references_exist(self):
		"""Validate that class exists"""
		if self.class_id and not frappe.db.exists("SIS Class", self.class_id):
			frappe.throw("Lớp không tồn tại")

		if self.route_id and not frappe.db.exists("SIS Bus Route", self.route_id):
			frappe.throw("Tuyến đường không tồn tại")
