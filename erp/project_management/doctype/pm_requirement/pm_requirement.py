# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMRequirement(Document):
    """
    PM Requirement - Doctype quản lý yêu cầu dự án
    
    Fields:
    - project_id: Link đến PM Project
    - title: Tiêu đề yêu cầu
    - description: Mô tả chi tiết
    - priority: Độ ưu tiên (low/medium/high/critical)
    - status: Trạng thái (new/approved/rejected)
    - created_by: User tạo yêu cầu
    """
    
    def before_insert(self):
        """Thiết lập created_by nếu chưa có"""
        if not self.created_by:
            self.created_by = frappe.session.user

