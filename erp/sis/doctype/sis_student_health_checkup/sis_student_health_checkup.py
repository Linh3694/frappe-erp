# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISStudentHealthCheckup(Document):
    """
    Doctype lưu kết quả khám sức khoẻ định kỳ của học sinh.
    Mỗi học sinh chỉ có 1 record/năm học (unique constraint: student_id + school_year_id).
    """
    
    def before_save(self):
        # Tự động tính BMI nếu có chiều cao và cân nặng
        if self.height and self.weight and self.height > 0:
            height_m = self.height / 100  # Convert cm to m
            self.bmi = round(self.weight / (height_m ** 2), 2)
    
    def validate(self):
        # Validate unique constraint (student_id + school_year_id)
        if not self.is_new():
            return
        
        existing = frappe.db.exists(
            "SIS Student Health Checkup",
            {
                "student_id": self.student_id,
                "school_year_id": self.school_year_id,
                "name": ("!=", self.name)
            }
        )
        if existing:
            frappe.throw(
                f"Học sinh {self.student_name or self.student_id} đã có bản ghi khám sức khoẻ trong năm học này.",
                title="Trùng lặp"
            )
