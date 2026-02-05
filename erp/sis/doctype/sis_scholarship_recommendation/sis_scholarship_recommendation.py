# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class SISScholarshipRecommendation(Document):
	"""
	Thư giới thiệu học bổng từ giáo viên.
	Được tạo tự động khi PHHS nộp đơn đăng ký học bổng.
	Giáo viên có thể viết thư hoặc từ chối.
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.set_teacher_name()
		self.validate_teacher_permission()
	
	def set_teacher_name(self):
		"""Lấy tên giáo viên từ User vì SIS Teacher không có full_name"""
		if self.teacher_id and not self.teacher_name:
			teacher_user = frappe.db.get_value("SIS Teacher", self.teacher_id, "user_id")
			if teacher_user:
				self.teacher_name = frappe.db.get_value("User", teacher_user, "full_name")
	
	def validate_teacher_permission(self):
		"""Kiểm tra giáo viên có quyền viết thư không"""
		# Cho phép System Manager và SIS Manager bypass
		user_roles = frappe.get_roles(frappe.session.user)
		if "System Manager" in user_roles or "SIS Manager" in user_roles:
			return
		
		# Kiểm tra teacher có đúng user không
		if self.teacher_id:
			teacher_user = frappe.db.get_value(
				"SIS Teacher",
				self.teacher_id,
				"user_id"
			)
			# Chỉ cho phép viết thư nếu là teacher được chỉ định
			# (kiểm tra khi submit, không kiểm tra khi tạo)
			if not self.is_new() and teacher_user != frappe.session.user:
				if "Instructor" in user_roles:
					frappe.throw("Bạn không có quyền chỉnh sửa thư giới thiệu này")
	
	def on_update(self):
		"""Sau khi cập nhật"""
		if self.has_value_changed("status"):
			self.update_application_status()
	
	def update_application_status(self):
		"""Cập nhật trạng thái của đơn đăng ký khi thư được submit hoặc denied"""
		if not self.application_id:
			return
		
		application = frappe.get_doc("SIS Scholarship Application", self.application_id)
		application.update_recommendation_status()
	
	def submit_recommendation(self, answers, average_rating_score=None):
		"""
		Submit thư giới thiệu với các câu trả lời.
		Args:
			answers: List các dict chứa câu trả lời
			average_rating_score: Điểm trung bình của các câu hỏi rating (optional)
		"""
		# Clear và thêm answers mới
		self.answers = []
		for answer in answers:
			self.append("answers", answer)
		
		# Lưu điểm trung bình nếu có
		if average_rating_score is not None:
			self.average_rating_score = average_rating_score
		
		self.status = "Submitted"
		self.submitted_at = now()
		self.save()
	
	def deny_recommendation(self, reason):
		"""
		Từ chối viết thư giới thiệu.
		Args:
			reason: Lý do từ chối
		"""
		if not reason:
			frappe.throw("Vui lòng nhập lý do từ chối")
		
		self.status = "Denied"
		self.denied_reason = reason
		self.denied_at = now()
		self.save()
