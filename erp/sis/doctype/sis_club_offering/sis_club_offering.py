# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

DAY_LABELS_VN = {
    "mon": "Thứ 2",
    "tue": "Thứ 3",
    "wed": "Thứ 4",
    "thu": "Thứ 5",
    "fri": "Thứ 6",
    "sat": "Thứ 7",
}

DAY_LABELS_EN = {
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
}


class SISClubOffering(Document):
    """
    Một môn CLB được mở trong một đợt, vào MỘT thứ cố định.

    Cùng một môn chạy cả thứ 3 lẫn thứ 5 => HAI bản ghi. Lý do:
      - `capacity` trở nên rõ nghĩa: 20 chỗ của BUỔI đó, không mơ hồ
        "20 tổng hay 20 mỗi buổi".
      - `day_of_week` là scalar nên dòng đăng ký mang được nó, và luật
        "mỗi thứ tối đa 1 môn" ép được bằng UNIQUE index ở tầng DB. Nếu thứ
        nằm trong child table thì không constraint nào diễn đạt nổi.

    KHÔNG đặt logic capacity ở đây — nó phải chạy bên trong row lock, xem
    erp/sis/utils/club_registration.py. `registered_count` chỉ được ghi từ đó.
    """

    def before_insert(self):
        self.created_by = frappe.session.user
        self.created_at = now_datetime()
        self.updated_at = now_datetime()

    def before_save(self):
        self.updated_at = now_datetime()
        self.validate_subject_is_club()
        self.resolve_titles()
        self.validate_capacity()
        self.validate_grades()
        self.validate_unique_subject_day()

    def validate_subject_is_club(self):
        """
        Môn gắn vào CLB phải có `subject_type = 'club'`.

        Gắn nhầm một môn học thuật không chỉ sai nghiệp vụ: các luồng TKB /
        phân công GV / học bạ lọc theo chính cột này, nên môn đó sẽ vừa nằm
        trong TKB vừa nằm trong CLB và không nơi nào phát hiện được.
        """
        if not self.subject_id:
            return
        if not frappe.db.has_column("SIS Subject", "subject_type"):
            return  # chưa chạy bench migrate — bỏ qua thay vì chặn toàn bộ

        subject_type = frappe.db.get_value("SIS Subject", self.subject_id, "subject_type")
        if subject_type and subject_type != "club":
            frappe.throw(
                "Môn đã chọn là môn học thuật, không dùng cho câu lạc bộ được. "
                "Hãy tạo môn mới với Loại môn học = «Câu lạc bộ», hoặc đổi loại của môn này."
            )

    def resolve_titles(self):
        """
        Snapshot tên song ngữ.

        `fetch_from` của Frappe chỉ đi được MỘT cấp nên không thể viết
        `subject_id.timetable_subject_id.title_vn`. Ưu tiên SIS Timetable Subject
        (title_vn + title_en đều reqd bên đó nên luôn đủ song ngữ); nếu môn chưa
        gắn timetable subject thì fallback về SIS Subject.title cho cả hai thứ
        tiếng — form staff sẽ cảnh báo để đi gắn cho đúng.
        """
        if not self.subject_id:
            return

        subject = frappe.db.get_value(
            "SIS Subject", self.subject_id, ["title", "timetable_subject_id", "campus_id"], as_dict=True
        )
        if not subject:
            return

        self.timetable_subject_id = subject.timetable_subject_id

        if subject.timetable_subject_id:
            tts = frappe.db.get_value(
                "SIS Timetable Subject",
                subject.timetable_subject_id,
                ["title_vn", "title_en"],
                as_dict=True,
            )
            if tts:
                self.title_vn = tts.title_vn or subject.title
                self.title_en = tts.title_en or tts.title_vn or subject.title
                return

        self.title_vn = subject.title
        self.title_en = subject.title

    def validate_capacity(self):
        if not self.capacity or int(self.capacity) < 1:
            frappe.throw("Giới hạn số lượng phải lớn hơn 0")

        current = int(self.registered_count or 0)
        if int(self.capacity) < current:
            frappe.throw(
                f"Không thể hạ giới hạn xuống {self.capacity} khi đã có {current} học sinh đăng ký"
            )

    def validate_grades(self):
        if not self.education_grades:
            frappe.throw("Phải chọn ít nhất một khối được áp dụng")

        grade_ids = [g.education_grade_id for g in self.education_grades]
        if len(grade_ids) != len(set(grade_ids)):
            frappe.throw("Không được chọn trùng khối")

        if not self.subject_id:
            return

        subject_stage = frappe.db.get_value("SIS Subject", self.subject_id, "education_stage")
        if not subject_stage:
            return

        for row in self.education_grades:
            grade_stage = frappe.db.get_value(
                "SIS Education Grade", row.education_grade_id, "education_stage_id"
            )
            if grade_stage and grade_stage != subject_stage:
                frappe.throw(
                    f"Khối «{row.education_grade_name or row.education_grade_id}» không thuộc cấp học "
                    f"của môn đã chọn. Môn dạy cho hai cấp cần hai bản ghi SIS Subject riêng."
                )

    def validate_unique_subject_day(self):
        """Trong một đợt, mỗi (môn, thứ) chỉ được mở một lần."""
        if not (self.period_id and self.subject_id and self.day_of_week):
            return

        duplicate = frappe.db.get_value(
            "SIS Club Offering",
            {
                "period_id": self.period_id,
                "subject_id": self.subject_id,
                "day_of_week": self.day_of_week,
                "name": ["!=", self.name or ""],
            },
            "name",
        )
        if duplicate:
            frappe.throw(
                f"Môn này đã được mở vào {DAY_LABELS_VN.get(self.day_of_week, self.day_of_week)} "
                f"trong đợt (mã {duplicate})"
            )

    def on_trash(self):
        if frappe.db.exists(
            "SIS Club Registration", {"offering_id": self.name, "status": "active"}
        ):
            frappe.throw(
                "Không thể xoá môn đang có học sinh đăng ký. Vui lòng huỷ các đăng ký trước."
            )
