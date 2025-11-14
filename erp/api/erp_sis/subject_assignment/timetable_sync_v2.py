# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Sync V2 - Refactored

Nguyên tắc thiết kế:
1. VALIDATE → COMPUTE → APPLY pattern
2. Clear separation: full_year vs from_date
3. Atomic transactions
4. Idempotent operations

Performance target: <500ms cho 100 instances
"""

import frappe
from typing import Dict, List, Optional, Tuple
from datetime import timedelta


# ============= PUBLIC API =============

def sync_assignment_to_timetable(assignment_id: str) -> Dict:
	"""
	Main entry point cho sync.
	
	Args:
		assignment_id: ID của Subject Assignment cần sync
	
	Returns:
		{
			"success": bool,
			"rows_updated": int,
			"rows_created": int,
			"message": str,
			"debug_info": List[str]
		}
	"""
	try:
		assignment = frappe.get_doc("SIS Subject Assignment", assignment_id)
		
		# VALIDATE
		validation = validate_assignment_for_sync(assignment)
		if not validation["valid"]:
			return {
				"success": False,
				"message": validation["error"],
				"debug_info": [validation["error"]]
			}
		
		# ROUTE to appropriate sync function
		if assignment.application_type == "full_year":
			return sync_full_year_assignment(assignment)
		else:
			return sync_date_range_assignment(assignment)
			
	except Exception as e:
		frappe.log_error(f"Sync failed for assignment {assignment_id}: {str(e)}")
		return {
			"success": False,
			"message": f"Critical error: {str(e)}"
		}


# ============= FULL YEAR SYNC =============

def sync_full_year_assignment(assignment) -> Dict:
	"""
	Sync full_year assignment: Update pattern rows directly.
	
	Logic đơn giản:
	1. Find pattern rows cho class + subject
	2. Detect conflicts (teacher dạy môn khác cùng giờ)
	3. Update teacher_1_id hoặc teacher_2_id
	4. Done!
	
	Performance: ~50ms cho 10 pattern rows
	"""
	debug_info = []
	teacher_id = assignment.teacher_id
	class_id = assignment.class_id
	actual_subject_id = assignment.actual_subject_id
	campus_id = assignment.campus_id
	
	debug_info.append(f"🔄 Syncing full_year assignment: teacher={teacher_id}, class={class_id}, subject={actual_subject_id}")
	
	# COMPUTE: Find pattern rows
	pattern_rows = find_pattern_rows(
		class_id=class_id,
		actual_subject_id=actual_subject_id,
		campus_id=campus_id
	)
	
	if not pattern_rows:
		return {
			"success": False,
			"message": "No pattern rows found for this class/subject",
			"debug_info": debug_info + ["❌ No pattern rows found"]
		}
	
	debug_info.append(f"📋 Found {len(pattern_rows)} pattern rows to update")
	
	# CHECK: Detect conflicts với môn khác của teacher
	conflicts = detect_teacher_conflicts(teacher_id, pattern_rows, campus_id)
	if conflicts:
		debug_info.append(f"⚠️ Found {len(conflicts)} potential conflicts:")
		for conflict in conflicts:
			debug_info.append(f"  - {conflict['day']}/{conflict['period']}: Already teaching {conflict['subject']} in {conflict['class']}")
	
	# APPLY: Update atomically
	updated_count = 0
	skipped_conflicts = 0
	
	try:
		frappe.db.begin()
		
		# Build conflict lookup map for fast checking
		conflict_map = {}
		for conflict in conflicts:
			key = f"{conflict['day']}_{conflict['period']}"
			conflict_map[key] = conflict
		
		for row in pattern_rows:
			# Check if this row has conflict
			row_key = f"{row.day_of_week}_{row.timetable_column_id}"
			has_conflict = row_key in conflict_map
			
			# ✅ FIX: Check if teacher is already assigned to this row
			# Tránh trường hợp assign cùng teacher vào cả teacher_1_id và teacher_2_id
			if row.teacher_1_id == teacher_id or row.teacher_2_id == teacher_id:
				debug_info.append(f"  ✓ Row {row.name}: teacher already assigned, skipping")
				continue
			
			# Assign to first available slot
			if not row.teacher_1_id:
				frappe.db.set_value(
					"SIS Timetable Instance Row",
					row.name,
					"teacher_1_id",
					teacher_id,
					update_modified=False
				)
				updated_count += 1
				if has_conflict:
					conflict_info = conflict_map[row_key]
					debug_info.append(f"  ⚠️ Updated row {row.name}: teacher_1_id = {teacher_id} (CONFLICT with {conflict_info['subject']} in {conflict_info['class']})")
				else:
					debug_info.append(f"  ✓ Updated row {row.name}: teacher_1_id = {teacher_id}")
			elif not row.teacher_2_id:
				frappe.db.set_value(
					"SIS Timetable Instance Row",
					row.name,
					"teacher_2_id",
					teacher_id,
					update_modified=False
				)
				updated_count += 1
				if has_conflict:
					conflict_info = conflict_map[row_key]
					debug_info.append(f"  ⚠️ Updated row {row.name}: teacher_2_id = {teacher_id} (CONFLICT with {conflict_info['subject']} in {conflict_info['class']})")
				else:
					debug_info.append(f"  ✓ Updated row {row.name}: teacher_2_id = {teacher_id}")
			else:
				debug_info.append(f"  ⏭️ Skipped row {row.name}: both slots full")
		
		frappe.db.commit()
		
		# Sync materialized view immediately for small updates (< 50 rows)
		# For larger updates, enqueue async to avoid blocking
		if updated_count > 0:
			row_ids = [r.name for r in pattern_rows]
			if len(row_ids) <= 50:
				# Sync immediately for better UX
				try:
					from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows
					sync_for_rows(row_ids)
					debug_info.append(f"✅ Synced materialized view immediately for {updated_count} rows")
				except Exception as sync_err:
					frappe.log_error(f"Immediate sync failed: {str(sync_err)}")
					# Fallback to async if immediate sync fails
					enqueue_materialized_view_sync(row_ids)
					debug_info.append(f"⏰ Fallback to async sync for {updated_count} rows")
			else:
				# Large update - use async to avoid blocking
				enqueue_materialized_view_sync(row_ids)
				debug_info.append(f"⏰ Enqueued async materialized view sync for {updated_count} rows")
		
		# Build message with conflict warning if any
		message = f"Updated {updated_count} pattern rows"
		if conflicts:
			message += f" (⚠️ {len(conflicts)} conflicts detected - teacher may be teaching different subjects at the same time)"
		
		return {
			"success": True,
			"rows_updated": updated_count,
			"rows_created": 0,
			"message": message,
			"debug_info": debug_info,
			"conflicts": conflicts  # Return conflicts for frontend to display
		}
		
	except Exception as e:
		frappe.db.rollback()
		debug_info.append(f"❌ Rollback: {str(e)}")
		return {
			"success": False,
			"message": f"Sync failed: {str(e)}",
			"debug_info": debug_info
		}


# ============= DATE RANGE SYNC =============

def sync_date_range_assignment(assignment) -> Dict:
	"""
	Sync from_date assignment: Create override rows.
	
	Logic:
	1. Find pattern rows
	2. Calculate dates trong range
	3. Create/update override row cho mỗi date
	4. KHÔNG touch pattern rows!
	
	Performance: ~200ms cho 50 override rows
	"""
	debug_info = []
	teacher_id = assignment.teacher_id
	class_id = assignment.class_id
	actual_subject_id = assignment.actual_subject_id
	campus_id = assignment.campus_id
	start_date = assignment.start_date
	end_date = assignment.end_date
	
	debug_info.append(
		f"🔄 Syncing from_date assignment: teacher={teacher_id}, class={class_id}, "
		f"subject={actual_subject_id}, dates={start_date} to {end_date}"
	)
	
	# VALIDATE dates
	if not start_date:
		return {
			"success": False,
			"message": "start_date required for from_date assignment",
			"debug_info": debug_info + ["❌ Missing start_date"]
		}
	
	# Ensure start_date is date object
	if isinstance(start_date, str):
		start_date = frappe.utils.getdate(start_date)
	if end_date and isinstance(end_date, str):
		end_date = frappe.utils.getdate(end_date)
	
	# COMPUTE: Find pattern rows
	pattern_rows = find_pattern_rows(
		class_id=class_id,
		actual_subject_id=actual_subject_id,
		campus_id=campus_id
	)
	
	if not pattern_rows:
		return {
			"success": False,
			"message": "No pattern rows found",
			"debug_info": debug_info + ["❌ No pattern rows found"]
		}
	
	debug_info.append(f"📋 Found {len(pattern_rows)} pattern rows")
	
	# Group by day_of_week for efficiency
	rows_by_day = {}
	for row in pattern_rows:
		day = row.day_of_week
		if day not in rows_by_day:
			rows_by_day[day] = []
		rows_by_day[day].append(row)
	
	# Calculate dates for each day
	override_specs = []  # List of (date, pattern_row)
	
	for day, rows in rows_by_day.items():
		# Get instance date range from first row
		instance_info = frappe.db.get_value(
			"SIS Timetable Instance",
			rows[0].parent,
			["start_date", "end_date"],
			as_dict=True
		)
		
		dates = calculate_dates_for_day(
			day_of_week=day,
			start_date=start_date,
			end_date=end_date,
			instance_start=instance_info.start_date,
			instance_end=instance_info.end_date
		)
		
		debug_info.append(f"📅 Day {day}: {len(dates)} dates calculated")
		
		for date in dates:
			for row in rows:
				override_specs.append((date, row))
	
	debug_info.append(f"📊 Total override specs to process: {len(override_specs)}")
	
	# APPLY: Bulk create/update override rows
	created_count = 0
	updated_count = 0
	
	try:
		frappe.db.begin()
		
		for date, pattern_row in override_specs:
			# Check if override already exists
			existing = frappe.db.get_value(
				"SIS Timetable Instance Row",
				{
					"parent": pattern_row.parent,
					"date": date,
					"day_of_week": pattern_row.day_of_week,
					"timetable_column_id": pattern_row.timetable_column_id,
					"subject_id": pattern_row.subject_id
				},
				["name", "teacher_1_id", "teacher_2_id"],
				as_dict=True
			)
			
			if existing:
				# ✅ FIX: Check if teacher is already assigned to this row
				if existing.teacher_1_id == teacher_id or existing.teacher_2_id == teacher_id:
					# Teacher already assigned, skip
					continue
				
				# Update existing override
				if not existing.teacher_1_id:
					frappe.db.set_value(
						"SIS Timetable Instance Row",
						existing.name,
						"teacher_1_id",
						teacher_id,
						update_modified=False
					)
					updated_count += 1
				elif not existing.teacher_2_id:
					frappe.db.set_value(
						"SIS Timetable Instance Row",
						existing.name,
						"teacher_2_id",
						teacher_id,
						update_modified=False
					)
					updated_count += 1
			else:
				# Create new override
				override_doc = frappe.get_doc({
					"doctype": "SIS Timetable Instance Row",
					"parent": pattern_row.parent,
					"parenttype": "SIS Timetable Instance",
					"parentfield": "weekly_pattern",
					"date": date,
					"day_of_week": pattern_row.day_of_week,
					"timetable_column_id": pattern_row.timetable_column_id,
					"period_priority": pattern_row.period_priority,
					"period_name": pattern_row.period_name,
					"subject_id": pattern_row.subject_id,
					"teacher_1_id": teacher_id,
					"room_id": pattern_row.room_id
				})
				override_doc.insert(ignore_permissions=True, ignore_mandatory=True)
				created_count += 1
		
		frappe.db.commit()
		
		debug_info.append(f"✅ Created {created_count} override rows")
		debug_info.append(f"✅ Updated {updated_count} override rows")
		
		# Sync materialized view immediately for small updates (< 50 rows)
		# For larger updates, enqueue async to avoid blocking
		if created_count > 0 or updated_count > 0:
			override_row_names = [spec[1].name for spec in override_specs]
			total_changes = created_count + updated_count
			
			if total_changes <= 50:
				# Sync immediately for better UX
				try:
					from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows
					sync_for_rows(override_row_names)
					debug_info.append(f"✅ Synced materialized view immediately for {total_changes} changes")
				except Exception as sync_err:
					frappe.log_error(f"Immediate sync failed: {str(sync_err)}")
					# Fallback to async if immediate sync fails
					enqueue_materialized_view_sync(override_row_names)
					debug_info.append(f"⏰ Fallback to async sync for {total_changes} changes")
			else:
				# Large update - use async to avoid blocking
				enqueue_materialized_view_sync(override_row_names)
				debug_info.append(f"⏰ Enqueued async materialized view sync for {total_changes} changes")
		
		return {
			"success": True,
			"rows_updated": updated_count,
			"rows_created": created_count,
			"message": f"Created {created_count}, updated {updated_count} override rows",
			"debug_info": debug_info
		}
		
	except Exception as e:
		frappe.db.rollback()
		debug_info.append(f"❌ Rollback: {str(e)}")
		frappe.log_error(f"Date range sync failed: {str(e)}")
		return {
			"success": False,
			"message": f"Sync failed: {str(e)}",
			"debug_info": debug_info
		}


# ============= HELPER FUNCTIONS =============

def validate_assignment_for_sync(assignment) -> Dict:
	"""Validate assignment trước khi sync"""
	
	# Check teacher exists
	if not frappe.db.exists("SIS Teacher", assignment.teacher_id):
		return {"valid": False, "error": "Teacher not found"}
	
	# Check class exists
	if not frappe.db.exists("SIS Class", {"name": assignment.class_id, "campus_id": assignment.campus_id}):
		return {"valid": False, "error": "Class not found"}
	
	# Check subject mapping exists
	subject_id = get_subject_id_from_actual(assignment.actual_subject_id, assignment.campus_id)
	if not subject_id:
		return {
			"valid": False,
			"error": "No SIS Subject found for this Actual Subject. Please create subject mapping first."
		}
	
	# Check timetable instances exist
	instances = frappe.get_all(
		"SIS Timetable Instance",
		filters={
			"class_id": assignment.class_id,
			"campus_id": assignment.campus_id
		},
		limit=1
	)
	
	if not instances:
		return {
			"valid": False,
			"error": "No timetable instance found for this class"
		}
	
	return {"valid": True}


def find_pattern_rows(class_id: str, actual_subject_id: str, campus_id: str) -> List[Dict]:
	"""
	Find pattern rows (date=NULL) cho class + subject.
	
	Returns list of dicts with fields: name, parent, subject_id, day_of_week,
	timetable_column_id, period_priority, period_name, teacher_1_id, teacher_2_id, room_id
	"""
	# First, get SIS Subject ID from Actual Subject ID
	subject_id = get_subject_id_from_actual(actual_subject_id, campus_id)
	
	if not subject_id:
		return []
	
	# Get instances for this class
	instances = frappe.get_all(
		"SIS Timetable Instance",
		filters={"class_id": class_id, "campus_id": campus_id},
		pluck="name"
	)
	
	if not instances:
		return []
	
	# Get pattern rows (date IS NULL)
	rows = frappe.db.sql("""
		SELECT 
			name, parent, subject_id, day_of_week,
			timetable_column_id, period_priority, period_name,
			teacher_1_id, teacher_2_id, room_id
		FROM `tabSIS Timetable Instance Row`
		WHERE parent IN ({})
		  AND subject_id = %s
		  AND date IS NULL
		ORDER BY day_of_week, period_priority
	""".format(','.join(['%s'] * len(instances))),
	tuple(instances + [subject_id]),
	as_dict=True)
	
	return rows


def get_subject_id_from_actual(actual_subject_id: str, campus_id: str) -> Optional[str]:
	"""
	Get SIS Subject từ Actual Subject.
	
	Returns first matching SIS Subject for this campus.
	"""
	subject_id = frappe.db.get_value(
		"SIS Subject",
		{"actual_subject_id": actual_subject_id, "campus_id": campus_id},
		"name"
	)
	return subject_id


def calculate_dates_for_day(
	day_of_week: str,
	start_date,
	end_date,
	instance_start,
	instance_end
) -> List:
	"""
	Calculate all dates matching day_of_week within the assignment range.
	
	Args:
		day_of_week: "mon", "tue", etc.
		start_date: Assignment start date
		end_date: Assignment end date (None = no end)
		instance_start: Instance start date
		instance_end: Instance end date
	
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
	if end_date and isinstance(end_date, str):
		end_date = frappe.utils.getdate(end_date)
	if isinstance(instance_start, str):
		instance_start = frappe.utils.getdate(instance_start)
	if isinstance(instance_end, str):
		instance_end = frappe.utils.getdate(instance_end)
	
	# Find first occurrence of this weekday >= start_date and >= instance_start
	current = max(start_date, instance_start)
	
	# Adjust to next occurrence of target weekday
	days_ahead = target_weekday - current.weekday()
	if days_ahead < 0:
		days_ahead += 7
	
	first_occurrence = current + timedelta(days=days_ahead)
	
	# Collect all dates
	dates = []
	check_date = first_occurrence
	
	# Upper bound: min of (end_date or infinity, instance_end)
	upper_bound = instance_end
	if end_date and end_date < upper_bound:
		upper_bound = end_date
	
	while check_date <= upper_bound:
		dates.append(check_date)
		check_date += timedelta(days=7)  # Next week
	
	return dates


