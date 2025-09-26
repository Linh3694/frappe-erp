# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISEventAttendance(Document):
	def validate(self):
		# Ensure the student is actually a participant in the event
		if not frappe.db.exists("SIS Event Student", {
			"event_id": self.event_id,
			"class_student_id": ["in", frappe.get_all("SIS Class Student", 
														filters={"student_id": self.student_id}, 
														pluck="name")]
		}):
			frappe.throw(f"Student {self.student_id} is not a participant in event {self.event_id}")