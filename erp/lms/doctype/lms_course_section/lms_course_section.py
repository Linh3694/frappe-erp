import frappe
from frappe.model.document import Document


class LMSCourseSection(Document):
	def validate(self):
		if not self.section_name or not str(self.section_name).strip():
			frappe.throw("Section name bắt buộc")
		if self.course and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course", self.course, "campus_id")
