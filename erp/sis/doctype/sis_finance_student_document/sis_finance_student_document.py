# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SISFinanceStudentDocument(Document):
    def before_insert(self):
        """Tự động set thông tin upload"""
        self.uploaded_by = frappe.session.user
        self.uploaded_at = now_datetime()
        
    def validate(self):
        """Validate document"""
        if not self.order_student_id:
            frappe.throw("Học sinh là bắt buộc")
        if not self.document_type:
            frappe.throw("Loại tài liệu là bắt buộc")
        if not self.file_url:
            frappe.throw("File là bắt buộc")
