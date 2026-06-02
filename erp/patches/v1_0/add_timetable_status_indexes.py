"""
Index cho truy vấn trạng thái tiết trên lưới TKB (điểm danh + sổ đầu bài).

- SIS Class Attendance: (class_id, date)
- SIS Class Log Subject: (timetable_instance_id, log_date)
"""

import frappe


def _create_index_if_missing(table_name, index_name, columns_sql):
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

	frappe.db.sql(f"CREATE INDEX {index_name} ON `{table_name}` ({columns_sql})")
	frappe.db.commit()
	frappe.logger().info(f"Created index {index_name} on {table_name}")


def execute():
	_create_index_if_missing(
		"tabSIS Class Attendance",
		"idx_sis_att_class_date",
		"class_id, date",
	)
	_create_index_if_missing(
		"tabSIS Class Log Subject",
		"idx_sis_clslog_inst_date",
		"timetable_instance_id, log_date",
	)
