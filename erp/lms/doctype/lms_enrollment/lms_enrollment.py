import frappe
from frappe.model.document import Document

from erp.lms.constants import ENROLLMENT_ROLE_STUDENT, ENROLLMENT_STATUS_ACTIVE


class LMSEnrollment(Document):
	def validate(self):
		if self.role == ENROLLMENT_ROLE_STUDENT and not self.student_id:
			frappe.throw("Student bắt buộc cho role student")
		if self.role in ("teacher", "ta", "designer", "observer") and not self.user:
			frappe.throw("User bắt buộc cho role giảng viên / staff")
		if self.section and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Course Section", self.section, "campus_id")
		if not self.status:
			self.status = ENROLLMENT_STATUS_ACTIVE
