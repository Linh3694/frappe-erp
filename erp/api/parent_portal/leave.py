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


def _normalize_user_email(email):
	"""Chuẩn hóa email để so sánh owner (không phân biệt hoa thường)."""
	return (email or "").strip().lower()


def _is_leave_created_via_parent_portal(owner):
	"""
	Đơn được tạo qua Parent Portal (bất kỳ phụ huynh nào), không phải giáo viên/SIS.
	Cùng tiêu chí với erp.api.erp_sis.leave — dựa trên domain email owner.
	"""
	return "@parent.wellspring.edu.vn" in _normalize_user_email(owner)


def _is_leave_created_by_current_parent(owner, parent_user_email=None):
	"""
	Phụ huynh đang đăng nhập có phải người tạo đơn không (dùng cho can_edit / update / delete).

	Returns:
		True/False nếu owner có giá trị.
		None nếu owner rỗng (caller dùng fallback parent_id cho bản ghi cũ).
	"""
	parent_user_email = parent_user_email or frappe.session.user
	if parent_user_email == "Guest":
		return False

	owner_norm = _normalize_user_email(owner)
	if not owner_norm:
		return None

	parent_norm = _normalize_user_email(parent_user_email)
	if owner_norm == parent_norm:
		return True

	if "@parent.wellspring.edu.vn" in owner_norm and "@parent.wellspring.edu.vn" in parent_norm:
		return owner_norm.split("@")[0] == parent_norm.split("@")[0]

	return False


