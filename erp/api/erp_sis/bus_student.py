# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.compreFace_service import compreFace_service

@frappe.whitelist()
def get_all_bus_students():
	"""Get all bus students without pagination - always returns full dataset"""
	try:
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			# Fallback to default if no campus found
			campus_id = "campus-1"

		# Apply campus filtering for data isolation
		filters = {"campus_id": campus_id}

		# Get all bus students with route information
		students = frappe.db.sql("""
			SELECT
				bs.name, bs.full_name, bs.student_code, bs.class_id,
				bs.route_id, bs.status, bs.campus_id, bs.school_year_id,
				bs.creation as created_at, bs.modified as updated_at,
				r.route_name, c.title as class_name
			FROM `tabSIS Bus Student` bs
			LEFT JOIN `tabSIS Bus Route` r ON bs.route_id = r.name
			LEFT JOIN `tabSIS Class` c ON bs.class_id = c.name
			WHERE bs.campus_id = %s
			ORDER BY bs.full_name ASC
		""", (campus_id,), as_dict=True)

		return success_response(
			data=students,
			message="Bus students retrieved successfully"
		)

	except Exception as e:
		frappe.log_error(f"Error getting bus students: {str(e)}")
		return error_response(f"Failed to get bus students: {str(e)}")

@frappe.whitelist()
def get_bus_student(name):
	"""Get a single bus student by name"""
	try:
		# Get bus student with route and class information
		student = frappe.db.sql("""
			SELECT
				bs.name, bs.full_name, bs.student_code, bs.class_id,
				bs.route_id, bs.status, bs.campus_id, bs.school_year_id,
				bs.creation as created_at, bs.modified as updated_at,
				r.route_name, c.title as class_name
			FROM `tabSIS Bus Student` bs
			LEFT JOIN `tabSIS Bus Route` r ON bs.route_id = r.name
			LEFT JOIN `tabSIS Class` c ON bs.class_id = c.name
			WHERE bs.name = %s
		""", (name,), as_dict=True)

		if student:
			return success_response(
				data=student[0],
				message="Bus student retrieved successfully"
			)
		else:
			return error_response("Bus student not found")

	except Exception as e:
		frappe.log_error(f"Error getting bus student: {str(e)}")
		return error_response(f"Failed to get bus student: {str(e)}")

@frappe.whitelist()
def create_bus_student(**data):
	"""Create a new bus student"""
	try:
		doc = frappe.get_doc({
			"doctype": "SIS Bus Student",
			**data
		})
		doc.insert()
		frappe.db.commit()

		# Sync to CompreFace in background
		if doc.status == "Active":  # Only sync active students
			# Get student_id from CRM Student using student_code
			student_record = frappe.get_all("CRM Student",
				filters={"student_code": doc.student_code},
				fields=["name"],
				limit=1
			)

			if student_record:
				crm_student_id = student_record[0].name
				frappe.enqueue(
					method="erp.api.erp_sis.bus_student.sync_student_to_compreface_background",
					queue="default",
					timeout=300,
					job_name=f"sync_student_{doc.student_code}",
					**{
						"student_id": crm_student_id,  # Use CRM Student ID
						"student_name": doc.full_name,
						"campus_id": doc.campus_id,
						"school_year_id": doc.school_year_id
					}
				)

		return success_response(
			data=doc.as_dict(),
			message="Bus student created successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error creating bus student: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus student: {str(e)}")


