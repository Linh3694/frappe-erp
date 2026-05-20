import frappe
from frappe.model.document import Document

from erp.lms.constants import QUESTION_TYPES


class LMSQuestion(Document):
	def validate(self):
		if not self.bank:
			frappe.throw("Question bank bắt buộc")
		if self.question_type not in QUESTION_TYPES:
			frappe.throw(f"question_type không hợp lệ: {self.question_type}")
