# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusTransportation(Document):
	def validate(self):
		self.validate_unique_fields()
		self.validate_driver_exists()

	def validate_unique_fields(self):
		"""Validate unique fields"""
		if self.vehicle_code:
			if frappe.db.exists("SIS Bus Transportation", {
				"vehicle_code": self.vehicle_code,
				"name": ("!=", self.name)
			}):
				frappe.throw("Mã xe đã tồn tại")

		if self.license_plate:
			if frappe.db.exists("SIS Bus Transportation", {
				"license_plate": self.license_plate,
				"name": ("!=", self.name)
			}):
				frappe.throw("Biển số đã tồn tại")

	def validate_driver_exists(self):
		"""Validate that the driver exists"""
		if self.driver_id:
			if not frappe.db.exists("SIS Bus Driver", self.driver_id):
				frappe.throw("Tài xế không tồn tại")
