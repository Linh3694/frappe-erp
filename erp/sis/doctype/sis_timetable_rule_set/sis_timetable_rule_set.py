# Copyright (c) 2026, Frappe Technologies and contributors

import frappe
from frappe.model.document import Document


class SISTimetableRuleSet(Document):
	def validate(self):
		# Mỗi campus + năm học + cấp học chỉ có tối đa một rule set mặc định
		if self.is_default and self.campus_id and self.school_year_id and self.education_stage_id:
			existing = frappe.db.exists(
				"SIS Timetable Rule Set",
				{
					"campus_id": self.campus_id,
					"school_year_id": self.school_year_id,
					"education_stage_id": self.education_stage_id,
					"is_default": 1,
					"name": ("!=", self.name),
				},
			)
			if existing:
				frappe.msgprint(
					f"Đã có rule set mặc định cho cặp năm học + cấp học này: {existing}",
					indicator="orange",
				)
