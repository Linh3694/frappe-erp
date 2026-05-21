import frappe
from frappe.model.document import Document

from erp.lms.constants import MODULE_ITEM_TYPES
from erp.lms.services.module_service import ITEM_CONTENT_DOCTYPE, NON_BLOCKING_ITEM_TYPES


class LMSModuleItem(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if self.item_type not in MODULE_ITEM_TYPES:
			frappe.throw(f"item_type không hợp lệ: {self.item_type}")

		# Auto gán content_ref_doctype theo loại
		if self.item_type in ITEM_CONTENT_DOCTYPE:
			self.content_ref_doctype = ITEM_CONTENT_DOCTYPE[self.item_type]

		if self.item_type == "video":
			if not self.video_asset:
				frappe.throw("Video asset bắt buộc cho item_type video")
			self.content_ref_doctype = "LMS Video Asset"
			self.content_ref_name = self.video_asset

		if self.item_type == "external_url":
			if not self.external_url or not str(self.external_url).strip():
				frappe.throw("external_url bắt buộc cho item_type external_url")

		# Các loại cần content_ref (trừ subheader/text)
		if self.item_type in ITEM_CONTENT_DOCTYPE:
			ref = self.content_ref_name or self.video_asset
			if not ref:
				frappe.throw(f"content_ref bắt buộc cho item_type {self.item_type}")
			if not frappe.db.exists(self.content_ref_doctype, ref):
				frappe.throw(f"{self.content_ref_doctype} {ref} không tồn tại")
			self._validate_content_same_course(ref)

	def _validate_content_same_course(self, ref_name: str):
		"""Đảm bảo nội dung gắn thuộc cùng course với module."""
		module_course = frappe.db.get_value("LMS Module", self.module, "course")
		if not module_course:
			return
		content_course = frappe.db.get_value(self.content_ref_doctype, ref_name, "course")
		if content_course and content_course != module_course:
			frappe.throw(
				f"Nội dung {ref_name} thuộc course khác — không thể gắn vào module này"
			)
