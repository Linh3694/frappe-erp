# Copyright (c) 2025, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISBusPickupPoint(Document):
	"""Doctype for managing bus pickup/drop-off points"""
	
	def validate(self):
		# Validate point_name is not empty
		if not self.point_name:
			frappe.throw("Tên điểm đón không được để trống")
		
		# Validate point_type
		if self.point_type not in ['Đón', 'Trả', 'Cả hai']:
			frappe.throw("Loại điểm đón không hợp lệ")

