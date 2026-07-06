# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ERPWard(Document):
	def validate(self):
		if self.ward_code:
			self.ward_code = self.ward_code.strip()
		if self.ward_name:
			self.ward_name = self.ward_name.strip()
