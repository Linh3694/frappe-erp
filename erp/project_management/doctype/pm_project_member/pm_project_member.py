# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class PMProjectMember(Document):
    """
    PM Project Member - Doctype quản lý thành viên dự án
    
    Fields:
    - project_id: Link đến PM Project
    - user_id: Link đến User
    - role: Vai trò trong dự án (owner/manager/member/viewer)
    - joined_at: Thời điểm tham gia
    
    Constraints:
    - Unique (project_id, user_id): Mỗi user chỉ có 1 membership trong 1 project
    """
    
    def validate(self):
        """Kiểm tra unique constraint (project_id, user_id)"""
        self.validate_unique_membership()
    
    def validate_unique_membership(self):
        """Đảm bảo không có duplicate member trong project"""
        existing = frappe.db.exists("PM Project Member", {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "name": ["!=", self.name]
        })
        
        if existing:
            frappe.throw(
                _("User {0} đã là thành viên của dự án này").format(self.user_id),
                title=_("Trùng lặp thành viên")
            )
    
    def before_insert(self):
        """Thiết lập joined_at nếu chưa có"""
        if not self.joined_at:
            self.joined_at = frappe.utils.now()

