# -*- coding: utf-8 -*-
# Copyright (c) 2026, ERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISReportCardApprovalConfig(Document):
    """
    DocType để khai báo người duyệt Level 3 và Level 4 theo educational_stage.
    
    Level 3: Reviewers - Duyệt toàn bộ báo cáo trước khi xuất bản
    Level 4: Final Approvers - Phê duyệt xuất bản chính thức
    """
    
    def validate(self):
        """Validate unique config per campus + education_stage + school_year."""
        self.validate_unique_config()
    
    def validate_unique_config(self):
        """Đảm bảo chỉ có 1 config active cho mỗi campus + education_stage."""
        if self.is_active:
            filters = {
                "campus_id": self.campus_id,
                "education_stage_id": self.education_stage_id,
                "is_active": 1,
                "name": ["!=", self.name]
            }
            if self.school_year_id:
                filters["school_year_id"] = self.school_year_id
            
            existing = frappe.get_all(
                "SIS Report Card Approval Config",
                filters=filters,
                limit=1
            )
            
            if existing:
                frappe.throw(
                    f"Đã tồn tại cấu hình phê duyệt active cho cấp học này. "
                    f"Vui lòng vô hiệu hóa cấu hình cũ trước khi tạo mới."
                )
