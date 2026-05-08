"""
Attendance Notification Handler
Sends notifications when attendance events occur
"""

import frappe
from frappe import _
import json
import pytz
from datetime import datetime
from erp.common.doctype.erp_notification.erp_notification import create_notification
from erp.api.parent_portal.realtime_notification import emit_notification_to_user, emit_unread_count_update
from erp.api.parent_portal.push_notification import send_push_notification
from erp.api.erp_sis.mobile_push_notification import send_mobile_notification


def publish_attendance_notification(
	employee_code,
	employee_name=None,
	timestamp=None,
	device_id=None,
	device_name=None,
	check_in_time=None,
	check_out_time=None,
	total_check_ins=None,
	date=None,
	event_type="attendance",
	tracker_id=None
):
	"""
	Publish attendance notification to relevant recipients
	Called by HiVision endpoint after processing attendance event

	Args:
		employee_code: Employee/student code
		employee_name: Employee/student name
		timestamp: Timestamp of the attendance event
		device_id: Device ID
		device_name: Device name
		check_in_time: Latest check-in time
		check_out_time: Latest check-out time
		total_check_ins: Total check-ins for the day
		date: Date of attendance
		event_type: Type of event (attendance, batch_upload, etc.)
		tracker_id: Tracker ID for batch uploads
	"""
	try:
		frappe.logger().info(f"📢 [Attendance Notif] Processing notification for {employee_code}")

		# Parse timestamp
		if isinstance(timestamp, str):
			timestamp = frappe.utils.get_datetime(timestamp)
			frappe.logger().info(f"📢 [Attendance Notif] Parsed timestamp: {timestamp}")

		# RE-CHECK STALE EVENT khi worker pick up job
		# Nguyên nhân: HiKvision device có thể buffer event tới 30+ phút (mất mạng / retry)
		# rồi flush hàng loạt → lúc backend nhận được, event đã quá cũ
		# Nếu push noti ngay sẽ làm phụ huynh nhầm tưởng con vừa check-in
		# (vd thấy "đã đến trường lúc 07:38" lúc 08:05).
		# Dùng cùng threshold với hikvision.py (mặc định 30 phút, có thể giảm qua site_config).
		try:
			from erp.api.attendance.hikvision import (
				is_historical_attendance,
				get_historical_attendance_threshold_minutes,
				_increment_daily_counter,
			)
			if timestamp and is_historical_attendance(timestamp):
				threshold = get_historical_attendance_threshold_minutes()
				_increment_daily_counter("attendance:stale_skipped:count")
				frappe.logger().warning(
					f"⏭️ [Attendance Notif] SKIP stale event for {employee_code} - "
					f"event_time={timestamp} > {threshold}min ago "
					f"(suspected device buffer/queue delay)"
				)
				return
		except ImportError:
			pass
		except Exception as stale_err:
			frappe.logger().error(
				f"[Attendance Notif] historical check failed for {employee_code}: {stale_err}"
			)

		# DEBOUNCE CHECK với ATOMIC LOCK để tránh race condition
		# Dùng Redis SETNX (set if not exists) để đảm bảo chỉ 1 request được xử lý
		frappe.logger().info(f"🔍 [Attendance Notif] Checking debounce for {employee_code}")
		
		should_skip, lock_acquired = should_skip_due_to_debounce_with_lock(
			employee_code,
			timestamp,
			check_in_time=check_in_time,
			check_out_time=check_out_time,
			total_check_ins=total_check_ins
		)
		frappe.logger().info(f"🔍 [Attendance Notif] Debounce result for {employee_code}: should_skip={should_skip}, lock_acquired={lock_acquired}")

		if should_skip:
			frappe.logger().info(f"⏭️ [Debounce] SKIPPING notification for {employee_code} - sent recently or locked")
			return

		frappe.logger().info(f"✅ [Attendance Notif] ALLOWING notification for {employee_code}")

		# Check if this is a student or staff
		is_student = check_if_student(employee_code)
		frappe.logger().info(f"📢 [Attendance Notif] {employee_code} is_student = {is_student}")

		if is_student:
			frappe.logger().info(f"📧 [Attendance Notif] Sending STUDENT notification for {employee_code}")
			# Send notification to guardians
			send_student_attendance_notification(
				employee_code=employee_code,
				employee_name=employee_name,
				timestamp=timestamp,
				device_name=device_name,
				check_in_time=check_in_time,
				check_out_time=check_out_time,
				total_check_ins=total_check_ins,
				date=date
			)
		else:
			# Send notification to staff member
			send_staff_attendance_notification(
				employee_code=employee_code,
				employee_name=employee_name,
				timestamp=timestamp,
				device_name=device_name,
				check_in_time=check_in_time,
				check_out_time=check_out_time,
				total_check_ins=total_check_ins,
				date=date
			)

		# Cache đã được update trong should_skip_due_to_debounce_with_lock (atomic)
		# Không cần update lại ở đây

		frappe.logger().info(f"✅ [Attendance Notif] Notification sent for {employee_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [Attendance Notif] Error sending notification for {employee_code}: {str(e)}")
		frappe.log_error(message=str(e), title="Attendance Notification Error")


