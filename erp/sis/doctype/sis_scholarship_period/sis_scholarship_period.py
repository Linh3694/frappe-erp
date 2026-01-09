# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate


class SISScholarshipPeriod(Document):
	"""
	Cấu hình kỳ đăng ký học bổng.
	Quản lý thời gian, cấp học áp dụng, người phê duyệt và form thư giới thiệu.
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.validate_dates()
		self.validate_single_open()
		self.set_system_fields()
	
	def validate_dates(self):
		"""Kiểm tra ngày bắt đầu phải trước ngày kết thúc"""
		if self.from_date and self.to_date:
			if getdate(self.from_date) > getdate(self.to_date):
				frappe.throw("Ngày bắt đầu phải trước ngày kết thúc")
	
	def validate_single_open(self):
		"""Chỉ cho phép 1 kỳ Open cho mỗi campus"""
		if self.status == "Open":
			# Tìm các kỳ khác đang Open cùng campus
			existing = frappe.db.get_all(
				"SIS Scholarship Period",
				filters={
					"status": "Open",
					"campus_id": self.campus_id,
					"name": ["!=", self.name or ""]
				},
				fields=["name", "title"]
			)
			
			if existing:
				frappe.throw(
					f"Đã có kỳ học bổng đang mở: {existing[0].title}. "
					"Vui lòng đóng kỳ đó trước khi mở kỳ mới."
				)
	
	def set_system_fields(self):
		"""Cập nhật các trường hệ thống"""
		if not self.created_by:
			self.created_by = frappe.session.user
		if not self.created_at:
			self.created_at = frappe.utils.now()
		self.updated_at = frappe.utils.now()
	
	def is_within_period(self):
		"""Kiểm tra xem hiện tại có trong thời gian đăng ký không"""
		today = getdate(nowdate())
		start = getdate(self.from_date) if self.from_date else None
		end = getdate(self.to_date) if self.to_date else None
		
		if not start or not end:
			return False
		
		return start <= today <= end
	
	def is_approver(self, user, education_stage_id=None):
		"""
		Kiểm tra user có phải là người phê duyệt không.
		Nếu có education_stage_id thì kiểm tra cho cấp học cụ thể.
		"""
		for approver in self.approvers:
			if approver.user_id == user:
				if education_stage_id:
					if approver.educational_stage_id == education_stage_id:
						return True
				else:
					return True
		return False
	
	def get_approver_stages(self, user):
		"""Lấy danh sách cấp học mà user được phê duyệt"""
		stages = []
		for approver in self.approvers:
			if approver.user_id == user:
				stages.append(approver.educational_stage_id)
		return stages
