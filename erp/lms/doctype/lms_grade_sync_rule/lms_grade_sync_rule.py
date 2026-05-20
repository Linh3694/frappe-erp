import frappe
from frappe.model.document import Document


class LMSGradeSyncRule(Document):
	def validate(self):
		if self.target_type == "report_card_component" and not self.sis_actual_subject_id:
			frappe.throw("SIS Actual Subject bắt buộc cho Report Card sync")
		if self.target_type == "class_log_student" and not self.class_log_field:
			frappe.throw("Class Log Field bắt buộc")
		if self.target_type == "homeroom_score" and not self.homeroom_class_log_score_id:
			frappe.throw("Homeroom Score Type bắt buộc")
		if self.grade_column and not self.campus_id:
			self.campus_id = frappe.db.get_value("LMS Grade Column", self.grade_column, "campus_id")