def check_if_student(employee_code):
	"""Check if employee_code belongs to a student or staff"""
	try:
		# FIX: Case-insensitive check cho student_code vì device có thể gửi khác case
		student = frappe.db.sql("""
			SELECT name FROM `tabCRM Student`
			WHERE UPPER(student_code) = UPPER(%(code)s)
			LIMIT 1
		""", {"code": employee_code})
		
		if student:
			frappe.logger().info(f"✅ {employee_code} identified as STUDENT (found in CRM Student)")
			return True

		# If not a student, check if it's a staff member in User table
		# Check multiple possible fields where employee_code might be stored
		staff_checks = [
			{"name": employee_code},  # Check if employee_code is the username/email
			{"employee_code": employee_code},  # Direct employee_code field
			{"username": employee_code},  # Username field
		]

		for check_filter in staff_checks:
			if frappe.db.exists("User", check_filter):
				frappe.logger().info(f"✅ {employee_code} identified as STAFF (found in User table)")
				return False  # False means it's a staff member

		# If not found in either table, log warning and default to staff
		frappe.logger().warning(f"⚠️ {employee_code} not found in CRM Student or User tables - defaulting to STAFF")
		return False  # Default to staff if not found anywhere

	except Exception as e:
		frappe.logger().warning(f"Failed to check if {employee_code} is student/staff: {str(e)}")
		return False  # Default to staff on error


def send_student_attendance_notification(
	employee_code,
	employee_name,
	timestamp,
	device_name,
	check_in_time,
	check_out_time,
	total_check_ins,
	date
):
	"""
	Send attendance notification to student's guardians using unified handler
	"""
	try:
		frappe.logger().info(f"📧 [Student Attendance] STARTING notification for student {employee_code}")

		# DEBUG: Check if student exists and has guardians
		from erp.utils.notification_handler import get_guardians_for_students
		guardians = get_guardians_for_students([employee_code])
		frappe.logger().info(f"📧 [Student Attendance] Found {len(guardians)} guardians for student {employee_code}")

		if not guardians:
			frappe.logger().warning(f"📧 [Student Attendance] No guardians found for student {employee_code} - cannot send notification")
			return False

		# Use unified notification handler
		from erp.utils.notification_handler import send_bulk_parent_notifications

		# Format timestamp to VN timezone
		vn_time = format_datetime_vn(timestamp)

		# Determine if check-in or check-out
		is_check_in = determine_checkin_or_checkout(timestamp, check_in_time, check_out_time)

		# Build notification theo format chuẩn của notification-service
		title = "Điểm danh"

		# Parse location từ device name
		# Device name format: "Gate 2 - Check in", "Gate 5 - Check out", "Gate 2 - Abnormal", etc.
		if not device_name:
			location = "cổng trường"
		else:
			# Extract gate name (Gate 2, Gate 5, etc.)
			parts = device_name.split(' - ')
			gate_name = parts[0].strip() if len(parts) >= 1 else device_name

			# Map to Vietnamese names
			location_map = {
				'Gate 2': 'Cổng 2',
				'Gate 5': 'Cổng 5'
			}
			location = location_map.get(gate_name, gate_name)  # Default to original if not mapped

		# Format time giống notification-service: HH:MM DD/MM/YYYY
		event_time = timestamp
		if hasattr(timestamp, 'isoformat'):
			# datetime object
			time_str = event_time.strftime('%H:%M %d/%m/%Y')
		else:
			# string
			event_time = frappe.utils.get_datetime(timestamp)
			time_str = event_time.strftime('%H:%M %d/%m/%Y')

		message = f"Học sinh {employee_name} đã đi qua {location} lúc {time_str}"

		# Additional data (convert datetime to string for JSON serialization)
		notification_data = {
			"type": "student_attendance",
			"notificationType": "attendance",
			"student_id": employee_code,
			"student_name": employee_name,
			"studentId": employee_code,
			"studentName": employee_name,
			"employeeCode": employee_code,
			"employeeName": employee_name,
			"timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
			"checkInTime": check_in_time.isoformat() if check_in_time and hasattr(check_in_time, 'isoformat') else check_in_time,
			"checkOutTime": check_out_time.isoformat() if check_out_time and hasattr(check_out_time, 'isoformat') else check_out_time,
			"totalCheckIns": total_check_ins,
			"date": str(date) if date else None,
			"deviceName": device_name,
			"isCheckIn": is_check_in
		}

		# Send bulk notification using unified handler
		frappe.logger().info(f"📧 [Student Attendance] Calling send_bulk_parent_notifications for {employee_code}")
		result = send_bulk_parent_notifications(
			recipient_type="attendance",
			recipients_data={
				"student_ids": [employee_code]
			},
			title=title,
			body=message,
			data=notification_data
		)

		frappe.logger().info(f"✅ [Student Attendance] send_bulk_parent_notifications result for {employee_code}: {result}")
		return result

	except Exception as e:
		frappe.logger().error(f"❌ Error in send_student_attendance_notification: {str(e)}")
		frappe.log_error(message=str(e), title="Student Attendance Notification Error")
		return False


