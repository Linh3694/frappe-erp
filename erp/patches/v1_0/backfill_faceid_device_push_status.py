"""Máy đã có controller_device_id nghĩa là đã đẩy xuống controller thành công."""

import frappe


def execute():
    if not frappe.db.table_exists("FaceID Device"):
        return
    frappe.db.sql(
        """
        UPDATE `tabFaceID Device`
        SET push_status = 'synced'
        WHERE IFNULL(controller_device_id, 0) > 0
          AND IFNULL(push_status, '') IN ('', 'pending')
        """
    )
