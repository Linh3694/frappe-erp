# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today

class SISHealthReport(Document):
	def before_insert(self):
		"""Set default values before insert"""
		if not self.report_date:
			self.report_date = today()
		
		if not self.created_by_user:
			self.created_by_user = frappe.session.user
			user = frappe.get_doc("User", frappe.session.user)
			self.created_by_name = user.full_name or frappe.session.user

	def validate(self):
		"""Validate health report data"""
		self.validate_student()
		self.validate_porridge_dates()
		self.fetch_student_info()

	def validate_student(self):
		"""Validate student exists"""
		if self.student_id:
			if not frappe.db.exists("CRM Student", self.student_id):
				frappe.throw(_("Học sinh không tồn tại"))

	def validate_porridge_dates(self):
		"""Validate porridge dates if porridge_registration is checked"""
		if self.porridge_registration:
			if not self.porridge_dates or len(self.porridge_dates) == 0:
				frappe.throw(_("Vui lòng thêm ít nhất một ngày ăn cháo"))
			
			# Validate each porridge date has at least one meal selected
			for pd in self.porridge_dates:
				if not pd.breakfast and not pd.lunch and not pd.afternoon:
					frappe.throw(_("Vui lòng chọn ít nhất một bữa ăn cho ngày {0}").format(pd.date))

	def fetch_student_info(self):
		"""Fetch student name and code from CRM Student"""
		if self.student_id:
			student = frappe.get_doc("CRM Student", self.student_id)
			self.student_name = student.student_name
			self.student_code = student.student_code
		
		if self.class_id:
			cls = frappe.get_doc("SIS Class", self.class_id)
			self.class_name = cls.title
			self.campus = cls.campus
