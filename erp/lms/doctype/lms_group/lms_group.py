import frappe
from frappe.model.document import Document


class LMSGroup(Document):
	def validate(self):
		if not self.group_name or not str(self.group_name).strip():
			frappe.throw("Tên nhóm bắt buộc")
		if self.section and not self.campus_id:
			course = frappe.db.get_value("LMS Course Section", self.section, "course")
			if course:
				self.campus_id = frappe.db.get_value("LMS Course", course, "campus_id")
