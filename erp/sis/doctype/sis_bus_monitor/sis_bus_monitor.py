# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISBusMonitor(Document):
	def validate(self):
		self.validate_unique_fields()

	def validate_unique_fields(self):
		"""CCCD là định danh duy nhất; số điện thoại được phép trùng (nhiều giám sát
		cùng nhà thầu dùng chung một số liên lạc)."""
		if self.citizen_id:
			if frappe.db.exists("SIS Bus Monitor", {
				"citizen_id": self.citizen_id,
				"name": ("!=", self.name)
			}):
				frappe.throw("Số CCCD đã tồn tại")