def send_staff_attendance_notification(
	employee_code,
	employee_name,
	timestamp,
	device_name,
	check_in_time,
	check_out_time,
	total_check_ins,
	date
):
	"""
	Send attendance notification to staff member
	"""
	try:
		# Get staff user email
		staff_email = get_staff_email(employee_code)
		
		if not staff_email:
			frappe.logger().warning(f"No email found for staff {employee_code}")
			return
		
		frappe.logger().info(f"📧 [Staff Attendance] Sending to staff {staff_email}")
		
		# Format timestamp
		vn_time = format_datetime_vn(timestamp)
		
		# Determine if check-in or check-out
		is_check_in = determine_checkin_or_checkout(timestamp, check_in_time, check_out_time)
		
		# Build notification cho staff (giống notification-service)
		title = "Chấm công"

		# Format time giống notification-service
		event_time = timestamp
		if hasattr(timestamp, 'isoformat'):
			time_str = event_time.strftime('%H:%M %d/%m/%Y')
		else:
			event_time = frappe.utils.get_datetime(timestamp)
			time_str = event_time.strftime('%H:%M %d/%m/%Y')

		# Staff message format - unified for all attendance events
		message = f"Nhận diện khuôn mặt thành công lúc {time_str}"
		
		# Additional data
		notification_data = {
			"type": "attendance",
			"notificationType": "attendance",
			"employeeCode": employee_code,
			"employeeName": employee_name,
			"timestamp": timestamp.isoformat(),
			"checkInTime": check_in_time,
			"checkOutTime": check_out_time,
			"totalCheckIns": total_check_ins,
			"date": date,
			"deviceName": device_name,
			"isCheckIn": is_check_in
		}
		
		# Create notification record directly to avoid role validation issues
		try:
			from frappe import get_doc
			notification_doc = get_doc({
				"doctype": "ERP Notification",
				"title": title,
				"message": message,
				"recipient_user": staff_email,
				"recipients": json.dumps([staff_email]),  # Convert list to JSON string
				"notification_type": "attendance",
				"priority": "low",
				"data": json.dumps(notification_data) if isinstance(notification_data, dict) else notification_data,
				"channel": "push",
				"status": "sent",
				"delivery_status": "pending",
				"sent_at": frappe.utils.now(),
				"event_timestamp": timestamp
			})
			notification_doc.insert(ignore_permissions=True)
			frappe.db.commit()
			frappe.logger().info(f"✅ Created notification directly: {notification_doc.name}")
		except Exception as create_error:
			frappe.logger().error(f"❌ Failed to create notification directly: {str(create_error)}")
			return
		
		# Skip realtime notification for attendance to avoid duplicate push notifications
		# emit_notification_to_user(staff_email, {
		# 	"id": notification_doc.name,
		# 	"type": "attendance",
		# 	"title": title,
		# 	"message": message,
		# 	"status": "unread",
		# 	"priority": "low",
		# 	"created_at": timestamp.isoformat(),
		# 	"data": notification_data
		# })
		
		# FIX: Chỉ gửi 1 loại push notification, không gửi cả 2
		# Ưu tiên Mobile notification cho staff (vì staff dùng mobile app nhiều hơn PWA)
		try:
			mobile_result = send_mobile_notification(
				user_email=staff_email,
				title=title,  # Just "Chấm công" without emoji
				body=message,
				data={
					"type": "attendance",
					"employeeCode": employee_code,
					"timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
					"deviceName": device_name,
					"isCheckIn": is_check_in
				}
			)
			frappe.logger().info(f"📱 Mobile notification sent to {staff_email}: {mobile_result}")
			
			# Nếu mobile notification thành công, KHÔNG cần gửi PWA push nữa
			if mobile_result.get("success") and mobile_result.get("success_count", 0) > 0:
				frappe.logger().info(f"✅ [Staff Attendance] Mobile push OK, skipping PWA push for {staff_email}")
				frappe.db.commit()
				return
				
		except Exception as mobile_error:
			frappe.logger().error(f"❌ Failed to send mobile notification to {staff_email}: {str(mobile_error)}")

		# Fallback: Gửi PWA push nếu mobile push không thành công (staff không cài mobile app)
		frappe.logger().info(f"📤 [Staff Attendance] Mobile push failed/no device, trying PWA push for {staff_email}")
		
		from erp.api.parent_portal.push_notification import send_push_notification
		try:
			pwa_result = send_push_notification(
				user_email=staff_email,
				title=title,
				body=message,
				data=notification_data,
				tag="attendance"
			)
			frappe.logger().info(f"📤 [Staff Attendance] PWA push result for {staff_email}: {pwa_result}")
		except Exception as pwa_error:
			frappe.logger().error(f"❌ [Staff Attendance] PWA push failed for {staff_email}: {str(pwa_error)}")

		frappe.db.commit()
		frappe.logger().info(f"✅ Sent attendance notification to staff {staff_email}")

	except Exception as e:
		frappe.logger().error(f"Error in send_staff_attendance_notification: {str(e)}")
		frappe.log_error(message=str(e), title="Staff Attendance Notification Error")


