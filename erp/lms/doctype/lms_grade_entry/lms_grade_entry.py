import frappe
from frappe.model.document import Document


class LMSGradeEntry(Document):
	def validate(self):
		if not self.column:
			frappe.throw("Grade column bắt buộc")
		if not self.student_id:
			frappe.throw("Student bắt buộc")