@frappe.whitelist(methods=["POST"])
def create_bus_student_from_sis():
	"""Create a new bus student from SIS student data"""
	try:
		# Try multiple sources for data
		student_id = None
		status = "Active"

		# Try from form_dict first (for form-encoded data)
		if frappe.local.form_dict:
			student_id = frappe.local.form_dict.get("student_id")
			status = frappe.local.form_dict.get("status", "Active")

		# Try to parse JSON from request data
		if not student_id and hasattr(frappe.request, 'data') and frappe.request.data:
			try:
				import json
				raw_data = frappe.request.data
				if isinstance(raw_data, bytes):
					raw_data = raw_data.decode('utf-8')

				json_data = json.loads(raw_data)
				student_id = json_data.get("student_id")
				status = json_data.get("status", "Active")
			except Exception as e:
				pass  # JSON parse failed, continue to next method

		# Last resort: try from frappe.form_dict
		if not student_id and hasattr(frappe, 'form_dict') and frappe.form_dict:
			student_id = frappe.form_dict.get("student_id")
			status = frappe.form_dict.get("status", "Active")

		if not student_id or str(student_id).strip() == "":
			frappe.logger().error(f"Student ID validation failed. student_id: '{student_id}'")
			return error_response("Student ID is required")

		# Get student information from CRM Student and SIS Class Student
		student_info = frappe.db.sql("""
			SELECT
				s.name as student_id,
				s.student_name as full_name,
				s.student_code,
				s.dob,
				s.gender,
				s.campus_id,
				cs.class_id,
				cs.school_year_id,
				c.title as class_name
			FROM `tabCRM Student` s
			INNER JOIN `tabSIS Class Student` cs ON s.name = cs.student_id
			LEFT JOIN `tabSIS Class` c ON cs.class_id = c.name
			WHERE s.name = %s
				AND cs.class_type = 'regular'
			ORDER BY cs.creation DESC
			LIMIT 1
		""", (student_id,), as_dict=True)

		if not student_info:
			return error_response("Student not found in SIS Class Student records")

		student_data = student_info[0]

		# Check if student is already assigned to bus
		existing_bus_student = frappe.db.exists("SIS Bus Student", {
			"student_code": student_data.student_code,
			"campus_id": student_data.campus_id
		})

		if existing_bus_student:
			return error_response(f"Student {student_data.student_code} is already assigned to bus service")

		# Create bus student record
		doc = frappe.get_doc({
			"doctype": "SIS Bus Student",
			"full_name": student_data.full_name,
			"student_code": student_data.student_code,
			"class_id": student_data.class_id,
			"status": status,
			"campus_id": student_data.campus_id,
			"school_year_id": student_data.school_year_id
		})

		doc.insert()
		frappe.db.commit()

		# Sync to CompreFace in background if status is Active
		if status == "Active":
			# Check complete status in CompreFace
			status_check = compreFace_service.check_subject_complete(student_data.student_code)
			
			subject_exists = False
			has_photos = False
			should_sync = True
			
			if status_check["success"]:
				status_data = status_check.get("data", {})
				subject_exists = status_data.get("subject_exists", False)
				has_photos = status_data.get("has_photos", False)
				
				# Only skip sync if subject exists AND has photos
				if subject_exists and has_photos:
					should_sync = False
					frappe.logger().info(
						f"Student {student_data.student_code} already complete in CompreFace "
						f"(subject exists and has {status_data.get('photos_count', 0)} photo(s)), marking as registered"
					)
					# Mark as registered
					frappe.db.set_value("SIS Bus Student", doc.name, "compreface_registered", 1)
					frappe.db.commit()

			if should_sync:
				# Student doesn't exist OR exists but has no photos - proceed with sync
				frappe.logger().info(
					f"Starting CompreFace sync for student {student_data.student_code} "
					f"(subject_exists={subject_exists}, has_photos={has_photos})"
				)

				# Get student's photo URL first
				photo_url = get_student_photo_url(student_data.student_code, student_data.campus_id, student_data.school_year_id)

				if not photo_url:
					frappe.logger().warning(f"No photo found for student {student_data.student_code}, cannot sync to CompreFace")
					# Create a notification for missing photo
					frappe.get_doc({
						"doctype": "ERP Notification",
						"title": f"No Photo for Student - {student_data.student_code}",
						"message": f"Cannot sync student {student_data.student_code} to CompreFace: No photo found. Please upload a photo.",
						"notification_type": "alert",
						"user": frappe.session.user or "Administrator"
					}).insert(ignore_permissions=True)
					frappe.db.commit()
				else:
					# Proceed with sync
					compreface_result = sync_student_to_compreface(
						student_data.student_code,
						student_data.full_name,
						student_data.campus_id,
						student_data.school_year_id
					)

					# Verify sync result and update registration status
					if compreface_result["success"]:
						# Add small delay and verify with complete check
						import time
						time.sleep(2)  # Wait 2 seconds for CompreFace to process

						# Verify with complete check
						for attempt in range(3):
							verify_check = compreFace_service.check_subject_complete(student_data.student_code)
							if verify_check["success"]:
								verify_data = verify_check.get("data", {})
								if verify_data.get("subject_exists") and verify_data.get("has_photos"):
									# Successfully verified - mark as registered
									frappe.db.set_value("SIS Bus Student", doc.name, "compreface_registered", 1)
									frappe.db.commit()
									frappe.logger().info(f"Successfully synced and verified student {student_data.student_code} in CompreFace")
									break
							if attempt < 2:  # Don't sleep after last attempt
								time.sleep(2)  # Wait another 2 seconds
					else:
						frappe.logger().warning(
							f"CompreFace sync failed for student {student_data.student_code}: "
							f"{compreface_result.get('message', '')}"
						)

						# Create a notification for failed sync
						frappe.get_doc({
							"doctype": "ERP Notification",
							"title": f"CompreFace Sync Failed - {student_data.student_code}",
							"message": f"Failed to sync student {student_data.student_code} to CompreFace: {compreface_result.get('message', '')}",
							"notification_type": "alert",
							"user": frappe.session.user or "Administrator"
						}).insert(ignore_permissions=True)
						frappe.db.commit()

		return success_response(
			data={
				"name": doc.name,
				"full_name": doc.full_name,
				"student_code": doc.student_code,
				"class_id": doc.class_id,
				"route_id": doc.route_id,
				"status": doc.status,
				"campus_id": doc.campus_id,
				"school_year_id": doc.school_year_id,
				"created_at": doc.creation,
				"updated_at": doc.modified
			},
			message="Bus student created successfully from SIS data"
		)

	except Exception as e:
		frappe.log_error(f"Error creating bus student from SIS: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to create bus student from SIS: {str(e)}")

