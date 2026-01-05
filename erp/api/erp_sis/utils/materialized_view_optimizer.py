# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Materialized View Optimizer

Tối ưu sync cho Teacher Timetable và Student Timetable.

Performance improvements:
- Incremental sync thay vì full sync
- Bulk operations thay vì individual queries
- Smart batching để tránh timeout

Target: <200ms cho 50 rows
"""

import frappe
from typing import List, Dict
from datetime import timedelta


def sync_for_rows(row_ids: List[str]):
	"""
	Sync materialized views cho specific rows (incremental).
	
	Thay vì sync toàn bộ instance, chỉ sync affected rows.
	Performance: 10x faster than full sync
	
	Args:
		row_ids: List of SIS Timetable Instance Row IDs
	"""
	if not row_ids:
		return
	
	frappe.logger().info(f"🔄 Starting incremental sync for {len(row_ids)} rows")
	
	# Get row details với instance info
	# ⚡ FIX: Also select teacher_1_id, teacher_2_id for backward compatibility
	rows = frappe.db.sql("""
		SELECT 
			r.name, r.parent, r.date, r.day_of_week,
			r.timetable_column_id, r.subject_id, r.room_id,
			r.teacher_1_id, r.teacher_2_id,
			i.class_id, i.start_date, i.end_date, i.campus_id
		FROM `tabSIS Timetable Instance Row` r
		INNER JOIN `tabSIS Timetable Instance` i ON r.parent = i.name
		WHERE r.name IN ({})
	""".format(','.join(['%s'] * len(row_ids))),
	tuple(row_ids),
	as_dict=True)
	
	# Get teachers from child table for each row
	teacher_map = {}  # row_id -> list of teacher_ids
	if rows:
		row_names = [r.name for r in rows]
		teacher_children = frappe.db.sql("""
			SELECT parent, teacher_id
			FROM `tabSIS Timetable Instance Row Teacher`
			WHERE parent IN ({})
			ORDER BY parent ASC, sort_order ASC
		""".format(','.join(['%s'] * len(row_names))),
		tuple(row_names),
		as_dict=True)
		
		for child in teacher_children:
			if child.parent not in teacher_map:
				teacher_map[child.parent] = []
			teacher_map[child.parent].append(child.teacher_id)
	
	# Attach teachers to rows
	# ⚡ FIX: Fallback to teacher_1_id, teacher_2_id if child table is empty
	for row in rows:
		teachers_from_child = teacher_map.get(row.name, [])
		
		if teachers_from_child:
			# Use teachers from child table (new format)
			row['teachers'] = teachers_from_child
		else:
			# Fallback: Use teacher_1_id, teacher_2_id (old format)
			fallback_teachers = []
			if row.get('teacher_1_id'):
				fallback_teachers.append(row['teacher_1_id'])
			if row.get('teacher_2_id'):
				fallback_teachers.append(row['teacher_2_id'])
			row['teachers'] = fallback_teachers
			
			if fallback_teachers:
				frappe.logger().info(f"📋 Row {row.name}: Using fallback teachers {fallback_teachers}")
	
	if not rows:
		frappe.logger().info("⚠️  No rows found to sync")
		return
	
	frappe.logger().info(f"📊 Processing {len(rows)} rows")
	
	# Sync Teacher Timetable
	teacher_count = sync_teacher_timetable_for_rows(rows)
	frappe.logger().info(f"✅ Teacher Timetable: {teacher_count} entries synced")
	
	# ⚡ DISABLED: Student Timetable sync removed (not used, wastes 50% performance)
	# Student Timetable table không được dùng trong hệ thống:
	# - Frontend không hiển thị
	# - Backend APIs không query
	# - Parent Portal query trực tiếp từ Timetable Pattern
	# student_count = sync_student_timetable_for_rows(rows)
	# frappe.logger().info(f"✅ Student Timetable: {student_count} entries synced")
	student_count = 0
	
	# Commit
	frappe.db.commit()
	
	frappe.logger().info(f"🎉 Incremental sync complete: {teacher_count}T + {student_count}S")


def sync_teacher_timetable_for_rows(rows: List[Dict]) -> int:
	"""
	Sync SIS Teacher Timetable cho specific rows.
	
	⚡ FIX (2026-01-05): Xóa entries cũ trước khi thêm mới
	
	Logic:
	1. XÓA entries cũ cho các rows đang sync (để remove orphaned entries)
	2. For pattern rows (date=NULL): Generate entries for all matching dates
	3. For override rows (date!=NULL): Generate entry for specific date
	
	Returns:
		int: Number of entries processed
	"""
	if not rows:
		return 0
	
	# ⚡ STEP 1: Xóa entries cũ cho các rows đang sync
	# Điều này đảm bảo orphaned entries (teachers đã bị remove) được xóa
	_delete_old_entries_for_rows(rows)
	
	# STEP 2: Tạo entries mới
	entries_to_upsert = []
	
	for row in rows:
		# Determine dates to sync
		if row.date:
			# Override row: specific date only
			dates = [row.date]
		else:
			# Pattern row: all dates matching day_of_week in instance range
			dates = calculate_all_dates_for_pattern_row(
				row.day_of_week,
				row.start_date,
				row.end_date
			)
		
		# Create entries for each teacher (from child table)
		teachers = row.get('teachers', [])
		for teacher_id in teachers:
			if not teacher_id:
				continue
			
			for date in dates:
				entries_to_upsert.append({
					"teacher_id": teacher_id,
					"class_id": row.class_id,
					"date": date,
					"day_of_week": row.day_of_week,
					"timetable_column_id": row.timetable_column_id,
					"subject_id": row.subject_id,
					"room_id": row.room_id,
					"timetable_instance_id": row.parent
				})
	
	# Bulk upsert
	if entries_to_upsert:
		bulk_upsert_teacher_timetable(entries_to_upsert)
	
	return len(entries_to_upsert)


def _delete_old_entries_for_rows(rows: List[Dict]):
	"""
	⚡ NEW (2026-01-05): Xóa entries cũ trong Teacher Timetable cho các rows đang sync.
	
	Điều này đảm bảo:
	1. Orphaned entries (teachers đã bị remove khỏi row) được xóa
	2. Entries được recreate fresh từ current teachers
	
	Logic:
	- Pattern rows (date=NULL): Xóa entries cho day_of_week + timetable_column_id trong range
	- Override rows (date!=NULL): Xóa entries cho specific date + timetable_column_id
	"""
	if not rows:
		return
	
	# Group rows by instance for batch delete
	for row in rows:
		instance_id = row.parent
		day_of_week = row.day_of_week
		column_id = row.timetable_column_id
		
		if row.date:
			# Override row: xóa entries cho specific date
			frappe.db.sql("""
				DELETE FROM `tabSIS Teacher Timetable`
				WHERE timetable_instance_id = %s
				  AND day_of_week = %s
				  AND timetable_column_id = %s
				  AND date = %s
			""", (instance_id, day_of_week, column_id, row.date))
		else:
			# Pattern row: xóa entries cho day_of_week + column trong range
			# Chỉ xóa entries trong date range của instance
			frappe.db.sql("""
				DELETE FROM `tabSIS Teacher Timetable`
				WHERE timetable_instance_id = %s
				  AND day_of_week = %s
				  AND timetable_column_id = %s
				  AND date BETWEEN %s AND %s
			""", (instance_id, day_of_week, column_id, row.start_date, row.end_date))


def sync_student_timetable_for_rows(rows: List[Dict]) -> int:
	"""
	Sync SIS Student Timetable cho specific rows.
	
	Similar logic to teacher timetable, but for students in class.
	
	Returns:
		int: Number of entries processed
	"""
	# Get unique classes from rows
	class_ids = list(set(row.class_id for row in rows))
	
	if not class_ids:
		return 0
	
	# Get students for these classes
	students_by_class = {}
	for class_id in class_ids:
		students = frappe.get_all(
			"SIS Class Student",
			filters={"class_id": class_id},
			pluck="student_id"
		)
		students_by_class[class_id] = students
	
	entries_to_upsert = []
	
	for row in rows:
		students = students_by_class.get(row.class_id, [])
		
		if not students:
			continue
		
		# Determine dates
		if row.date:
			dates = [row.date]
		else:
			dates = calculate_all_dates_for_pattern_row(
				row.day_of_week,
				row.start_date,
				row.end_date
			)
		
		# Create entries for each student
		for student_id in students:
			for date in dates:
				entries_to_upsert.append({
					"student_id": student_id,
					"class_id": row.class_id,
					"date": date,
					"day_of_week": row.day_of_week,
					"timetable_column_id": row.timetable_column_id,
					"subject_id": row.subject_id,
					"room_id": row.room_id,
					"timetable_instance_id": row.parent
				})
	
	# Bulk upsert
	if entries_to_upsert:
		bulk_upsert_student_timetable(entries_to_upsert)
	
	return len(entries_to_upsert)


def calculate_all_dates_for_pattern_row(day_of_week: str, start_date, end_date) -> List:
	"""
	Calculate all dates matching day_of_week trong instance range.
	
	Args:
		day_of_week: "mon", "tue", etc.
		start_date: Instance start date
		end_date: Instance end date
	
	Returns:
		List of date objects
	"""
	day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
	target_weekday = day_map.get(day_of_week.lower())
	
	if target_weekday is None:
		return []
	
	# Ensure dates are date objects
	if isinstance(start_date, str):
		start_date = frappe.utils.getdate(start_date)
	if isinstance(end_date, str):
		end_date = frappe.utils.getdate(end_date)
	
	# Find first occurrence
	current = start_date
	days_ahead = target_weekday - current.weekday()
	if days_ahead < 0:
		days_ahead += 7
	
	first_occurrence = current + timedelta(days=days_ahead)
	
	# Collect all dates
	dates = []
	check_date = first_occurrence
	
	while check_date <= end_date:
		dates.append(check_date)
		check_date += timedelta(days=7)
	
	return dates


def bulk_upsert_teacher_timetable(entries: List[Dict]):
	"""
	Bulk insert/update Teacher Timetable entries.
	
	Performance: 100x faster than individual inserts.
	Uses MySQL ON DUPLICATE KEY UPDATE for efficiency.
	"""
	if not entries:
		return
	
	# Group entries by unique key to deduplicate
	by_key = {}
	for entry in entries:
		key = (
			entry["teacher_id"],
			entry["class_id"],
			entry["date"],
			entry["timetable_column_id"]
		)
		by_key[key] = entry
	
	entries = list(by_key.values())
	
	# Batch insert with ON DUPLICATE KEY UPDATE
	chunk_size = 100
	for i in range(0, len(entries), chunk_size):
		chunk = entries[i:i + chunk_size]
		
		values = []
		params = []
		
		for entry in chunk:
			values.append("(%s, %s, %s, %s, %s, %s, %s, %s)")
			params.extend([
				entry["teacher_id"],
				entry["class_id"],
				entry["date"],
				entry["day_of_week"],
				entry["timetable_column_id"],
				entry["subject_id"],
				entry.get("room_id"),
				entry["timetable_instance_id"]
			])
		
		# ⚡ FIX: Generate names for new entries
		# Add name field to each value tuple
		values_with_names = []
		params_with_names = []
		for val_idx in range(0, len(params), 8):  # 8 fields per entry
			# Generate unique name: teacher_date_column
			teacher_id = params[val_idx]
			date_val = params[val_idx + 2]
			column_id = params[val_idx + 4]
			name = f"{teacher_id}_{date_val}_{column_id}"
			
			# Prepend name to the value list
			params_with_names.extend([
				name,
				params[val_idx],     # teacher_id
				params[val_idx + 1], # class_id
				params[val_idx + 2], # date
				params[val_idx + 3], # day_of_week
				params[val_idx + 4], # timetable_column_id
				params[val_idx + 5], # subject_id
				params[val_idx + 6], # room_id
				params[val_idx + 7]  # timetable_instance_id
			])
			values_with_names.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s)")
		
		# Execute bulk upsert with name field
		frappe.db.sql(f"""
			INSERT INTO `tabSIS Teacher Timetable`
			(name, teacher_id, class_id, date, day_of_week, timetable_column_id,
			 subject_id, room_id, timetable_instance_id)
			VALUES {', '.join(values_with_names)}
			ON DUPLICATE KEY UPDATE
				subject_id = VALUES(subject_id),
				room_id = VALUES(room_id),
				timetable_instance_id = VALUES(timetable_instance_id)
		""", tuple(params_with_names))


def bulk_upsert_student_timetable(entries: List[Dict]):
	"""
	Bulk insert/update Student Timetable entries.
	
	Similar to teacher timetable but for students.
	"""
	if not entries:
		return
	
	# Deduplicate by key
	by_key = {}
	for entry in entries:
		key = (
			entry["student_id"],
			entry["class_id"],
			entry["date"],
			entry["timetable_column_id"]
		)
		by_key[key] = entry
	
	entries = list(by_key.values())
	
	# Batch insert
	chunk_size = 100
	for i in range(0, len(entries), chunk_size):
		chunk = entries[i:i + chunk_size]
		
		values = []
		params = []
		
		for entry in chunk:
			# ⚡ FIX: Generate unique name for each entry
			student_id = entry["student_id"]
			date_val = entry["date"]
			column_id = entry["timetable_column_id"]
			name = f"{student_id}_{date_val}_{column_id}"
			
			values.append("(%s, %s, %s, %s, %s, %s, %s, %s, %s)")
			params.extend([
				name,  # ⚡ ADD name field
				entry["student_id"],
				entry["class_id"],
				entry["date"],
				entry["day_of_week"],
				entry["timetable_column_id"],
				entry["subject_id"],
				entry.get("room_id"),
				entry["timetable_instance_id"]
			])
		
		frappe.db.sql(f"""
			INSERT INTO `tabSIS Student Timetable`
			(name, student_id, class_id, date, day_of_week, timetable_column_id,
			 subject_id, room_id, timetable_instance_id)
			VALUES {', '.join(values)}
			ON DUPLICATE KEY UPDATE
				subject_id = VALUES(subject_id),
				room_id = VALUES(room_id),
				timetable_instance_id = VALUES(timetable_instance_id)
		""", tuple(params))

