"""
Parent Portal Leave Request API
Handles leave request submission and management for parent portal

This is a dedicated API module for parent portal only.
Do not share with admin/erp_sis modules.
"""

import frappe
from frappe import _
from datetime import datetime, timedelta
import json
from erp.utils.api_response import validation_error_response, list_response, error_response, success_response, forbidden_response, not_found_response


def _get_current_parent():
	"""Get current logged in parent/guardian"""
	user_email = frappe.session.user
	if user_email == "Guest":
		return None

	# Extract guardian_id from email (format: guardian_id@parent.wellspring.edu.vn)
	if "@parent.wellspring.edu.vn" not in user_email:
		return None

	guardian_id = user_email.split("@")[0]

	# Get the actual guardian name from guardian_id field
	guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
	return guardian


def _check_overlapping_leave_requests(student_id, start_date, end_date):
	"""Check if there are overlapping leave requests for this student
	
	Args:
		student_id: Student ID
		start_date: Start date of new leave request (string: YYYY-MM-DD)
		end_date: End date of new leave request (string: YYYY-MM-DD)
	
	Returns:
		Dict with:
		- overlapping_dates: List of individual dates that overlap
		- overlapping_requests: List of request details
		- has_overlap: Boolean flag
	"""
	from datetime import datetime, timedelta
	
	# Convert string dates to datetime objects
	new_start = datetime.strptime(str(start_date), '%Y-%m-%d').date()
	new_end = datetime.strptime(str(end_date), '%Y-%m-%d').date()
	
	# Find all existing leave requests for this student
	existing_requests = frappe.get_all(
		"SIS Student Leave Request",
		filters={"student_id": student_id},
		fields=["name", "start_date", "end_date", "reason"]
	)
	
	overlapping_requests = []
	overlapping_dates_set = set()
	
	for req in existing_requests:
		req_start = datetime.strptime(str(req.start_date), '%Y-%m-%d').date()
		req_end = datetime.strptime(str(req.end_date), '%Y-%m-%d').date()
		
		# Check if date ranges overlap
		# Ranges overlap if: new_start <= req_end AND new_end >= req_start
		if new_start <= req_end and new_end >= req_start:
			overlapping_requests.append({
				"id": req.name,
				"start_date": str(req.start_date),
				"end_date": str(req.end_date),
				"reason": req.reason
			})
			
			# Collect all overlapping dates
			current_date = max(new_start, req_start)
			overlap_end = min(new_end, req_end)
			while current_date <= overlap_end:
				overlapping_dates_set.add(str(current_date))
				current_date += timedelta(days=1)
	
	# Sort overlapping dates
	overlapping_dates = sorted(list(overlapping_dates_set))
	
	return {
		"has_overlap": len(overlapping_requests) > 0,
		"overlapping_dates": overlapping_dates,
		"overlapping_requests": overlapping_requests
	}


def _get_homeroom_teachers_for_student(student_id):
	"""Get homeroom teacher user_id(s) for a student
	
	Args:
		student_id: Student ID
	
	Returns:
		List of dicts: [{"user_id": "teacher@email.com", "teacher_name": "...", "class_title": "..."}]
	"""
	try:
		# Step 1: Get class(es) for this student from SIS Class Student
		class_students = frappe.get_all(
			"SIS Class Student",
			filters={"student_id": student_id},
			fields=["class_id"]
		)
		
		if not class_students:
			frappe.logger().info(f"📚 No class found for student {student_id}")
			return []
		
		class_ids = [cs.class_id for cs in class_students]
		
		# Step 2: Get homeroom teachers from SIS Class
		classes = frappe.get_all(
			"SIS Class",
			filters={"name": ["in", class_ids]},
			fields=["name", "title", "homeroom_teacher", "vice_homeroom_teacher"]
		)
		
		if not classes:
			frappe.logger().info(f"📚 No SIS Class records found for class_ids {class_ids}")
			return []
		
		# Step 3: Collect all homeroom teachers
		teacher_ids = set()
		class_info_map = {}
		
		for cls in classes:
			if cls.homeroom_teacher:
				teacher_ids.add(cls.homeroom_teacher)
				class_info_map[cls.homeroom_teacher] = cls.title
			if cls.vice_homeroom_teacher:
				teacher_ids.add(cls.vice_homeroom_teacher)
				if cls.vice_homeroom_teacher not in class_info_map:
					class_info_map[cls.vice_homeroom_teacher] = cls.title
		
		if not teacher_ids:
			frappe.logger().info(f"📚 No homeroom teachers found for classes {class_ids}")
			return []
		
		# Step 4: Get user_id from SIS Teacher
		teachers = frappe.get_all(
			"SIS Teacher",
			filters={"name": ["in", list(teacher_ids)]},
			fields=["name", "user_id"]
		)
		
		result = []
		for teacher in teachers:
			if teacher.user_id:
				# Get teacher name from User
				teacher_name = frappe.db.get_value("User", teacher.user_id, "full_name") or teacher.user_id
				result.append({
					"user_id": teacher.user_id,
					"teacher_id": teacher.name,
					"teacher_name": teacher_name,
					"class_title": class_info_map.get(teacher.name, "")
				})
		
		frappe.logger().info(f"✅ Found {len(result)} homeroom teachers for student {student_id}: {[t['user_id'] for t in result]}")
		return result
		
	except Exception as e:
		frappe.logger().error(f"❌ Error getting homeroom teachers for student {student_id}: {str(e)}")
		return []