@frappe.whitelist()
def update_bus_student(name, **data):
	"""Update an existing bus student"""
	try:
		doc = frappe.get_doc("SIS Bus Student", name)
		old_status = doc.status
		doc.update(data)
		doc.save()
		frappe.db.commit()

		# Handle CompreFace sync based on status change
		if "status" in data:
			if data["status"] == "Active" and old_status != "Active":
				# Status changed to Active - sync to CompreFace
				# Get student_id from CRM Student using student_code
				student_record = frappe.get_all("CRM Student",
					filters={"student_code": doc.student_code},
					fields=["name"],
					limit=1
				)

				if student_record:
					crm_student_id = student_record[0].name
					frappe.enqueue(
						method="erp.api.erp_sis.bus_student.sync_student_to_compreface_background",
						queue="default",
						timeout=300,
						job_name=f"sync_student_{doc.student_code}",
						**{
							"student_id": crm_student_id,  # Use CRM Student ID
							"student_name": doc.full_name,
							"campus_id": doc.campus_id,
							"school_year_id": doc.school_year_id
						}
					)
			elif data["status"] == "Inactive" and old_status == "Active":
				# Status changed to Inactive - remove from CompreFace
				frappe.enqueue(
					method="erp.api.erp_sis.bus_student.remove_student_from_compreface_background",
					queue="default",
					timeout=300,
					job_name=f"remove_student_{doc.student_code}",
					**{"student_code": doc.student_code}
				)

		return success_response(
			data=doc.as_dict(),
			message="Bus student updated successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error updating bus student: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to update bus student: {str(e)}")

@frappe.whitelist()
def delete_bus_student(name=None):
	"""Delete a bus student"""
	try:
		# Get name from multiple sources
		if not name:
			name = frappe.form_dict.get('name') or frappe.local.form_dict.get('name')
		
		if not name:
			return error_response("Student name/ID is required")
		
		# Get student info before deletion for CompreFace cleanup
		doc = frappe.get_doc("SIS Bus Student", name)
		student_code = doc.student_code

		frappe.delete_doc("SIS Bus Student", name)
		frappe.db.commit()

		# Remove from CompreFace in background
		frappe.enqueue(
			method="erp.api.erp_sis.bus_student.remove_student_from_compreface_background",
			queue="default",
			timeout=300,
			job_name=f"remove_student_{student_code}",
			**{"student_code": student_code}
		)

		return success_response(
			message="Bus student deleted successfully"
		)
	except Exception as e:
		frappe.log_error(f"Error deleting bus student: {str(e)}")
		frappe.db.rollback()
		return error_response(f"Failed to delete bus student: {str(e)}")

@frappe.whitelist()
def get_available_classes():
	"""Get available classes"""
	return frappe.db.sql("""
		SELECT name, class_name
		FROM `tabSIS Class`
		WHERE status = 'Active'
		ORDER BY class_name
	""", as_dict=True)

@frappe.whitelist()
def get_available_routes():
	"""Get available routes"""
	return frappe.db.sql("""
		SELECT name, route_name
		FROM `tabSIS Bus Route`
		WHERE status = 'Hoạt động'
		ORDER BY route_name
	""", as_dict=True)