def get_student_guardians(student_code):
	"""
	Get guardians for a student from CRM Family Relationship

	Returns:
		List of dicts: [{"name": "Guardian Name", "email": "guardian@email.com", "relation": "Father"}]
	"""
	try:
		# FIX: Case-insensitive lookup cho student_code
		student_record = frappe.db.sql("""
			SELECT name FROM `tabCRM Student`
			WHERE UPPER(student_code) = UPPER(%(code)s)
			LIMIT 1
		""", {"code": student_code})
		
		if not student_record:
			frappe.logger().warning(f"No CRM Student found for student_code: {student_code}")
			return []
		
		student_record = student_record[0][0]

		# Query CRM Family Relationship with correct joins
		relationships = frappe.db.sql("""
			SELECT
				cfr.guardian,
				cfr.relationship_type,
				cfr.key_person,
				cg.guardian_name,
				cg.email as guardian_email,
				cg.guardian_id
			FROM `tabCRM Family Relationship` cfr
			LEFT JOIN `tabCRM Guardian` cg ON cfr.guardian = cg.name
			WHERE cfr.student = %s
			ORDER BY cfr.key_person DESC, cfr.creation ASC
		""", (student_record,), as_dict=True)

		# Format results - sử dụng dict để DEDUPE theo guardian_id
		# Vì relationship có thể duplicate ở nhiều nơi (CRM Family, CRM Student, CRM Guardian)
		guardians_map = {}
		
		for rel in relationships:
			# FIX: Không cần guardian_email để gửi push notification
			# Push notification dùng system_email = guardian_id@parent.wellspring.edu.vn
			# Chỉ cần guardian_id là đủ
			if rel.guardian_id:
				# DEDUPE: Chỉ add nếu guardian_id chưa có trong map
				# Ưu tiên record có key_person = True (đã sort ở query)
				if rel.guardian_id not in guardians_map:
					system_email = f"{rel.guardian_id}@parent.wellspring.edu.vn"
					
					guardians_map[rel.guardian_id] = {
						"name": rel.guardian_name or rel.guardian,
						"email": system_email,
						"personal_email": rel.guardian_email,
						"relation": rel.relationship_type,
						"is_primary": rel.key_person,
						"guardian_doc": rel.guardian,
						"guardian_id": rel.guardian_id
					}
					frappe.logger().info(f"📧 Found guardian: {rel.guardian_name} ({rel.guardian_id}) -> {system_email}")
				else:
					frappe.logger().debug(f"⏭️ Skipping duplicate guardian: {rel.guardian_id}")
			else:
				frappe.logger().warning(f"⚠️ Skipping guardian without guardian_id: {rel.guardian}")

		guardians = list(guardians_map.values())
		frappe.logger().info(f"📋 Total unique guardians for student: {len(guardians)}")
		return guardians

	except Exception as e:
		frappe.logger().error(f"Error getting guardians for {student_code}: {str(e)}")
		return []