def _send_leave_notification_to_teachers(student_id, student_name, parent_name, leave_request_id, reason, reason_display, start_date, end_date):
	"""Send push notification to homeroom teachers when parent creates leave request
	
	Args:
		student_id: Student ID
		student_name: Student name for display
		parent_name: Parent name who created the request
		leave_request_id: Created leave request ID
		reason: Leave reason code
		reason_display: Localized reason text
		start_date: Leave start date (YYYY-MM-DD)
		end_date: Leave end date (YYYY-MM-DD)
	"""
	try:
		from erp.api.erp_sis.mobile_push_notification import send_mobile_notification
		
		# Get homeroom teachers for this student
		teachers = _get_homeroom_teachers_for_student(student_id)
		
		if not teachers:
			frappe.logger().info(f"📱 No homeroom teachers to notify for student {student_id}")
			return
		
		# Format dates for display
		try:
			start_date_display = datetime.strptime(str(start_date), '%Y-%m-%d').strftime('%d/%m/%Y')
			end_date_display = datetime.strptime(str(end_date), '%Y-%m-%d').strftime('%d/%m/%Y')
		except:
			start_date_display = str(start_date)
			end_date_display = str(end_date)
		
		# Lấy class_id của học sinh (lớp chủ nhiệm) để mobile app navigate đúng
		class_id = None
		if teachers:
			# Lấy class_id từ SIS Class Student - lớp đầu tiên của học sinh
			class_students = frappe.get_all(
				"SIS Class Student",
				filters={"student_id": student_id},
				fields=["class_id"],
				limit=1
			)
			if class_students:
				class_id = class_students[0].class_id

		# Prepare notification content
		notification_title = "Đơn xin nghỉ phép mới"
		notification_body = f"Phụ huynh gửi đơn nghỉ cho {student_name}. Lý do: {reason_display}. Ngày: {start_date_display} - {end_date_display}"
		
		notification_data = {
			"type": "leave_request",
			"action": "new_leave_from_parent",
			"student_id": student_id,
			"student_name": student_name,
			"parent_name": parent_name,
			"leave_request_id": leave_request_id,
			"class_id": class_id,
			"reason": reason,
			"reason_display": reason_display,
			"start_date": str(start_date),
			"end_date": str(end_date)
		}
		
		# Send notification to each teacher
		success_count = 0
		for teacher in teachers:
			try:
				result = send_mobile_notification(
					user_email=teacher["user_id"],
					title=notification_title,
					body=notification_body,
					data=notification_data
				)
				
				if result.get("success"):
					success_count += 1
					frappe.logger().info(f"✅ Sent leave notification to teacher {teacher['user_id']}")
				else:
					frappe.logger().warning(f"⚠️ Failed to send notification to {teacher['user_id']}: {result.get('message')}")
					
			except Exception as teacher_error:
				frappe.logger().error(f"❌ Error sending notification to {teacher['user_id']}: {str(teacher_error)}")
		
		frappe.logger().info(f"📱 Leave notification sent to {success_count}/{len(teachers)} teachers for student {student_id}")
		
	except Exception as e:
		frappe.logger().error(f"❌ Error in _send_leave_notification_to_teachers: {str(e)}")
		# Don't raise - notification failure shouldn't fail the leave request


