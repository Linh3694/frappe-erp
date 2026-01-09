# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SISScholarshipAchievement(Document):
	"""
	Child table: Thành tích/hoạt động của học sinh trong đơn đăng ký học bổng.
	Gồm 4 loại:
	- standardized_test: Bài thi chuẩn hoá quốc tế (IELTS, SAT, ...)
	- award: Giải thưởng/thành tích
	- extracurricular: Hoạt động ngoại khoá
	- other: Khác
	"""
	pass
