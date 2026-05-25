# -*- coding: utf-8 -*-
"""Scheduled task: đồng bộ trạng thái quá hạn mượn sách thư viện."""

import frappe


def sync_library_overdue_job():
	"""Chạy hàng ngày lúc 01:00 — cập nhật overdue cho transaction/copy."""
	frappe.logger().info("[LIBRARY] Bắt đầu sync_library_overdue_job...")
	try:
		from erp.api.erp_sis.library import sync_overdue_status

		count = sync_overdue_status()
		frappe.logger().info(f"[LIBRARY] sync_library_overdue_job hoàn thành: {count} item quá hạn")
	except Exception as ex:
		frappe.log_error(f"[LIBRARY] sync_library_overdue_job failed: {ex}")
		frappe.logger().error(f"[LIBRARY] sync_library_overdue_job exception: {ex}")
