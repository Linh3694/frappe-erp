# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SISScholarshipFormSection(Document):
	"""
	Child table: Section của form thư giới thiệu.
	Mỗi section có tên (VD: III. Đánh giá) và chứa nhiều câu hỏi.
	Câu hỏi được lưu dưới dạng JSON để linh hoạt.
	"""
	pass
