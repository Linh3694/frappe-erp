# Copyright (c) 2026, WSHN and contributors
import frappe
from frappe.model.document import Document


class FaceIDAccessGroup(Document):
    def validate(self):
        seen = set()
        for row in self.devices or []:
            if row.device in seen:
                frappe.throw(f"Thiết bị {row.device} bị khai trùng trong nhóm")
            seen.add(row.device)

        if self.valid_from and self.valid_to and str(self.valid_from) > str(self.valid_to):
            frappe.throw("Hiệu lực từ phải nhỏ hơn hoặc bằng hiệu lực đến")

        # Nhóm hệ thống (PH cổng đón) do engine dựng — chặn sửa thành viên/máy bằng tay
        if self.managed_by == "system" and not self.flags.faceid_system_write:
            before = self.get_doc_before_save()
            if before and self._devices_changed(before):
                frappe.throw(
                    "Nhóm hệ thống: danh sách máy do engine quản lý, không sửa tay"
                )

    def _devices_changed(self, before) -> bool:
        old = sorted(r.device for r in before.devices or [])
        new = sorted(r.device for r in self.devices or [])
        return old != new

    def on_trash(self):
        if self.managed_by == "system" and not self.flags.faceid_system_write:
            frappe.throw("Không xóa được nhóm hệ thống")
        frappe.db.delete("FaceID Access Group Member", {"group": self.name})
