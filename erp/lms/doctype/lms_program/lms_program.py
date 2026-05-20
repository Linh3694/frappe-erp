import frappe
from frappe.model.document import Document


class LMSProgram(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