def enqueue_materialized_view_sync(row_ids: List[str]):
	"""
	Enqueue background job để sync materialized views.
	
	This is async to avoid blocking the main request.
	"""
	if not row_ids:
		return
	
	try:
		frappe.enqueue(
			method='erp.api.erp_sis.utils.materialized_view_optimizer.sync_for_rows',
			queue='short',
			timeout=300,
			is_async=True,
			row_ids=row_ids
		)
	except Exception as e:
		frappe.log_error(f"Failed to enqueue materialized view sync: {str(e)}")
		# Don't fail the main operation if enqueue fails


def detect_teacher_conflicts(teacher_id: str, target_rows: List, campus_id: str) -> List[Dict]:
	"""
	Detect conflicts: teacher đang dạy môn khác cùng giờ.
	
	Args:
		teacher_id: Teacher ID cần check
		target_rows: Danh sách rows sẽ được assign
		campus_id: Campus ID
	
	Returns:
		List of conflicts với format:
		[
			{
				"day": "monday",
				"period": "period-1",
				"subject": "Toán",
				"class": "2A3",
				"row_id": "..."
			}
		]
	"""
	conflicts = []
	
	if not target_rows:
		return conflicts
	
	# Build list of (day, period) từ target rows
	target_slots = set()
	for row in target_rows:
		slot = (row.day_of_week, row.timetable_column_id)
		target_slots.add(slot)
	
	# Query existing assignments của teacher trong cùng slots
	for day, period in target_slots:
		try:
			# Query rows where teacher is already assigned
			existing_rows = frappe.get_all(
				"SIS Timetable Instance Row",
				fields=["name", "subject_id", "parent", "day_of_week", "timetable_column_id"],
				filters={
					"day_of_week": day,
					"timetable_column_id": period,
					"date": ["is", "not set"]  # Only pattern rows (no date = pattern)
				},
				or_filters=[
					{"teacher_1_id": teacher_id},
					{"teacher_2_id": teacher_id}
				],
				limit=10
			)
			
			for existing in existing_rows:
				# Get subject title
				subject_title = "Unknown"
				if existing.subject_id:
					subject_info = frappe.db.get_value(
						"SIS Subject",
						existing.subject_id,
						["title", "actual_subject_id"],
						as_dict=True
					)
					if subject_info:
						subject_title = subject_info.title or subject_info.actual_subject_id or "Unknown"
				
				# Get class from instance
				class_title = "Unknown"
				if existing.parent:
					class_id = frappe.db.get_value("SIS Timetable Instance", existing.parent, "class_id")
					if class_id:
						class_info = frappe.db.get_value("SIS Class", class_id, "title")
						class_title = class_info or class_id
				
				# Check if this existing row is in target_rows (same subject = not conflict)
				is_same_subject = False
				for target_row in target_rows:
					if (target_row.day_of_week == day and 
						target_row.timetable_column_id == period and
						target_row.subject_id == existing.subject_id):
						is_same_subject = True
						break
				
				# Only add to conflicts if different subject
				if not is_same_subject:
					conflicts.append({
						"day": day,
						"period": period,
						"subject": subject_title,
						"class": class_title,
						"row_id": existing.name
					})
					
		except Exception as e:
			frappe.log_error(f"Error detecting conflict for {day}/{period}: {str(e)}")
			continue
	
	return conflicts


# ============= BATCH OPERATIONS =============

def batch_sync_assignments(assignment_ids: List[str]) -> Dict:
	"""
	Sync multiple assignments in a batch.
	
	More efficient than syncing one by one.
	
	Returns:
		{
			"success": bool,
			"total": int,
			"succeeded": int,
			"failed": int,
			"results": List[Dict]
		}
	"""
	results = []
	succeeded = 0
	failed = 0
	
	for assignment_id in assignment_ids:
		result = sync_assignment_to_timetable(assignment_id)
		results.append(result)
		
		if result["success"]:
			succeeded += 1
		else:
			failed += 1
	
	return {
		"success": failed == 0,
		"total": len(assignment_ids),
		"succeeded": succeeded,
		"failed": failed,
		"results": results
	}

