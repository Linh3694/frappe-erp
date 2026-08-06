# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MDMDevice(Document):
    def validate(self):
        if self.serial_number:
            self.serial_number = self.serial_number.strip()
        if not self.serial_number:
            frappe.throw("Serial máy là bắt buộc")

    def on_trash(self):
        """Thu hồi peer WireGuard khi xóa bản ghi.

        Chỉ ghi log nếu thu hồi lỗi — không chặn việc xóa, vì bản ghi Frappe
        không phải nguồn chuẩn của cấu hình wg0.
        """
        if not self.wg_pubkey:
            return
        try:
            from erp.api.mdm.wireguard import revoke_peer

            revoke_peer(self.wg_pubkey)
        except Exception:
            frappe.log_error(
                title=f"MDM revoke WG peer {self.name}",
                message=frappe.get_traceback(),
            )