def _validate_parent_student_access(parent_id, student_ids):
	"""Validate that parent has access to all students and is key person
	
	Query CRM Family Relationship directly to get guardian-student relationships with key_person flag.
	
	Args:
		parent_id: Guardian name (from _get_current_parent)
		student_ids: List of student IDs to validate
	
	Returns:
		True if guardian is key person for ALL students, False otherwise
	"""
	frappe.logger().info(f"🔍 [KEY_PERSON_CHECK] Validating access - Guardian: {parent_id}, Students: {student_ids}")
	
	# Verify parent_id exists
	if not parent_id:
		frappe.logger().error(f"❌ [KEY_PERSON_CHECK] parent_id is empty!")
		return False
	
	try:
		# Query CRM Family Relationship directly
		# Find all relationships where guardian = parent_id AND key_person = 1
		all_relationships = frappe.get_all(
			"CRM Family Relationship",
			filters={"guardian": parent_id},
			fields=["name", "student", "key_person", "access", "relationship_type", "parent"]
		)
		
		frappe.logger().info(f"✅ [KEY_PERSON_CHECK] Guardian {parent_id} found")
		frappe.logger().info(f"   Total relationships in DB: {len(all_relationships)}")
		
		# Log all relationships
		for idx, rel in enumerate(all_relationships):
			frappe.logger().info(f"   [{idx}] Student: {rel.student}, Key Person: {rel.key_person}, Access: {rel.access}, Type: {rel.relationship_type}, Family: {rel.parent}")
		
	except Exception as e:
		frappe.logger().error(f"❌ [KEY_PERSON_CHECK] Error loading relationships: {str(e)}")
		return False
	
	# Create a dict for quick lookup: {student_id: {key_person, access, ...}}
	student_relationships = {}
	for rel in all_relationships:
		if rel.student not in student_relationships:
			student_relationships[rel.student] = rel
	
	# Check each student
	for student_id in student_ids:
		frappe.logger().info(f"🔎 [KEY_PERSON_CHECK] Checking student: {student_id}")
		
		if student_id not in student_relationships:
			frappe.logger().error(f"❌ [KEY_PERSON_CHECK] Student {student_id} NOT FOUND in relationships for guardian {parent_id}")
			frappe.logger().error(f"   Available students: {list(student_relationships.keys())}")
			return False
		
		rel = student_relationships[student_id]
		frappe.logger().info(f"   Found relationship - Student: {rel.student}, Key Person: {rel.key_person} (type: {type(rel.key_person)}), Access: {rel.access}")
		
		# Check if key_person is True/1
		if not rel.key_person:
			frappe.logger().error(f"❌ [KEY_PERSON_CHECK] Guardian {parent_id} is NOT key_person for student {student_id}")
			frappe.logger().error(f"   Key person flag: {rel.key_person}")
			return False
		
		frappe.logger().info(f"✅ [KEY_PERSON_CHECK] Guardian {parent_id} IS key_person for student {student_id}")

	frappe.logger().info(f"✅ [KEY_PERSON_CHECK] SUCCESS - Guardian {parent_id} is key_person for all {len(student_ids)} students")
	return True


