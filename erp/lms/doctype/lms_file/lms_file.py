import frappe
from frappe.model.document import Document


class LMSFile(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if self.section and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course Section", self.section, "campus_id")
		elif self.course and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course", self.course, "campus_id")