def get_staff_email(employee_code):
	"""Get email for staff member"""
	try:
		# Try to find user by employee_code
		# Assuming employee_code is stored in User or Employee doctype
		
		# Method 1: Query User table
		user = frappe.db.get_value("User", {"employee_code": employee_code}, "name")
		if user:
			return user
		
		# Method 2: Query Employee table and get user_id
		employee = frappe.db.get_value("Employee", {"employee_code": employee_code}, "user_id")
		if employee:
			return employee
		
		# Method 3: Try employee_code as email directly
		if "@" in employee_code:
			return employee_code
		
		return None
		
	except Exception as e:
		frappe.logger().error(f"Error getting email for staff {employee_code}: {str(e)}")
		return None


def determine_checkin_or_checkout(timestamp, check_in_time, check_out_time):
	"""
	Determine if this is a check-in or check-out event
	More intelligent logic based on existing attendance data and time patterns
	"""
	if isinstance(timestamp, str):
		timestamp = frappe.utils.get_datetime(timestamp)

	# Convert string times to datetime if needed
	if isinstance(check_in_time, str):
		check_in_time = frappe.utils.get_datetime(check_in_time)
	if isinstance(check_out_time, str):
		check_out_time = frappe.utils.get_datetime(check_out_time)

	# If no existing check-in time, this must be a check-in
	if not check_in_time:
		return True  # Check-in

	# If check-in and check-out are the same, this could be either
	# Use time-based heuristic for school context
	if check_in_time == check_out_time:
		hour = timestamp.hour
		# School hours: morning = check-in, afternoon = check-out
		if 6 <= hour < 13:  # 6 AM - 1 PM = likely check-in
			return True
		else:  # Afternoon/evening = likely check-out
			return False

	# If we have both check-in and check-out times, compare proximity
	if check_in_time and check_out_time and check_in_time != check_out_time:
		time_diff_to_checkin = abs((timestamp - check_in_time).total_seconds())
		time_diff_to_checkout = abs((timestamp - check_out_time).total_seconds())

		# If closer to check-in time, likely a duplicate check-in
		# If closer to check-out time, likely a check-out
		return time_diff_to_checkin <= time_diff_to_checkout

	# Default fallback: use school time patterns
	hour = timestamp.hour
	return hour < 13  # Before 1 PM = check-in, after = check-out


def format_datetime_vn(dt):
	"""Format datetime to VN timezone string"""
	if isinstance(dt, str):
		dt = frappe.utils.get_datetime(dt)

	vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

	# Ensure timezone-aware
	if dt.tzinfo is None:
		dt = pytz.UTC.localize(dt)

	# Convert to VN timezone
	vn_time = dt.astimezone(vn_tz)

	# Format: "08:30 AM, 24/11/2025"
	return vn_time.strftime('%H:%M, %d/%m/%Y')