@frappe.whitelist()
def check_compreface_subject(student_code=None):
	"""
	Check if a student subject exists in CompreFace and has photos
	
	Returns comprehensive status with 3 possible states:
	- no_subject: Subject does not exist in CompreFace
	- subject_only: Subject exists but has no photos
	- complete: Subject exists and has photos
	"""
	try:
		# Read student_code from request parameters if not provided
		if not student_code:
			# Try frappe.form_dict first (for POST data)
			student_code = frappe.form_dict.get("student_code")

			# If not found, try request.args (for query parameters)
			if not student_code and hasattr(frappe, 'request') and hasattr(frappe.request, 'args'):
				student_code = frappe.request.args.get("student_code")

		if not student_code:
			return error_response("Student code is required")

		# Get bus student record
		bus_student = frappe.db.get_value("SIS Bus Student",
			{"student_code": student_code},
			["name", "compreface_registered"],
			as_dict=True
		)

		# Check complete status from CompreFace API
		import time
		complete_status = None
		
		for attempt in range(3):
			check_result = compreFace_service.check_subject_complete(student_code)
			if check_result["success"]:
				complete_status = check_result.get("data", {})
				
				# Update database flag based on complete status
				if bus_student:
					should_be_registered = (
						complete_status.get("subject_exists") and 
						complete_status.get("has_photos")
					)
					current_registered = bus_student.get("compreface_registered")
					
					# Only update if status has changed
					if should_be_registered != current_registered:
						frappe.db.set_value(
							"SIS Bus Student", 
							bus_student.name, 
							"compreface_registered", 
							1 if should_be_registered else 0
						)
						frappe.db.commit()
				
				break
			elif attempt < 2:  # Don't sleep after last attempt
				time.sleep(2)  # Wait 2 seconds between attempts

		# If we couldn't get status, fallback to database flag
		if not complete_status:
			if bus_student and bus_student.get("compreface_registered"):
				complete_status = {
					"subject_exists": True,
					"has_photos": True,
					"photos_count": 1,  # Unknown, assume at least 1
					"status": "complete"
				}
			else:
				complete_status = {
					"subject_exists": False,
					"has_photos": False,
					"photos_count": 0,
					"status": "no_subject"
				}

		# Prepare response with legacy 'exists' field for backward compatibility
		return success_response(
			data={
				# Legacy field (for backward compatibility)
				"exists": complete_status.get("subject_exists") and complete_status.get("has_photos"),
				
				# New detailed fields
				"subject_exists": complete_status.get("subject_exists", False),
				"has_photos": complete_status.get("has_photos", False),
				"photos_count": complete_status.get("photos_count", 0),
				"status": complete_status.get("status", "no_subject"),
				
				# Additional info
				"bus_student_id": bus_student.name if bus_student else None,
				"database_registered": bus_student.get("compreface_registered") if bus_student else False
			},
			message=f"Subject {student_code}: {complete_status.get('status', 'unknown')}"
		)

	except Exception as e:
		frappe.log_error(f"Error checking CompreFace subject: {str(e)}")
		return error_response(f"Failed to check CompreFace subject: {str(e)}")


@frappe.whitelist()
def test_compreface_connectivity():
	"""Test CompreFace server connectivity"""
	try:
		result = compreFace_service.test_api_endpoints()
		return result
	except Exception as e:
		frappe.log_error(f"Error testing CompreFace connectivity: {str(e)}", "Bus Student API")
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist()
def debug_compreface_status(student_code=None):
	"""Debug endpoint to check CompreFace status in detail"""
	try:
		if not student_code:
			student_code = frappe.form_dict.get("student_code")
		
		if not student_code:
			return error_response("Student code is required")
		
		frappe.logger().info(f"[Debug] Checking CompreFace status for {student_code}")
		
		# 1. Check subject info directly
		subject_info = compreFace_service.get_subject_info(student_code)
		frappe.logger().info(f"[Debug] get_subject_info result: {subject_info}")
		
		# 2. Check photos count
		photos_info = compreFace_service.get_subject_photos_count(student_code)
		frappe.logger().info(f"[Debug] get_subject_photos_count result: {photos_info}")
		
		# 3. Check complete status
		complete_status = compreFace_service.check_subject_complete(student_code)
		frappe.logger().info(f"[Debug] check_subject_complete result: {complete_status}")
		
		return success_response(
			data={
				"student_code": student_code,
				"subject_info": subject_info,
				"photos_info": photos_info,
				"complete_status": complete_status
			},
			message=f"Debug info for {student_code}"
		)
		
	except Exception as e:
		frappe.log_error(f"Error in debug endpoint: {str(e)}")
		return error_response(f"Debug failed: {str(e)}")


@frappe.whitelist()
def test_compreface_add_face():
	"""Test CompreFace add face functionality"""
	try:
		result = compreFace_service.test_add_face()
		return result
	except Exception as e:
		frappe.log_error(f"Error testing CompreFace add face: {str(e)}", "Bus Student API")
		return {
			"success": False,
			"error": str(e)
		}