@frappe.whitelist()
def submit_leave_request():
	"""Submit leave request for multiple students"""
	try:
		# Get data from appropriate source based on request type
		# Check if files exist AND not empty
		has_files = frappe.request.files and len(frappe.request.files) > 0
		
		if has_files:
			# FormData with files - use request.form
			data = frappe.request.form
			frappe.logger().info(f"Using frappe.request.form (has {len(frappe.request.files)} files)")
		elif frappe.request.is_json:
			# JSON request - use request.json
			data = frappe.request.json or {}
			frappe.logger().info("Using frappe.request.json (JSON body)")
		else:
			# Fallback to form_dict
			data = frappe.form_dict
			frappe.logger().info("Using frappe.form_dict (fallback)")
		
		if frappe.request.is_json:
			frappe.logger().info(f"frappe.request.json: {frappe.request.json}")

		# Required fields validation (except students, handled separately)
		required_fields = ['reason', 'start_date', 'end_date']
		for field in required_fields:
			if field not in data or not data[field]:
				frappe.logger().error(f"Missing field: {field}, value: {data.get(field)}")
				return validation_error_response(f"Thiếu trường bắt buộc: {field}", {field: [f"Trường {field} là bắt buộc"]})

		# Validate reason
		valid_reasons = ['sick_child', 'family_matters', 'other']
		if data['reason'] not in valid_reasons:
			return validation_error_response("Lý do không hợp lệ", {"reason": ["Lý do phải là một trong: con_ốm, gia_đình_có_việc_bận, lý_do_khác"]})

		# Validate other_reason if reason is 'other'
		if data['reason'] == 'other' and not data.get('other_reason', '').strip():
			return validation_error_response("Vui lòng nhập lý do khác", {"other_reason": ["Vui lòng nhập lý do cụ thể khi chọn 'Lý do khác'"]})

		# Get current parent
		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")

		students = data['students']
		if isinstance(students, str):
			try:
				students = json.loads(students)
			except:
				return validation_error_response("Dữ liệu học sinh không hợp lệ", {"students": ["Định dạng danh sách học sinh không hợp lệ"]})

		# Validate students list
		if not students or (isinstance(students, list) and len(students) == 0):
			return validation_error_response("Vui lòng chọn ít nhất một học sinh", {"students": ["Phải chọn ít nhất một học sinh"]})
		
		# Log the request
		frappe.logger().info(f"📝 [SUBMIT_LEAVE_REQUEST] Parent: {parent_id}, Students requested: {students}, Reason: {data.get('reason')}, Dates: {data.get('start_date')} to {data.get('end_date')}")

		# Validate parent has access to all students AND is key person
		if not _validate_parent_student_access(parent_id, students):
			error_msg = "Bạn chưa được cấp quyền tạo đơn, hãy liên hệ người liên hệ chính hoặc nhà trường để cấp quyền tạo đơn."
			frappe.logger().error(f"❌ Parent {parent_id} failed key_person validation for students {students}")
			
			return error_response(error_msg)

		created_requests = []

		# Create separate request for each student
		for student_id in students:
			# Check for overlapping leave requests
			# This prevents duplicate/overlapping leave records for the same student
			overlap_check = _check_overlapping_leave_requests(student_id, data['start_date'], data['end_date'])
			if overlap_check['has_overlap']:
				# Format overlapping dates (Vietnamese + English) - DD/MM format only
				overlapping_dates = overlap_check['overlapping_dates']
				# Convert from YYYY-MM-DD to DD/MM format
				dates_formatted = []
				for date_str in overlapping_dates:
					try:
						date_obj = datetime.strptime(date_str, '%Y-%m-%d')
						dates_formatted.append(date_obj.strftime('%d/%m'))
					except:
						dates_formatted.append(date_str)
				
				dates_str_vi = ", ".join(dates_formatted)  # e.g. "06/11, 07/11, 08/11"
				
				frappe.logger().warning(f"⚠️ Student {student_id} has overlapping leave requests on dates: {dates_str_vi}")
				
				# Song ngữ error message
				error_msg_vi = f"Ngày {dates_str_vi} đã có đơn xin nghỉ phép."
				
				return error_response(error_msg_vi)
			
			# Get student campus
			student_campus = frappe.db.get_value("CRM Student", student_id, "campus_id")
			if not student_campus:
				continue

			# Create leave request
			try:
				leave_request = frappe.get_doc({
					"doctype": "SIS Student Leave Request",
					"student_id": student_id,
					"parent_id": parent_id,
					"campus_id": student_campus,
					"reason": data['reason'],
					"other_reason": data.get('other_reason', ''),
					"start_date": data['start_date'],
					"end_date": data['end_date'],
					"description": data.get('description', ''),
					"submitted_at": datetime.now()
				})
				
				# Bypass permissions but allow validation to run (to populate student_name, parent_name, student_code)
				leave_request.flags.ignore_permissions = True
				leave_request.insert()
			except Exception as e:
				frappe.logger().error(f"❌ Error creating leave request for student {student_id}: {str(e)}")
				error_detail = str(e)
				return error_response(f"Lỗi khi tạo đơn: {error_detail}")

			# Attach files if any
			if frappe.request.files:
				for file_key, file_obj in frappe.request.files.items():
					if file_key.startswith('documents'):
						file_doc = frappe.get_doc({
							"doctype": "File",
							"file_name": file_obj.filename,
							"attached_to_doctype": "SIS Student Leave Request",
							"attached_to_name": leave_request.name,
							"content": file_obj.stream.read(),
							"is_private": 1
						})
						file_doc.insert(ignore_permissions=True)

			created_requests.append({
				"id": leave_request.name,
				"student_id": student_id,
				"student_name": leave_request.student_name
			})

		# Transform reason to Vietnamese for notification
		reason_mapping = {
			'sick_child': 'Con ốm',
			'family_matters': 'Gia đình có việc bận',
			'other': 'Lý do khác'
		}
		
		# Get parent name for notification
		parent_name = "Phụ huynh"
		try:
			guardian_doc = frappe.get_doc("CRM Guardian", parent_id)
			parent_name = guardian_doc.guardian_name or "Phụ huynh"
		except:
			pass

		# Send push notifications to homeroom teachers for each student
		for req in created_requests:
			try:
				reason_display = data.get('other_reason') if data['reason'] == 'other' else reason_mapping.get(data['reason'], data['reason'])
				_send_leave_notification_to_teachers(
					student_id=req["student_id"],
					student_name=req["student_name"],
					parent_name=parent_name,
					leave_request_id=req["id"],
					reason=data['reason'],
					reason_display=reason_display,
					start_date=data['start_date'],
					end_date=data['end_date']
				)
			except Exception as noti_error:
				# Don't fail the request if notification fails
				frappe.logger().error(f"❌ Error sending notification for leave request {req['id']}: {str(noti_error)}")

		return success_response({
			"message": f"Đã gửi đơn xin nghỉ phép cho {len(created_requests)} học sinh",
			"requests": created_requests
		})

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Leave Request Submit Error")
		return error_response(f"Lỗi khi gửi đơn xin nghỉ phép: {str(e)}")


