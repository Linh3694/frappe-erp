import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime


class LMSCalendarEvent(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if self.start and self.end and get_datetime(self.end) < get_datetime(self.start):
			frappe.throw("End phải sau Start")
		if self.course and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course", self.course, "campus_id")