@frappe.whitelist(methods=["POST"])
def sync_bus_student_to_compreface():
	"""Sync a specific bus student to CompreFace"""
	try:
		# Try multiple sources for data
		student_id = None

		# Try from form_dict first (for form-encoded data)
		if frappe.local.form_dict:
			student_id = frappe.local.form_dict.get("student_id")

		# Try to parse JSON from request data
		if not student_id and hasattr(frappe.request, 'data') and frappe.request.data:
			try:
				import json
				raw_data = frappe.request.data
				if isinstance(raw_data, bytes):
					raw_data = raw_data.decode('utf-8')

				json_data = json.loads(raw_data)
				student_id = json_data.get("student_id")
			except Exception as e:
				pass  # JSON parse failed, continue to next method

		# Last resort: try from frappe.form_dict
		if not student_id and hasattr(frappe, 'form_dict') and frappe.form_dict:
			student_id = frappe.form_dict.get("student_id")

		if not student_id or str(student_id).strip() == "":
			frappe.logger().error(f"Student ID validation failed in sync. student_id: '{student_id}'")
			return error_response("Student ID is required")

		# Get bus student details
		bus_student = frappe.get_doc("SIS Bus Student", student_id)

		if not bus_student:
			return error_response("Bus student not found")

		# Check complete status in CompreFace
		status_check = compreFace_service.check_subject_complete(bus_student.student_code)
		
		subject_exists = False
		has_photos = False
		
		if status_check["success"]:
			status_data = status_check.get("data", {})
			subject_exists = status_data.get("subject_exists", False)
			has_photos = status_data.get("has_photos", False)
			
			# If already complete, no need to sync
			if subject_exists and has_photos:
				# Update database flag
				frappe.db.set_value("SIS Bus Student", bus_student.name, "compreface_registered", 1)
				frappe.db.commit()
				
				return success_response(
					data={
						"status": "already_complete",
						"photos_count": status_data.get("photos_count", 0)
					},
					message=f"Student {bus_student.student_code} already complete in CompreFace with {status_data.get('photos_count', 0)} photo(s)"
				)

		# Check if photo exists before trying to sync
		photo_url = get_student_photo_url(bus_student.student_code, bus_student.campus_id, bus_student.school_year_id)
		
		if not photo_url:
			return error_response(
				f"Cannot sync student {bus_student.student_code}: No photo found. Please upload a photo first."
			)

		# Proceed with sync
		frappe.logger().info(
			f"Syncing student {bus_student.student_code} "
			f"(subject_exists={subject_exists}, has_photos={has_photos})"
		)
		
		compreface_result = sync_student_to_compreface(
			bus_student.student_code,
			bus_student.full_name,
			bus_student.campus_id,
			bus_student.school_year_id
		)

		# Verify sync result
		if compreface_result["success"]:
			import time
			time.sleep(2)  # Wait for processing

			# Verify with complete check (multiple attempts)
			verification_status = None
			for attempt in range(3):
				frappe.logger().info(f"[CompreFace Sync] Verification attempt {attempt + 1}/3 for {bus_student.student_code}")
				verify_check = compreFace_service.check_subject_complete(bus_student.student_code)
				
				if verify_check["success"]:
					verify_data = verify_check.get("data", {})
					verification_status = verify_data.get("status", "unknown")
					
					frappe.logger().info(
						f"[CompreFace Sync] Verification result: "
						f"subject_exists={verify_data.get('subject_exists')}, "
						f"has_photos={verify_data.get('has_photos')}, "
						f"photos_count={verify_data.get('photos_count', 0)}"
					)
					
					if verify_data.get("subject_exists") and verify_data.get("has_photos"):
						# Successfully verified - mark as registered
						frappe.db.set_value("SIS Bus Student", bus_student.name, "compreface_registered", 1)
						frappe.db.commit()
						frappe.logger().info(f"[CompreFace Sync] ✓ Successfully synced and verified student {bus_student.student_code}")
						
						return success_response(
							data={
								"status": "synced",
								"photos_count": verify_data.get("photos_count", 1)
							},
							message=f"Successfully synced student {bus_student.student_code} to CompreFace"
						)
				
				if attempt < 2:  # Don't sleep after last attempt
					time.sleep(2)  # Wait another 2 seconds
			
			# Verification failed after all attempts
			if verification_status == "no_subject":
				# Subject doesn't exist at all - sync actually failed
				frappe.logger().error(
					f"[CompreFace Sync] ✗ Sync reported success but subject does not exist in CompreFace. "
					f"This indicates add_face_to_subject failed and subject was cleaned up."
				)
				return error_response(
					f"Sync failed: Subject {bus_student.student_code} was not created in CompreFace. "
					f"This usually means face detection failed or image quality is poor."
				)
			elif verification_status == "subject_only":
				# Subject exists but no photos - partial success
				frappe.logger().warning(
					f"[CompreFace Sync] ⚠ Subject {bus_student.student_code} created but no photos added. "
					f"Face detection may have failed."
				)
				return error_response(
					f"Partial sync: Subject created but face not added for {bus_student.student_code}. "
					f"Face may not be detected in the image."
				)
			else:
				# Unknown status - can't verify
				frappe.logger().warning(
					f"[CompreFace Sync] ⚠ Cannot verify sync status for {bus_student.student_code} after 3 attempts"
				)
				return success_response(
					data={
						"status": "synced_unverified"
					},
					message=f"Synced student {bus_student.student_code} but verification is pending (please check manually)"
				)
		else:
			error_msg = compreface_result.get("message", "Unknown error")
			error_detail = compreface_result.get("error_detail", error_msg)
			frappe.logger().error(f"[CompreFace Sync] ✗ Failed to sync student {bus_student.student_code}: {error_detail}")
			return error_response(f"Failed to sync student {bus_student.student_code}: {error_detail}")

	except Exception as e:
		frappe.log_error(f"Error syncing bus student to CompreFace: {str(e)}")
		return error_response(f"Failed to sync bus student to CompreFace: {str(e)}")


