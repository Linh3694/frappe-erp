"""
Index cho tabSIS Class Log Student — sự cố chậm 16-17h (2026-08-06).

Slow log / query nóng:
  SELECT name, docstatus FROM `tabSIS Class Log Student`
  WHERE class_student_id = ? ORDER BY modified DESC

Bảng ~280k rows; không có index trên class_student_id → dùng index `modified` rồi filter.
DocType search_index chỉ tạo index 1 cột — cần composite cho ORDER BY modified.
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
	# WHERE class_student_id = ? ORDER BY modified
	_create_index_if_missing(
		"tabSIS Class Log Student",
		"idx_cls_log_stu_class_student_modified",
		"`class_student_id`, `modified`",
	)
	# student_id đứng một mình: uq_subject_student không cover (leftmost = subject_id)
	_create_index_if_missing(
		"tabSIS Class Log Student",
		"idx_cls_log_stu_student_id",
		"`student_id`",
	)
