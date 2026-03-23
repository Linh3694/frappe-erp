"""
Gán checkup_phase = beginning cho bản ghi khám SK cũ (trước khi có trường đợt khám).
Chạy sau migrate khi cột đã tồn tại.
"""

import frappe


def execute():
	"""Đảm bảo mọi bản ghi đều có đợt khám (mặc định đầu năm học)."""
	if not frappe.db.table_exists("tabSIS Student Health Checkup"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabSIS Student Health Checkup`
		SET `checkup_phase` = 'beginning'
		WHERE `checkup_phase` IS NULL OR `checkup_phase` = ''
		"""
	)
	frappe.db.commit()