@frappe.whitelist()
def get_students_for_bus_selection(search_term=None, school_year_id=None):
	"""Get students available for bus assignment with search functionality"""
	try:
		# Get current user's campus information from roles
		campus_id = get_current_campus_from_context()

		if not campus_id:
			campus_id = "campus-1"

		# Build base query to get students from SIS Class Student
		query = """
			SELECT DISTINCT
				s.name as student_id,
				s.student_name as full_name,
				s.student_code,
				s.dob,
				s.gender,
				s.campus_id,
				cs.class_id,
				cs.school_year_id,
				c.title as class_name,
				sy.title_vn as school_year_name
			FROM `tabCRM Student` s
			INNER JOIN `tabSIS Class Student` cs ON s.name = cs.student_id
			LEFT JOIN `tabSIS Class` c ON cs.class_id = c.name
			LEFT JOIN `tabSIS School Year` sy ON cs.school_year_id = sy.name
			WHERE s.campus_id = %s
				AND cs.class_type = 'regular'
		"""

		params = [campus_id]

		# Add school year filter if provided
		if school_year_id:
			query += " AND cs.school_year_id = %s"
			params.append(school_year_id)

		# Add search filter if provided
		if search_term and str(search_term).strip():
			search_pattern = f"%{str(search_term).strip()}%"
			query += """
				AND (LOWER(s.student_name) LIKE LOWER(%s)
					OR LOWER(s.student_code) LIKE LOWER(%s)
					OR LOWER(c.title) LIKE LOWER(%s))
			"""
			params.extend([search_pattern, search_pattern, search_pattern])

		query += " ORDER BY s.student_name ASC"

		students = frappe.db.sql(query, params, as_dict=True)

		# Enrich with photo URLs
		if students:
			student_ids = [s.get('student_id') for s in students if s.get('student_id')]
			if student_ids:
				photos = frappe.db.sql("""
					SELECT
						student_id,
						photo,
						upload_date
					FROM `tabSIS Photo`
					WHERE student_id IN %(student_ids)s
						AND type = 'student'
						AND status = 'Active'
					ORDER BY upload_date DESC
				""", {"student_ids": student_ids}, as_dict=True)

				# Create photo mapping
				photo_map = {}
				for photo in photos:
					student_id = photo.get('student_id')
					if student_id and student_id not in photo_map:
						photo_url = photo.get('photo')
						if photo_url:
							if photo_url.startswith('/files/'):
								photo_url = frappe.utils.get_url(photo_url)
							elif not photo_url.startswith('http'):
								photo_url = frappe.utils.get_url('/files/' + photo_url)
							photo_map[student_id] = photo_url

				# Add photo URLs to students
				for student in students:
					student_id = student.get('student_id')
					student['photo_url'] = photo_map.get(student_id)

		return success_response(
			data=students,
			message=f"Found {len(students)} students available for bus assignment"
		)

	except Exception as e:
		frappe.log_error(f"Error getting students for bus selection: {str(e)}")
		return error_response(f"Failed to get students for bus selection: {str(e)}")


