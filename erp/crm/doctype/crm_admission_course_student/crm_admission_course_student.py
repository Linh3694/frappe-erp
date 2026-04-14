# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class CRMAdmissionCourseStudent(Document):
    """Học sinh đăng ký khoá học tuyển sinh"""

    def validate(self):
        # Kiểm tra gán lớp khớp khoá học và quy tắc 1 lớp chính quy / nhiều lớp chạy
        if not self.course_id:
            return

        regular_in_course = frappe.get_all(
            "CRM Admission Course Class",
            filters={
                "parent": self.course_id,
                "parenttype": "CRM Admission Course",
                "class_type": "regular",
            },
            pluck="name",
        )

        if regular_in_course and not self.regular_class:
            frappe.throw(_("Phải chọn một lớp chính quy vì khoá học đã khai báo lớp chính quy."))

        if self.regular_class:
            row = frappe.db.get_value(
                "CRM Admission Course Class",
                self.regular_class,
                ["parent", "class_type"],
                as_dict=True,
            )
            if (
                not row
                or row.parent != self.course_id
                or row.class_type != "regular"
            ):
                frappe.throw(_("Lớp chính quy không hợp lệ hoặc không thuộc khoá học này."))

        seen_running = set()
        for line in self.running_classes or []:
            cc = line.course_class
            if not cc:
                continue
            if cc in seen_running:
                frappe.throw(_("Không được trùng lớp chạy trong cùng một học sinh."))
            seen_running.add(cc)
            row = frappe.db.get_value(
                "CRM Admission Course Class",
                cc,
                ["parent", "class_type"],
                as_dict=True,
            )
            if (
                not row
                or row.parent != self.course_id
                or row.class_type != "running"
            ):
                frappe.throw(_("Lớp chạy không hợp lệ hoặc không thuộc khoá học này."))

        if not regular_in_course and self.regular_class:
            frappe.throw(_("Khoá học không có lớp chính quy — không được gán lớp chính quy."))

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
