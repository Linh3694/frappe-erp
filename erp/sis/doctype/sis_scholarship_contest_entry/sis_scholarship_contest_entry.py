# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


def _guess_file_type(filename: str) -> str:
	"""Phân loại file từ extension phục vụ preview trên frontend."""
	if not filename:
		return "other"
	ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	image_ext = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
	video_ext = {"mp4", "mov", "avi", "webm", "mkv"}
	office_ext = {"ppt", "pptx", "doc", "docx", "xls", "xlsx"}
	if ext in image_ext:
		return "image"
	if ext in video_ext:
		return "video"
	if ext == "pdf":
		return "pdf"
	if ext in office_ext:
		return "office"
	return "other"


class SISScholarshipContestEntry(Document):
	"""Child table: bài dự thi / tài liệu bài thi trong đơn học bổng."""

	def before_insert(self):
		self.uploaded_by = frappe.session.user
		self.uploaded_at = now()
		self.file_type = _guess_file_type(self.file_name or "")
