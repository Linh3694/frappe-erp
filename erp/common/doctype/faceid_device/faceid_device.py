# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FaceIDDevice(Document):
    def validate(self):
        # IP không được trống
        if not self.ip:
            frappe.throw("IP thiết bị là bắt buộc")

    def after_insert(self):
        self._sync_to_controller()

    def on_update(self):
        self._sync_to_controller()

    def on_trash(self):
        """Xóa thiết bị trên controller local khi xóa doc Frappe."""
        try:
            from erp.api.faceid.device_gateway import delete_device_from_controller

            delete_device_from_controller(self.controller_device_id)
        except Exception:
            frappe.log_error(
                title=f"FaceID on_trash device {self.name}",
                message=frappe.get_traceback(),
            )

    def _sync_to_controller(self):
        """Đẩy máy xuống controller sau khi lưu trên Frappe."""
        if frappe.flags.get("faceid_skip_controller_push"):
            return
        try:
            from erp.api.faceid.device_gateway import push_device_to_controller

            push_device_to_controller(self)
        except Exception as e:
            frappe.log_error(
                title=f"FaceID push device {self.name}",
                message=frappe.get_traceback(),
            )
            frappe.throw(f"Không đẩy được xuống controller: {e}")
