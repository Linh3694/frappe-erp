"""
Tối ưu index cho `tabERP Time Attendance` — fix p95 chậm của
`erp.api.attendance.query.get_students_day_map`.

Vấn đề cũ:
- Index `idx_emp_date (employee_code, date)` không tối ưu cho pattern
  `WHERE employee_code IN (500 codes) AND date = X` — MySQL phải làm 500
  random lookups, mỗi lookup tới 1 page khác nhau.
- SELECT cần thêm các field check_in_time / check_out_time / total_check_ins
  → buộc 1 row lookup nữa, mà row chứa LONGTEXT raw_data → ít row/page → I/O lớn.

Chiến lược mới:
1. `idx_date_emp_cover (date, employee_code, check_in_time, check_out_time,
   total_check_ins)` — covering index cho `get_students_day_map`. Seek 1 lần
   tới `date`, range scan các `employee_code`, KHÔNG cần đọc row.
2. Giữ `idx_emp_date (employee_code, date)` — tối ưu cho
   `get_employee_attendance_range` (1 emp, range date).
3. Drop `idx_employee_code` và `idx_date` — đã bị duplicated bởi 2 composite
   ở trên (left-most prefix rule).

Created: 2026-05-11
"""

import frappe


TABLE = "tabERP Time Attendance"


def _index_exists(name: str) -> bool:
	rows = frappe.db.sql(
		f"SHOW INDEX FROM `{TABLE}` WHERE Key_name = %s",
		(name,),
		as_dict=True,
	)
	return bool(rows)


def _drop_index_if_exists(name: str) -> None:
	if not _index_exists(name):
		return
	try:
		frappe.db.sql(f"DROP INDEX `{name}` ON `{TABLE}`")
		frappe.db.commit()
		frappe.logger().info(f"Dropped index {name} on {TABLE}")
	except Exception as e:
		frappe.logger().warning(f"Could not drop index {name}: {e}")


def _create_index(name: str, columns: str) -> None:
	if _index_exists(name):
		frappe.logger().info(f"Index {name} already exists, skipping")
		return
	try:
		frappe.db.sql(f"CREATE INDEX `{name}` ON `{TABLE}` ({columns})")
		frappe.db.commit()
		frappe.logger().info(f"Created index {name} ({columns}) on {TABLE}")
	except Exception as e:
		if "Duplicate key name" in str(e):
			frappe.logger().info(f"Index {name} duplicate, skip")
		else:
			frappe.logger().error(f"Error creating index {name}: {e}")
			raise


def execute():
	if not frappe.db.table_exists("ERP Time Attendance"):
		frappe.logger().info(f"{TABLE} not exists, skip")
		return

	# Index chính cho daily map: covering, đặt date trước để gom rows cùng ngày
	_create_index(
		"idx_date_emp_cover",
		"date, employee_code, check_in_time, check_out_time, total_check_ins",
	)

	# Đảm bảo (employee_code, date) tồn tại cho range query
	if not _index_exists("idx_emp_date"):
		_create_index("idx_emp_date", "employee_code, date")

	# Dọn các index dư thừa (đã được left-most prefix bởi 2 composite ở trên)
	_drop_index_if_exists("idx_employee_code")
	_drop_index_if_exists("idx_date")
