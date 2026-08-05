# Copyright (c) 2026, WSHN and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint


class FaceIDDevice(Document):
    def validate(self):
        # IP không được trống
        if not self.ip:
            frappe.throw("IP thiết bị là bắt buộc")

    def after_insert(self):
        self._sync_to_controller()
        self._queue_provision()

    def on_update(self):
        self._sync_to_controller()
        # Chỉ provision lại khi thứ ảnh hưởng tới cấu hình trên máy đổi
        if self.has_value_changed("ip") or self.has_value_changed("enable_remote_check"):
            self._queue_provision()

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

    def _queue_provision(self):
        """Trỏ event host + NTP + remote-check xuống máy ngay sau khi khai báo."""
        if frappe.flags.get("faceid_skip_controller_push"):
            return
        if not cint(self.auto_provision):
            return
        try:
            from erp.api.faceid.sync_worker import create_device_sync_job

            create_device_sync_job("provision_device", "FaceID Device", self.name, priority=6)
        except Exception:
            frappe.log_error(
                title=f"FaceID queue provision {self.name}",
                message=frappe.get_traceback(),
            )

    def _sync_to_controller(self):
        """Đẩy máy xuống controller sau khi lưu trên Frappe.

        Không chặn việc lưu: controller/tunnel chết thì máy vẫn được khai báo trên
        Frappe, đánh dấu push_status=failed và xếp job retry.
        """
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
            frappe.db.set_value(
                "FaceID Device",
                self.name,
                {"push_status": "failed", "last_error": str(e)[:500]},
                update_modified=False,
            )
            try:
                from erp.api.faceid.sync_worker import create_device_sync_job

                create_device_sync_job(
                    "upsert_device", "FaceID Device", self.name, priority=9
                )
            except Exception:
                frappe.log_error(
                    title=f"FaceID queue device job {self.name}",
                    message=frappe.get_traceback(),
                )
            frappe.msgprint(
                f"Đã lưu trên Frappe nhưng chưa đẩy được xuống controller: {e}. "
                "Hệ thống sẽ tự thử lại.",
                indicator="orange",
                alert=True,
            )
