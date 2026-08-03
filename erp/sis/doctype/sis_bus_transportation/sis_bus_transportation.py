# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusTransportation(Document):
	def validate(self):
		self.validate_unique_fields()

	def validate_unique_fields(self):
		"""Validate unique fields"""
		if self.license_plate:
			if frappe.db.exists("SIS Bus Transportation", {
				"license_plate": self.license_plate,
				"name": ("!=", self.name)
			}):
				frappe.throw("Biển số đã tồn tại")
