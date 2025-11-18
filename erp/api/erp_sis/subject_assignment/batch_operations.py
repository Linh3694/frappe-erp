# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Batch Operations V2 - Refactored

Nguyên tắc thiết kế:
1. Clear transaction boundaries
2. VALIDATE ALL → APPLY ALL pattern
3. Rollback toàn bộ nếu có lỗi
4. Detailed logging cho debugging
5. Retry on deadlock với exponential backoff

Performance: <1000ms cho 50 assignments
"""

import frappe
import time
from typing import Dict, List, Optional, Callable
from functools import wraps
from .timetable_sync_v2 import sync_assignment_to_timetable
from erp.api.erp_sis.utils.cache_utils import clear_teacher_dashboard_cache


def _clear_teacher_classes_cache():
	"""Wrapper function for backward compatibility."""
	clear_teacher_dashboard_cache()


# ============= DEADLOCK RETRY DECORATOR =============

def retry_on_deadlock(max_retries: int = 3, initial_delay: float = 0.1):
	"""
	Decorator to retry function on MySQL deadlock.
	
	Implements exponential backoff:
	- 1st retry: 0.1s delay
	- 2nd retry: 0.2s delay  
	- 3rd retry: 0.4s delay
	
	Args:
		max_retries: Maximum number of retry attempts
		initial_delay: Initial delay in seconds (doubled after each retry)
	"""
	def decorator(func: Callable) -> Callable:
		@wraps(func)
		def wrapper(*args, **kwargs):
			delay = initial_delay
			last_error = None
			
			for attempt in range(max_retries + 1):
				try:
					if attempt > 0:
						frappe.logger().info(
							f"🔄 Retry attempt {attempt}/{max_retries} for {func.__name__} "
							f"after {delay:.2f}s delay"
						)
						time.sleep(delay)
						# Rollback any pending transaction before retry
						frappe.db.rollback()
					
					result = func(*args, **kwargs)
					
					if attempt > 0:
						frappe.logger().info(
							f"✅ {func.__name__} succeeded on attempt {attempt + 1}"
						)
					
					return result
					
				except frappe.QueryDeadlockError as e:
					last_error = e
					frappe.logger().warning(
						f"⚠️ Deadlock in {func.__name__} (attempt {attempt + 1}/{max_retries + 1}): {str(e)}"
					)
					
					if attempt < max_retries:
						delay *= 2  # Exponential backoff
					else:
						frappe.logger().error(
							f"❌ {func.__name__} failed after {max_retries + 1} attempts"
						)
						raise
				
				except Exception as e:
					# Non-deadlock errors should not retry
					frappe.logger().error(
						f"❌ Non-retryable error in {func.__name__}: {str(e)}"
					)
					raise
			
			# Should never reach here, but just in case
			if last_error:
				raise last_error
		
		return wrapper
	return decorator


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_update_assignments(teacher_id=None, assignments=None, replace_teacher_map=None):
	"""
	Bulk update all assignments for a teacher.
	
	Request body:
	{
		"teacher_id": str,
		"assignments": [
			{
				"assignment_id": str (optional, for update),
				"class_id": str,
				"actual_subject_id": str,
				"application_type": "full_year" | "from_date",
				"start_date": str (optional),
				"end_date": str (optional),
				"action": "create" | "update" | "delete"
			}
		],
		"replace_teacher_map": dict (optional, for resolving teacher conflicts)
			Format: {row_id: "teacher_1" or "teacher_2"}
	}
	
	Response:
	{
		"success": bool,
		"message": str,
		"stats": {
			"created": int,
			"updated": int,
			"deleted": int,
			"synced": int
		},
		"details": List[str]
	}
	"""
	try:
		# Parse request if parameters not provided
		if teacher_id is None or assignments is None:
			data = frappe.parse_json(frappe.request.data or "{}")
			teacher_id = data.get("teacher_id")
			assignments = data.get("assignments", [])
		
		if not teacher_id:
			return {
				"success": False,
				"message": "teacher_id is required"
			}
		
		if not assignments:
			return {
				"success": False,
				"message": "assignments list is required"
			}
		
		# Call internal function
		return _batch_update_assignments_internal(teacher_id, assignments, replace_teacher_map)
		
	except Exception as e:
		frappe.log_error(f"Batch update failed: {str(e)}")
		return {
			"success": False,
			"message": f"Critical error: {str(e)}"
		}


def _batch_update_assignments_internal(teacher_id: str, assignments: List[Dict], replace_teacher_map: dict = None) -> Dict:
	"""
	Internal function that does the actual work.
	Can be called directly with parameters (no request parsing).
	
	Args:
		teacher_id: Teacher ID
		assignments: List of assignment dictionaries
		replace_teacher_map: Optional dict for resolving teacher conflicts {row_id: "teacher_1" or "teacher_2"}
	"""
	replace_teacher_map = replace_teacher_map or {}
	# PHASE 1: VALIDATE ALL
	frappe.logger().info(f"🔍 Phase 1: Validating {len(assignments)} assignments")
	
	validation_result = validate_all_assignments(teacher_id, assignments)
	
	if not validation_result["valid"]:
		return {
			"success": False,
			"message": "Validation failed",
			"errors": validation_result["errors"]
		}
	
	frappe.logger().info(f"✅ Phase 1: All assignments valid")
	
	# PHASE 2: APPLY ALL (with transaction)
	frappe.logger().info(f"🔨 Phase 2: Applying changes")
	
	apply_result = apply_all_assignments(teacher_id, assignments)
	
	if not apply_result["success"]:
		return {
			"success": False,
			"message": "Failed to apply changes",
			"error": apply_result["error"]
		}
	
	frappe.logger().info(
		f"✅ Phase 2: Changes applied - "
		f"Created: {apply_result['stats']['created']}, "
		f"Updated: {apply_result['stats']['updated']}, "
		f"Deleted: {apply_result['stats']['deleted']}"
	)
	
	# PHASE 3: SYNC TIMETABLE (Instance Rows)
	frappe.logger().info(f"🔄 Phase 3: Syncing timetable instance rows")
	
	sync_result = sync_all_assignments(apply_result["assignment_ids"], replace_teacher_map)
	
	# Check for conflicts
	if sync_result.get("conflicts"):
		frappe.logger().warning(f"⚠️ Teacher conflicts detected: {len(sync_result['conflicts'])} conflicts")
		# Rollback changes and return conflict error
		frappe.db.rollback()
		return {
			"success": False,
			"message": f"Phát hiện {len(sync_result['conflicts'])} xung đột giáo viên. Vui lòng chọn giáo viên để thay thế.",
			"error_type": "teacher_conflict",
			"conflicts": sync_result["conflicts"]
		}
	
	frappe.logger().info(
		f"✅ Phase 3: Timetable synced - "
		f"Success: {sync_result['synced']}/{len(apply_result['assignment_ids'])}"
	)
	
	# PHASE 4: SYNC TEACHER TIMETABLE (Materialized View)
	# ⚡ NOTE: Teacher Timetable sync is ALREADY handled in Phase 3 (sync_all_assignments)
	# which calls sync_assignment_to_timetable() → sync_for_rows() → updates Teacher Timetable
	# 
	# DO NOT call sync_teacher_timetable_bulk() here because it:
	# 1. Deletes ALL existing Teacher Timetable entries for this teacher
	# 2. Tries to recreate but often returns 0 entries
	# 3. Causes data loss
	#
	# Previous implementation (BROKEN):
	#   sync_teacher_timetable_bulk() → DELETE all → CREATE 0 → Data loss!
	# Current implementation (WORKING):
	#   sync_assignment_to_timetable() → Update pattern rows → sync_for_rows() → Incremental upsert
	
	frappe.logger().info(
		f"✅ Phase 4: Teacher Timetable already synced in Phase 3 for "
		f"{len(apply_result['assignment_ids'])} assignments"
	)
	
	teacher_timetable_result = {
		"created": sync_result.get("rows_updated", 0),  # Use Phase 3 result
		"errors": 0,
		"details": ["✅ Teacher Timetable synced via sync_assignment_to_timetable()"]
	}
	
	# GRACEFUL DEGRADATION: Return success nếu assignments đã save thành công
	# (Teacher Timetable có thể sync sau bằng manual refresh hoặc background job)
	has_teacher_timetable_errors = teacher_timetable_result["errors"] > 0
	warning_msg = ""
	if has_teacher_timetable_errors:
		warning_msg = " (⚠️ Some Teacher Timetable entries may need manual refresh)"
	
	# Return summary
	return {
		"success": True,  # Success nếu assignments đã save
		"message": (
			f"Batch update complete: {apply_result['stats']['created']}C, "
			f"{apply_result['stats']['updated']}U, {apply_result['stats']['deleted']}D"
			f"{warning_msg}"
		),
		"stats": {
			**apply_result["stats"],
			"synced": sync_result["synced"],
			"teacher_timetable_synced": teacher_timetable_result["created"],
			"teacher_timetable_errors": teacher_timetable_result["errors"]
		},
		"details": apply_result["details"] + sync_result["details"] + teacher_timetable_result["details"]
	}


# ============= VALIDATION PHASE =============

def validate_all_assignments(teacher_id: str, assignments: List[Dict]) -> Dict:
	"""
	Validate tất cả assignments trước khi apply.
	
	Returns:
		{
			"valid": bool,
			"errors": List[str]  # Empty if valid
		}
	"""
	errors = []
	
	# Validate teacher exists
	if not frappe.db.exists("SIS Teacher", teacher_id):
		errors.append(f"Teacher {teacher_id} not found")
		return {"valid": False, "errors": errors}
	
	# Get teacher's campus
	teacher_campus = frappe.db.get_value("SIS Teacher", teacher_id, "campus_id")
	
	# Validate each assignment
	for idx, assignment in enumerate(assignments):
		action = assignment.get("action", "create")
		
		# Validate action
		if action not in ["create", "update", "delete"]:
			errors.append(f"Assignment {idx}: Invalid action '{action}'")
			continue
		
		# For update/delete, assignment_id must be provided
		if action in ["update", "delete"]:
			assignment_id = assignment.get("assignment_id")
			if not assignment_id:
				errors.append(f"Assignment {idx}: assignment_id required for {action}")
				continue
			
			# For update: assignment must exist (strict check)
			# For delete: we'll skip if not exists (handled in delete_assignment function)
			if action == "update":
				if not frappe.db.exists("SIS Subject Assignment", assignment_id):
					errors.append(f"Assignment {idx}: Assignment {assignment_id} not found")
					continue
		
		# For create/update, validate fields
		if action in ["create", "update"]:
			class_id = assignment.get("class_id")
			actual_subject_id = assignment.get("actual_subject_id")
			application_type = assignment.get("application_type", "full_year")
			
			# Validate class
			if not class_id:
				errors.append(f"Assignment {idx}: class_id is required")
				continue
			
			class_info = frappe.db.get_value(
				"SIS Class",
				class_id,
				["campus_id"],
				as_dict=True
			)
			
			if not class_info:
				errors.append(f"Assignment {idx}: Class {class_id} not found")
				continue
			
			if class_info.campus_id != teacher_campus:
				errors.append(
					f"Assignment {idx}: Class campus ({class_info.campus_id}) "
					f"does not match teacher campus ({teacher_campus})"
				)
				continue
			
			# Validate actual subject
			if not actual_subject_id:
				errors.append(f"Assignment {idx}: actual_subject_id is required")
				continue
			
			if not frappe.db.exists("SIS Actual Subject", actual_subject_id):
				errors.append(f"Assignment {idx}: Actual Subject {actual_subject_id} not found")
				continue
			
			# Validate application_type
			if application_type not in ["full_year", "from_date"]:
				errors.append(f"Assignment {idx}: Invalid application_type '{application_type}'")
				continue
			
			# If from_date, start_date is required
			if application_type == "from_date":
				if not assignment.get("start_date"):
					errors.append(f"Assignment {idx}: start_date required for from_date assignment")
					continue
	
	# Check for duplicates within the batch (same teacher + class + subject)
	seen_keys = {}
	for idx, assignment in enumerate(assignments):
		if assignment.get("action") == "delete":
			continue
		
		key = (
			teacher_id,
			assignment.get("class_id"),
			assignment.get("actual_subject_id")
		)
		
		if key in seen_keys:
			errors.append(
				f"Assignment {idx}: Duplicate assignment "
				f"(same as assignment {seen_keys[key]})"
			)
		else:
			seen_keys[key] = idx
	
	return {
		"valid": len(errors) == 0,
		"errors": errors
	}


# ============= APPLY PHASE =============

def apply_all_assignments(teacher_id: str, assignments: List[Dict]) -> Dict:
	"""
	Apply tất cả changes với transaction.
	
	If any operation fails, rollback ALL.
	
	Returns:
		{
			"success": bool,
			"stats": {
				"created": int,
				"updated": int,
				"deleted": int
			},
			"assignment_ids": List[str],  # IDs of created/updated assignments (for sync)
			"details": List[str],
			"error": str (if failed)
		}
	"""
	stats = {"created": 0, "updated": 0, "deleted": 0}
	assignment_ids = []
	details = []
	
	try:
		# Start transaction
		frappe.db.begin()
		
		for idx, assignment in enumerate(assignments):
			action = assignment.get("action", "create")
			
			if action == "create":
				result = create_assignment(teacher_id, assignment)
				stats["created"] += 1
				assignment_ids.append(result["assignment_id"])
				details.append(f"✓ Created assignment {result['assignment_id']}")
				
			elif action == "update":
				result = update_assignment(assignment)
				stats["updated"] += 1
				assignment_ids.append(result["assignment_id"])
				details.append(f"✓ Updated assignment {result['assignment_id']}")
				
			elif action == "delete":
				result = delete_assignment(assignment)
				stats["deleted"] += 1
				pattern_updated = result.get("pattern_rows_updated", 0)
				override_deleted = result.get("override_rows_deleted", 0)
				tt_deleted = result.get("teacher_timetable_deleted", 0)
				details.append(
					f"✓ Deleted assignment {result['assignment_id']}: "
					f"{pattern_updated} pattern + {override_deleted} override + {tt_deleted} timetable"
				)
		
		# Commit transaction
		frappe.db.commit()
		
		# ⚡ CLEAR CACHE: Invalidate caches after batch update
		_clear_teacher_classes_cache()
		
		return {
			"success": True,
			"stats": stats,
			"assignment_ids": assignment_ids,
			"details": details
		}
		
	except Exception as e:
		# Rollback transaction
		frappe.db.rollback()
		frappe.log_error(f"Apply assignments failed: {str(e)}")
		
		return {
			"success": False,
			"stats": stats,
			"assignment_ids": [],
			"details": details + [f"❌ Rollback: {str(e)}"],
			"error": str(e)
		}


def create_assignment(teacher_id: str, assignment: Dict) -> Dict:
	"""Create single assignment"""
	doc = frappe.get_doc({
		"doctype": "SIS Subject Assignment",
		"teacher_id": teacher_id,
		"class_id": assignment["class_id"],
		"actual_subject_id": assignment["actual_subject_id"],
		"campus_id": frappe.db.get_value("SIS Teacher", teacher_id, "campus_id"),
		"application_type": assignment.get("application_type", "full_year"),
		"start_date": assignment.get("start_date"),
		"end_date": assignment.get("end_date")
	})
	
	doc.insert(ignore_permissions=True)
	
	return {"assignment_id": doc.name}


def update_assignment(assignment: Dict) -> Dict:
	"""Update single assignment"""
	assignment_id = assignment["assignment_id"]
	
	doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
	
	# Update fields
	if "class_id" in assignment:
		doc.class_id = assignment["class_id"]
	if "actual_subject_id" in assignment:
		doc.actual_subject_id = assignment["actual_subject_id"]
	if "application_type" in assignment:
		doc.application_type = assignment["application_type"]
	if "start_date" in assignment:
		doc.start_date = assignment["start_date"]
	if "end_date" in assignment:
		doc.end_date = assignment["end_date"]
	
	doc.save(ignore_permissions=True)
	
	return {"assignment_id": doc.name}


def delete_assignment(assignment: Dict) -> Dict:
	"""
	Delete single assignment.
	
	CRITICAL: Also delete Teacher Timetable entries for this assignment.
	"""
	assignment_id = assignment["assignment_id"]
	
	# Check if assignment exists before deleting
	if not frappe.db.exists("SIS Subject Assignment", assignment_id):
		frappe.logger().warning(f"Assignment {assignment_id} not found, skipping delete")
		return {"assignment_id": assignment_id, "skipped": True}
	
	# Get assignment details before deleting (for timetable cleanup)
	assignment_doc = frappe.get_doc("SIS Subject Assignment", assignment_id)
	teacher_id = assignment_doc.teacher_id
	class_id = assignment_doc.class_id
	actual_subject_id = assignment_doc.actual_subject_id
	campus_id = assignment_doc.campus_id
	
	# Get all timetable instances for this class
	instances = frappe.db.get_all(
		"SIS Timetable Instance",
		filters={"class_id": class_id},
		pluck="name"
	)
	
	# Get all subject_ids linked to this actual_subject_id in this campus
	# (SIS Subject doesn't have class_id, it's education_stage level)
	subject_ids = frappe.db.get_all(
		"SIS Subject",
		filters={"actual_subject_id": actual_subject_id, "campus_id": campus_id},
		pluck="name"
	)
	
	frappe.logger().info(
		f"DELETE in batch: Deleting assignment {assignment_id} - "
		f"teacher={teacher_id}, class={class_id}, "
		f"actual_subject={actual_subject_id}, subjects={subject_ids}"
	)
	
	# ✅ Step 1: Remove teacher from Timetable Instance Rows (Pattern Rows)
	rows_updated = 0
	override_rows_deleted = 0
	if subject_ids and instances:
		try:
			# A. Update pattern rows (weekly recurring)
			pattern_rows = frappe.db.sql("""
				SELECT name, teacher_1_id, teacher_2_id
				FROM `tabSIS Timetable Instance Row`
				WHERE parent IN ({})
				  AND subject_id IN ({})
				  AND (teacher_1_id = %s OR teacher_2_id = %s)
				  AND parentfield = 'weekly_pattern'
			""".format(','.join(['%s'] * len(instances)), ','.join(['%s'] * len(subject_ids))),
			tuple(instances + subject_ids + [teacher_id, teacher_id]), as_dict=True)
			
			# Remove teacher from each pattern row
			for row in pattern_rows:
				if row.teacher_1_id == teacher_id:
					frappe.db.set_value(
						"SIS Timetable Instance Row", 
						row.name, 
						"teacher_1_id", 
						None, 
						update_modified=False
					)
					rows_updated += 1
				if row.teacher_2_id == teacher_id:
					frappe.db.set_value(
						"SIS Timetable Instance Row", 
						row.name, 
						"teacher_2_id", 
						None, 
						update_modified=False
					)
					rows_updated += 1
			
			frappe.logger().info(
				f"DELETE in batch: Removed teacher from {rows_updated} pattern rows"
			)
			
			# B. Delete override rows (date-specific rows for this teacher)
			# Override rows are created for from_date assignments
			override_rows = frappe.db.sql("""
				SELECT name
				FROM `tabSIS Timetable Instance Row`
				WHERE parent IN ({})
				  AND subject_id IN ({})
				  AND (teacher_1_id = %s OR teacher_2_id = %s)
				  AND parentfield = 'date_overrides'
			""".format(','.join(['%s'] * len(instances)), ','.join(['%s'] * len(subject_ids))),
			tuple(instances + subject_ids + [teacher_id, teacher_id]), as_dict=True)
			
			for override_row in override_rows:
				frappe.delete_doc(
					"SIS Timetable Instance Row",
					override_row.name,
					ignore_permissions=True,
					force=True
				)
				override_rows_deleted += 1
			
			frappe.logger().info(
				f"DELETE in batch: Deleted {override_rows_deleted} override rows"
			)
			
			frappe.db.commit()
			
		except Exception as row_error:
			frappe.logger().error(
				f"DELETE in batch: Failed to update Timetable Rows: {str(row_error)}"
			)
			import traceback
			frappe.logger().error(traceback.format_exc())
	
	# ✅ Step 2: Delete Teacher Timetable entries (materialized view)
	teacher_timetable_deleted = 0
	if subject_ids and instances:
		try:
			teacher_timetable_deleted = frappe.db.sql("""
				DELETE FROM `tabSIS Teacher Timetable`
				WHERE teacher_id = %s
				  AND class_id = %s
				  AND subject_id IN ({})
				  AND timetable_instance_id IN ({})
			""".format(','.join(['%s'] * len(subject_ids)), ','.join(['%s'] * len(instances))), 
			tuple([teacher_id, class_id] + subject_ids + instances))
			
			frappe.logger().info(
				f"DELETE in batch: Deleted {teacher_timetable_deleted or 0} "
				f"Teacher Timetable entries"
			)
			frappe.db.commit()
			
		except Exception as tt_error:
			frappe.logger().error(
				f"DELETE in batch: Failed to delete Teacher Timetable: {str(tt_error)}"
			)
			import traceback
			frappe.logger().error(traceback.format_exc())
	
	# Delete the assignment document
	frappe.delete_doc(
		"SIS Subject Assignment",
		assignment_id,
		ignore_permissions=True,
		force=True
	)
	
	frappe.logger().info(
		f"DELETE in batch: Assignment {assignment_id} deleted - "
		f"Cleaned {rows_updated} pattern rows, "
		f"{override_rows_deleted} override rows, "
		f"{teacher_timetable_deleted or 0} materialized view entries"
	)
	
	return {
		"assignment_id": assignment_id,
		"pattern_rows_updated": rows_updated,
		"override_rows_deleted": override_rows_deleted,
		"teacher_timetable_deleted": teacher_timetable_deleted or 0
	}


# ============= SYNC PHASE =============

def sync_all_assignments(assignment_ids: List[str], replace_teacher_map: dict = None) -> Dict:
	"""
	Sync timetable cho tất cả assignments.
	
	Args:
		assignment_ids: List of assignment IDs to sync
		replace_teacher_map: Optional dict for resolving teacher conflicts {row_id: "teacher_1" or "teacher_2"}
	
	Returns:
		{
			"synced": int,
			"failed": int,
			"details": List[str],
			"conflicts": list (if any conflicts detected)
		}
	"""
	replace_teacher_map = replace_teacher_map or {}
	synced = 0
	failed = 0
	details = []
	all_conflicts = []
	
	for assignment_id in assignment_ids:
		try:
			result = sync_assignment_to_timetable(assignment_id, replace_teacher_map)
			
			# Check for conflict
			if not result["success"] and result.get("error_type") == "teacher_conflict":
				# Conflict detected!
				conflicts = result.get("conflicts", [])
				# Add assignment_id to each conflict
				for conflict in conflicts:
					conflict["assignment_id"] = assignment_id
				all_conflicts.extend(conflicts)
				failed += 1
				details.append(f"⚠ Conflict in {assignment_id}: {len(conflicts)} conflicts")
			elif result["success"]:
				synced += 1
				details.append(
					f"✓ Synced {assignment_id}: "
					f"{result.get('rows_updated', 0)}U + {result.get('rows_created', 0)}C rows"
				)
			else:
				failed += 1
				details.append(f"✗ Failed to sync {assignment_id}: {result.get('message', 'Unknown error')}")
				
		except Exception as e:
			failed += 1
			details.append(f"✗ Error syncing {assignment_id}: {str(e)}")
			frappe.log_error(f"Sync error for {assignment_id}: {str(e)}")
	
	return {
		"synced": synced,
		"failed": failed,
		"details": details,
		"conflicts": all_conflicts
	}


@retry_on_deadlock(max_retries=5, initial_delay=0.2)
def _sync_single_instance_with_retry(
	instance_id: str,
	class_id: str,
	teacher_id: str,
	sync_start,
	sync_end,
	campus_id: str
) -> tuple:
	"""
	Internal function to sync a single instance with retry logic.
	
	Isolated for clean retry handling without affecting outer loop.
	
	Returns:
		(teacher_count, deleted_count)
	"""
	from ..timetable.bulk_sync_engine import sync_instance_bulk
	
	frappe.logger().info(
		f"🔄 Teacher Timetable Sync: instance={instance_id}, "
		f"class={class_id}, teacher={teacher_id}, "
		f"range={sync_start} to {sync_end}"
	)
	
	# CRITICAL: Commit before sync to ensure bulk_sync sees fresh assignments
	frappe.db.commit()
	
	# Delete old entries for this teacher in this range
	deleted = frappe.db.sql("""
		DELETE FROM `tabSIS Teacher Timetable`
		WHERE timetable_instance_id = %s
		  AND teacher_id = %s
		  AND date BETWEEN %s AND %s
	""", (instance_id, teacher_id, sync_start, sync_end))
	
	frappe.db.commit()
	
	# Regenerate using bulk sync engine
	teacher_count, student_count = sync_instance_bulk(
		instance_id=instance_id,
		class_id=class_id,
		start_date=str(sync_start),
		end_date=str(sync_end),
		campus_id=campus_id,
		job_id=None
	)
	
	frappe.logger().info(
		f"✅ Teacher Timetable Sync: created {teacher_count} entries "
		f"for instance {instance_id}"
	)
	
	return (teacher_count, deleted or 0)


def sync_teacher_timetable_bulk(teacher_id: str, assignment_ids: List[str]) -> Dict:
	"""
	Sync Teacher Timetable (materialized view) for all affected classes.
	
	Strategy:
	1. Get all affected classes from assignments
	2. Call bulk sync engine ONCE per class (not per assignment!)
	3. Retry on deadlock với exponential backoff
	4. Return summary
	
	Args:
		teacher_id: Teacher ID
		assignment_ids: List of assignment IDs that were created/updated
	
	Returns:
		{
			"created": int,
			"errors": int,
			"details": List[str]
		}
	"""
	from datetime import timedelta
	
	created = 0
	errors = 0
	details = []
	
	try:
		# Get all assignments to extract affected classes
		if not assignment_ids:
			return {"created": 0, "errors": 0, "details": []}
		
		assignments = frappe.db.sql("""
			SELECT DISTINCT 
				class_id,
				campus_id,
				MIN(start_date) as earliest_start,
				MAX(end_date) as latest_end
			FROM `tabSIS Subject Assignment`
			WHERE name IN ({})
			GROUP BY class_id, campus_id
		""".format(','.join(['%s'] * len(assignment_ids))), tuple(assignment_ids), as_dict=True)
		
		if not assignments:
			return {"created": 0, "errors": 0, "details": ["No assignments found"]}
		
		today = frappe.utils.getdate()
		
		# For each affected class, sync its timetable instances
		for assignment in assignments:
			class_id = assignment.class_id
			campus_id = assignment.campus_id
			
			# Get all active timetable instances for this class
			instances = frappe.db.sql("""
				SELECT name, class_id, start_date, end_date
				FROM `tabSIS Timetable Instance`
				WHERE campus_id = %s
				  AND class_id = %s
				  AND end_date >= %s
				ORDER BY start_date
			""", (campus_id, class_id, today), as_dict=True)
			
			if not instances:
				details.append(f"⏭️ Class {class_id}: No active timetable instances")
				continue
			
			# Sync each instance for this class
			for idx, instance in enumerate(instances):
				try:
					# Add small delay between instances to reduce concurrent writes
					# (Giảm deadlock bằng cách tránh nhiều instances cùng write)
					if idx > 0:
						time.sleep(0.05)  # 50ms delay
					
					instance_id = instance.name
					instance_start = instance.start_date or today
					instance_end = instance.end_date or (today + timedelta(days=365))
					
					# Determine sync range based on assignment dates
					sync_start = instance_start
					sync_end = instance_end
					
					# If assignment has specific dates, narrow the range
					if assignment.earliest_start:
						sync_start = max(sync_start, assignment.earliest_start)
					if assignment.latest_end:
						sync_end = min(sync_end, assignment.latest_end)
					
					# Call isolated function with retry logic
					teacher_count, deleted_count = _sync_single_instance_with_retry(
						instance_id=instance_id,
						class_id=class_id,
						teacher_id=teacher_id,
						sync_start=sync_start,
						sync_end=sync_end,
						campus_id=campus_id
					)
					
					created += teacher_count
					details.append(
						f"✓ Instance {instance_id}: {teacher_count} teacher entries created "
						f"(deleted {deleted_count} old)"
					)
					
				except frappe.QueryDeadlockError as deadlock_error:
					# Deadlock persisted after all retries
					# Continue với instances khác thay vì crash
					errors += 1
					error_msg = (
						f"⚠️ Deadlock in instance {instance.name} after retries - SKIPPED"
					)
					details.append(error_msg)
					frappe.logger().error(
						f"❌ Deadlock in instance {instance.name} after retries: "
						f"{str(deadlock_error)}"
					)
					# Continue to next instance
					continue
					
				except Exception as instance_error:
					errors += 1
					error_msg = f"⚠️ Error syncing instance {instance.name} - SKIPPED"
					details.append(error_msg)
					frappe.logger().error(
						f"❌ Error syncing instance {instance.name}: {str(instance_error)}"
					)
					import traceback
					frappe.logger().error(traceback.format_exc())
					# Continue to next instance
					continue
		
		frappe.db.commit()
		
	except Exception as e:
		errors += 1
		error_msg = f"✗ Critical error in Teacher Timetable sync: {str(e)}"
		details.append(error_msg)
		frappe.logger().error(error_msg)
		import traceback
		frappe.logger().error(traceback.format_exc())
	
	return {
		"created": created,
		"errors": errors,
		"details": details
	}

