"""
Index cho thống kê kỷ luật theo tháng (discipline_monthly_escalation).

Query nóng khi mở danh sách ghi nhận lỗi:
  COUNT trên Record JOIN Student Entry theo student_id + applied_level + date
  và legacy target_student + date

Sự cố 2026-08-05 ~16:10: DB CPU 100% do N+1 COUNT đồng thời.
"""

import frappe


def _create_index_if_missing(table_name, index_name, columns_sql):
	# Bỏ qua nếu bảng chưa migrate
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
		"tabSIS Discipline Record",
		"idx_sdr_date",
		"`date`",
	)
	_create_index_if_missing(
		"tabSIS Discipline Record",
		"idx_sdr_target_student_date",
		"`target_student`, `date`",
	)
	_create_index_if_missing(
		"tabSIS Discipline Record Student Entry",
		"idx_sdrse_student_level_parent",
		"`student_id`, `applied_level`, `parent`",
	)
