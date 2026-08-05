"""
Index cho module_tracker / record_guardian_activity.

Query nóng (after_request mỗi API parent portal):
  SELECT name FROM `tabPortal Guardian Activity`
  WHERE guardian = %s AND activity_date = %s AND activity_type = %s
  LIMIT 1

Không có index composite → full scan ~250k rows → DB CPU 100% (2026-08-05).
"""

import frappe


def _create_index_if_missing(table_name, index_name, columns_sql):
	# Bỏ qua nếu bảng chưa có (site mới / migrate dở)
	if not frappe.db.table_exists(table_name):
		frappe.logger().info(f"Table {table_name} does not exist, skipping index {index_name}")
		return

	existing = frappe.db.sql(
		f"SHOW INDEX FROM `{table_name}` WHERE Key_name = %s",
		(index_name,),
		as_dict=True,
	)
	if existing:
		frappe.logger().info(f"Index {index_name} already exists on {table_name}")
		return

	frappe.db.sql(f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns_sql})")
	frappe.db.commit()
	frappe.logger().info(f"Created index {index_name} on {table_name}")


def execute():
	_create_index_if_missing(
		"tabPortal Guardian Activity",
		"idx_pga_guardian_date_type",
		"`guardian`, `activity_date`, `activity_type`",
	)
