# -*- coding: utf-8 -*-
"""Chuẩn hoá trạng thái CRM Admission Course Student: registered -> registered_interest, not_attended -> registered_interest."""

import frappe


def execute():
    """Map giá trị cũ sang mã trạng thái mới (sau khi migrate DocType)."""
    pairs = [
        ("registered", "registered_interest"),
        ("not_attended", "registered_interest"),
    ]
    for old, new in pairs:
        frappe.db.sql(
            """
            UPDATE `tabCRM Admission Course Student`
            SET `status` = %s
            WHERE `status` = %s
            """,
            (new, old),
        )
    frappe.db.commit()
