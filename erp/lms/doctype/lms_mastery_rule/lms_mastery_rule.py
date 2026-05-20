import frappe
from frappe.model.document import Document


class LMSMasteryRule(Document):
	def validate(self):
		if not self.quiz and not self.outcome:
			frappe.throw("Cần chọn Quiz hoặc Outcome làm điều kiện")
		module_course = frappe.db.get_value("LMS Module", self.module, "course")
		next_course = frappe.db.get_value("LMS Module", self.next_module, "course")
		if module_course != self.course or next_course != self.course:
			frappe.throw("Module và Next Module phải thuộc cùng course")
		if self.course and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course", self.course, "campus_id")
