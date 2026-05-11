# -*- coding: utf-8 -*-
"""
Bật Track Changes cho mọi DocType thuộc app erp (theo Module Def).

- Chỉ DocType cha (istable=0): tránh Version khổng lồ cho các bảng con (Child Table).
- Chạy một lần qua bench migrate; site nào đã bật rồi thì giữ nguyên.
"""

import frappe


def execute():
	modules = frappe.get_all("Module Def", filters={"app_name": "erp"}, pluck="name")
	if not modules:
		return

	names = frappe.get_all(
		"DocType",
		filters={"module": ["in", modules], "istable": 0, "track_changes": 0},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("DocType", name, "track_changes", 1, update_modified=False)

	if names:
		frappe.db.commit()
	frappe.clear_cache()
