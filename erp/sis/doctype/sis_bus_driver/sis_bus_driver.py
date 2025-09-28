# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusDriver(Document):
	def validate(self):
		self.validate_unique_fields()

	def validate_unique_fields(self):
		"""Validate unique fields"""
		if self.citizen_id:
			if frappe.db.exists("SIS Bus Driver", {
				"citizen_id": self.citizen_id,
				"name": ("!=", self.name)
			}):
				frappe.throw("Số CCCD đã tồn tại")

		if self.driver_code:
			if frappe.db.exists("SIS Bus Driver", {
				"driver_code": self.driver_code,
				"name": ("!=", self.name)
			}):
				frappe.throw("Mã Driver đã tồn tại")

		if self.phone_number:
			if frappe.db.exists("SIS Bus Driver", {
				"phone_number": self.phone_number,
				"name": ("!=", self.name)
			}):
				frappe.throw("Số điện thoại đã tồn tại")

		if self.contractor:
			if frappe.db.exists("SIS Bus Driver", {
				"contractor": self.contractor,
				"name": ("!=", self.name)
			}):
				frappe.throw("Nhà cung cấp đã tồn tại")
