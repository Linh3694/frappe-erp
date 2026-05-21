"""Chuẩn hóa position module/items — chạy một lần sau nâng cấp Module Builder."""

import frappe


def execute():
	"""Gán position 1..n theo creation cho mọi course/module."""
	courses = frappe.get_all("LMS Course", pluck="name")
	for course in courses:
		modules = frappe.get_all(
			"LMS Module",
			filters={"course": course},
			fields=["name"],
			order_by="position asc, creation asc",
		)
		for idx, mod in enumerate(modules, start=1):
			frappe.db.set_value("LMS Module", mod.name, "position", idx)
			items = frappe.get_all(
				"LMS Module Item",
				filters={"module": mod.name},
				fields=["name"],
				order_by="position asc, creation asc",
			)
			for jdx, item in enumerate(items, start=1):
				frappe.db.set_value("LMS Module Item", item.name, "position", jdx)
	frappe.db.commit()
