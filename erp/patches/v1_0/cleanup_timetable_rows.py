# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Migration Script: Cleanup Timetable Rows

Mục tiêu:
1. Tìm và xóa duplicate pattern rows
2. Tìm và xóa orphan override rows (không có parent pattern)
3. Log chi tiết để review

Run: bench --site admin.sis.wellspring.edu.vn migrate
"""

import frappe
from frappe import _


def execute():
	"""Main migration function"""
	frappe.logger().info("=" * 80)
	frappe.logger().info("Starting Timetable Rows Cleanup Migration")
	frappe.logger().info("=" * 80)
	
	stats = {
		"total_instances": 0,
		"duplicate_pattern_rows": 0,
		"orphan_override_rows": 0,
		"failed_instances": 0
	}
	
	# Get all timetable instances
	instances = frappe.get_all("SIS Timetable Instance", pluck="name")
	stats["total_instances"] = len(instances)
	
	frappe.logger().info(f"Processing {len(instances)} timetable instances")
	
	# Process each instance
	for instance_id in instances:
		try:
			result = cleanup_instance_rows(instance_id)
			stats["duplicate_pattern_rows"] += result["duplicates_removed"]
			stats["orphan_override_rows"] += result["orphans_removed"]
		except Exception as e:
			frappe.logger().error(f"Failed to process instance {instance_id}: {str(e)}")
			stats["failed_instances"] += 1
			continue
	
	# Commit
	frappe.db.commit()
	
	# Log summary
	frappe.logger().info("=" * 80)
	frappe.logger().info("Timetable Rows Cleanup Complete")
	frappe.logger().info(f"  - Instances processed: {stats['total_instances']}")
	frappe.logger().info(f"  - Duplicate pattern rows removed: {stats['duplicate_pattern_rows']}")
	frappe.logger().info(f"  - Orphan override rows removed: {stats['orphan_override_rows']}")
	frappe.logger().info(f"  - Failed instances: {stats['failed_instances']}")
	frappe.logger().info("=" * 80)


def cleanup_instance_rows(instance_id):
	"""
	Cleanup rows for a single instance
	
	Returns:
		dict: {"duplicates_removed": int, "orphans_removed": int}
	"""
	result = {
		"duplicates_removed": 0,
		"orphans_removed": 0
	}
	
	# Step 1: Clean duplicate pattern rows
	duplicates = cleanup_duplicate_pattern_rows(instance_id)
	result["duplicates_removed"] = duplicates
	
	# Step 2: Clean orphan override rows
	orphans = cleanup_orphan_override_rows(instance_id)
	result["orphans_removed"] = orphans
	
	return result


def cleanup_duplicate_pattern_rows(instance_id):
	"""
	Find and remove duplicate pattern rows.
	
	Duplicate: Same (subject_id, day_of_week, timetable_column_id) with date=NULL
	
	Strategy:
	- Group by (subject, day, column)
	- If > 1 row: Keep row with teacher, delete others
	"""
	# Get all pattern rows (date IS NULL)
	pattern_rows = frappe.get_all(
		"SIS Timetable Instance Row",
		fields=["name", "subject_id", "day_of_week", "timetable_column_id", 
		        "teacher_1_id", "teacher_2_id"],
		filters={
			"parent": instance_id,
			"date": ["is", "not set"]
		}
	)
	
	if not pattern_rows:
		return 0
	
	# Group by key
	rows_by_key = {}
	for row in pattern_rows:
		key = (row.subject_id, row.day_of_week, row.timetable_column_id)
		if key not in rows_by_key:
			rows_by_key[key] = []
		rows_by_key[key].append(row)
	
	# Find duplicates
	deleted_count = 0
	
	for key, rows in rows_by_key.items():
		if len(rows) <= 1:
			continue  # No duplicates
		
		subject_id, day, column = key
		
		# Sort: rows with teacher first, then by name (newer = higher number)
		rows_sorted = sorted(
			rows,
			key=lambda r: (
				not bool(r.teacher_1_id or r.teacher_2_id),  # False (has teacher) comes first
				-(int(r.name.split('-')[-1]) if '-' in r.name and r.name.split('-')[-1].isdigit() else 0)
			)
		)
		
		# Keep first, delete rest
		keep_row = rows_sorted[0]
		frappe.logger().info(
			f"Instance {instance_id}: Keeping row {keep_row.name} "
			f"(teacher={keep_row.teacher_1_id or keep_row.teacher_2_id or 'none'})"
		)
		
		for row in rows_sorted[1:]:
			try:
				frappe.delete_doc(
					"SIS Timetable Instance Row",
					row.name,
					ignore_permissions=True,
					force=True
				)
				deleted_count += 1
				frappe.logger().info(f"  ✓ Deleted duplicate row {row.name}")
			except Exception as e:
				frappe.logger().error(f"  ✗ Failed to delete row {row.name}: {str(e)}")
	
	return deleted_count


def cleanup_orphan_override_rows(instance_id):
	"""
	Find and remove orphan override rows.
	
	Orphan: Override row (date != NULL) without matching pattern row
	
	A valid override must have a pattern row with:
	- Same (subject_id, day_of_week, timetable_column_id)
	- date IS NULL
	"""
	# Get all override rows (date IS NOT NULL)
	override_rows = frappe.get_all(
		"SIS Timetable Instance Row",
		fields=["name", "subject_id", "day_of_week", "timetable_column_id", "date"],
		filters={
			"parent": instance_id,
			"date": ["is", "set"]
		}
	)
	
	if not override_rows:
		return 0
	
	# Get all pattern row keys for quick lookup
	pattern_keys = set()
	pattern_rows = frappe.get_all(
		"SIS Timetable Instance Row",
		fields=["subject_id", "day_of_week", "timetable_column_id"],
		filters={
			"parent": instance_id,
			"date": ["is", "not set"]
		}
	)
	
	for row in pattern_rows:
		key = (row.subject_id, row.day_of_week, row.timetable_column_id)
		pattern_keys.add(key)
	
	# Check each override row
	deleted_count = 0
	
	for override_row in override_rows:
		key = (override_row.subject_id, override_row.day_of_week, override_row.timetable_column_id)
		
		if key not in pattern_keys:
			# Orphan: no parent pattern row
			try:
				frappe.delete_doc(
					"SIS Timetable Instance Row",
					override_row.name,
					ignore_permissions=True,
					force=True
				)
				deleted_count += 1
				frappe.logger().info(
					f"Instance {instance_id}: Deleted orphan override row {override_row.name} "
					f"(date={override_row.date})"
				)
			except Exception as e:
				frappe.logger().error(
					f"Instance {instance_id}: Failed to delete orphan {override_row.name}: {str(e)}"
				)
	
	return deleted_count

