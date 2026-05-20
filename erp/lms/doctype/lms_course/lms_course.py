import frappe
from frappe.model.document import Document

from erp.lms.constants import COURSE_STATE_DRAFT


class LMSCourse(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if not self.campus_id and self.program:
			self.campus_id = frappe.db.get_value("LMS Program", self.program, "campus_id")
		if not self.course_state:
			self.course_state = COURSE_STATE_DRAFT
