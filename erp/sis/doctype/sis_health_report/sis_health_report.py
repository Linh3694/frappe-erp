# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today, now_datetime, getdate
from datetime import datetime, timedelta

# Hằng số cho thời gian đăng ký bữa cháo
LUNCH_AFTERNOON_DEADLINE_HOUR = 9  # Bữa trưa và xế cho hôm nay phải đăng ký trước 9h
BREAKFAST_DEADLINE_HOUR = 20  # Bữa sáng phải đăng ký trước 20h ngày hôm trước


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
		self.validate_porridge_time_constraints()
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

	def validate_porridge_time_constraints(self):
		"""
		Validate thời gian đăng ký bữa cháo:
		- Bữa trưa và bữa xế cho ngày hôm nay: phải đăng ký trước 9h sáng
		- Bữa sáng: phải đăng ký trước 1 ngày (trước 20h tối ngày hôm trước)
		"""
		if not self.porridge_registration or not self.porridge_dates:
			return
		
		current_datetime = now_datetime()
		current_date = getdate(today())
		current_hour = current_datetime.hour
		
		for pd in self.porridge_dates:
			pd_date = getdate(pd.date)
			days_diff = (pd_date - current_date).days
			
			# Không cho phép đăng ký cho ngày trong quá khứ
			if days_diff < 0:
				frappe.throw(_("Không thể đăng ký ăn cháo cho ngày đã qua ({0})").format(pd.date))
			
			# Ngày hôm nay
			if days_diff == 0:
				# Bữa sáng cho ngày hôm nay - không được phép (vì phải đăng ký từ hôm trước)
				if pd.breakfast:
					frappe.throw(_("Bữa sáng phải được đăng ký từ ngày hôm trước (trước 20h). Không thể đăng ký bữa sáng cho ngày hôm nay ({0})").format(pd.date))
				
				# Bữa trưa và xế cho ngày hôm nay - phải trước 9h
				if (pd.lunch or pd.afternoon) and current_hour >= LUNCH_AFTERNOON_DEADLINE_HOUR:
					frappe.throw(_("Bữa trưa và bữa xế cho ngày hôm nay ({0}) phải được đăng ký trước {1}h sáng").format(
						pd.date, LUNCH_AFTERNOON_DEADLINE_HOUR
					))
			
			# Ngày mai
			elif days_diff == 1:
				# Bữa sáng cho ngày mai - phải đăng ký trước 20h hôm nay
				if pd.breakfast and current_hour >= BREAKFAST_DEADLINE_HOUR:
					frappe.throw(_("Bữa sáng cho ngày mai ({0}) phải được đăng ký trước {1}h tối hôm nay").format(
						pd.date, BREAKFAST_DEADLINE_HOUR
					))

	def fetch_student_info(self):
		"""Fetch student name and code from CRM Student"""
		if self.student_id:
			try:
				student = frappe.get_doc("CRM Student", self.student_id)
				self.student_name = student.student_name
				self.student_code = student.student_code
			except Exception as e:
				frappe.logger().warning(f"Could not fetch student info: {str(e)}")
		
		if self.class_id:
			try:
				cls = frappe.get_doc("SIS Class", self.class_id)
				self.class_name = cls.title
				# campus là virtual field, sẽ được fetch tự động từ class_id.campus
			except Exception as e:
				frappe.logger().warning(f"Could not fetch class info: {str(e)}")
