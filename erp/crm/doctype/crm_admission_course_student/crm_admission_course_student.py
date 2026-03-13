# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CRMAdmissionCourseStudent(Document):
    """Học sinh đăng ký khoá học tuyển sinh"""

    def _update_course_student_count(self):
        """Cập nhật student_count cho CRM Admission Course"""
        if not self.course_id:
            return
        count = frappe.db.count(
            "CRM Admission Course Student",
            filters={"course_id": self.course_id}
        )
        frappe.db.set_value(
            "CRM Admission Course",
            self.course_id,
            "student_count",
            count,
            update_modified=False
        )

    def after_insert(self):
        self._update_course_student_count()

    def on_trash(self):
        # on_trash chạy trước khi doc bị xóa, nên count vẫn bao gồm doc này -> set count - 1
        if not self.course_id:
            return
        count = frappe.db.count(
            "CRM Admission Course Student",
            filters={"course_id": self.course_id}
        )
        frappe.db.set_value(
            "CRM Admission Course",
            self.course_id,
            "student_count",
            max(0, count - 1),
            update_modified=False
        )
