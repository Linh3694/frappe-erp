# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


# Điểm tối đa tổng (chỉ giới hạn tổng, không giới hạn từng tiêu chí - đồng bộ với FE)
TOTAL_MAX_SCORE = 50

# Các trường điểm (để tính tổng)
SCORE_FIELDS = [
	"ctvn_score", "ctqt_score", "standardized_test_score", "quality_score",
	"extracurricular_score", "competition_score", "recommendation_score", "video_score"
]


class SISScholarshipScoring(Document):
	"""
	Chấm điểm hồ sơ học bổng.
	Người phê duyệt bắt buộc chấm điểm trước khi duyệt/từ chối hồ sơ.
	Chỉ giới hạn điểm tổng <= 50 (không giới hạn từng tiêu chí riêng lẻ).
	"""
	
	def validate(self):
		"""Validate trước khi lưu"""
		self.validate_scores()
		self.calculate_total()
		self.set_scored_at()
	
	def validate_scores(self):
		"""Chỉ kiểm tra: điểm từng mục >= 0 và tổng <= 50 (đồng bộ với FE)"""
		total = 0
		for field in SCORE_FIELDS:
			score = getattr(self, field, 0) or 0
			if score < 0:
				frappe.throw(f"Điểm {field} không được âm")
			total += score
		if total > TOTAL_MAX_SCORE:
			frappe.throw(f"Tổng điểm không được vượt quá {TOTAL_MAX_SCORE}")
	
	def calculate_total(self):
		"""Tính tổng điểm và phần trăm"""
		total = 0
		for field in SCORE_FIELDS:
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
		"""Kiểm tra đã chấm điểm chưa (chỉ cần tổng > 0, đồng bộ với FE)"""
		total = getattr(self, "total_score", 0) or 0
		return total > 0
