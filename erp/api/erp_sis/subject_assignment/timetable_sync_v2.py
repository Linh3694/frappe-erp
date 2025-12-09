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
	Sync full_year assignment: Update ALL rows (pattern + override) with ALL teachers.
	
	NEW LOGIC (Unlimited Teachers):
	1. Find ALL rows (pattern + override) cho class + subject
	2. Find ALL assignments for this class + subject (not just current one)
	3. Clear existing teachers child table
	4. Insert ALL teachers from ALL assignments into child table
	
	⚡ FIX: Now syncs BOTH pattern rows AND override rows!
	Override rows were previously skipped, causing teachers to be missing.
	
	NO MORE CONFLICTS: Since we support unlimited teachers, no conflict detection needed.
	
	Args:
		assignment: SIS Subject Assignment doc
		replace_teacher_map: DEPRECATED - no longer used (kept for backward compatibility)
	
	Performance: ~100ms cho 10 pattern rows, ~500ms cho 50 rows (pattern + override)
	"""
	debug_info = []
	teacher_id = assignment.teacher_id
	class_id = assignment.class_id
	actual_subject_id = assignment.actual_subject_id
	campus_id = assignment.campus_id
	
	debug_info.append(f"🔄 Syncing full_year assignment: class={class_id}, subject={actual_subject_id}")
	
	# STEP 1: Find ALL rows (pattern + override)
	# ⚡ FIX: Use find_all_rows instead of find_pattern_rows
	all_rows = find_all_rows(
		class_id=class_id,
		actual_subject_id=actual_subject_id,
		campus_id=campus_id
	)
	
	if not all_rows:
		return {
			"success": False,
			"message": "No timetable rows found for this class/subject",
			"debug_info": debug_info + ["❌ No timetable rows found"]
		}
	
	pattern_count = len([r for r in all_rows if r.date is None])
	override_count = len([r for r in all_rows if r.date is not None])
	debug_info.append(f"📋 Found {len(all_rows)} rows ({pattern_count} pattern, {override_count} override)")
	
	# STEP 2: Get ALL assignments for this class + subject
	all_assignments = frappe.get_all(
		"SIS Subject Assignment",
		fields=["name", "teacher_id"],
		filters={
			"class_id": class_id,
			"actual_subject_id": actual_subject_id,
			"campus_id": campus_id,
			"application_type": "full_year"
		},
		order_by="creation asc"
	)
	
	if not all_assignments:
		debug_info.append("⚠️ No assignments found")
		return {
			"success": False,
			"message": "No assignments found for this class/subject",
			"debug_info": debug_info
		}
	
	teacher_ids = [a.teacher_id for a in all_assignments if a.teacher_id]
	debug_info.append(f"👥 Found {len(teacher_ids)} teachers from {len(all_assignments)} assignments")
	
	if not teacher_ids:
		debug_info.append("⚠️ No teachers found")
		return {
			"success": False,
			"message": "No teachers found in assignments",
			"debug_info": debug_info
		}
	
	# STEP 3: Update ALL rows (pattern + override) with ALL teachers
	updated_count = 0
	
	try:
		for row in all_rows:
			# ⚡ FIX: Use direct SQL to update teachers (more reliable than ORM)
			update_row_teachers_sql(row.name, teacher_ids)
			updated_count += 1
			debug_info.append(f"  ✓ Updated row {row.name}: {len(teacher_ids)} teachers")
		
		# ⚡ CRITICAL: Sync materialized view INSIDE try block
		if updated_count > 0:
			row_ids = [r.name for r in all_rows]
			if len(row_ids) <= 50:
				# ⚡ CRITICAL: Sync immediately for small updates
				# If sync fails, we MUST throw exception to trigger rollback
				try:
					from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows
					sync_for_rows(row_ids)
					debug_info.append(f"✅ Synced materialized view immediately")
				except Exception as mat_view_error:
					error_msg = f"Teacher Timetable sync failed: {str(mat_view_error)}"
					frappe.log_error(error_msg, "Materialized View Sync Error")
					debug_info.append(f"❌ {error_msg}")
					
					# ⚡ THROW EXCEPTION to trigger transaction rollback
					# This ensures assignment is not created if timetable sync fails
					raise Exception(f"Failed to sync Teacher Timetable: {str(mat_view_error)}")
			else:
				# For large updates (>50 rows), use direct sync instead of enqueue
				# Background jobs are unreliable - we need immediate feedback
				try:
					from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows
					frappe.logger().info(f"🔄 Syncing large update: {len(row_ids)} rows")
					sync_for_rows(row_ids)
					debug_info.append(f"✅ Synced {len(row_ids)} rows successfully")
				except Exception as mat_view_error:
					error_msg = f"Teacher Timetable sync failed for {len(row_ids)} rows: {str(mat_view_error)}"
					frappe.log_error(error_msg, "Materialized View Sync Error")
					debug_info.append(f"❌ {error_msg}")
					
					# ⚡ THROW EXCEPTION to trigger transaction rollback
					raise Exception(f"Failed to sync Teacher Timetable: {str(mat_view_error)}")
		
		frappe.logger().info(f"✅ Synced {updated_count} pattern rows with {len(teacher_ids)} teachers")
		
		message = f"Successfully synced {updated_count} rows with {len(teacher_ids)} teachers"
		
		return {
			"success": True,
			"rows_updated": updated_count,
			"rows_created": 0,
			"message": message,
			"debug_info": debug_info
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
	Sync from_date assignment: Create override rows with ALL teachers.
	
	NEW LOGIC (Unlimited Teachers):
	1. Find pattern rows
	2. Calculate dates trong range  
	3. Get ALL assignments for class + subject
	4. Create/update override rows with ALL teachers in child table
	
	NO MORE CONFLICTS: Since we support unlimited teachers, no conflict detection needed.
	
	Args:
		assignment: SIS Subject Assignment doc
		replace_teacher_map: DEPRECATED - no longer used
	
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
	
	# ✅ NEW APPROACH: Use subject_id as key instead of row_id
	# This way resolution persists across rollback/retry cycles
	resolution_by_subject = {}
	
	if replace_teacher_map:
		# Try to detect format by checking if keys look like subject IDs
		first_key = next(iter(replace_teacher_map.keys()))
		if first_key.startswith("SIS_ACTUAL_SUBJECT-") or first_key.startswith("SIS-SUBJECT-"):
			# Already subject_id format
			resolution_by_subject = replace_teacher_map
			debug_info.append(f"📋 Using subject-based resolution map: {len(resolution_by_subject)} subjects")
		else:
			# Legacy row_id format - keep for backward compatibility
			debug_info.append(f"📋 Using row-based resolution map: {len(replace_teacher_map)} rows")
			resolution_by_subject = {}  # Will use row-based logic below
	
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
	affected_row_ids = []  # ⚡ FIX: Track created/updated override row IDs for sync
	
	try:
		# NOTE: Don't begin transaction here - caller manages transaction
		# frappe.db.begin()

		for date, pattern_row in override_specs:
			# Check if override already exists
			# ⚡ FIX: Search by parent_timetable_instance OR parent (handle both cases)
			# Also search ANY override row with same date + slot, not just from current pattern
			existing = frappe.db.sql("""
				SELECT name, teacher_1_id, teacher_2_id
				FROM `tabSIS Timetable Instance Row`
				WHERE date = %s
				  AND day_of_week = %s
				  AND timetable_column_id = %s
				  AND subject_id = %s
				  AND (parent = %s OR parent_timetable_instance = %s)
				ORDER BY creation DESC
				LIMIT 1
			""", (date, pattern_row.day_of_week, pattern_row.timetable_column_id,
				  pattern_row.subject_id, pattern_row.parent, pattern_row.parent),
			as_dict=True)
			existing = existing[0] if existing else None
			
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
					
					# ✅ Check resolution by SUBJECT_ID first (persistent across retries)
					replace_slot = None
					if resolution_by_subject and pattern_row.subject_id in resolution_by_subject:
						replace_slot = resolution_by_subject[pattern_row.subject_id]
						frappe.logger().info(f"✅ Found subject-based resolution: {pattern_row.subject_id} → {replace_slot}")
					elif existing.name in replace_teacher_map:
						# Legacy: check by row_id
						replace_slot = replace_teacher_map[existing.name]
						frappe.logger().info(f"✅ Found row-based resolution: {existing.name} → {replace_slot}")
					
					if replace_slot:
						# User provided resolution
						if replace_slot not in ["teacher_1", "teacher_2"]:
							frappe.logger().error(f"Invalid replace_slot: {replace_slot} for row {existing.name}")
							continue
						
						# ⚡ FIX: Use direct SQL to update child table
						# Build teacher list based on resolution
						if replace_slot == "teacher_1":
							# Replace teacher_1 with new teacher, keep teacher_2
							new_teachers = [tid for tid in [teacher_id, existing.teacher_2_id] if tid]
						else:  # replace_slot == "teacher_2"
							# Keep teacher_1, replace teacher_2 with new teacher
							new_teachers = [tid for tid in [existing.teacher_1_id, teacher_id] if tid]
						
						update_row_teachers_sql(existing.name, new_teachers)
						affected_row_ids.append(existing.name)
						updated_count += 1
						debug_info.append(
							f"✅ Replaced {replace_slot} on {date} - {pattern_row.timetable_column_id} (subject: {pattern_row.subject_id})"
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
					# ⚡ FIX: Use direct SQL - get existing teachers and add new one
					existing_teachers = frappe.db.sql("""
						SELECT teacher_id FROM `tabSIS Timetable Instance Row Teacher`
						WHERE parent = %s ORDER BY sort_order
					""", (existing.name,), as_dict=True)
					new_teachers = [t.teacher_id for t in existing_teachers] + [teacher_id]
					update_row_teachers_sql(existing.name, new_teachers)
					affected_row_ids.append(existing.name)
					updated_count += 1
				elif not existing.teacher_1_id:
					# teacher_1 is empty (edge case) → Add to teacher_1
					# ⚡ FIX: Use direct SQL - get existing teachers and add new one
					existing_teachers = frappe.db.sql("""
						SELECT teacher_id FROM `tabSIS Timetable Instance Row Teacher`
						WHERE parent = %s ORDER BY sort_order
					""", (existing.name,), as_dict=True)
					new_teachers = [teacher_id] + [t.teacher_id for t in existing_teachers]
					update_row_teachers_sql(existing.name, new_teachers)
					affected_row_ids.append(existing.name)
					updated_count += 1
			else:
				# No existing override row - need to create one
				
				# ⚡ FIX: Get teachers from pattern row's child table
				pattern_teachers = frappe.db.sql("""
					SELECT teacher_id FROM `tabSIS Timetable Instance Row Teacher`
					WHERE parent = %s ORDER BY sort_order
				""", (pattern_row.name,), as_dict=True)
				pattern_teacher_ids = [t.teacher_id for t in pattern_teachers]
				
				if teacher_id in pattern_teacher_ids:
					# Teacher already assigned in pattern, skip
					continue
				
				# ⚡ SIMPLIFIED: Create override with ALL existing teachers + new teacher
				override_doc = frappe.get_doc({
					"doctype": "SIS Timetable Instance Row",
					"parent": pattern_row.parent,
					"parent_timetable_instance": pattern_row.parent,
					"parenttype": "SIS Timetable Instance",
					"parentfield": "date_overrides",
					"date": date,
					"day_of_week": pattern_row.day_of_week,
					"timetable_column_id": pattern_row.timetable_column_id,
					"period_priority": pattern_row.period_priority,
					"period_name": pattern_row.period_name,
					"subject_id": pattern_row.subject_id,
					"room_id": pattern_row.room_id
				})
				
				# Insert first to get name
				override_doc.insert(ignore_permissions=True, ignore_mandatory=True)
				
				# ⚡ FIX: Copy ALL teachers from pattern row + add new teacher
				new_teachers = pattern_teacher_ids.copy()
				if teacher_id and teacher_id not in new_teachers:
					new_teachers.append(teacher_id)
				
				if new_teachers:
					update_row_teachers_sql(override_doc.name, new_teachers)
				
				affected_row_ids.append(override_doc.name)
				created_count += 1
		
		# Check if there are unresolved conflicts
		if conflicts:
			# Group conflicts by subject_id - user only needs to choose once per subject
			# For date range assignments, conflicts may span multiple dates
			# ✅ KEY CHANGE: Use subject_id as conflict identifier (not row_id)
			conflicts_grouped = {}
			row_ids_by_subject = {}  # Map subject_id -> list of row_ids
			
			for conflict in conflicts:
				subject_id = conflict["subject_id"]
				
				if subject_id not in conflicts_grouped:
					# First conflict for this subject - use as representative
					# ✅ Use subject_id as the conflict key
					conflict["conflict_key"] = subject_id  # Use subject_id instead of row_id
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
				f"⚠️ FROM_DATE: DETECTED CONFLICTS: {len(conflicts)} total rows, "
				f"grouped into {len(grouped_conflicts)} subject conflicts. "
				f"Returning to caller for resolution."
			)
			
			debug_info.append(
				f"⚠️ Found {len(conflicts)} conflict rows, "
				f"grouped into {len(grouped_conflicts)} conflicts (by subject)"
			)
			
			conflict_response = {
				"success": False,
				"message": f"Phát hiện {len(grouped_conflicts)} xung đột giáo viên. Vui lòng chọn giáo viên để thay thế.",
				"error_type": "teacher_conflict",
				"conflicts": grouped_conflicts,
				"rows_created": 0,
				"rows_updated": 0,
				"debug_info": debug_info
			}
			
			frappe.logger().info(f"🚫 FROM_DATE Conflict response: {conflict_response}")
			return conflict_response

		# No conflicts or all resolved → Return success (caller handles commit)
		debug_info.append(f"✅ Created {created_count} override rows")
		debug_info.append(f"✅ Updated {updated_count} override rows")
		
		# ⚡ FIX: Sync affected override rows (created/updated), NOT pattern rows
		if affected_row_ids:
			total_changes = len(affected_row_ids)
			debug_info.append(f"📋 Affected row IDs to sync: {affected_row_ids}")
			
			# ⚡ CRITICAL: Always sync immediately (no async!)
			# Background jobs are unreliable - we need immediate feedback
			try:
				from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows
				frappe.logger().info(f"🔄 Syncing Teacher Timetable for {total_changes} override rows: {affected_row_ids}")
				sync_for_rows(affected_row_ids)
				debug_info.append(f"✅ Synced materialized view for {total_changes} override rows")
			except Exception as sync_err:
				error_msg = f"Teacher Timetable sync failed for {total_changes} override rows: {str(sync_err)}"
				frappe.log_error(error_msg, "Materialized View Sync Error")
				debug_info.append(f"❌ {error_msg}")
				
				# ⚡ THROW EXCEPTION to trigger transaction rollback
				# This ensures override rows are not created if timetable sync fails
				raise Exception(f"Failed to sync Teacher Timetable: {str(sync_err)}")
		else:
			debug_info.append("⚠️ No override rows were created/updated - skipping sync")
		
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

def update_row_teachers_sql(row_name: str, teacher_ids: List[str]) -> int:
	"""
	⚡ FIX: Update teachers child table using direct SQL.
	
	This ensures data is properly persisted to database, unlike Frappe ORM
	which may have issues with child table updates.
	
	Args:
		row_name: SIS Timetable Instance Row name
		teacher_ids: List of teacher IDs to set
		
	Returns:
		Number of teachers inserted
	"""
	# ⚡ FIX: Dedupe teacher_ids - preserve order, remove duplicates and None
	seen = set()
	unique_teacher_ids = []
	for tid in teacher_ids:
		if tid and tid not in seen:
			seen.add(tid)
			unique_teacher_ids.append(tid)
	
	# Step 1: Delete ALL existing teachers from child table
	frappe.db.sql("""
		DELETE FROM `tabSIS Timetable Instance Row Teacher`
		WHERE parent = %s
	""", (row_name,))
	
	# Step 2: Insert new teachers (deduplicated)
	inserted = 0
	for idx, tid in enumerate(unique_teacher_ids, start=1):
		child_name = frappe.generate_hash(length=10)
		frappe.db.sql("""
			INSERT INTO `tabSIS Timetable Instance Row Teacher`
			(name, parent, parenttype, parentfield, teacher_id, sort_order, idx)
			VALUES (%s, %s, 'SIS Timetable Instance Row', 'teachers', %s, %s, %s)
		""", (child_name, row_name, tid, idx, idx))
		inserted += 1
	
	return inserted


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
	# ⚡ FIX: Don't filter by campus_id (consistent with find_pattern_rows)
	instances = frappe.get_all(
		"SIS Timetable Instance",
		filters={"class_id": assignment.class_id},
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
	
	⚡ FIX: Now searches ALL SIS Subjects that map to the same Actual Subject.
	This fixes the bug where sync fails because different education_stages have
	different SIS Subjects for the same Actual Subject.
	
	Returns list of dicts with fields: name, parent, subject_id, day_of_week,
	timetable_column_id, period_priority, period_name, teacher_1_id, teacher_2_id, room_id
	"""
	# ⚡ FIX: Get ALL SIS Subject IDs from Actual Subject (across education_stages)
	subject_ids = get_all_subject_ids_from_actual(actual_subject_id, campus_id)
	
	if not subject_ids:
		frappe.logger().warning(
			f"find_pattern_rows: No SIS Subjects found for actual_subject={actual_subject_id}, campus={campus_id}"
		)
		return []
	
	frappe.logger().info(
		f"find_pattern_rows: Found {len(subject_ids)} SIS Subjects for actual_subject={actual_subject_id}: {subject_ids}"
	)
	
	# ⚡ FIX: Get instances for this class WITHOUT campus_id filter
	# (consistent with get_class_week() which also doesn't filter by campus_id)
	instances = frappe.get_all(
		"SIS Timetable Instance",
		filters={"class_id": class_id},
		pluck="name"
	)
	
	if not instances:
		frappe.logger().warning(
			f"find_pattern_rows: No timetable instances for class={class_id}"
		)
		return []
	
	frappe.logger().info(
		f"find_pattern_rows: Found {len(instances)} timetable instances for class={class_id}"
	)
	
	# ⚡ FIX: Get pattern rows for ANY of the subject_ids (date IS NULL)
	rows = frappe.db.sql("""
		SELECT 
			name, parent, subject_id, day_of_week,
			timetable_column_id, period_priority, period_name,
			teacher_1_id, teacher_2_id, room_id
		FROM `tabSIS Timetable Instance Row`
		WHERE parent IN ({instances})
		  AND subject_id IN ({subjects})
		  AND date IS NULL
		ORDER BY day_of_week, period_priority
	""".format(
		instances=','.join(['%s'] * len(instances)),
		subjects=','.join(['%s'] * len(subject_ids))
	),
	tuple(instances + subject_ids),
	as_dict=True)
	
	frappe.logger().info(
		f"find_pattern_rows: Found {len(rows)} pattern rows for class={class_id}, subjects={subject_ids}"
	)
	
	return rows


