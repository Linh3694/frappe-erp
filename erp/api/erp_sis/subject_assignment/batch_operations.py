# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

"""
Batch Operations V2 - Refactored

Nguyên tắc thiết kế:
1. Clear transaction boundaries
2. VALIDATE ALL → APPLY ALL pattern
3. Rollback toàn bộ nếu có lỗi
4. Detailed logging cho debugging

Performance: <1000ms cho 50 assignments
"""

import frappe
from typing import Dict, List, Optional
from .timetable_sync_v2 import sync_assignment_to_timetable


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_update_assignments(teacher_id=None, assignments=None):
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
		]
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
		return _batch_update_assignments_internal(teacher_id, assignments)
		
	except Exception as e:
		frappe.log_error(f"Batch update failed: {str(e)}")
		return {
			"success": False,
			"message": f"Critical error: {str(e)}"
		}


def _batch_update_assignments_internal(teacher_id: str, assignments: List[Dict]) -> Dict:
	"""
	Internal function that does the actual work.
	Can be called directly with parameters (no request parsing).
	"""
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
	
	sync_result = sync_all_assignments(apply_result["assignment_ids"])
	
	frappe.logger().info(
		f"✅ Phase 3: Timetable synced - "
		f"Success: {sync_result['synced']}/{len(apply_result['assignment_ids'])}"
	)
	
	# PHASE 4: SYNC TEACHER TIMETABLE (Materialized View)
	frappe.logger().info(f"🔄 Phase 4: Syncing Teacher Timetable (materialized view)")
	
	teacher_timetable_result = sync_teacher_timetable_bulk(
		teacher_id=teacher_id,
		assignment_ids=apply_result["assignment_ids"]
	)
	
	frappe.logger().info(
		f"✅ Phase 4: Teacher Timetable synced - "
		f"Created: {teacher_timetable_result['created']}, "
		f"Errors: {teacher_timetable_result['errors']}"
	)
	
	# Return summary
	return {
		"success": True,
		"message": f"Batch update complete: {apply_result['stats']['created']}C, "
		           f"{apply_result['stats']['updated']}U, {apply_result['stats']['deleted']}D",
		"stats": {
			**apply_result["stats"],
			"synced": sync_result["synced"],
			"teacher_timetable_synced": teacher_timetable_result["created"]
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
				details.append(f"✓ Deleted assignment {result['assignment_id']}")
		
		# Commit transaction
		frappe.db.commit()
		
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
	"""Delete single assignment"""
	assignment_id = assignment["assignment_id"]
	
	# Check if assignment exists before deleting
	if not frappe.db.exists("SIS Subject Assignment", assignment_id):
		frappe.logger().warning(f"Assignment {assignment_id} not found, skipping delete")
		return {"assignment_id": assignment_id, "skipped": True}
	
	frappe.delete_doc(
		"SIS Subject Assignment",
		assignment_id,
		ignore_permissions=True,
		force=True
	)
	
	return {"assignment_id": assignment_id}


# ============= SYNC PHASE =============

def sync_all_assignments(assignment_ids: List[str]) -> Dict:
	"""
	Sync timetable cho tất cả assignments.
	
	Returns:
		{
			"synced": int,
			"failed": int,
			"details": List[str]
		}
	"""
	synced = 0
	failed = 0
	details = []
	
	for assignment_id in assignment_ids:
		try:
			result = sync_assignment_to_timetable(assignment_id)
			
			if result["success"]:
				synced += 1
				details.append(
					f"✓ Synced {assignment_id}: "
					f"{result['rows_updated']}U + {result['rows_created']}C rows"
				)
			else:
				failed += 1
				details.append(f"✗ Failed to sync {assignment_id}: {result['message']}")
				
		except Exception as e:
			failed += 1
			details.append(f"✗ Error syncing {assignment_id}: {str(e)}")
			frappe.log_error(f"Sync error for {assignment_id}: {str(e)}")
	
	return {
		"synced": synced,
		"failed": failed,
		"details": details
	}


def sync_teacher_timetable_bulk(teacher_id: str, assignment_ids: List[str]) -> Dict:
	"""
	Sync Teacher Timetable (materialized view) for all affected classes.
	
	Strategy:
	1. Get all affected classes from assignments
	2. Call bulk sync engine ONCE per class (not per assignment!)
	3. Return summary
	
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
	from ..timetable.bulk_sync_engine import sync_instance_bulk
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
			for instance in instances:
				try:
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
					
					created += teacher_count
					details.append(
						f"✓ Instance {instance_id}: {teacher_count} teacher entries created "
						f"(deleted {deleted or 0} old)"
					)
					
					frappe.logger().info(
						f"✅ Teacher Timetable Sync: created {teacher_count} entries "
						f"for instance {instance_id}"
					)
					
				except Exception as instance_error:
					errors += 1
					error_msg = f"✗ Error syncing instance {instance.name}: {str(instance_error)}"
					details.append(error_msg)
					frappe.logger().error(error_msg)
					import traceback
					frappe.logger().error(traceback.format_exc())
		
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

