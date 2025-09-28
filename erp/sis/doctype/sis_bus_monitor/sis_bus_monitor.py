# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusMonitor(Document):
	def validate(self):
		self.validate_unique_fields()

	def validate_unique_fields(self):
		"""Validate unique fields"""
		if self.citizen_id:
			if frappe.db.exists("SIS Bus Monitor", {
				"citizen_id": self.citizen_id,
				"name": ("!=", self.name)
			}):
				frappe.throw("Số CCCD đã tồn tại")

		if self.monitor_code:
			if frappe.db.exists("SIS Bus Monitor", {
				"monitor_code": self.monitor_code,
				"name": ("!=", self.name)
			}):
				frappe.throw("Mã Monitor đã tồn tại")

		if self.phone_number:
			if frappe.db.exists("SIS Bus Monitor", {
				"phone_number": self.phone_number,
				"name": ("!=", self.name)
			}):
				frappe.throw("Số điện thoại đã tồn tại")

		if self.contractor:
			if frappe.db.exists("SIS Bus Monitor", {
				"contractor": self.contractor,
				"name": ("!=", self.name)
			}):
				frappe.throw("Nhà cung cấp đã tồn tại")
