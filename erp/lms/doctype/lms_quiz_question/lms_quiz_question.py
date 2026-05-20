import frappe
from frappe.model.document import Document


class LMSQuizQuestion(Document):
	def validate(self):
		if not self.quiz or not self.question:
			frappe.throw("Quiz và question bắt buộc")
