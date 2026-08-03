# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.search import build_search_condition, sort_by_relevance

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
		# Also join with CRM Student to get crm_student_id for compatibility with Bus Route Student
		students = frappe.db.sql("""
			SELECT
				bs.name, bs.full_name, bs.student_code, bs.class_id,
				bs.route_id, bs.status, bs.campus_id, bs.school_year_id,
				bs.creation as created_at, bs.modified as updated_at,
				r.route_name, c.title as class_name,
				s.name as crm_student_id
			FROM `tabSIS Bus Student` bs
			LEFT JOIN `tabSIS Bus Route` r ON bs.route_id = r.name
			LEFT JOIN `tabSIS Class` c ON bs.class_id = c.name
			LEFT JOIN `tabCRM Student` s ON bs.student_code = s.student_code
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
		doc.update(data)
		doc.save()
		frappe.db.commit()

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
		# Get name from multiple sources (handle both GET and POST)
		if not name:
			# Try frappe.form_dict first (works for most cases)
			name = frappe.form_dict.get('name')
		
		if not name:
			# Try request args for GET requests
			if hasattr(frappe, 'request') and frappe.request:
				name = frappe.request.args.get('name')
		
		if not name:
			# Debug: log what we received
			frappe.logger().error(f"delete_bus_student: No name received. form_dict: {dict(frappe.form_dict)}")
			return error_response("Student name/ID is required")

		frappe.delete_doc("SIS Bus Student", name)
		frappe.db.commit()

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
			search_frag, search_params = build_search_condition(
				["s.student_name", "s.student_code", "c.title"], search_term
			)
			if search_frag:
				query += " AND " + search_frag
				params.extend(search_params)

		query += " ORDER BY s.student_name ASC"

		students = frappe.db.sql(query, params, as_dict=True)
		# Khop nhat len dau (chuan chung, xem erp/utils/search.py)
		students = sort_by_relevance(
			students, ["full_name", "student_code", "class_name"], search_term, id_field="student_id"
		)

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
					ORDER BY (SELECT sy.start_date FROM `tabSIS School Year` sy WHERE sy.name = school_year_id) DESC,
					         upload_date DESC
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


@frappe.whitelist()
def migrate_route_students_to_bus_students():
	"""
	Migrate students from existing Bus Route Students to Bus Students.
	This is a one-time migration to transfer students from the old system to the new one.
	
	Process:
	1. Get all unique student_ids from SIS Bus Route Student
	2. For each student, get information from CRM Student and SIS Class Student
	3. Create SIS Bus Student if not already exists (check by student_code)
	
	Returns:
		Summary of migration operation
	"""
	try:
		# Get current user's campus
		campus_id = get_current_campus_from_context()
		if not campus_id:
			campus_id = "campus-1"
		
		# Get active school year (is_enable = 1, ordered by start_date desc)
		school_year_doc = frappe.get_all(
			"SIS School Year", 
			filters={"is_enable": 1, "campus_id": campus_id},
			fields=["name"],
			order_by="start_date desc",
			limit=1
		)
		if not school_year_doc:
			# Fallback: get any school year
			school_year_doc = frappe.get_all(
				"SIS School Year", 
				filters={"campus_id": campus_id},
				fields=["name"],
				order_by="creation desc",
				limit=1
			)
		school_year = school_year_doc[0].name if school_year_doc else None
		
		# Get all unique students from Bus Route Students with their info
		route_students = frappe.db.sql("""
			SELECT DISTINCT
				rs.student_id,
				s.student_name,
				s.student_code,
				s.campus_id,
				cs.class_id,
				cs.school_year_id
			FROM `tabSIS Bus Route Student` rs
			INNER JOIN `tabCRM Student` s ON rs.student_id = s.name
			LEFT JOIN `tabSIS Class Student` cs ON (
				cs.student_id = rs.student_id 
				AND (cs.class_type = 'regular' OR cs.class_type IS NULL)
			)
			WHERE s.student_code IS NOT NULL
			ORDER BY s.student_name ASC
		""", as_dict=True)
		
		if not route_students:
			return success_response(
				data={"total": 0, "migrated": 0, "skipped": 0, "failed": 0},
				message="Không có học sinh nào để migrate"
			)
		
		# Get existing bus students to avoid duplicates
		existing_bus_students = frappe.db.sql("""
			SELECT student_code 
			FROM `tabSIS Bus Student`
			WHERE campus_id = %s
		""", (campus_id,), as_dict=True)
		
		existing_codes = set([s.student_code for s in existing_bus_students])
		
		results = {
			"total": len(route_students),
			"migrated": 0,
			"skipped": 0,
			"failed": 0,
			"details": []
		}
		
		# Deduplicate by student_code (in case same student appears multiple times)
		processed_codes = set()
		
		for student in route_students:
			student_code = student.get("student_code")
			
			# Skip if already processed in this batch
			if student_code in processed_codes:
				continue
			processed_codes.add(student_code)
			
			# Skip if already exists in Bus Student
			if student_code in existing_codes:
				results["skipped"] += 1
				results["details"].append({
					"student_code": student_code,
					"student_name": student.get("student_name"),
					"status": "skipped",
					"reason": "Đã tồn tại trong Bus Student"
				})
				continue
			
			try:
				# Determine school_year_id: prefer from student data, then fallback
				student_school_year = student.get("school_year_id") or school_year
				if not student_school_year:
					# Last fallback: get any school year from campus
					any_school_year = frappe.get_all(
						"SIS School Year",
						filters={"campus_id": campus_id},
						fields=["name"],
						limit=1
					)
					student_school_year = any_school_year[0].name if any_school_year else None
				
				if not student_school_year:
					results["failed"] += 1
					results["details"].append({
						"student_code": student_code,
						"student_name": student.get("student_name"),
						"status": "failed",
						"reason": "Không tìm thấy năm học"
					})
					continue
				
				# Create new Bus Student
				doc = frappe.get_doc({
					"doctype": "SIS Bus Student",
					"full_name": student.get("student_name"),
					"student_code": student_code,
					"class_id": student.get("class_id"),
					"status": "Active",
					"campus_id": student.get("campus_id") or campus_id,
					"school_year_id": student_school_year
				})
				doc.insert(ignore_permissions=True)
				
				results["migrated"] += 1
				results["details"].append({
					"student_code": student_code,
					"student_name": student.get("student_name"),
					"status": "migrated",
					"bus_student_id": doc.name
				})
				
			except Exception as e:
				results["failed"] += 1
				results["details"].append({
					"student_code": student_code,
					"student_name": student.get("student_name"),
					"status": "failed",
					"reason": str(e)
				})
		
		frappe.db.commit()
		
		message = f"Đã migrate {results['migrated']}/{results['total']} học sinh. "
		if results["skipped"] > 0:
			message += f"Đã bỏ qua (tồn tại): {results['skipped']}. "
		if results["failed"] > 0:
			message += f"Thất bại: {results['failed']}."
		
		return success_response(
			data=results,
			message=message
		)
		
	except Exception as e:
		frappe.log_error(f"Error migrating route students to bus students: {str(e)}")
		return error_response(f"Lỗi migration: {str(e)}")
