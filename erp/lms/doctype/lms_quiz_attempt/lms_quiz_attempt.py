import frappe
from frappe.model.document import Document

_QUIZ_ATTEMPT_STATES = {"in_progress", "submitted", "graded"}


class LMSQuizAttempt(Document):
	def validate(self):
		if self.workflow_state not in _QUIZ_ATTEMPT_STATES:
			frappe.throw(f"workflow_state không hợp lệ: {self.workflow_state}")
		if not self.workflow_state:
			self.workflow_state = "in_progress"
