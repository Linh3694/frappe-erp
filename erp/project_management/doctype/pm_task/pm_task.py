# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMTask(Document):
    """
    PM Task - Doctype quản lý task/công việc trong dự án
    
    Fields:
    - project_id: Link đến PM Project
    - title: Tiêu đề task
    - description: Mô tả chi tiết
    - status: Trạng thái (backlog/todo/in_progress/review/done)
    - priority: Độ ưu tiên (low/medium/high/critical)
    - created_by: User tạo task (quan trọng cho permission/analytics/audit)
    - due_date: Hạn hoàn thành
    - tags: Các tag cách nhau bởi dấu phẩy
    - order_index: Thứ tự trong column (cho drag-drop)
    """
    
    def before_insert(self):
        """Thiết lập created_by và order_index"""
        if not self.created_by:
            self.created_by = frappe.session.user
        
        # Đặt order_index là số lớn nhất trong cùng project + status
        if self.order_index == 0:
            max_order = frappe.db.sql("""
                SELECT MAX(order_index) as max_order
                FROM `tabPM Task`
                WHERE project_id = %s AND status = %s
            """, (self.project_id, self.status), as_dict=True)
            
            if max_order and max_order[0].max_order is not None:
                self.order_index = max_order[0].max_order + 1
            else:
                self.order_index = 0
    
    def after_insert(self):
        """Log change sau khi tạo task"""
        self.log_change("task_created", None, {
            "title": self.title,
            "status": self.status,
            "priority": self.priority
        })
    
    def on_update(self):
        """Log change khi cập nhật task"""
        # Lấy doc cũ để so sánh
        old_doc = self.get_doc_before_save()
        if old_doc:
            changes = {}
            for field in ["title", "status", "priority", "due_date", "tags", "order_index"]:
                old_val = getattr(old_doc, field, None)
                new_val = getattr(self, field, None)
                if old_val != new_val:
                    changes[field] = {"old": old_val, "new": new_val}
            
            if changes:
                self.log_change("task_updated", 
                    {k: v["old"] for k, v in changes.items()},
                    {k: v["new"] for k, v in changes.items()}
                )
    
    def log_change(self, action, old_value, new_value):
        """Ghi log thay đổi vào PM Change Log"""
        try:
            import json
            log = frappe.get_doc({
                "doctype": "PM Change Log",
                "project_id": self.project_id,
                "action": action,
                "actor_id": frappe.session.user,
                "target_type": "task",
                "target_id": self.name,
                "old_value": json.dumps(old_value) if old_value else None,
                "new_value": json.dumps(new_value) if new_value else None
            })
            log.insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error logging task change: {str(e)}")

