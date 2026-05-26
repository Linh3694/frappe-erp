# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISTimetablePinnedSlot(Document):
	def validate(self):
		if not self.timetable_subject_id and not self.is_blocking:
			frappe.throw("Phải chọn môn hoặc bật Blocking Slot")