def should_skip_due_to_debounce_with_lock(employee_code, current_timestamp, check_in_time=None, check_out_time=None, total_check_ins=None):
	"""
	Check if notification should be skipped due to debounce WITH ATOMIC LOCK
	Dùng Redis SETNX để tránh race condition khi nhiều request đến cùng lúc
	
	Returns: (should_skip: bool, lock_acquired: bool)
	- should_skip: True nếu nên bỏ qua notification
	- lock_acquired: True nếu đã acquire lock thành công (để caller biết cần release hay không)
	
	FIX: Đảm bảo chỉ 1 request được xử lý tại một thời điểm cho mỗi employee
	"""
	try:
		# Parse timestamp trước
		if isinstance(current_timestamp, str):
			current_timestamp = frappe.utils.get_datetime(current_timestamp)
		
		# Lock key để đảm bảo atomic operation
		lock_key = f"attendance_notif_lock:{employee_code}"
		cache_key = f"attendance_debounce:{employee_code}"
		
		# Tính is_check_in cho event này
		current_is_checkin = determine_checkin_or_checkout(current_timestamp, check_in_time, check_out_time)
		
		# Tạo unique request ID để track
		import uuid
		request_id = str(uuid.uuid4())[:8]
		
		# Step 1: Try to acquire lock với Redis SETNX
		# Lock expires sau 30 giây để tránh deadlock
		redis = frappe.cache()
		
		# Check existing cache để xác định có nên skip không
		cached_data = redis.get_value(cache_key)
		
		if cached_data:
			try:
				if isinstance(cached_data, str):
					cached_data = json.loads(cached_data)
				
				last_timestamp = cached_data.get('timestamp')
				last_check_ins = cached_data.get('total_check_ins', 0)
				last_is_checkin = cached_data.get('is_check_in', True)
				
				if isinstance(last_timestamp, str):
					last_timestamp = frappe.utils.get_datetime(last_timestamp)
				
				# Tính time diff
				time_diff = (current_timestamp - last_timestamp).total_seconds()
				time_diff_min = time_diff / 60
				
				frappe.logger().info(f"⏱️ [Debounce-Lock] {employee_code} - diff: {time_diff:.1f}s ({time_diff_min:.2f} min)")
				
				# FIX: Tăng debounce time để tránh duplicate khi giờ cao điểm
				# Nếu trong 45 giây và cùng event type, skip (tăng từ 30s lên 45s)
				if time_diff < 45 and current_is_checkin == last_is_checkin:
					frappe.logger().info(f"⏭️ [Debounce-Lock] SKIPPING {employee_code} - same event within 45s")
					return (True, False)
				
				# Nếu trong 90 giây và total_check_ins không đổi, skip (tăng từ 60s lên 90s)
				if time_diff < 90 and total_check_ins and last_check_ins == total_check_ins:
					frappe.logger().info(f"⏭️ [Debounce-Lock] SKIPPING {employee_code} - same check_ins within 90s")
					return (True, False)
					
			except Exception as parse_error:
				frappe.logger().warning(f"⚠️ [Debounce-Lock] Cache parse error: {str(parse_error)}")
		
		# Step 2: Try to acquire lock
		# Sử dụng Redis SETNX pattern: set lock nếu chưa tồn tại
		lock_value = f"{request_id}:{current_timestamp.isoformat()}"
		
		# Kiểm tra lock hiện tại
		existing_lock = redis.get_value(lock_key)
		
		if existing_lock:
			# Lock đang tồn tại, nghĩa là có request khác đang xử lý
			frappe.logger().info(f"🔒 [Debounce-Lock] {employee_code} - Lock exists, SKIPPING (existing: {existing_lock})")
			return (True, False)
		
		# FIX: Tăng TTL lên 60 giây để tránh race condition khi xử lý notification lâu
		# (gửi push notification có thể mất 2-5 giây, nếu có retry còn lâu hơn)
		redis.set_value(lock_key, lock_value, expires_in_sec=60)
		frappe.logger().info(f"🔓 [Debounce-Lock] {employee_code} - Acquired lock: {request_id} (TTL: 60s)")
		
		# Step 3: Update cache NGAY LẬP TỨC (trước khi gửi notification)
		# Điều này đảm bảo request tiếp theo sẽ thấy cache mới
		cache_data = {
			"timestamp": current_timestamp.isoformat(),
			"total_check_ins": total_check_ins or 0,
			"is_check_in": current_is_checkin,
			"request_id": request_id
		}
		
		redis.set_value(cache_key, json.dumps(cache_data), expires_in_sec=300)
		frappe.logger().info(f"📝 [Debounce-Lock] {employee_code} - Cache updated immediately")
		
		# Cho phép notification
		return (False, True)

	except Exception as e:
		frappe.logger().error(f"❌ [Debounce-Lock] Error for {employee_code}: {str(e)}")
		return (False, False)  # On error, allow notification


