# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDDeviceSlot(Document):
    def validate(self):
        slot = int(self.slot or 0)
        if slot < 1 or slot > 16:
            frappe.throw("slot phải từ 1 đến 16 (giới hạn week plan của Hikvision)")

        dup_slot = frappe.db.get_value(
            "FaceID Device Slot",
            {"device": self.device, "slot": slot, "name": ["!=", self.name or ""]},
            "name",
        )
        if dup_slot:
            frappe.throw(f"Máy {self.device} đã dùng slot {slot} cho lịch khác")

        dup_sig = frappe.db.get_value(
            "FaceID Device Slot",
            {
                "device": self.device,
                "schedule_signature": self.schedule_signature,
                "name": ["!=", self.name or ""],
            },
            "name",
        )
        if dup_sig:
            frappe.throw(f"Máy {self.device} đã có slot cho lịch {self.schedule_signature}")
