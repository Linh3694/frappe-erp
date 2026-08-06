# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document

MAX_SEGMENTS_PER_DAY = 8  # giới hạn firmware Hikvision: 8 đoạn/ngày trong 1 week plan


class FaceIDWorkShift(Document):
    """Ca chỉ là khung giờ.

    Slot trên máy do engine cấp phát theo TỪNG máy (`FaceID Device Slot`), vì
    lịch hiệu lực trên một đầu đọc là HỢP các ca của mọi nhóm mà person thuộc
    về — không gắn cứng được một slot cho một ca.

    Sửa khung giờ ở đây sẽ lan xuống máy qua hook `on_work_shift_changed`
    (tính lại các nhóm đang dùng ca này).
    """

    def validate(self):
        per_day: dict[int, int] = {}
        for row in self.periods or []:
            if row.start_time and row.end_time and str(row.start_time) >= str(row.end_time):
                frappe.throw(f"Thứ {row.weekday}: giờ bắt đầu phải nhỏ hơn giờ kết thúc")
            if row.weekday:
                weekday = int(row.weekday)
                per_day[weekday] = per_day.get(weekday, 0) + 1

        for weekday, count in per_day.items():
            if count > MAX_SEGMENTS_PER_DAY:
                frappe.throw(
                    f"Thứ {weekday} có {count} khung giờ, vượt giới hạn "
                    f"{MAX_SEGMENTS_PER_DAY} đoạn/ngày của thiết bị"
                )