@frappe.whitelist()
def get_my_leave_requests(student_id=None):
	"""Get leave requests for current parent's students"""
	try:
		# Get student_id from query parameters if not passed as argument
		if not student_id:
			student_id = frappe.request.args.get('student_id')
		
		frappe.logger().info(f"📝 [GET_LEAVE_REQUESTS] Called with student_id: {student_id}")
		frappe.logger().info(f"📝 [GET_LEAVE_REQUESTS] Request args: {frappe.form_dict}")
		frappe.logger().info(f"📝 [GET_LEAVE_REQUESTS] Query args: {dict(frappe.request.args)}")
		
		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")
		
		# Get parent's email for ownership check
		parent_user_email = frappe.session.user
		parent_guardian_id = None
		if "@parent.wellspring.edu.vn" in parent_user_email:
			parent_guardian_id = parent_user_email.split("@")[0]
		actual_parent_id = parent_id

		# Get all students where current guardian has any relationship (key person or not)
		# This ensures parent sees all leave requests for their children, even if created by teacher
		# Query CRM Family Relationship directly to get all student IDs linked to this guardian
		all_relationships = frappe.get_all(
			"CRM Family Relationship",
			filters={"guardian": parent_id},
			fields=["student"]
		)
		student_ids = list(set([rel.student for rel in all_relationships]))  # Unique student IDs
		
		if not student_ids:
			return list_response([])  # No students linked to this parent

		# Build filters - filter by student_id instead of parent_id
		# This ensures all parents of a student can see leave requests for that student
		filters = {"student_id": ["in", student_ids]}
		if student_id:
			# If specific student_id requested, ensure it belongs to this parent
			frappe.logger().info(f"DEBUG: Requested student_id={student_id}, parent student_ids={student_ids}")
			if student_id in student_ids:
				filters = {"student_id": student_id}
				frappe.logger().info(f"DEBUG: Using specific student filter: {filters}")
			else:
				frappe.logger().info(f"DEBUG: Student {student_id} not in parent's students {student_ids}, returning empty")
				return list_response([])  # Student doesn't belong to this parent

		# Get leave requests - include owner field
		frappe.logger().info(f"DEBUG: Final filters used: {filters}")
		requests = frappe.get_all(
			"SIS Student Leave Request",
			filters=filters,
			fields=[
				"name", "student_id", "student_name", "student_code",
				"reason", "other_reason", "start_date", "end_date",
				"total_days", "description", "submitted_at",
				"creation", "modified", "owner", "parent_id"
			],
			order_by="creation desc"
		)
		frappe.logger().info(f"DEBUG: Found {len(requests)} leave requests")
		for req in requests[:3]:  # Log first 3 requests
			frappe.logger().info(f"DEBUG: Request {req.name} for student {req.student_id}")

		# Transform reason to Vietnamese for display
		reason_mapping = {
			'sick_child': 'Con ốm',
			'family_matters': 'Gia đình có việc bận',
			'other': 'Lý do khác'
		}

		for request in requests:
			request['reason_display'] = reason_mapping.get(request['reason'], request['reason'])
			
			# Check if can edit (within 24 hours AND created by this parent)
			# Leave can only be edited if:
			# 1. Created by this parent (owner is parent's email) OR owner is None (old records)
			# 2. Within 24 hours
			is_created_by_parent = False
			if request.get('owner'):
				# Check if owner is parent's email or parent portal user
				if request['owner'] == parent_user_email:
					is_created_by_parent = True
				elif parent_guardian_id and request['owner'].startswith(parent_guardian_id):
					is_created_by_parent = True
				# Also check if owner is a parent portal email pattern
				elif "@parent.wellspring.edu.vn" in str(request['owner']):
					owner_guardian_id = str(request['owner']).split("@")[0]
					if owner_guardian_id == parent_guardian_id:
						is_created_by_parent = True
			else:
				# Old records without owner - assume created by parent if parent_id matches
				is_created_by_parent = (request.get('parent_id') == actual_parent_id) if actual_parent_id else False
			
			if request['submitted_at']:
				submitted_time = datetime.strptime(str(request['submitted_at']), '%Y-%m-%d %H:%M:%S.%f')
				time_diff = datetime.now() - submitted_time
				within_24_hours = time_diff.total_seconds() <= (24 * 60 * 60)
				request['can_edit'] = is_created_by_parent and within_24_hours
			else:
				request['can_edit'] = is_created_by_parent
			
			# Add creator info for display
			request['is_created_by_parent'] = is_created_by_parent

		return list_response(requests)

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Get Leave Requests Error")
		return error_response(f"Lỗi khi lấy danh sách đơn xin nghỉ phép: {str(e)}")


