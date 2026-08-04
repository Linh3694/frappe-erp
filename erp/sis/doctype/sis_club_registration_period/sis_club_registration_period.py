# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime


class SISClubRegistrationPeriod(Document):
    """
    Đợt đăng ký câu lạc bộ.

    Hai khung thời gian TÁCH BIỆT:
      - display_*      : khoảng phụ huynh NHÌN THẤY đợt trên Parent Portal (để xem
                         giới thiệu + đồng hồ đếm ngược trước khi cổng mở).
      - registration_* : khoảng thực sự NHẬN đăng ký.

    Vì vậy display_start <= registration_start: không thể mở đăng ký trước khi
    phụ huynh được nhìn thấy đợt.
    """

    def before_insert(self):
        self.created_by = frappe.session.user
        self.created_at = now_datetime()
        self.updated_at = now_datetime()

    def before_save(self):
        self.updated_at = now_datetime()
        self.validate_timelines()
        self.validate_single_open_period()

    def validate_timelines(self):
        """Kiểm tra hai khung thời gian và quan hệ giữa chúng."""
        if self.display_start_datetime and self.display_end_datetime:
            if get_datetime(self.display_start_datetime) >= get_datetime(self.display_end_datetime):
                frappe.throw("Thời gian bắt đầu hiển thị phải trước thời gian kết thúc hiển thị")

        if self.registration_start_datetime and self.registration_end_datetime:
            if get_datetime(self.registration_start_datetime) >= get_datetime(
                self.registration_end_datetime
            ):
                frappe.throw("Thời gian bắt đầu đăng ký phải trước thời gian kết thúc đăng ký")

        if self.display_start_datetime and self.registration_start_datetime:
            if get_datetime(self.registration_start_datetime) < get_datetime(
                self.display_start_datetime
            ):
                frappe.throw(
                    "Thời gian bắt đầu đăng ký không được sớm hơn thời gian bắt đầu hiển thị "
                    "— phụ huynh phải nhìn thấy đợt trước khi cổng đăng ký mở"
                )

        if self.status == "Open" and not (
            self.display_start_datetime
            and self.display_end_datetime
            and self.registration_start_datetime
            and self.registration_end_datetime
        ):
            frappe.throw("Đợt ở trạng thái Open phải điền đủ cả hai khung thời gian")

    def validate_single_open_period(self):
        """
        Chỉ cho phép MỘT đợt Open trên mỗi (campus, năm học).

        Nếu có hai đợt Open cùng lúc thì `get_period_overview` của Parent Portal
        không xác định được nên trả đợt nào — phụ huynh sẽ thấy đợt tuỳ ý.
        """
        if self.status != "Open":
            return

        filters = {
            "status": "Open",
            "school_year_id": self.school_year_id,
            "name": ["!=", self.name or ""],
        }
        if self.campus_id:
            filters["campus_id"] = self.campus_id

        existing = frappe.db.get_value("SIS Club Registration Period", filters, "title_vn")
        if existing:
            frappe.throw(
                f"Đã có một đợt đang mở trong năm học này: «{existing}». "
                "Vui lòng đóng đợt đó trước khi mở đợt mới."
            )

    def on_trash(self):
        if frappe.db.exists("SIS Club Offering", {"period_id": self.name}):
            frappe.throw(
                "Không thể xoá đợt đang có môn CLB. Vui lòng xoá các môn trong đợt trước."
            )

    # ------------------------------------------------------------------
    # Helpers dùng chung cho API
    # ------------------------------------------------------------------

    def is_within_display_window(self, now=None):
        now = now or now_datetime()
        if not (self.display_start_datetime and self.display_end_datetime):
            return False
        return (
            get_datetime(self.display_start_datetime)
            <= now
            <= get_datetime(self.display_end_datetime)
        )

    def is_within_registration_window(self, now=None):
        now = now or now_datetime()
        if not (self.registration_start_datetime and self.registration_end_datetime):
            return False
        return (
            get_datetime(self.registration_start_datetime)
            <= now
            <= get_datetime(self.registration_end_datetime)
        )