def find_all_rows(class_id: str, actual_subject_id: str, campus_id: str) -> List[Dict]:
	"""
	Find ALL rows (both pattern AND override) cho class + subject.
	
	⚡ NEW: This function finds ALL timetable rows, not just pattern rows.
	Used by sync_full_year_assignment to ensure override rows also get teachers.
	
	Returns list of dicts with fields: name, parent, subject_id, day_of_week,
	timetable_column_id, period_priority, period_name, teacher_1_id, teacher_2_id, room_id, date
	"""
	subject_ids = get_all_subject_ids_from_actual(actual_subject_id, campus_id)
	
	if not subject_ids:
		frappe.logger().warning(
			f"find_all_rows: No SIS Subjects found for actual_subject={actual_subject_id}, campus={campus_id}"
		)
		return []
	
	# Get instances for this class
	instances = frappe.get_all(
		"SIS Timetable Instance",
		filters={"class_id": class_id, "campus_id": campus_id},
		pluck="name"
	)
	
	if not instances:
		frappe.logger().warning(
			f"find_all_rows: No timetable instances for class={class_id}, campus={campus_id}"
		)
		return []
	
	# ⚡ Get ALL rows (pattern + override) for ANY of the subject_ids
	rows = frappe.db.sql("""
		SELECT 
			name, parent, subject_id, day_of_week,
			timetable_column_id, period_priority, period_name,
			teacher_1_id, teacher_2_id, room_id, date
		FROM `tabSIS Timetable Instance Row`
		WHERE (parent IN ({instances}) OR parent_timetable_instance IN ({instances}))
		  AND subject_id IN ({subjects})
		ORDER BY date, day_of_week, period_priority
	""".format(
		instances=','.join(['%s'] * len(instances)),
		subjects=','.join(['%s'] * len(subject_ids))
	),
	tuple(instances + instances + subject_ids),
	as_dict=True)
	
	pattern_count = len([r for r in rows if r.date is None])
	override_count = len([r for r in rows if r.date is not None])
	
	frappe.logger().info(
		f"find_all_rows: Found {len(rows)} rows ({pattern_count} pattern, {override_count} override) "
		f"for class={class_id}, subjects={subject_ids}"
	)
	
	return rows