def _is_within_24_hours(submitted_at):
	"""Kiểm tra đơn còn trong thời hạn 24 giờ kể từ submitted_at."""
	if not submitted_at:
		return True
	submitted_time = datetime.strptime(str(submitted_at), "%Y-%m-%d %H:%M:%S.%f")
	time_diff = datetime.now() - submitted_time
	return time_diff.total_seconds() <= (24 * 60 * 60)


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
		from erp.api.erp_sis.mobile_push_notification import send_mobile_notification_persisted
		
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
				result = send_mobile_notification_persisted(
					user_email=teacher["user_id"],
					title=notification_title,
					body=notification_body,
					data=notification_data,
					erp_notification_type="leave",
					reference_doctype="SIS Student Leave Request",
					reference_name=leave_request_id,
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
	"""Validate phụ huynh có quan hệ gia đình với các học sinh
	
	Chỉ cần có quan hệ trong CRM Family Relationship là đủ quyền tạo đơn.
	Không yêu cầu key_person nữa.
	
	Args:
		parent_id: Guardian name (from _get_current_parent)
		student_ids: List of student IDs to validate
	
	Returns:
		True nếu guardian có quan hệ với TẤT CẢ các student, False nếu không
	"""
	frappe.logger().info(f"🔍 [FAMILY_CHECK] Validating access - Guardian: {parent_id}, Students: {student_ids}")
	
	if not parent_id:
		frappe.logger().error(f"❌ [FAMILY_CHECK] parent_id is empty!")
		return False
	
	try:
		all_relationships = frappe.get_all(
			"CRM Family Relationship",
			filters={"guardian": parent_id},
			fields=["name", "student", "relationship_type", "parent"]
		)
		
		frappe.logger().info(f"✅ [FAMILY_CHECK] Guardian {parent_id} found, total relationships: {len(all_relationships)}")
		
	except Exception as e:
		frappe.logger().error(f"❌ [FAMILY_CHECK] Error loading relationships: {str(e)}")
		return False
	
	student_set = set(rel.student for rel in all_relationships)
	
	for student_id in student_ids:
		if student_id not in student_set:
			frappe.logger().error(f"❌ [FAMILY_CHECK] Student {student_id} NOT FOUND in relationships for guardian {parent_id}")
			return False
		
		frappe.logger().info(f"✅ [FAMILY_CHECK] Guardian {parent_id} has relationship with student {student_id}")

	frappe.logger().info(f"✅ [FAMILY_CHECK] SUCCESS - Guardian {parent_id} has access to all {len(student_ids)} students")
	return True


def _get_student_display_name(student_id):
	"""Lấy tên hiển thị của học sinh để báo lỗi theo từng HS."""
	return frappe.db.get_value("CRM Student", student_id, "student_name") or student_id


def _format_overlap_dates(overlapping_dates):
	"""Chuyển danh sách ngày overlap sang định dạng DD/MM."""
	dates_formatted = []
	for date_str in overlapping_dates:
		try:
			date_obj = datetime.strptime(date_str, '%Y-%m-%d')
			dates_formatted.append(date_obj.strftime('%d/%m'))
		except Exception:
			dates_formatted.append(date_str)
	return dates_formatted


def _validate_students_for_leave_batch(students, start_date, end_date):
	"""Validate tất cả học sinh trước khi tạo đơn batch.

	Returns:
		(errors, student_campuses): errors là list message; student_campuses map student_id -> campus_id
	"""
	errors = []
	student_campuses = {}

	for student_id in students:
		student_name = _get_student_display_name(student_id)

		overlap_check = _check_overlapping_leave_requests(student_id, start_date, end_date)
		if overlap_check['has_overlap']:
			dates_str_vi = ", ".join(_format_overlap_dates(overlap_check['overlapping_dates']))
			frappe.logger().warning(
				f"⚠️ Student {student_id} has overlapping leave requests on dates: {dates_str_vi}"
			)
			errors.append(f"{student_name}: Ngày {dates_str_vi} đã có đơn xin nghỉ phép.")
			continue

		student_campus = frappe.db.get_value("CRM Student", student_id, "campus_id")
		if not student_campus:
			errors.append(f"{student_name}: Không tìm thấy thông tin campus.")
			continue

		student_campuses[student_id] = student_campus

	return errors, student_campuses


def _read_leave_request_documents():
	"""Đọc file đính kèm một lần trước vòng lặp tạo đơn."""
	document_files = []
	if not frappe.request.files:
		return document_files

	for file_key, file_obj in frappe.request.files.items():
		if file_key.startswith('documents'):
			document_files.append({
				"file_name": file_obj.filename,
				"content": file_obj.stream.read(),
			})

	return document_files


def _attach_documents_to_leave_request(leave_request_name, document_files):
	"""Gắn file đính kèm vào đơn nghỉ phép."""
	for doc in document_files:
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": doc["file_name"],
			"attached_to_doctype": "SIS Student Leave Request",
			"attached_to_name": leave_request_name,
			"content": doc["content"],
			"is_private": 1,
		})
		file_doc.insert(ignore_permissions=True)


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

		# Validate phụ huynh có quan hệ gia đình với học sinh
		if not _validate_parent_student_access(parent_id, students):
			error_msg = "Bạn không có quan hệ gia đình với học sinh được chọn. Vui lòng liên hệ nhà trường."
			frappe.logger().error(f"❌ Parent {parent_id} has no family relationship with students {students}")
			
			return error_response(error_msg)

		# Validate tất cả HS trước — không insert nếu có lỗi
		validation_errors, student_campuses = _validate_students_for_leave_batch(
			students, data['start_date'], data['end_date']
		)
		if validation_errors:
			return error_response("\n".join(validation_errors))

		document_files = _read_leave_request_documents()
		created_requests = []

		try:
			# Tạo đơn riêng cho từng học sinh sau khi validate pass
			for student_id in students:
				student_campus = student_campuses[student_id]
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

				# Bypass permissions nhưng vẫn chạy validation (populate student_name, ...)
				leave_request.flags.ignore_permissions = True
				leave_request.insert()

				if document_files:
					_attach_documents_to_leave_request(leave_request.name, document_files)

				created_requests.append({
					"id": leave_request.name,
					"student_id": student_id,
					"student_name": leave_request.student_name
				})
		except Exception as e:
			frappe.db.rollback()
			frappe.logger().error(f"❌ Error creating leave requests batch: {str(e)}")
			return error_response(f"Lỗi khi tạo đơn: {str(e)}")

		if len(created_requests) != len(students):
			frappe.db.rollback()
			return error_response("Không thể tạo đầy đủ đơn nghỉ phép cho tất cả học sinh.")

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
		
		parent_user_email = frappe.session.user

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

			# Badge: đơn do phụ huynh (portal) hay giáo viên/SIS tạo — không phụ thuộc PH đang xem
			request['is_created_by_parent'] = _is_leave_created_via_parent_portal(
				request.get('owner')
			)

			# can_edit: chỉ PH đã tạo đơn mới được sửa, trong vòng 24 giờ
			created_by_me = _is_leave_created_by_current_parent(
				request.get('owner'), parent_user_email
			)
			if created_by_me is None:
				# Bản ghi cũ không có owner — fallback theo parent_id (người tạo)
				created_by_me = request.get('parent_id') == parent_id

			request['can_edit'] = bool(created_by_me) and _is_within_24_hours(
				request.get('submitted_at')
			)

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

		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")

		if frappe.session.user == "Guest":
			return error_response("Vui lòng đăng nhập để chỉnh sửa đơn")

		# Quyền xem: PH có quan hệ với học sinh của đơn
		if not _validate_parent_student_access(parent_id, [leave_request.student_id]):
			return error_response("Bạn không có quyền chỉnh sửa đơn này")

		# Chỉ PH đã tạo đơn mới được sửa
		created_by_me = _is_leave_created_by_current_parent(leave_request.owner)
		if created_by_me is None:
			created_by_me = leave_request.parent_id == parent_id
		if not created_by_me:
			return error_response("Bạn chỉ có thể chỉnh sửa đơn nghỉ phép mà bạn đã tạo")

		if leave_request.owner and not _is_leave_created_via_parent_portal(leave_request.owner):
			return error_response("Không thể chỉnh sửa đơn nghỉ phép do giáo viên tạo")

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

		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")

		if frappe.session.user == "Guest":
			return error_response("Vui lòng đăng nhập để xóa đơn")

		if not _validate_parent_student_access(parent_id, [leave_request.student_id]):
			return error_response("Bạn không có quyền xóa đơn này")

		created_by_me = _is_leave_created_by_current_parent(leave_request.owner)
		if created_by_me is None:
			created_by_me = leave_request.parent_id == parent_id
		if not created_by_me:
			return error_response("Bạn chỉ có thể xóa đơn nghỉ phép mà bạn đã tạo")

		if leave_request.owner and not _is_leave_created_via_parent_portal(leave_request.owner):
			return error_response("Không thể xóa đơn nghỉ phép do giáo viên tạo")

		if not _is_within_24_hours(leave_request.submitted_at):
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
