import frappe
from frappe.model.document import Document

from erp.lms.constants import (
	SUBMISSION_STATE_GRADED,
	SUBMISSION_STATE_NEEDS_REVISION,
	SUBMISSION_STATE_SUBMITTED,
	SUBMISSION_STATE_UNSUBMITTED,
)

_SUBMISSION_STATES = {
	SUBMISSION_STATE_UNSUBMITTED,
	SUBMISSION_STATE_SUBMITTED,
	SUBMISSION_STATE_GRADED,
	SUBMISSION_STATE_NEEDS_REVISION,
}


class LMSSubmission(Document):
	def validate(self):
		if self.workflow_state not in _SUBMISSION_STATES:
			frappe.throw(f"workflow_state không hợp lệ: {self.workflow_state}")
		if not self.workflow_state:
			self.workflow_state = SUBMISSION_STATE_UNSUBMITTED
