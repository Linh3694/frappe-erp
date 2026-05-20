import frappe
from frappe.model.document import Document


class LMSBlueprintCourse(Document):
	def validate(self):
		if self.template_course:
			is_bp = frappe.db.get_value("LMS Course", self.template_course, "is_blueprint")
			if not is_bp:
				frappe.throw("Template course phải có is_blueprint=1")
			if not self.campus_id:
				self.campus_id = frappe.db.get_value("LMS Course", self.template_course, "campus_id")
			if not self.title:
				self.title = frappe.db.get_value("LMS Course", self.template_course, "title")
