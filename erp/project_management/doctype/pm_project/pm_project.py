# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PMProject(Document):
    """
    PM Project - Doctype quản lý dự án
    
    Fields:
    - title: Tên dự án
    - description: Mô tả dự án
    - owner_id: User tạo dự án
    - status: Trạng thái (active/archived)
    - visibility: Phạm vi hiển thị (private/internal)
    - campus_id: Campus liên kết
    """
    
    def before_insert(self):
        """Thiết lập owner_id nếu chưa có"""
        if not self.owner_id:
            self.owner_id = frappe.session.user
    
    def after_insert(self):
        """Tự động thêm owner vào danh sách members với role 'owner'"""
        # Tạo member record cho owner
        member = frappe.get_doc({
            "doctype": "PM Project Member",
            "project_id": self.name,
            "user_id": self.owner_id,
            "role": "owner",
            "joined_at": frappe.utils.now()
        })
        member.insert(ignore_permissions=True)
        frappe.db.commit()

