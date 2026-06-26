# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDWorkShift(Document):
    def validate(self):
        # Slot 1-16, unique — tránh vượt giới hạn máy Hikvision
        slot = int(self.device_slot or 0)
        if slot < 1 or slot > 16:
            frappe.throw("device_slot phải từ 1 đến 16")
        for row in self.periods or []:
            if row.start_time and row.end_time and str(row.start_time) >= str(row.end_time):
                frappe.throw(f"Thứ {row.weekday}: giờ bắt đầu phải nhỏ hơn giờ kết thúc")

    # Operator-driven: không auto sync — admin bấm "Áp dụng xuống máy"
