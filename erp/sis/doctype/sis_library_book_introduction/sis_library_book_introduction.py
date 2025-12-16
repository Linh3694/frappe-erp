# -*- coding: utf-8 -*-
# Copyright (c) 2025, WIS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class SISLibraryBookIntroduction(Document):
	"""Quản lý bài viết giới thiệu sách"""
	
	def before_insert(self):
		"""Ghi nhận người tạo khi tạo mới"""
		if not self.created_by:
			self.created_by = frappe.session.user
	
	def before_save(self):
		"""Ghi nhận người cập nhật mỗi khi lưu"""
		self.updated_by = frappe.session.user
	
	def validate(self):
		"""Validate dữ liệu trước khi lưu"""
		# Kiểm tra title_id có tồn tại không
		if self.title_id and not frappe.db.exists("SIS Library Title", self.title_id):
			frappe.throw(f"Đầu sách {self.title_id} không tồn tại")
		
		# Validate status
		if self.status not in ["draft", "published"]:
			frappe.throw("Trạng thái không hợp lệ. Chỉ chấp nhận: draft hoặc published")
