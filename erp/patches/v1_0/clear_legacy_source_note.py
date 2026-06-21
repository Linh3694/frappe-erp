# -*- coding: utf-8 -*-
"""Nguồn 3 đổi từ text tự do sang Link CRM Source Note → xoá giá trị text cũ.

Các giá trị `source_note` cũ là text tự do, không khớp docname của danh mục
mới nên sẽ là Link không hợp lệ. Theo quyết định "bỏ data cũ", xoá hết.
"""

import frappe


def execute():
    try:
        if frappe.db.has_column("CRM Lead Source", "source_note"):
            frappe.db.sql("UPDATE `tabCRM Lead Source` SET source_note = NULL")
    except Exception:
        frappe.log_error(title="clear_legacy_source_note")
