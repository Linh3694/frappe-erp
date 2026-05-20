import frappe
from frappe.model.document import Document

from erp.lms.constants import MODULE_ITEM_TYPES


class LMSModuleItem(Document):
	def validate(self):
		if not self.title or not str(self.title).strip():
			frappe.throw("Title bắt buộc")
		if self.item_type not in MODULE_ITEM_TYPES:
			frappe.throw(f"item_type không hợp lệ: {self.item_type}")
		if self.item_type == "video" and not self.video_asset:
			frappe.throw("Video asset bắt buộc cho item_type video")
		if self.item_type == "video" and self.video_asset:
			self.content_ref_doctype = "LMS Video Asset"
			self.content_ref_name = self.video_asset