@frappe.whitelist()
def update_leave_request():
	"""Update leave request (within 24 hours)"""
	try:
		# Get data from appropriate source based on request type
		# Check if files exist AND not empty
		has_files = frappe.request.files and len(frappe.request.files) > 0
		
		if has_files:
			# FormData with files - use request.form
			data = frappe.request.form
		elif frappe.request.is_json:
			# JSON request - use request.json
			data = frappe.request.json or {}
		else:
			# Fallback to form_dict
			data = frappe.form_dict

		# Required fields
		if 'id' not in data:
			return validation_error_response("Thiếu ID đơn xin nghỉ phép", {"id": ["ID đơn xin nghỉ phép là bắt buộc"]})

		leave_request_id = data['id']

		# Get leave request
		leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

		# Check ownership - only parent who created can edit
		parent_id = _get_current_parent()
		if leave_request.parent_id != parent_id:
			return error_response("Bạn không có quyền chỉnh sửa đơn này")
		
		# Check if created by this parent (via owner field)
		parent_user_email = frappe.session.user
		is_created_by_parent = False
		if leave_request.owner:
			# Check if owner is parent's email or parent portal user
			if parent_user_email == "Guest":
				return error_response("Vui lòng đăng nhập để chỉnh sửa đơn")
			if leave_request.owner == parent_user_email:
				is_created_by_parent = True
			else:
				# Check if owner matches parent guardian_id pattern
				if "@parent.wellspring.edu.vn" in parent_user_email:
					parent_guardian_id = parent_user_email.split("@")[0]
					if leave_request.owner.startswith(parent_guardian_id):
						is_created_by_parent = True
		else:
			# Old records without owner - assume created by parent if parent_id matches
			is_created_by_parent = (leave_request.parent_id == parent_id)
		
		if not is_created_by_parent:
			return error_response("Bạn chỉ có thể chỉnh sửa đơn nghỉ phép mà bạn đã tạo")

		# Check if can edit (within 24 hours)
		if not leave_request.can_edit():
			return error_response("Đã quá thời hạn chỉnh sửa (24 giờ)")

		# Update fields
		updatable_fields = ['reason', 'other_reason', 'start_date', 'end_date', 'description']

		for field in updatable_fields:
			if field in data:
				leave_request.set(field, data[field])

		# Handle file attachments if any
		if frappe.request.files:
			for file_key, file_obj in frappe.request.files.items():
				if file_key.startswith('documents'):
					file_doc = frappe.get_doc({
						"doctype": "File",
						"file_name": file_obj.filename,
						"attached_to_doctype": "SIS Student Leave Request",
						"attached_to_name": leave_request.name,
						"content": file_obj.stream.read(),
						"is_private": 1
					})
					file_doc.insert(ignore_permissions=True)

		# Save - this will trigger on_update() hook which re-syncs attendance if dates changed
		leave_request.flags.ignore_permissions = True
		leave_request.save()
		
		# Commit to ensure attendance sync is persisted
		frappe.db.commit()

		return success_response({
			"message": "Đã cập nhật đơn xin nghỉ phép thành công",
			"request": {
				"id": leave_request.name,
				"student_name": leave_request.student_name
			}
		})

	except frappe.DoesNotExistError:
		return error_response("Không tìm thấy đơn xin nghỉ phép")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Update Leave Request Error")
		return error_response(f"Lỗi khi cập nhật đơn xin nghỉ phép: {str(e)}")


