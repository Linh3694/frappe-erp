# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SISTeacherTimetable(Document):
	# begin: auto-generated types
	# This file will be overwritten when re-running `bench migrate`
	# end: auto-generated types

	pass


def create_indexes():
	"""
	⚡ Tạo composite index để tối ưu DELETE queries.
	
	Index này giúp query DELETE trong materialized_view_optimizer.py chạy nhanh hơn 10-100x.
	
	Gọi function này một lần sau khi migrate:
	    bench execute erp.sis.doctype.sis_teacher_timetable.sis_teacher_timetable.create_indexes
	"""
	frappe.logger().info("🔧 Creating indexes for SIS Teacher Timetable...")
	
	# Composite index cho DELETE query pattern:
	# WHERE timetable_instance_id = X AND day_of_week = Y AND timetable_column_id = Z AND date BETWEEN A AND B
	try:
		frappe.db.sql("""
			CREATE INDEX IF NOT EXISTS idx_teacher_timetable_delete_pattern
			ON `tabSIS Teacher Timetable` (timetable_instance_id, day_of_week, timetable_column_id, date)
		""")
		frappe.logger().info("✅ Created index: idx_teacher_timetable_delete_pattern")
	except Exception as e:
		# Index có thể đã tồn tại
		frappe.logger().warning(f"⚠️ Could not create idx_teacher_timetable_delete_pattern: {e}")
	
	# Index cho query lấy entries theo teacher + date range
	try:
		frappe.db.sql("""
			CREATE INDEX IF NOT EXISTS idx_teacher_timetable_teacher_date
			ON `tabSIS Teacher Timetable` (teacher_id, date)
		""")
		frappe.logger().info("✅ Created index: idx_teacher_timetable_teacher_date")
	except Exception as e:
		frappe.logger().warning(f"⚠️ Could not create idx_teacher_timetable_teacher_date: {e}")
	
	frappe.db.commit()
	frappe.logger().info("🎉 Index creation complete!")
