# Copyright (c) 2026, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime


class ERPRoomBooking(Document):
    """Lượt đặt phòng — nguồn dữ liệu duy nhất cho lịch đặt phòng & chống trùng giờ.

    Được tạo từ trang Đặt phòng (không kèm ticket) hoặc từ form ticket Hành chính
    category 'sự kiện/CSVC' (kèm ticket, link qua source_ticket).
    """

    def validate(self):
        st = get_datetime(self.start_time) if self.start_time else None
        et = get_datetime(self.end_time) if self.end_time else None
        if not st or not et:
            frappe.throw(_("Thiếu thời gian bắt đầu / kết thúc"))
        if et <= st:
            frappe.throw(_("Thời gian kết thúc phải sau thời gian bắt đầu"))