def get_student_photo_url(student_code: str, campus_id: str, school_year_id: str) -> str:
	"""
	Get the latest photo URL for a student from SIS Photo

	Args:
		student_code: Student code to find photos for
		campus_id: Campus ID for filtering
		school_year_id: School year ID for filtering

	Returns:
		Photo URL or empty string if not found
	"""
	try:
		# First, find the CRM Student ID using the student_code
		crm_student = frappe.db.get_value("CRM Student", {"student_code": student_code}, "name")
		if not crm_student:
			frappe.logger().warning(f"No CRM Student found for student_code: {student_code}")
			return ""

		# Get the latest photo for this student using CRM Student ID
		photo = frappe.db.sql("""
			SELECT photo
			FROM `tabSIS Photo`
			WHERE type = 'student'
			AND student_id = %s
			AND status = 'Active'
			ORDER BY upload_date DESC, creation DESC
			LIMIT 1
		""", (crm_student,), as_dict=True)

		frappe.logger().info(f"Photo query for student {student_code}: found {len(photo) if photo else 0} photos")

		if photo:
			frappe.logger().info(f"Photo data: {photo[0]}")

		all_photos = frappe.db.sql("""
			SELECT name, student_id, type, status, photo
			FROM `tabSIS Photo`
			WHERE student_id = %s
		""", (crm_student,), as_dict=True)

		frappe.logger().info(f"All photos for student {student_code}: {len(all_photos) if all_photos else 0} records")
		if all_photos:
			frappe.logger().info(f"Sample photo records: {all_photos[:2]}")

		# Debug: Check table structure
		columns = frappe.db.sql("DESCRIBE `tabSIS Photo`", as_dict=True)
		frappe.logger().info(f"SIS Photo table columns: {[col['Field'] for col in columns]}")

		if photo and photo[0].photo:
			# Convert relative URL to full URL
			file_url = photo[0].photo
			if file_url.startswith('/files/'):
				site_url = frappe.utils.get_url()
				return f"{site_url}{file_url}"
			elif not file_url.startswith('http'):
				return frappe.utils.get_url('/files/' + file_url)
			return file_url

		return ""

	except Exception as e:
		frappe.log_error(f"Error getting student photo for {student_code}: {str(e)}", "Bus Student API")
		return ""


def sync_student_to_compreface(student_code: str, student_name: str, campus_id: str, school_year_id: str) -> dict:
	"""
	Sync student information to CompreFace for face recognition

	Args:
		student_code: Student code (used as subject ID)
		student_name: Student full name
		campus_id: Campus ID
		school_year_id: School year ID

	Returns:
		Dict with sync result
	"""
	try:
		frappe.logger().info(f"[CompreFace Sync] Starting for student {student_code}")

		# Test connectivity first
		try:
			connectivity_test = compreFace_service.test_api_endpoints()
			if not connectivity_test.get("success"):
				error_msg = f"CompreFace server not accessible: {connectivity_test.get('error', 'Unknown error')}"
				frappe.logger().error(f"[CompreFace Sync] {error_msg}")
				return {
					"success": False,
					"error": "Connection Error",
					"message": error_msg
				}
			frappe.logger().info(f"[CompreFace Sync] Server connectivity OK")
		except Exception as conn_e:
			error_msg = f"Failed to test CompreFace connectivity: {str(conn_e)}"
			frappe.logger().error(f"[CompreFace Sync] {error_msg}")

		# Get student's photo first
		photo_url = get_student_photo_url(student_code, campus_id, school_year_id)

		if not photo_url:
			frappe.logger().warning(f"[CompreFace Sync] No photo found for student {student_code}")
			return {
				"success": False,
				"error": "No photo found",
				"message": f"No photo found for student {student_code}. Please upload a photo first."
			}
		
		frappe.logger().info(f"[CompreFace Sync] Photo URL found: {photo_url[:50]}...")

		# Check complete status of subject in CompreFace
		frappe.logger().info(f"[CompreFace Sync] Checking subject status for {student_code}")
		status_check = compreFace_service.check_subject_complete(student_code)
		
		subject_exists = False
		has_photos = False
		should_create_subject = True
		
		if status_check["success"]:
			status_data = status_check.get("data", {})
			subject_exists = status_data.get("subject_exists", False)
			has_photos = status_data.get("has_photos", False)
			should_create_subject = not subject_exists
			
			frappe.logger().info(
				f"[CompreFace Sync] Status for {student_code}: "
				f"subject_exists={subject_exists}, has_photos={has_photos}, photos_count={status_data.get('photos_count', 0)}"
			)
		else:
			frappe.logger().warning(f"[CompreFace Sync] Could not check status, proceeding with create attempt")

		# Create subject if needed
		if should_create_subject:
			frappe.logger().info(f"[CompreFace Sync] Creating subject {student_code} in CompreFace")
			create_result = compreFace_service.create_subject(student_code, student_name)
			
			if not create_result["success"]:
				error_detail = create_result.get("error_detail", create_result.get("error", "Unknown error"))
				frappe.logger().error(
					f"[CompreFace Sync] Failed to create subject {student_code}: "
					f"Error: {create_result.get('error', 'N/A')}, Detail: {error_detail}"
				)
				return {
					"success": False,
					"error": create_result.get("error", "Unknown error"),
					"error_detail": error_detail,
					"message": create_result.get("message", f"Failed to create subject: {error_detail}")
				}
			else:
				# Check if it's a 409 (already exists) - this is OK
				if "already exists" in create_result.get("message", "").lower():
					frappe.logger().info(f"[CompreFace Sync] Subject {student_code} already exists (409), continuing with add_face")
				else:
					frappe.logger().info(f"[CompreFace Sync] Subject {student_code} created successfully")
		else:
			frappe.logger().info(f"[CompreFace Sync] Subject {student_code} already exists (from check), skipping creation")

		# Add face to subject
		frappe.logger().info(f"[CompreFace Sync] Adding face to subject {student_code}")
		add_face_result = compreFace_service.add_face_to_subject(student_code, photo_url)

		if add_face_result["success"]:
			frappe.logger().info(f"[CompreFace Sync] ✓ Successfully synced student {student_code}")
			return {
				"success": True,
				"message": f"Student {student_code} synced to CompreFace successfully",
				"data": {
					"subject_created": should_create_subject,
					"face_added": True
				}
			}
		else:
			error_detail = add_face_result.get("error_detail", add_face_result.get("error", "Unknown error"))
			error_msg = add_face_result.get("message", f"Failed to add face: {error_detail}")
			frappe.logger().error(
				f"[CompreFace Sync] ✗ Failed to add face for {student_code}: "
				f"Error: {add_face_result.get('error', 'N/A')}, Detail: {error_detail}"
			)
			
			# Only delete subject if we just created it AND face addition failed
			if should_create_subject:
				frappe.logger().info(f"[CompreFace Sync] Cleaning up newly created subject {student_code}")
				compreFace_service.delete_subject(student_code)
			
			return {
				"success": False,
				"error": add_face_result.get("error", "Unknown error"),
				"error_detail": error_detail,
				"message": error_msg
			}

	except Exception as e:
		error_msg = f"Exception syncing student {student_code} to CompreFace: {type(e).__name__}: {str(e)}"
		frappe.log_error(error_msg, "Bus Student API")
		frappe.logger().error(f"[CompreFace Sync] {error_msg}")
		return {
			"success": False,
			"error": type(e).__name__,
			"error_detail": str(e),
			"message": f"Failed to sync student {student_code}: {str(e)}"
		}


