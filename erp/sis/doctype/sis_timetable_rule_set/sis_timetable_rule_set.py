# Copyright (c) 2026, Frappe Technologies and contributors

import frappe
from frappe.model.document import Document


class SISTimetableRuleSet(Document):
	def validate(self):
		if self.is_default and self.campus_id:
			existing = frappe.db.exists(
				"SIS Timetable Rule Set",
				{"campus_id": self.campus_id, "is_default": 1, "name": ("!=", self.name)},
			)
			if existing:
				frappe.msgprint(f"Campus đã có Rule Set default: {existing}", indicator="orange")
