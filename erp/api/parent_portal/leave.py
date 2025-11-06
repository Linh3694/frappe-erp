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


def _validate_parent_student_access(parent_id, student_ids):
	"""Validate that parent has access to all students and is key person
	
	Args:
		parent_id: Guardian name (from _get_current_parent)
		student_ids: List of student IDs to validate
	
	Returns:
		True if guardian is key person for ALL students, False otherwise
	"""
	for student_id in student_ids:
		# Check if relationship exists where:
		# - guardian = parent_id (current logged in guardian)
		# - student = student_id
		# - key_person = true
		relationship = frappe.db.get_value("CRM Family Relationship", {
			"guardian": parent_id,  # guardian field, not parent (parent is family name)
			"student": student_id,
			"key_person": 1  # Must be key person
		}, ["name", "key_person"])

		if not relationship:  # If no relationship found or key_person is not 1
			frappe.logger().warning(f"Guardian {parent_id} is NOT key_person for student {student_id}")
			return False

	frappe.logger().info(f"Guardian {parent_id} validated as key_person for all {len(student_ids)} students")
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

		# Validate parent has access to all students AND is key person
		if not _validate_parent_student_access(parent_id, students):
			return error_response("Bạn không có quyền gửi đơn cho một số học sinh đã chọn. Chỉ người liên hệ chính (key person) mới có thể tạo đơn nghỉ phép.")

		created_requests = []

		# Create separate request for each student
		for student_id in students:
			# Get student campus
			student_campus = frappe.db.get_value("CRM Student", student_id, "campus_id")
			if not student_campus:
				continue

			# Create leave request
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

			leave_request.insert(ignore_permissions=True)

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
	family_relationships = frappe.get_all(
		"CRM Family Relationship",
		filters={"guardian": parent_id},  # guardian field, not parent (parent is family name)
		fields=["student"]
	)
	
	student_ids = [rel.student for rel in family_relationships] if family_relationships else []
	
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

		# Validate and save
		leave_request.save(ignore_permissions=True)

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

		# PARENT PORTAL: Only allow parents to see their own children's leave request attachments
		parent_id = _get_current_parent()
		if not parent_id:
			return error_response("Không tìm thấy thông tin phụ huynh")

		if leave_request.parent_id != parent_id:
			return forbidden_response("Bạn chỉ có thể xem file đính kèm của đơn nghỉ phép của con mình")

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
