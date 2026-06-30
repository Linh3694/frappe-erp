# Copyright (c) 2026, Wellspring and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Xóa User Permission tự-tham-chiếu trên doctype SIS Campus.

	Trước đây create_user_campus_permissions() và setup_campus_permissions()
	tạo User Permission allow="SIS Campus" applicable_for="SIS Campus" cho mỗi
	user được gán campus. Record này giới hạn chính doctype SIS Campus xuống còn
	các campus đã gán, khiến user (kể cả System Manager) không tạo được campus
	mới vì doc mới chưa có name (name=None không khớp danh sách for_value):
	  "Not allowed for SIS Campus: None".

	Chỉ xóa đúng nhóm tự-tham-chiếu (applicable_for="SIS Campus"). Các User
	Permission scope dữ liệu cho doctype khác (applicable_for != "SIS Campus",
	ví dụ SIS Class, SIS Teacher, ...) được GIỮ NGUYÊN.
	"""
	deleted = frappe.db.count(
		"User Permission",
		{"allow": "SIS Campus", "applicable_for": "SIS Campus"},
	)
	frappe.db.delete(
		"User Permission",
		{"allow": "SIS Campus", "applicable_for": "SIS Campus"},
	)
	frappe.db.commit()
	print(f"[remove_sis_campus_self_user_permission] Đã xóa {deleted} User Permission tự-tham-chiếu trên SIS Campus")
