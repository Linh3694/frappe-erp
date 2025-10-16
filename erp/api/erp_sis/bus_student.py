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
			frappe.enqueue(
				method="erp.api.erp_sis.bus_student.sync_student_to_compreface_background",
				queue="default",
				timeout=300,
				job_name=f"sync_student_{doc.student_code}",
				**{
					"student_code": doc.student_code,
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


@frappe.whitelist()
def create_bus_student_from_sis(**data):
	"""Create a new bus student from SIS student data"""
	try:
		student_id = data.get("student_id")
		route_id = data.get("route_id")
		status = data.get("status", "Active")

		if not student_id or str(student_id).strip() == "":
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
			"route_id": route_id,
			"status": status,
			"campus_id": student_data.campus_id,
			"school_year_id": student_data.school_year_id
		})

		doc.insert()
		frappe.db.commit()

		# Sync to CompreFace in background if status is Active
		if status == "Active":
			compreface_result = sync_student_to_compreface(
				student_data.student_code,
				student_data.full_name,
				student_data.campus_id,
				student_data.school_year_id
			)

			# If CompreFace sync fails, still create the bus student but log the error
			if not compreface_result["success"]:
				frappe.logger().warning(f"CompreFace sync failed for student {student_data.student_code}: {compreface_result.get('message', '')}")

				# Create a notification for failed sync
				frappe.get_doc({
					"doctype": "ERP Notification",
					"title": f"CompreFace Sync Failed - {student_data.student_code}",
					"message": f"Failed to sync student {student_data.student_code} to CompreFace: {compreface_result.get('message', '')}",
					"notification_type": "Error",
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
				frappe.enqueue(
					method="erp.api.erp_sis.bus_student.sync_student_to_compreface_background",
					queue="default",
					timeout=300,
					job_name=f"sync_student_{doc.student_code}",
					**{
						"student_code": doc.student_code,
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
def delete_bus_student(name):
	"""Delete a bus student"""
	try:
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
		# Get the latest photo for this student
		photo = frappe.db.sql("""
			SELECT file_url
			FROM `tabSIS Photo`
			WHERE photo_type = 'student'
			AND student_code = %s
			AND campus_id = %s
			AND school_year_id = %s
			ORDER BY creation DESC
			LIMIT 1
		""", (student_code, campus_id, school_year_id), as_dict=True)

		if photo and photo[0].file_url:
			# Convert relative URL to full URL
			file_url = photo[0].file_url
			if file_url.startswith('/files/'):
				site_url = frappe.utils.get_url()
				return f"{site_url}{file_url}"
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
		# Get student's photo
		photo_url = get_student_photo_url(student_code, campus_id, school_year_id)

		if not photo_url:
			return {
				"success": False,
				"error": "No photo found",
				"message": f"No photo found for student {student_code}"
			}

		# Create subject in CompreFace
		create_result = compreFace_service.create_subject(student_code, student_name)

		if not create_result["success"]:
			return create_result

		# Add face to subject
		add_face_result = compreFace_service.add_face_to_subject(student_code, photo_url)

		if add_face_result["success"]:
			frappe.logger().info(f"Successfully synced student {student_code} to CompreFace")
			return {
				"success": True,
				"message": f"Student {student_code} synced to CompreFace successfully"
			}
		else:
			# If adding face failed, try to clean up the created subject
			compreFace_service.delete_subject(student_code)
			return add_face_result

	except Exception as e:
		frappe.log_error(f"Error syncing student {student_code} to CompreFace: {str(e)}", "Bus Student API")
		return {
			"success": False,
			"error": str(e),
			"message": f"Failed to sync student {student_code} to CompreFace"
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

def sync_student_to_compreface_background(student_code: str, student_name: str, campus_id: str, school_year_id: str):
	"""
	Background job to sync student to CompreFace
	This function runs in background queue to avoid blocking the main API response
	"""
	try:
		frappe.logger().info(f"Starting background sync for student {student_code} to CompreFace")

		result = sync_student_to_compreface(student_code, student_name, campus_id, school_year_id)

		if result["success"]:
			frappe.logger().info(f"Background sync completed successfully for student {student_code}")
		else:
			frappe.logger().error(f"Background sync failed for student {student_code}: {result.get('message', '')}")

			# Create a notification or log for failed sync
			frappe.get_doc({
				"doctype": "ERP Notification",
				"title": f"CompreFace Sync Failed - {student_code}",
				"message": f"Failed to sync student {student_code} to CompreFace: {result.get('message', '')}",
				"notification_type": "Error",
				"user": "Administrator"  # Or get current user
			}).insert(ignore_permissions=True)

	except Exception as e:
		frappe.log_error(f"Background sync error for student {student_code}: {str(e)}", "Bus Student Background Job")


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
