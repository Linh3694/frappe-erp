import frappe
from frappe.model.document import Document

from erp.lms.constants import SHOW_ANSWERS


class LMSQuiz(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if self.show_correct_answers and self.show_correct_answers not in SHOW_ANSWERS:
			frappe.throw(f"show_correct_answers không hợp lệ: {self.show_correct_answers}")
		if self.section and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course Section", self.section, "campus_id")
		elif self.course and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course", self.course, "campus_id")
