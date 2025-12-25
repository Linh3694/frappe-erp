# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime


class PMProjectInvitation(Document):
    """
    PM Project Invitation - Doctype quản lý lời mời tham gia dự án
    
    Fields:
    - project_id: Link đến PM Project
    - inviter_id: User gửi lời mời
    - invitee_id: User được mời
    - role: Vai trò được mời (manager/member/viewer)
    - status: Trạng thái (pending/accepted/declined/expired)
    - expires_at: Thời điểm hết hạn (default: 7 ngày)
    - message: Lời nhắn từ người mời
    """
    
    def before_insert(self):
        """Thiết lập expires_at mặc định là 7 ngày sau"""
        if not self.expires_at:
            self.expires_at = add_days(now_datetime(), 7)
        
        # Kiểm tra user đã là member chưa
        self.validate_not_already_member()
        
        # Kiểm tra đã có pending invitation chưa
        self.validate_no_pending_invitation()
    
    def validate_not_already_member(self):
        """Kiểm tra user chưa là member của project"""
        existing_member = frappe.db.exists("PM Project Member", {
            "project_id": self.project_id,
            "user_id": self.invitee_id
        })
        
        if existing_member:
            frappe.throw(
                f"User {self.invitee_id} đã là thành viên của dự án này",
                title="Đã là thành viên"
            )
    
    def validate_no_pending_invitation(self):
        """Kiểm tra không có pending invitation cho user này"""
        existing_invitation = frappe.db.exists("PM Project Invitation", {
            "project_id": self.project_id,
            "invitee_id": self.invitee_id,
            "status": "pending",
            "name": ["!=", self.name or ""]
        })
        
        if existing_invitation:
            frappe.throw(
                f"Đã có lời mời đang chờ xử lý cho user {self.invitee_id}",
                title="Lời mời trùng lặp"
            )

