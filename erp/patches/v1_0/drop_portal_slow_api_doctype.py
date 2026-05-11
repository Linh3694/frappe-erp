# -*- coding: utf-8 -*-
"""
Xóa DocType Portal Slow API — slow API chỉ log ra Loki (event_kind=slow_api).
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Portal Slow API"):
		return

	frappe.delete_doc("DocType", "Portal Slow API", force=True, ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache()
