# Copyright (c) 2026, Wellspring International School

import uuid

import frappe
from frappe.model.document import Document

from erp.lms.constants import VIDEO_STATUS_DRAFT


class LMSVideoAsset(Document):
	def before_insert(self):
		if not self.asset_id:
			self.asset_id = str(uuid.uuid4())
		if not self.status:
			self.status = VIDEO_STATUS_DRAFT
		if not self.uploaded_by:
			self.uploaded_by = frappe.session.user

	def validate(self):
		if self.file_size is not None and self.file_size < 0:
			frappe.throw("File size không hợp lệ")
