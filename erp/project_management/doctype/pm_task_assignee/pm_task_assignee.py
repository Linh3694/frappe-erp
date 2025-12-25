# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class PMTaskAssignee(Document):
    """
    PM Task Assignee - Doctype quản lý người được gán task
    
    Fields:
    - task_id: Link đến PM Task
    - user_id: User được gán
    - assigned_at: Thời điểm gán
    - assigned_by: User thực hiện việc gán
    
    Note: 
    - Một task có thể có nhiều assignees
    - Mỗi assignee chỉ được gán 1 lần cho 1 task
    """
    
    def validate(self):
        """Kiểm tra unique constraint (task_id, user_id)"""
        self.validate_unique_assignment()
    
    def validate_unique_assignment(self):
        """Đảm bảo không có duplicate assignment"""
        existing = frappe.db.exists("PM Task Assignee", {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "name": ["!=", self.name]
        })
        
        if existing:
            frappe.throw(
                _("User {0} đã được gán vào task này").format(self.user_id),
                title=_("Trùng lặp assignment")
            )
    
    def before_insert(self):
        """Thiết lập assigned_at và assigned_by"""
        if not self.assigned_at:
            self.assigned_at = frappe.utils.now()
        if not self.assigned_by:
            self.assigned_by = frappe.session.user

