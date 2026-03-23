# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISStudentHealthCheckup(Document):
    """
    Doctype lưu kết quả khám sức khoẻ định kỳ của học sinh.
    Mỗi học sinh tối đa 2 record/năm học: đầu năh và cuối năh (unique: student_id + school_year_id + checkup_phase).
    """
    
    def before_save(self):
        # Tự động tính BMI nếu có chiều cao và cân nặng
        if self.height and self.weight and self.height > 0:
            height_m = self.height / 100  # Convert cm to m
            self.bmi = round(self.weight / (height_m ** 2), 2)
    
    def validate(self):
        # Trùng theo (student_id, school_year_id, checkup_phase)
        if not self.checkup_phase:
            frappe.throw("Đợt khám (checkup_phase) là bắt buộc", title="Thiếu dữ liệu")

        filters = {
            "student_id": self.student_id,
            "school_year_id": self.school_year_id,
            "checkup_phase": self.checkup_phase,
        }
        if not self.is_new():
            filters["name"] = ("!=", self.name)

        existing = frappe.db.exists("SIS Student Health Checkup", filters)
        if existing:
            phase_label = "đầu năm học" if self.checkup_phase == "beginning" else "cuối năm học"
            frappe.throw(
                f"Học sinh {self.student_name or self.student_id} đã có bản ghi khám sức khoẻ ({phase_label}) trong năm học này.",
                title="Trùng lặp",
            )
