# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISTimetableGenerationSession(Document):
	def validate(self):
		if self.status == "Published" and not self.published_timetable_id:
			frappe.throw("Không thể đặt trạng thái Published khi chưa có TKB đã publish")

	def before_save(self):
		if self.is_new():
			self.status = "Configuring"
