import frappe
from frappe.model.document import Document


class LMSCourseProgress(Document):
	def validate(self):
		if self.percent_complete is not None and (self.percent_complete < 0 or self.percent_complete > 100):
			frappe.throw("percent_complete phải từ 0 đến 100")
