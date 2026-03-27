# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISTimetableGenerationRequirement(Document):
	def validate(self):
		if self.periods_per_week < 0:
			frappe.throw("Số tiết/tuần không được âm")
		if self.max_periods_per_day < 1:
			frappe.throw("Tối đa tiết/ngày phải >= 1")
		if self.periods_per_week > 0 and self.max_periods_per_day > self.periods_per_week:
			self.max_periods_per_day = self.periods_per_week