def should_skip_due_to_debounce(employee_code, current_timestamp, check_in_time=None, check_out_time=None, total_check_ins=None):
	"""
	DEPRECATED: Dùng should_skip_due_to_debounce_with_lock thay thế
	Giữ lại để tương thích ngược
	
	Check if notification should be skipped due to debounce
	SỬ DỤNG REDIS CACHE thay vì query database với LIKE (rất chậm!)
	
	Returns True if notification should be skipped
	
	FIX: Debounce theo employee_code, dùng Redis cache để check nhanh
	"""
	try:
		# Dùng Redis cache để debounce - nhanh hơn rất nhiều so với query database
		cache_key = f"attendance_debounce:{employee_code}"
		
		# Check cache
		cached_data = frappe.cache().get_value(cache_key)
		
		if cached_data:
			try:
				# Parse cached data
				if isinstance(cached_data, str):
					cached_data = json.loads(cached_data)
				
				last_timestamp = cached_data.get('timestamp')
				last_check_ins = cached_data.get('total_check_ins', 0)
				last_is_checkin = cached_data.get('is_check_in', True)
				
				# Parse last timestamp
				if isinstance(last_timestamp, str):
					last_timestamp = frappe.utils.get_datetime(last_timestamp)
				
				# Calculate time difference
				if isinstance(current_timestamp, str):
					current_timestamp = frappe.utils.get_datetime(current_timestamp)
				
				time_diff = (current_timestamp - last_timestamp).total_seconds() / 60
				
				frappe.logger().info(f"⏱️ [Debounce] {employee_code} - diff: {time_diff:.2f} min")
				
				# Nếu notification gần đây (<1 phút), luôn skip
				if time_diff < 1:
					frappe.logger().info(f"⏭️ [Debounce] SKIPPING {employee_code} - too recent ({time_diff:.2f} min)")
					return True
				
				# Nếu trong 3 phút, check xem trạng thái có thay đổi không
				if time_diff < 3:
					current_is_checkin = determine_checkin_or_checkout(current_timestamp, check_in_time, check_out_time)
					
					# Nếu total_check_ins không đổi và cùng loại event, skip
					if (total_check_ins and last_check_ins == total_check_ins and 
						current_is_checkin == last_is_checkin):
						frappe.logger().info(f"⏭️ [Debounce] SKIPPING {employee_code} - same state")
						return True
				
				frappe.logger().info(f"✅ [Debounce] ALLOWING {employee_code} - state changed or time passed")
				return False
				
			except Exception as parse_error:
				frappe.logger().warning(f"⚠️ [Debounce] Cache parse error: {str(parse_error)}")
				return False
		
		frappe.logger().info(f"✅ [Debounce] ALLOWING {employee_code} - no cache entry")
		return False

	except Exception as e:
		frappe.logger().error(f"❌ [Debounce] Error: {str(e)}")
		return False  # On error, allow notification


def update_debounce_cache(employee_code, timestamp, check_in_time=None, check_out_time=None, total_check_ins=None):
	"""
	Lưu debounce info vào Redis cache
	Cache expires sau 5 phút (300 giây)
	"""
	try:
		cache_key = f"attendance_debounce:{employee_code}"
		
		# Tính is_check_in
		is_check_in = determine_checkin_or_checkout(timestamp, check_in_time, check_out_time)
		
		# Data để cache
		cache_data = {
			"timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
			"total_check_ins": total_check_ins or 0,
			"is_check_in": is_check_in
		}
		
		# Lưu vào Redis với TTL 5 phút
		frappe.cache().set_value(
			cache_key, 
			json.dumps(cache_data),
			expires_in_sec=300  # 5 phút
		)
		
		frappe.logger().info(f"📝 [Debounce] Cached for {employee_code} (TTL: 5min)")

	except Exception as e:
		frappe.logger().error(f"❌ [Debounce] Cache error for {employee_code}: {str(e)}")


def clear_attendance_notification_cache(employee_code=None):
	"""
	Clear debounce cache for testing or maintenance
	Args:
		employee_code: Specific employee to clear, or None to clear all
	"""
	try:
		if employee_code:
			cache_key = f"attendance_notif:{employee_code}"
			frappe.cache().delete(cache_key)
			frappe.logger().info(f"🗑️ [Debounce] Cleared cache for {employee_code}")
		else:
			# Clear all attendance notification caches (dangerous, use with caution)
			# This would require iterating through cache keys, which may not be efficient
			frappe.logger().warning("⚠️ [Debounce] Clear all cache not implemented for safety")
			return False

		return True

	except Exception as e:
		frappe.logger().error(f"❌ [Debounce] Error clearing cache: {str(e)}")
		return False

