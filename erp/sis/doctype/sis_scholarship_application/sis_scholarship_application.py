# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SISScholarshipApplication(Document):
	"""
	Đơn đăng ký học bổng của học sinh.
	Quản lý thông tin học sinh, thành tích, thư giới thiệu và điểm số.
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.validate_period()
		self.set_student_info()
		self.set_teacher_names()
	
	def validate_period(self):
		"""Kiểm tra kỳ học bổng có hợp lệ không"""
		if not self.scholarship_period_id:
			return
		
		period = frappe.get_doc("SIS Scholarship Period", self.scholarship_period_id)
		
		# Kiểm tra trạng thái (chỉ khi tạo mới)
		if self.is_new() and period.status != "Open":
			frappe.throw("Kỳ học bổng này chưa mở hoặc đã đóng đăng ký")
		
		# Kiểm tra thời gian (chỉ khi tạo mới)
		if self.is_new() and not period.is_within_period():
			frappe.throw("Không trong thời gian đăng ký học bổng")
	
	def set_student_info(self):
		"""Tự động điền thông tin học sinh từ lớp chính quy"""
		if not self.student_id:
			return
		
		# Lấy thông tin lớp chính quy
		if not self.class_id:
			class_student = frappe.db.get_value(
				"SIS Class Student",
				{"student_id": self.student_id},
				["class_id"],
				as_dict=True,
				order_by="creation desc"
			)
			if class_student:
				self.class_id = class_student.class_id
		
		# Lấy thông tin cấp học từ lớp
		if self.class_id and not self.education_stage_id:
			class_info = frappe.db.get_value(
				"SIS Class",
				self.class_id,
				["education_grade"],
				as_dict=True
			)
			if class_info and class_info.education_grade:
				grade_info = frappe.db.get_value(
					"SIS Education Grade",
					class_info.education_grade,
					["education_stage_id"],
					as_dict=True
				)
				if grade_info:
					self.education_stage_id = grade_info.education_stage_id
		
		# Lấy GVCN nếu chưa có
		if self.class_id and not self.main_teacher_id:
			class_info = frappe.db.get_value(
				"SIS Class",
				self.class_id,
				["homeroom_teacher"],
				as_dict=True
			)
			if class_info and class_info.homeroom_teacher:
				self.main_teacher_id = class_info.homeroom_teacher
	
	def set_teacher_names(self):
		"""Set tên giáo viên từ User (vì SIS Teacher không có full_name)"""
		# Lấy tên GVCN
		if self.main_teacher_id:
			teacher_user = frappe.db.get_value("SIS Teacher", self.main_teacher_id, "user_id")
			if teacher_user:
				self.main_teacher_name = frappe.db.get_value("User", teacher_user, "full_name")
		
		# Lấy tên GV thứ 2
		if self.second_teacher_id:
			teacher_user = frappe.db.get_value("SIS Teacher", self.second_teacher_id, "user_id")
			if teacher_user:
				self.second_teacher_name = frappe.db.get_value("User", teacher_user, "full_name")
	
	def after_insert(self):
		"""Sau khi tạo đơn mới"""
		try:
			self.create_recommendation_records()
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), "Scholarship Create Recommendation Error")
		
		# Luôn cập nhật status dù có lỗi tạo recommendation hay không
		self.update_status_to_waiting()
	
	def create_recommendation_records(self):
		"""Tạo records thư giới thiệu cho GVCN và GV thứ 2"""
		# Tạo cho GVCN (bắt buộc)
		if self.main_teacher_id:
			main_rec = frappe.get_doc({
				"doctype": "SIS Scholarship Recommendation",
				"application_id": self.name,
				"teacher_id": self.main_teacher_id,
				"recommendation_type": "main",
				"status": "Pending"
			})
			main_rec.insert(ignore_permissions=True)
			self.db_set("main_recommendation_id", main_rec.name)
			self.db_set("main_recommendation_status", "Pending")
		
		# Tạo cho GV thứ 2 (nếu có)
		if self.second_teacher_id:
			second_rec = frappe.get_doc({
				"doctype": "SIS Scholarship Recommendation",
				"application_id": self.name,
				"teacher_id": self.second_teacher_id,
				"recommendation_type": "second",
				"status": "Pending"
			})
			second_rec.insert(ignore_permissions=True)
			self.db_set("second_recommendation_id", second_rec.name)
			self.db_set("second_recommendation_status", "Pending")
	
	def update_status_to_waiting(self):
		"""Chuyển trạng thái sang WaitingRecommendation"""
		self.db_set("status", "WaitingRecommendation")
		self.db_set("submitted_at", now())
	
	def check_recommendations_complete(self):
		"""Kiểm tra tất cả thư giới thiệu đã hoàn thành chưa"""
		# GVCN bắt buộc phải có thư
		if self.main_recommendation_status != "Submitted":
			return False
		
		# GV thứ 2 nếu có thì phải có thư
		if self.second_teacher_id and self.second_recommendation_status != "Submitted":
			return False
		
		return True
	
	def update_recommendation_status(self):
		"""Cập nhật trạng thái recommendation từ các thư con"""
		# Cập nhật từ main recommendation
		if self.main_recommendation_id:
			main_status = frappe.db.get_value(
				"SIS Scholarship Recommendation",
				self.main_recommendation_id,
				"status"
			)
			self.main_recommendation_status = main_status
		
		# Cập nhật từ second recommendation
		if self.second_recommendation_id:
			second_status = frappe.db.get_value(
				"SIS Scholarship Recommendation",
				self.second_recommendation_id,
				"status"
			)
			self.second_recommendation_status = second_status
		
		# Kiểm tra nếu GV denied
		if self.main_recommendation_status == "Denied":
			self.status = "DeniedByTeacher"
		elif self.second_recommendation_status == "Denied":
			self.status = "DeniedByTeacher"
		# Kiểm tra nếu hoàn thành tất cả
		elif self.check_recommendations_complete():
			self.status = "RecommendationSubmitted"
		
		self.save(ignore_permissions=True)