@frappe.whitelist()
def delete_leave_request():
	"""Delete leave request"""
	try:
		data = json.loads(frappe.request.data or '{}')
		frappe.logger().info(f"Delete leave request data: {data}")

		# Required field
		if 'id' not in data:
			return validation_error_response("Thiếu ID đơn xin nghỉ phép", {"id": ["ID đơn xin nghỉ phép là bắt buộc"]})

		leave_request_id = data['id']

		# Get leave request
		leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

		# Check ownership - only parent who created can delete
		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")

		if leave_request.parent_id != parent_id:
			return error_response("Bạn không có quyền xóa đơn này")
		
		# Check if created by this parent (via owner field)
		parent_user_email = frappe.session.user
		is_created_by_parent = False
		if leave_request.owner:
			# Check if owner is parent's email or parent portal user
			if parent_user_email == "Guest":
				return error_response("Vui lòng đăng nhập để xóa đơn")
			if leave_request.owner == parent_user_email:
				is_created_by_parent = True
			else:
				# Check if owner matches parent guardian_id pattern
				if "@parent.wellspring.edu.vn" in parent_user_email:
					parent_guardian_id = parent_user_email.split("@")[0]
					if leave_request.owner.startswith(parent_guardian_id):
						is_created_by_parent = True
		else:
			# Old records without owner - assume created by parent if parent_id matches
			is_created_by_parent = (leave_request.parent_id == parent_id)
		
		if not is_created_by_parent:
			return error_response("Bạn chỉ có thể xóa đơn nghỉ phép mà bạn đã tạo")

		# Check if within editable time (24 hours)
		if leave_request.submitted_at:
			submitted_time = datetime.strptime(str(leave_request.submitted_at), '%Y-%m-%d %H:%M:%S.%f')
			time_diff = datetime.now() - submitted_time
			if time_diff.total_seconds() > (24 * 60 * 60):
				return error_response("Đã quá thời hạn xóa đơn (24 giờ)")

		# Delete the request
		frappe.delete_doc("SIS Student Leave Request", leave_request_id, ignore_permissions=True)

		return success_response({"message": "Đã xóa đơn xin nghỉ phép thành công"})

	except frappe.DoesNotExistError:
		return error_response("Không tìm thấy đơn xin nghỉ phép")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Delete Leave Request Error")
		return error_response(f"Lỗi khi xóa đơn xin nghỉ phép: {str(e)}")


@frappe.whitelist()
def get_student_leave_requests(student_id):
	"""Get leave requests for a specific student (for teachers/admins)"""
	try:
		if not student_id:
			return validation_error_response("Thiếu student_id", {"student_id": ["Student ID là bắt buộc"]})

		# Check permissions (SIS Teacher, SIS Admin, SIS Manager, System Manager)
		user_roles = frappe.get_roles(frappe.session.user)
		allowed_roles = ['SIS Teacher', 'SIS Admin', 'SIS Manager', 'System Manager']

		if not any(role in user_roles for role in allowed_roles):
			return error_response("Bạn không có quyền xem thông tin này")

		requests = frappe.get_all(
			"SIS Student Leave Request",
			filters={"student_id": student_id},
			fields=[
				"name", "student_name", "parent_name", "reason", "other_reason",
				"start_date", "end_date", "total_days", "description",
				"submitted_at", "creation", "modified"
			],
			order_by="creation desc"
		)

		# Transform reason to Vietnamese
		reason_mapping = {
			'sick_child': 'Con ốm',
			'family_matters': 'Gia đình có việc bận',
			'other': 'Lý do khác'
		}

		for request in requests:
			request['reason_display'] = reason_mapping.get(request['reason'], request['reason'])

		return list_response(requests)

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Get Student Leave Requests Error")
		return error_response(f"Lỗi khi lấy đơn xin nghỉ phép của học sinh: {str(e)}")


# @frappe.whitelist()
# def debug_relationships():
# 	"""Debug API to check parent-student relationships"""
# 	try:
# 		parent_id = _get_current_parent()
# 		if not parent_id:
# 			return error_response("Không tìm thấy thông tin phụ huynh")

