# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime

from erp.sis.utils.club_days import (
    DAY_ORDER,
    days_to_csv,
    format_days_vn,
    normalize_days,
)


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
        self.normalize_activity_days()
        self.validate_timelines()
        self.validate_single_open_period()
        self.validate_activity_days_cover_offerings()

    # ------------------------------------------------------------------
    # Ngày sinh hoạt
    # ------------------------------------------------------------------

    def normalize_activity_days(self):
        """
        Chuẩn hoá về CSV đúng thứ tự tuần, bỏ trùng và bỏ giá trị lạ.

        Lưu CSV thay vì child table: tối đa sáu token cố định, mà child table thì
        Frappe xoá và tạo lại toàn bộ dòng con sau mỗi `parent.save()` — thừa
        rủi ro cho một danh sách bé thế này.
        """
        # `self.get(...)` chứ không phải `self.activity_days`: giữa lúc deploy code
        # và lúc chạy migrate thì field chưa có trong meta, truy cập thẳng sẽ
        # AttributeError và làm hỏng MỌI thao tác lưu đợt.
        self.activity_days = days_to_csv(self.get("activity_days"))

    def get_activity_days(self):
        """
        Các thứ đợt này cho phép mở buổi.

        Để TRỐNG nghĩa là chưa cấu hình -> cho phép mọi thứ. Nhờ vậy các đợt tạo
        trước khi có trường này vẫn chạy nguyên như cũ, không cần patch backfill.
        """
        days = normalize_days(self.get("activity_days"))
        return days or list(DAY_ORDER)

    def validate_activity_days_cover_offerings(self):
        """
        Không cho bỏ một thứ đang có buổi.

        Nếu cho qua thì buổi đó thành mồ côi: bảng cấu hình không còn cột để hiện
        nó, nhưng phụ huynh vẫn đăng ký được vì Parent Portal gom theo buổi thật.
        Sửa được bằng cách xoá buổi trước, nên báo rõ thứ nào đang vướng.
        """
        days = normalize_days(self.get("activity_days"))
        if not days or not self.name:
            return

        orphan = frappe.get_all(
            "SIS Club Offering",
            filters={"period_id": self.name, "day_of_week": ["not in", days]},
            fields=["day_of_week"],
            distinct=True,
            pluck="day_of_week",
        )
        if orphan:
            frappe.throw(
                f"Không thể bỏ {format_days_vn(orphan)} khỏi ngày sinh hoạt vì đợt "
                f"đang có môn mở vào những thứ đó. Hãy gỡ các buổi đó ở tab «Môn CLB» trước."
            )

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
