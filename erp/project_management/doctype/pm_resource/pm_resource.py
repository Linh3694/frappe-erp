# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMResource(Document):
    """
    PM Resource - Doctype quản lý tài nguyên/file trong dự án
    
    Fields:
    - project_id: Link đến PM Project
    - target_type: Loại đối tượng (project/requirement/task)
    - target_id: ID của đối tượng được gắn resource
    - filename: Tên file
    - file_url: URL file (Attach field)
    - file_type: MIME type
    - file_size: Kích thước file (bytes)
    - uploaded_by: User upload file
    """
    
    def before_insert(self):
        """Thiết lập uploaded_by và target_id mặc định"""
        if not self.uploaded_by:
            self.uploaded_by = frappe.session.user
        
        # Nếu target_type là project thì target_id = project_id
        if self.target_type == "project" and not self.target_id:
            self.target_id = self.project_id