# 		# Get all relationships for this parent
# 		parent_relationships = frappe.get_all("CRM Family Relationship",
# 			filters={"parent": parent_id},
# 			fields=["student", "parent", "relationship_type"]
# 		)

# 		# Get all students from auth storage (frontend data)
# 		user_email = frappe.session.user
# 		if "@parent.wellspring.edu.vn" in user_email:
# 			guardian_id_from_email = user_email.split("@")[0]

# 			# Get actual guardian name
# 			actual_guardian_name = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id_from_email}, "name")

# 			# Get comprehensive data like frontend does
# 			comprehensive_data = frappe.get_all(
# 				"CRM Family Relationship",
# 				filters={"parent": actual_guardian_name},
# 				fields=["student", "relationship_type"]
# 			)

# 			students_data = []
# 			for rel in comprehensive_data:
# 				try:
# 					student_doc = frappe.get_doc("CRM Student", rel.student)
# 					students_data.append({
# 						"name": student_doc.name,
# 						"student_name": student_doc.student_name,
# 						"student_code": student_doc.student_code
# 					})
# 				except:
# 					continue

# 		return success_response({
# 			"parent_id": parent_id,
# 			"user_email": user_email,
# 			"parent_relationships": parent_relationships,
# 			"students_from_relationships": students_data
# 		})

# 	except Exception as e:
# 		frappe.logger().error(f"Debug relationships error: {str(e)}")
# 		return error_response(f"Lỗi debug: {str(e)}")


@frappe.whitelist()
def get_leave_request_attachments():
	"""
	Get all attachments for a leave request - PARENT PORTAL ONLY

	This endpoint is dedicated for parent portal usage.
	Admins should use erp.api.erp_sis.leave.get_leave_request_attachments instead.
	"""
	try:
		# Try to get leave_request_id from various sources
		leave_request_id = frappe.form_dict.get('leave_request_id') or frappe.request.args.get('leave_request_id')

		if not leave_request_id:
			return validation_error_response("Thiếu leave_request_id", {"leave_request_id": ["Leave request ID là bắt buộc"]})

		# Get the leave request to check permissions
		leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

		# PARENT PORTAL: Verify parent has access to this student
		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")

		# Get parent's students to verify access
		all_relationships = frappe.get_all(
			"CRM Family Relationship",
			filters={"guardian": parent_id},
			fields=["student"]
		)
		student_ids = [rel.student for rel in all_relationships]

		# Check if the leave request's student belongs to this parent
		if leave_request.student_id not in student_ids:
			return forbidden_response("Bạn không có quyền truy cập file đính kèm của đơn này")

		# Get all files attached to this leave request
		attachments = frappe.get_all("File",
			filters={
				"attached_to_doctype": "SIS Student Leave Request",
				"attached_to_name": leave_request_id,
				"is_private": 1
			},
			fields=["name", "file_name", "file_url", "file_size", "creation"],
			order_by="creation desc"
		)

		# Add full URLs for files
		for attachment in attachments:
			if attachment.file_url and not attachment.file_url.startswith('http'):
				attachment.file_url = frappe.utils.get_url(attachment.file_url)

		return list_response(attachments)

	except frappe.DoesNotExistError:
		return not_found_response("Không tìm thấy đơn xin nghỉ phép")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Get Leave Request Attachments Error")
		return error_response(f"Lỗi khi lấy file đính kèm: {str(e)}")


@frappe.whitelist()
def get_all_leave_requests():
	"""Get all leave requests (for admins/managers)"""
	try:
		# Check permissions
		user_roles = frappe.get_roles(frappe.session.user)
		allowed_roles = ['SIS Admin', 'SIS Manager', 'System Manager']

		if not any(role in user_roles for role in allowed_roles):
			return error_response("Bạn không có quyền xem thông tin này")

		requests = frappe.get_all(
			"SIS Student Leave Request",
			fields=[
				"name", "student_name", "student_code", "parent_name",
				"campus_id", "reason", "start_date", "end_date",
				"total_days", "submitted_at"
			],
			order_by="creation desc"
		)

		# Transform reason to Vietnamese
		reason_mapping = {
			'sick_child': 'Con ốm',
			'family_matters': 'Gia đình có việc bận',
			'other': 'Lý do khác'
		}

		for request in requests:
			request['reason_display'] = reason_mapping.get(request['reason'], request['reason'])

		return list_response(requests)

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Parent Portal Get All Leave Requests Error")
		return error_response(f"Lỗi khi lấy danh sách tất cả đơn xin nghỉ phép: {str(e)}")