def get_subject_id_from_actual(actual_subject_id: str, campus_id: str) -> Optional[str]:
	"""
	Get SIS Subject từ Actual Subject.
	
	Returns first matching SIS Subject for this campus.
	
	⚠️ DEPRECATED: Use get_all_subject_ids_from_actual() for reliable matching.
	This function may return wrong subject when multiple SIS Subjects exist
	for different education_stages.
	"""
	subject_id = frappe.db.get_value(
		"SIS Subject",
		{"actual_subject_id": actual_subject_id, "campus_id": campus_id},
		"name"
	)
	return subject_id


def get_all_subject_ids_from_actual(actual_subject_id: str, campus_id: str) -> List[str]:
	"""
	Get ALL SIS Subjects từ Actual Subject.
	
	⚡ FIX: Returns ALL matching SIS Subjects for this campus (across education_stages).
	This ensures we find pattern rows regardless of which SIS Subject was used in timetable.
	
	Args:
		actual_subject_id: SIS Actual Subject ID
		campus_id: Campus ID
		
	Returns:
		List of SIS Subject IDs
	"""
	subjects = frappe.db.get_all(
		"SIS Subject",
		filters={"actual_subject_id": actual_subject_id, "campus_id": campus_id},
		pluck="name"
	)
	return subjects or []


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
	⚡ Sync materialized views DIRECTLY (no background job).
	
	Background jobs were getting stuck - synchronous execution is more reliable.
	Function renamed from enqueue_* but kept for backward compatibility.
	"""
	if not row_ids:
		return
	
	try:
		# Import and call directly instead of enqueue
		from erp.api.erp_sis.utils.materialized_view_optimizer import sync_for_rows
		
		frappe.logger().info(f"🔄 Starting SYNCHRONOUS materialized view sync for {len(row_ids)} rows")
		sync_for_rows(row_ids)
		frappe.logger().info(f"✅ Materialized view sync completed for {len(row_ids)} rows")
	except Exception as e:
		frappe.log_error(f"Failed to sync materialized views: {str(e)}")
		# Don't fail the main operation if sync fails
		frappe.logger().warning(f"⚠️ Materialized view sync failed: {str(e)}")


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


# detect_teacher_conflicts function removed - no longer needed with unlimited teachers support


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

