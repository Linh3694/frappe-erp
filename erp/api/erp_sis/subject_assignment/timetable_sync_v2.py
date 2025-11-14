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

def sync_assignment_to_timetable(assignment_id: str, replace_teacher_map: dict = None) -> Dict:
	"""
	Main entry point cho sync.
	
	Args:
		assignment_id: ID của Subject Assignment cần sync
		replace_teacher_map: Optional dict for resolving teacher conflicts
		                     Format: {row_id: "teacher_1" or "teacher_2"}
	
	Returns:
		{
			"success": bool,
			"rows_updated": int,
			"rows_created": int,
			"message": str,
			"debug_info": List[str],
			"conflicts": list (if conflict detected),
			"error_type": str (if error)
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
			return sync_full_year_assignment(assignment, replace_teacher_map=replace_teacher_map)
		else:
			return sync_date_range_assignment(assignment, replace_teacher_map=replace_teacher_map)
			
	except Exception as e:
		frappe.log_error(f"Sync failed for assignment {assignment_id}: {str(e)}")
		return {
			"success": False,
			"message": f"Critical error: {str(e)}"
		}


# ============= FULL YEAR SYNC =============

def sync_full_year_assignment(assignment, replace_teacher_map: dict = None) -> Dict:
	"""
	Sync full_year assignment: Update pattern rows directly.
	
	Logic:
	1. Find pattern rows cho class + subject
	2. Detect conflicts (teacher dạy môn khác cùng giờ)
	3. Check if both teacher slots are full → CONFLICT!
	4. Update teacher_1_id hoặc teacher_2_id (or replace based on user choice)
	
	Args:
		assignment: SIS Subject Assignment doc
		replace_teacher_map: Optional dict {row_id: "teacher_1" or "teacher_2"}
		                     Can also use special key format for grouped conflicts:
		                     {row_id: {"choice": "teacher_1", "apply_to": [row_id1, row_id2, ...]}}
	
	Performance: ~50ms cho 10 pattern rows
	"""
	replace_teacher_map = replace_teacher_map or {}
	debug_info = []
	teacher_id = assignment.teacher_id
	class_id = assignment.class_id
	actual_subject_id = assignment.actual_subject_id
	campus_id = assignment.campus_id
	
	debug_info.append(f"🔄 Syncing full_year assignment: teacher={teacher_id}, class={class_id}, subject={actual_subject_id}")
	
	# ✅ EXPAND replace_teacher_map if it contains grouped resolutions
	# Frontend may send: {representative_row_id: "teacher_1"} with affected_row_ids in conflict
	# We need to expand it to: {row_id1: "teacher_1", row_id2: "teacher_1", ...}
	expanded_map = {}
	for key, value in replace_teacher_map.items():
		if isinstance(value, dict) and "choice" in value and "apply_to" in value:
			# Grouped format: {row_id: {"choice": "teacher_1", "apply_to": [...]}}
			choice = value["choice"]
			for row_id in value["apply_to"]:
				expanded_map[row_id] = choice
		else:
			# Simple format: {row_id: "teacher_1"}
			expanded_map[key] = value
	
	replace_teacher_map = expanded_map
	
	if replace_teacher_map:
		debug_info.append(f"📋 Replace teacher map has {len(replace_teacher_map)} entries")
	
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
	
	# DEBUG: Log teacher slots in pattern rows
	for i, row in enumerate(pattern_rows[:3]):  # Log first 3 rows for debugging
		frappe.logger().info(
			f"DEBUG Pattern Row {i+1}: {row.name} - "
			f"teacher_1={row.teacher_1_id}, teacher_2={row.teacher_2_id}"
		)
	
	# CHECK: Detect conflicts với môn khác của teacher
	conflicts = detect_teacher_conflicts(teacher_id, pattern_rows, campus_id)
	if conflicts:
		debug_info.append(f"⚠️ Found {len(conflicts)} potential conflicts:")
		for conflict in conflicts:
			debug_info.append(f"  - {conflict['day']}/{conflict['period']}: Already teaching {conflict['subject']} in {conflict['class']}")
	
	# APPLY: Update atomically
	updated_count = 0
	skipped_conflicts = 0
	teacher_conflicts = []  # Track conflicts when both slots are full
	
	try:
		# NOTE: Don't begin transaction here - caller manages transaction
		# frappe.db.begin()

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
				# Both teacher slots are full → CONFLICT!
				frappe.logger().warning(
					f"⚠️ CONFLICT DETECTED in row {row.name}: "
					f"teacher_1={row.teacher_1_id}, teacher_2={row.teacher_2_id}, "
					f"trying to add teacher={teacher_id}"
				)
				
				# Check if user provided resolution for this conflict
				if row.name in replace_teacher_map:
					# User chose which teacher to replace
					replace_slot = replace_teacher_map[row.name]  # "teacher_1" or "teacher_2"
					
					if replace_slot not in ["teacher_1", "teacher_2"]:
						frappe.logger().error(f"Invalid replace_slot: {replace_slot} for row {row.name}")
						continue
					
					frappe.db.set_value(
						"SIS Timetable Instance Row",
						row.name,
						f"{replace_slot}_id",
						teacher_id,
						update_modified=False
					)
					updated_count += 1
					debug_info.append(
						f"✅ Replaced {replace_slot} in row {row.name}"
					)
				else:
					# No resolution provided → Add to conflicts list
					teacher_conflicts.append({
						"row_id": row.name,
						"date": None,  # Pattern rows don't have date
						"day_of_week": row.day_of_week,
						"period_id": row.timetable_column_id,
						"period_name": row.period_name,
						"subject_id": row.subject_id,
						"teacher_1_id": row.teacher_1_id,
						"teacher_1_name": get_teacher_name(row.teacher_1_id),
						"teacher_2_id": row.teacher_2_id,
						"teacher_2_name": get_teacher_name(row.teacher_2_id),
						"new_teacher_id": teacher_id,
						"new_teacher_name": get_teacher_name(teacher_id)
					})
					frappe.logger().warning(
						f"⚠️ Added to conflicts list: {len(teacher_conflicts)} total conflicts"
					)
					debug_info.append(f"  ⚠️ Conflict in row {row.name}: both slots full")
		
		# Check if there are unresolved conflicts
		if teacher_conflicts:
			# Group conflicts by subject_id - user only needs to choose once per subject
			# Then we'll apply the resolution to ALL rows for that subject
			conflicts_grouped = {}
			row_ids_by_subject = {}  # Map subject_id -> list of row_ids
			
			for conflict in teacher_conflicts:
				subject_id = conflict["subject_id"]
				
				if subject_id not in conflicts_grouped:
					# First conflict for this subject - use as representative
					conflicts_grouped[subject_id] = conflict
					row_ids_by_subject[subject_id] = []
				
				# Track all row_ids for this subject
				row_ids_by_subject[subject_id].append(conflict["row_id"])
			
			# Convert to list and add row_ids info
			grouped_conflicts = []
			for subject_id, conflict in conflicts_grouped.items():
				conflict["affected_row_ids"] = row_ids_by_subject[subject_id]
				conflict["affected_row_count"] = len(row_ids_by_subject[subject_id])
				grouped_conflicts.append(conflict)
			
			# Return conflicts to caller - caller handles rollback
			frappe.logger().warning(
				f"⚠️ DETECTED CONFLICTS: {len(teacher_conflicts)} total rows, "
				f"grouped into {len(grouped_conflicts)} subject conflicts. "
				f"Returning to caller for resolution."
			)

			debug_info.append(
				f"⚠️ Found {len(teacher_conflicts)} conflict rows, "
				f"grouped into {len(grouped_conflicts)} conflicts (by subject)"
			)
			
			conflict_response = {
				"success": False,
				"message": f"Phát hiện {len(grouped_conflicts)} xung đột giáo viên. Vui lòng chọn giáo viên để thay thế.",
				"error_type": "teacher_conflict",
				"conflicts": grouped_conflicts,
				"rows_updated": 0,
				"rows_created": 0,
				"debug_info": debug_info
			}
			
			frappe.logger().info(f"🚫 Conflict response: {conflict_response}")
			return conflict_response

		# No conflicts or all resolved → Return success (caller handles commit)
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
		# Don't rollback - let caller handle transaction
		debug_info.append(f"❌ Error: {str(e)}")
		return {
			"success": False,
			"message": f"Sync failed: {str(e)}",
			"debug_info": debug_info
		}


# ============= DATE RANGE SYNC =============

def sync_date_range_assignment(assignment, replace_teacher_map: dict = None) -> Dict:
	"""
	Sync from_date assignment: Create override rows.
	
	Logic:
	1. Find pattern rows
	2. Calculate dates trong range
	3. Check for conflicts (both teacher slots full)
	4. If conflicts and no resolution → Return conflict error
	5. If conflicts with resolution → Apply replacement
	6. Create/update override rows
	
	Args:
		assignment: SIS Subject Assignment doc
		replace_teacher_map: Optional dict {row_id: "teacher_1" or "teacher_2"}
		                     Tells which teacher to replace when conflict
	
	Returns:
		{
			"success": bool,
			"message": str,
			"rows_created": int,
			"rows_updated": int,
			"conflicts": list (if conflict detected),
			"error_type": "teacher_conflict" (if conflict)
		}
	
	Performance: ~200ms cho 50 override rows
	"""
	debug_info = []
	teacher_id = assignment.teacher_id
	class_id = assignment.class_id
	actual_subject_id = assignment.actual_subject_id
	campus_id = assignment.campus_id
	start_date = assignment.start_date
	end_date = assignment.end_date
	replace_teacher_map = replace_teacher_map or {}
	
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
	conflicts = []  # Track conflicts for user resolution
	
	try:
		# NOTE: Don't begin transaction here - caller manages transaction
		# frappe.db.begin()

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
				# Check if teacher is already assigned to this row
				if existing.teacher_1_id == teacher_id or existing.teacher_2_id == teacher_id:
					# Teacher already assigned, skip
					continue
				
				# Check if both teacher slots are full → CONFLICT!
				if existing.teacher_1_id and existing.teacher_2_id:
					# Both slots full - need user to choose who to replace
					frappe.logger().warning(
						f"⚠️ FROM_DATE CONFLICT: Existing override {existing.name} on {date} - "
						f"teacher_1={existing.teacher_1_id}, teacher_2={existing.teacher_2_id}, "
						f"trying to add teacher={teacher_id}"
					)
					
					# Check if user provided resolution for this conflict
					if existing.name in replace_teacher_map:
						# User chose which teacher to replace
						replace_slot = replace_teacher_map[existing.name]  # "teacher_1" or "teacher_2"
						
						if replace_slot not in ["teacher_1", "teacher_2"]:
							frappe.logger().error(f"Invalid replace_slot: {replace_slot} for row {existing.name}")
							continue
						
						frappe.db.set_value(
							"SIS Timetable Instance Row",
							existing.name,
							f"{replace_slot}_id",
							teacher_id,
							update_modified=False
						)
						updated_count += 1
						debug_info.append(
							f"✅ Replaced {replace_slot} on {date} - {pattern_row.timetable_column_id}"
						)
					else:
						# No resolution provided → Add to conflicts list
						conflicts.append({
							"row_id": existing.name,
							"date": str(date),
							"day_of_week": pattern_row.day_of_week,
							"period_id": pattern_row.timetable_column_id,
							"period_name": pattern_row.period_name,
							"subject_id": pattern_row.subject_id,
							"teacher_1_id": existing.teacher_1_id,
							"teacher_1_name": get_teacher_name(existing.teacher_1_id),
							"teacher_2_id": existing.teacher_2_id,
							"teacher_2_name": get_teacher_name(existing.teacher_2_id),
							"new_teacher_id": teacher_id,
							"new_teacher_name": get_teacher_name(teacher_id)
						})
						frappe.logger().warning(
							f"⚠️ FROM_DATE: Added existing override conflict: {len(conflicts)} total conflicts"
						)
				elif not existing.teacher_2_id:
					# teacher_2 is empty → Add as co-teacher
					frappe.db.set_value(
						"SIS Timetable Instance Row",
						existing.name,
						"teacher_2_id",
						teacher_id,
						update_modified=False
					)
					updated_count += 1
				elif not existing.teacher_1_id:
					# teacher_1 is empty (edge case) → Add to teacher_1
					frappe.db.set_value(
						"SIS Timetable Instance Row",
						existing.name,
						"teacher_1_id",
						teacher_id,
						update_modified=False
					)
					updated_count += 1
			else:
				# No existing override row - need to create one
				
				# Check if teacher is already in pattern row (skip if yes)
				if pattern_row.teacher_1_id == teacher_id or pattern_row.teacher_2_id == teacher_id:
					# Teacher already assigned in pattern, skip
					continue
				
				# Check if pattern row already has 2 teachers → CONFLICT!
				if pattern_row.teacher_1_id and pattern_row.teacher_2_id:
					# Pattern row already has 2 teachers - conflict!
					frappe.logger().warning(
						f"⚠️ FROM_DATE CONFLICT: Pattern row {pattern_row.name} on {date} - "
						f"teacher_1={pattern_row.teacher_1_id}, teacher_2={pattern_row.teacher_2_id}, "
						f"trying to add teacher={teacher_id}"
					)
					
					# Check if user provided resolution
					# Note: We use a temporary key since override doesn't exist yet
					temp_key = f"pattern_{pattern_row.name}_{date}"
					if temp_key in replace_teacher_map:
						# User chose which teacher to replace
						replace_slot = replace_teacher_map[temp_key]
						
						if replace_slot not in ["teacher_1", "teacher_2"]:
							frappe.logger().error(f"Invalid replace_slot: {replace_slot}")
							continue
						
						# Create override with replacement
						teacher_1 = teacher_id if replace_slot == "teacher_1" else pattern_row.teacher_1_id
						teacher_2 = teacher_id if replace_slot == "teacher_2" else pattern_row.teacher_2_id
						
						override_doc = frappe.get_doc({
							"doctype": "SIS Timetable Instance Row",
							"parent": pattern_row.parent,
							"parenttype": "SIS Timetable Instance",
							"parentfield": "date_overrides",
							"date": date,
							"day_of_week": pattern_row.day_of_week,
							"timetable_column_id": pattern_row.timetable_column_id,
							"period_priority": pattern_row.period_priority,
							"period_name": pattern_row.period_name,
							"subject_id": pattern_row.subject_id,
							"teacher_1_id": teacher_1,
							"teacher_2_id": teacher_2,
							"room_id": pattern_row.room_id
						})
						override_doc.insert(ignore_permissions=True, ignore_mandatory=True)
						created_count += 1
						debug_info.append(
							f"✅ Created override with {replace_slot} replaced on {date}"
						)
					else:
						# No resolution provided → Add to conflicts list
						conflicts.append({
							"row_id": temp_key,  # Use temp key for pattern-based conflicts
							"date": str(date),
							"day_of_week": pattern_row.day_of_week,
							"period_id": pattern_row.timetable_column_id,
							"period_name": pattern_row.period_name,
							"subject_id": pattern_row.subject_id,
							"teacher_1_id": pattern_row.teacher_1_id,
							"teacher_1_name": get_teacher_name(pattern_row.teacher_1_id),
							"teacher_2_id": pattern_row.teacher_2_id,
							"teacher_2_name": get_teacher_name(pattern_row.teacher_2_id),
							"new_teacher_id": teacher_id,
							"new_teacher_name": get_teacher_name(teacher_id)
						})
						frappe.logger().warning(
							f"⚠️ FROM_DATE: Added to conflicts list: {len(conflicts)} total conflicts"
						)
				else:
					# Pattern row has room - create override with co-teaching
					# Copy from pattern row but set teacher_2 as the new teacher
					# teacher_1 will remain as pattern's teacher_1 (original teacher)
					override_doc = frappe.get_doc({
						"doctype": "SIS Timetable Instance Row",
						"parent": pattern_row.parent,
						"parenttype": "SIS Timetable Instance",
						"parentfield": "date_overrides",  # ✅ Must be date_overrides, not weekly_pattern!
						"date": date,
						"day_of_week": pattern_row.day_of_week,
						"timetable_column_id": pattern_row.timetable_column_id,
						"period_priority": pattern_row.period_priority,
						"period_name": pattern_row.period_name,
						"subject_id": pattern_row.subject_id,
						"teacher_1_id": pattern_row.teacher_1_id,  # Keep original teacher as teacher_1
						"teacher_2_id": teacher_id,  # Add new teacher as teacher_2 (co-teaching)
						"room_id": pattern_row.room_id
					})
					override_doc.insert(ignore_permissions=True, ignore_mandatory=True)
					created_count += 1
		
		# Check if there are unresolved conflicts
		if conflicts:
			# Return conflicts to caller - caller handles rollback
			frappe.logger().warning(
				f"⚠️ FROM_DATE: DETECTED CONFLICTS: {len(conflicts)} conflicts detected. "
				f"Returning to caller for resolution."
			)
			
			debug_info.append(f"⚠️ Found {len(conflicts)} conflicts requiring user resolution")
			
			conflict_response = {
				"success": False,
				"message": f"Phát hiện {len(conflicts)} xung đột giáo viên. Vui lòng chọn giáo viên để thay thế.",
				"error_type": "teacher_conflict",
				"conflicts": conflicts,
				"rows_created": 0,
				"rows_updated": 0,
				"debug_info": debug_info
			}
			
			frappe.logger().info(f"🚫 FROM_DATE Conflict response: {conflict_response}")
			return conflict_response

		# No conflicts or all resolved → Return success (caller handles commit)
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
		# Don't rollback - let caller handle transaction
		debug_info.append(f"❌ Error: {str(e)}")
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


def get_teacher_name(teacher_id: str) -> str:
	"""
	Get teacher's display name from User table.
	
	Args:
		teacher_id: SIS Teacher ID
		
	Returns:
		Teacher's full name or user_id as fallback
	"""
	try:
		# Get user_id from SIS Teacher
		user_id = frappe.db.get_value("SIS Teacher", teacher_id, "user_id")
		if not user_id:
			return teacher_id
		
		# Get full_name from User
		full_name = frappe.db.get_value("User", user_id, "full_name")
		return full_name or user_id
	except Exception as e:
		frappe.log_error(f"Failed to get teacher name for {teacher_id}: {str(e)}")
		return teacher_id


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

