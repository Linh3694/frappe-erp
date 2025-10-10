import frappe
from frappe import _
from frappe.model.document import Document
from datetime import datetime, timedelta


class SISStudentLeaveRequest(Document):
	def before_save(self):
		"""Calculate total days and validate dates"""
		self.calculate_total_days()
		self.validate_dates()

	def calculate_total_days(self):
		"""Calculate total leave days"""
		if self.start_date and self.end_date:
			start = datetime.strptime(str(self.start_date), '%Y-%m-%d')
			end = datetime.strptime(str(self.end_date), '%Y-%m-%d')
			# Include both start and end dates
			self.total_days = (end - start).days + 1

	def validate_dates(self):
		"""Validate start and end dates"""
		if self.start_date and self.end_date:
			if self.start_date > self.end_date:
				frappe.throw(_("Ngày kết thúc phải sau hoặc bằng ngày bắt đầu"))

	def validate(self):
		"""Additional validations"""
		self.validate_parent_student_relationship()
		self.populate_student_info()
		self.populate_parent_info()

	def validate_parent_student_relationship(self):
		"""Validate that parent has relationship with the student"""
		if not frappe.db.exists("CRM Family Relationship", {
			"parent": self.parent_id,
			"student": self.student_id
		}):
			frappe.throw(_("Phụ huynh không có quyền gửi đơn cho học sinh này"))

	def populate_student_info(self):
		"""Populate student name and code from student_id"""
		if self.student_id:
			student = frappe.get_doc("CRM Student", self.student_id)
			self.student_name = student.student_name
			self.student_code = student.student_code

	def populate_parent_info(self):
		"""Populate parent name from parent_id"""
		if self.parent_id:
			parent = frappe.get_doc("CRM Guardian", self.parent_id)
			self.parent_name = parent.guardian_name

	@frappe.whitelist()
	def can_edit(self):
		"""Check if this leave request can still be edited by parent"""
		if not self.submitted_at:
			return True

		# Check if within 24 hours
		submitted_time = datetime.strptime(str(self.submitted_at), '%Y-%m-%d %H:%M:%S.%f')
		time_diff = datetime.now() - submitted_time

		return time_diff.total_seconds() <= (24 * 60 * 60)  # 24 hours in seconds
