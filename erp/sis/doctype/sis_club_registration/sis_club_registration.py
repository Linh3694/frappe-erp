# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SISClubRegistration(Document):
    """
    Một dòng cho mỗi (học sinh, môn CLB).

    Dạng một-dòng-một-đăng-ký (thay vì doc cha + child table như SIS Menu
    Registration) là điều kiện cần để hai luật nghiệp vụ ép được ở tầng DB:

        uq_club_reg_student_subject (period_id, subject_id, active_student_key)
            -> mỗi HS tối đa 1 đăng ký / 1 môn / 1 đợt (kể cả môn mở nhiều thứ)
        uq_club_reg_student_day     (period_id, day_of_week, active_student_key)
            -> mỗi HS tối đa 1 môn / thứ

    Ngoài ra child table bị Frappe XOÁ VÀ TẠO LẠI mỗi lần parent.save(), nên
    mọi lần "lưu thêm môn" sẽ thành read-modify-write — tức lost update khi hai
    request chạy song song. Ở đây mỗi lần lưu chỉ là một INSERT độc lập.

    CẢNH BÁO: không đặt logic capacity ở controller. Việc kiểm còn chỗ phải chạy
    bên trong row lock của SIS Club Offering — xem erp/sis/utils/club_registration.py.
    Controller có thể bị gọi từ bất kỳ đường nào (bench console, import) và khi đó
    không có lock nào cả.
    """

    def before_insert(self):
        if not self.registration_datetime:
            self.registration_datetime = now_datetime()

    def before_save(self):
        # MariaDB bỏ qua dòng có cột NULL trong UNIQUE index. Nhờ vậy hai ràng buộc
        # ở trên chỉ áp lên dòng đang active, và một đăng ký đã huỷ không chặn học
        # sinh đăng ký lại chính môn đó.
        self.active_student_key = self.student_id if self.status == "active" else None

        if self.status == "cancelled":
            if not self.cancelled_at:
                self.cancelled_at = now_datetime()
            if not self.cancelled_by:
                self.cancelled_by = frappe.session.user
