# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMTaskComment(Document):
    """
    PM Task Comment - Doctype quản lý comments cho task
    
    Fields:
    - task_id: Link đến PM Task
    - comment_text: Nội dung comment
    - created_by: User tạo comment
    - creation_date: Thời gian tạo comment
    """
    
    def before_insert(self):
        """Thiết lập created_by và creation_date"""
        if not self.created_by:
            self.created_by = frappe.session.user
        if not self.creation_date:
            self.creation_date = frappe.utils.now()
    
    def after_insert(self):
        """Log change sau khi tạo comment"""
        try:
            # Lấy thông tin task để log
            task = frappe.get_doc("PM Task", self.task_id)
            
            # Tạo change log
            log = frappe.get_doc({
                "doctype": "PM Change Log",
                "project_id": task.project_id,
                "action": "comment_added",
                "actor_id": frappe.session.user,
                "target_type": "task",
                "target_id": self.task_id,
                "new_value": self.comment_text[:100]  # Chỉ lưu 100 ký tự đầu
            })
            log.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error logging comment: {str(e)}")
    
    def on_trash(self):
        """Log change khi xóa comment"""
        try:
            task = frappe.get_doc("PM Task", self.task_id)
            
            log = frappe.get_doc({
                "doctype": "PM Change Log",
                "project_id": task.project_id,
                "action": "comment_deleted",
                "actor_id": frappe.session.user,
                "target_type": "task",
                "target_id": self.task_id,
            })
            log.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error logging comment deletion: {str(e)}")

