# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FaceIDDevice(Document):
    def validate(self):
        # IP không được trống
        if not self.ip:
            frappe.throw("IP thiết bị là bắt buộc")

    def on_trash(self):
        """Xóa thiết bị trên controller local khi xóa doc Frappe."""
        if not self.controller_device_id:
            return
        try:
            from erp.utils.faceid_gateway import gateway_delete

            gateway_delete(f"/api/devices/{self.controller_device_id}")
        except Exception:
            frappe.log_error(
                title=f"FaceID on_trash device {self.name}",
                message=frappe.get_traceback(),
            )
