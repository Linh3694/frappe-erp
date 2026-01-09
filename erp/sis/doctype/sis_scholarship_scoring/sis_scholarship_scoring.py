# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


# Định nghĩa điểm tối đa cho từng tiêu chí
MAX_SCORES = {
	"ctvn_score": 6,
	"ctqt_score": 8,
	"standardized_test_score": 6,
	"quality_score": 3,
	"extracurricular_score": 5,
	"competition_score": 5,
	"recommendation_score": 5,
	"video_score": 12
}

TOTAL_MAX_SCORE = 50


class SISScholarshipScoring(Document):
	"""
	Chấm điểm hồ sơ học bổng.
	Người phê duyệt bắt buộc chấm điểm trước khi duyệt/từ chối hồ sơ.
	Tổng điểm tối đa: 50 điểm.
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.validate_scores()
		self.calculate_total()
		self.set_scored_at()
	
	def validate_scores(self):
		"""Kiểm tra điểm không vượt quá điểm tối đa"""
		for field, max_score in MAX_SCORES.items():
			score = getattr(self, field, 0) or 0
			if score < 0:
				frappe.throw(f"Điểm {field} không được âm")
			if score > max_score:
				frappe.throw(f"Điểm {field} không được vượt quá {max_score}")
	
	def calculate_total(self):
		"""Tính tổng điểm và phần trăm"""
		total = 0
		for field in MAX_SCORES.keys():
			score = getattr(self, field, 0) or 0
			total += score
		
		self.total_score = round(total, 1)
		self.percentage = round((total / TOTAL_MAX_SCORE) * 100, 1)
	
	def set_scored_at(self):
		"""Cập nhật thời gian chấm điểm"""
		if not self.scored_at:
			self.scored_at = now()
	
	def after_insert(self):
		"""Sau khi tạo bản chấm điểm"""
		self.update_application_score()
	
	def on_update(self):
		"""Sau khi cập nhật"""
		self.update_application_score()
	
	def update_application_score(self):
		"""Cập nhật điểm vào đơn đăng ký"""
		if self.application_id:
			frappe.db.set_value(
				"SIS Scholarship Application",
				self.application_id,
				{
					"scoring_id": self.name,
					"total_score": self.total_score,
					"total_percentage": self.percentage
				}
			)
	
	def is_complete(self):
		"""Kiểm tra đã chấm đủ tất cả tiêu chí chưa"""
		for field in MAX_SCORES.keys():
			score = getattr(self, field, None)
			if score is None:
				return False
		return True
