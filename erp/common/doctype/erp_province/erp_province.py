# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ERPProvince(Document):
	def validate(self):
		if self.province_code:
			self.province_code = self.province_code.strip()
		if self.province_name:
			self.province_name = self.province_name.strip()
