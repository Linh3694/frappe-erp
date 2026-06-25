# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMAdmissionTarget(Document):
    def validate(self):
        # Tính tổng mục tiêu phòng ban từ các khối
        total = 0
        seen_grades = set()
        for row in self.grade_targets or []:
            grade = (row.target_grade or "").strip()
            if not grade:
                continue
            if grade in seen_grades:
                frappe.throw(_("Khối \"{0}\" bị trùng trong danh sách mục tiêu.").format(grade))
            seen_grades.add(grade)
            total += int(row.enrollment_target or 0)
        self.total_enrollment_target = total

        # Không trùng PIC trong bảng thành viên
        seen_pics = set()
        for row in self.member_targets or []:
            pic = (row.pic or "").strip()
            if not pic:
                continue
            if pic in seen_pics:
                frappe.throw(_("PIC \"{0}\" bị trùng trong danh sách mục tiêu cá nhân.").format(pic))
            seen_pics.add(pic)
