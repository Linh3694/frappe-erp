"""
Tạo bảng raw SQL tabSIS_TKB_Gen_Result để lưu kết quả draft của auto-generation TKB.
Bảng này CÁCH LY hoàn toàn với hệ thống TKB đang dùng.

Created: 2026-03-27
"""

import frappe


def execute():
	if frappe.db.sql("SHOW TABLES LIKE 'tabSIS_TKB_Gen_Result'"):
		frappe.logger().info("Table tabSIS_TKB_Gen_Result already exists, skipping")
		return

	frappe.db.sql("""
		CREATE TABLE `tabSIS_TKB_Gen_Result` (
			`name` varchar(140) NOT NULL,
			`session_id` varchar(140) NOT NULL,
			`class_id` varchar(140) NOT NULL,
			`day_of_week` varchar(10) NOT NULL,
			`timetable_column_id` varchar(140) NOT NULL,
			`timetable_subject_id` varchar(140) DEFAULT NULL,
			`teacher_ids` text DEFAULT NULL,
			`room_id` varchar(140) DEFAULT NULL,
			`period_priority` int DEFAULT 0,
			`creation` datetime DEFAULT CURRENT_TIMESTAMP,
			PRIMARY KEY (`name`),
			INDEX `idx_session` (`session_id`),
			INDEX `idx_session_class` (`session_id`, `class_id`),
			UNIQUE KEY `uq_slot` (`session_id`, `class_id`, `day_of_week`, `timetable_column_id`)
		) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
	""")

	frappe.db.commit()
	frappe.logger().info("Successfully created table tabSIS_TKB_Gen_Result")
