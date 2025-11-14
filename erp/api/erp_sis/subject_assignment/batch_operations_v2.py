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
	
	# PHASE 3: SYNC TIMETABLE
	frappe.logger().info(f"🔄 Phase 3: Syncing timetable")
	
	sync_result = sync_all_assignments(apply_result["assignment_ids"])
	
	frappe.logger().info(
		f"✅ Phase 3: Timetable synced - "
		f"Success: {sync_result['synced']}/{len(apply_result['assignment_ids'])}"
	)
	
	# Return summary
	return {
		"success": True,
		"message": f"Batch update complete: {apply_result['stats']['created']}C, "
		           f"{apply_result['stats']['updated']}U, {apply_result['stats']['deleted']}D",
		"stats": {
			**apply_result["stats"],
			"synced": sync_result["synced"]
		},
		"details": apply_result["details"] + sync_result["details"]
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
		
		# For update/delete, assignment_id must exist
		if action in ["update", "delete"]:
			assignment_id = assignment.get("assignment_id")
			if not assignment_id:
				errors.append(f"Assignment {idx}: assignment_id required for {action}")
				continue
			
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

