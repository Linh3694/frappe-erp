# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt
"""Đảm bảo bypass_supersession = 0 cho bản ghi cũ (nếu cột NULL sau migrate)."""

import frappe


def execute():
    # has_column nhận *tên DocType*, không phải tên bảng tab...
    if not frappe.db.has_column("SIS Finance Order Student", "bypass_supersession"):
        return
    frappe.db.sql(
        """
        UPDATE `tabSIS Finance Order Student`
        SET bypass_supersession = 0
        WHERE bypass_supersession IS NULL
        """
    )
