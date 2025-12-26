# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate


class SISReenrollmentConfig(Document):
	"""
	Cấu hình đợt tái ghi danh.
	Quản lý thời gian, tài liệu và các mức ưu đãi.
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.validate_dates()
		self.validate_single_active()
		self.set_system_fields()
	
	def validate_dates(self):
		"""Kiểm tra ngày bắt đầu phải trước ngày kết thúc"""
		if self.start_date and self.end_date:
			if getdate(self.start_date) > getdate(self.end_date):
				frappe.throw("Ngày bắt đầu phải trước ngày kết thúc")
		
		# Kiểm tra các deadline trong bảng ưu đãi
		if self.discounts:
			for discount in self.discounts:
				if discount.deadline:
					if self.end_date and getdate(discount.deadline) > getdate(self.end_date):
						frappe.throw(f"Hạn ưu đãi {discount.deadline} không được sau ngày kết thúc {self.end_date}")
	
	def validate_single_active(self):
		"""Chỉ cho phép 1 config active cho mỗi campus"""
		if self.is_active:
			# Tìm các config khác đang active cùng campus
			existing = frappe.db.get_all(
				"SIS Re-enrollment Config",
				filters={
					"is_active": 1,
					"campus_id": self.campus_id,
					"name": ["!=", self.name or ""]
				},
				fields=["name", "title"]
			)
			
			if existing:
				frappe.throw(
					f"Đã có đợt tái ghi danh đang mở: {existing[0].title}. "
					"Vui lòng tắt đợt đó trước khi bật đợt mới."
				)
	
	def set_system_fields(self):
		"""Cập nhật các trường hệ thống"""
		if not self.created_by:
			self.created_by = frappe.session.user
		if not self.created_at:
			self.created_at = frappe.utils.now()
		self.updated_at = frappe.utils.now()
	
	def is_within_period(self):
		"""Kiểm tra xem hiện tại có trong thời gian tái ghi danh không"""
		today = getdate(nowdate())
		start = getdate(self.start_date) if self.start_date else None
		end = getdate(self.end_date) if self.end_date else None
		
		if not start or not end:
			return False
		
		return start <= today <= end
	
	def get_current_discount(self):
		"""Lấy mức ưu đãi hiện tại dựa trên ngày hôm nay"""
		today = getdate(nowdate())
		
		if not self.discounts:
			return None
		
		# Sắp xếp theo deadline tăng dần và tìm mức ưu đãi phù hợp
		sorted_discounts = sorted(self.discounts, key=lambda x: getdate(x.deadline))
		
		for discount in sorted_discounts:
			if today <= getdate(discount.deadline):
				return {
					"deadline": discount.deadline,
					"description": discount.description,
					"annual_discount": discount.annual_discount,
					"semester_discount": discount.semester_discount
				}
		
		# Nếu đã quá tất cả các hạn, trả về mức cuối cùng (thường là 0%)
		last_discount = sorted_discounts[-1] if sorted_discounts else None
		if last_discount:
			return {
				"deadline": last_discount.deadline,
				"description": last_discount.description,
				"annual_discount": 0,
				"semester_discount": 0,
				"expired": True
			}
		
		return None

