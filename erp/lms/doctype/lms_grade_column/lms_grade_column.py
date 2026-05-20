import frappe
from frappe.model.document import Document

from erp.lms.constants import GRADE_COLUMN_TYPES


class LMSGradeColumn(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if self.column_type not in GRADE_COLUMN_TYPES:
			frappe.throw(f"column_type không hợp lệ: {self.column_type}")
		if self.section and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course Section", self.section, "campus_id")
