# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMChangeLog(Document):
    """
    PM Change Log - Doctype ghi lịch sử thay đổi trong dự án
    
    Fields:
    - project_id: Link đến PM Project
    - action: Loại hành động (task_created, task_moved, member_added, etc.)
    - actor_id: User thực hiện hành động
    - target_type: Loại đối tượng (project/requirement/task/member)
    - target_id: ID của đối tượng bị thay đổi
    - old_value: JSON chứa giá trị cũ
    - new_value: JSON chứa giá trị mới
    
    Note: 
    - Sử dụng field `creation` có sẵn của Frappe làm timestamp
    - Không cần tạo field timestamp riêng
    - Change logs không thể xóa hoặc sửa (audit trail)
    """
    
    def before_insert(self):
        """Thiết lập actor_id nếu chưa có"""
        if not self.actor_id:
            self.actor_id = frappe.session.user