def remove_student_from_compreface(student_code: str) -> dict:
	"""
	Remove student from CompreFace

	Args:
		student_code: Student code to remove

	Returns:
		Dict with removal result
	"""
	try:
		result = compreFace_service.delete_subject(student_code)

		if result["success"]:
			frappe.logger().info(f"Successfully removed student {student_code} from CompreFace")
		else:
			frappe.logger().warning(f"Failed to remove student {student_code} from CompreFace: {result.get('message', '')}")

		return result

	except Exception as e:
		frappe.log_error(f"Error removing student {student_code} from CompreFace: {str(e)}", "Bus Student API")
		return {
			"success": False,
			"error": str(e),
			"message": f"Failed to remove student {student_code} from CompreFace"
		}


# Background job functions for CompreFace synchronization

def sync_student_to_compreface_background(student_id: str, student_name: str, campus_id: str, school_year_id: str):
	"""
	Background job to sync student to CompreFace
	This function runs in background queue to avoid blocking the main API response
	"""
	try:
		frappe.logger().info(f"Starting background sync for student {student_id} to CompreFace")

		result = sync_student_to_compreface(student_id, student_name, campus_id, school_year_id)

		if result["success"]:
			frappe.logger().info(f"Background sync completed successfully for student {student_id}")
		else:
			frappe.logger().error(f"Background sync failed for student {student_id}: {result.get('message', '')}")

			# Create a notification or log for failed sync
			frappe.get_doc({
				"doctype": "ERP Notification",
				"title": f"CompreFace Sync Failed - {student_id}",
				"message": f"Failed to sync student {student_id} to CompreFace: {result.get('message', '')}",
				"notification_type": "alert",
				"user": "Administrator"  # Or get current user
			}).insert(ignore_permissions=True)

	except Exception as e:
		frappe.log_error(f"Background sync error for student {student_id}: {str(e)}", "Bus Student Background Job")


def remove_student_from_compreface_background(student_code: str):
	"""
	Background job to remove student from CompreFace
	This function runs in background queue to avoid blocking the main API response
	"""
	try:
		frappe.logger().info(f"Starting background removal for student {student_code} from CompreFace")

		result = remove_student_from_compreface(student_code)

		if result["success"]:
			frappe.logger().info(f"Background removal completed successfully for student {student_code}")
		else:
			frappe.logger().warning(f"Background removal had issues for student {student_code}: {result.get('message', '')}")

	except Exception as e:
		frappe.log_error(f"Background removal error for student {student_code}: {str(e)}", "Bus Student Background Job")
