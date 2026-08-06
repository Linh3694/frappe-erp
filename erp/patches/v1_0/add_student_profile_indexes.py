"""
Index cho hồ sơ học sinh (get_student_profile / resolve_student_access).

Query nóng:
  - Class Student / Student Subject theo student_id (+ năm học)
  - Subject Assignment theo (class_id, actual_subject_id, school_year_id)
  - Timetable Instance Row theo teacher (fallback quyền GV bộ môn)

Không có index student_id → full scan trên bảng lớn (~mọi lần mở hồ sơ).
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

	frappe.db.sql(f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns_sql})")
	frappe.db.commit()
	frappe.logger().info(f"Created index {index_name} on {table_name}")


def execute():
	_create_index_if_missing(
		"tabSIS Class Student",
		"idx_scs_student_year",
		"`student_id`, `school_year_id`",
	)
	_create_index_if_missing(
		"tabSIS Student Subject",
		"idx_sss_student_class",
		"`student_id`, `class_id`",
	)
	_create_index_if_missing(
		"tabSIS Subject Assignment",
		"idx_ssa_class_subject_year",
		"`class_id`, `actual_subject_id`, `school_year_id`",
	)
	_create_index_if_missing(
		"tabSIS Timetable Instance Row",
		"idx_stir_teacher_1",
		"`teacher_1_id`",
	)
	_create_index_if_missing(
		"tabSIS Timetable Instance Row",
		"idx_stir_teacher_2",
		"`teacher_2_id`",
	)
