"""Trước đây provision suy remote-check từ cờ cổng đón — giữ nguyên hành vi cho máy cũ."""

import frappe


def execute():
    if not frappe.db.table_exists("FaceID Device"):
        return
    frappe.db.sql(
        """
        UPDATE `tabFaceID Device`
        SET enable_remote_check = 1
        WHERE IFNULL(is_pickup_gate, 0) = 1
          AND IFNULL(enable_remote_check, 0) = 0
        """
    )
