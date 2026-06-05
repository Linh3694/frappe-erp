"""
Thêm cột variant_index vào tabSIS_TKB_Gen_Result cho đa nghiệm (G2).
Cập nhật UNIQUE KEY để cho phép nhiều biến thể cùng slot.

Created: 2026-06-05
"""

import frappe


def execute():
	if not frappe.db.sql("SHOW TABLES LIKE 'tabSIS_TKB_Gen_Result'"):
		frappe.logger().warning("tabSIS_TKB_Gen_Result chưa tồn tại, bỏ qua patch variant_index")
		return

	cols = {r[0] for r in frappe.db.sql("SHOW COLUMNS FROM `tabSIS_TKB_Gen_Result`")}
	if "variant_index" not in cols:
		frappe.db.sql("""
			ALTER TABLE `tabSIS_TKB_Gen_Result`
			ADD COLUMN `variant_index` int NOT NULL DEFAULT 0 AFTER `period_priority`
		""")

	# Thay unique key cũ (không có variant_index) bằng key mới
	indexes = frappe.db.sql("SHOW INDEX FROM `tabSIS_TKB_Gen_Result` WHERE Key_name = 'uq_slot'", as_dict=True)
	if indexes:
		frappe.db.sql("ALTER TABLE `tabSIS_TKB_Gen_Result` DROP INDEX `uq_slot`")

	new_indexes = frappe.db.sql(
		"SHOW INDEX FROM `tabSIS_TKB_Gen_Result` WHERE Key_name = 'uq_slot_variant'",
		as_dict=True,
	)
	if not new_indexes:
		frappe.db.sql("""
			ALTER TABLE `tabSIS_TKB_Gen_Result`
			ADD UNIQUE KEY `uq_slot_variant`
			(`session_id`, `variant_index`, `class_id`, `day_of_week`, `timetable_column_id`)
		""")

	frappe.db.commit()
	frappe.logger().info("Patched tabSIS_TKB_Gen_Result with variant_index")
