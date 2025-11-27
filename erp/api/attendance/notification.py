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

		# DEBOUNCE CHECK: Skip if notification sent recently with enhanced context checking
		frappe.logger().info(f"🔍 [Attendance Notif] Checking debounce for {employee_code}")
		should_skip = should_skip_due_to_debounce(
			employee_code,
			timestamp,
			check_in_time=check_in_time,
			check_out_time=check_out_time,
			total_check_ins=total_check_ins
		)
		frappe.logger().info(f"🔍 [Attendance Notif] Debounce result for {employee_code}: should_skip={should_skip}")

		if should_skip:
			frappe.logger().info(f"⏭️ [Debounce] SKIPPING notification for {employee_code} - sent recently")
			return

		frappe.logger().info(f"✅ [Attendance Notif] ALLOWING notification for {employee_code}")

		# Check if this is a student or staff
		is_student = check_if_student(employee_code)

		if is_student:
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

		# UPDATE DEBOUNCE CACHE: Mark notification as sent
		update_debounce_cache(employee_code, timestamp)

		frappe.logger().info(f"✅ [Attendance Notif] Notification sent for {employee_code}")

	except Exception as e:
		frappe.logger().error(f"❌ [Attendance Notif] Error sending notification for {employee_code}: {str(e)}")
		frappe.log_error(message=str(e), title="Attendance Notification Error")


def check_if_student(employee_code):
	"""Check if employee_code belongs to a student or staff"""
	try:
		# First, check if it's a student in CRM Student table
		student = frappe.db.exists("CRM Student", {"student_code": employee_code})
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
		frappe.logger().info(f"📧 [Student Attendance] Processing attendance for student {employee_code}")

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
		result = send_bulk_parent_notifications(
			recipient_type="attendance",
			recipients_data={
				"student_ids": [employee_code]
			},
			title=title,
			body=message,
			data=notification_data
		)

		frappe.logger().info(f"✅ [Student Attendance] Sent attendance notification for {employee_code}: {result}")
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
		
		# Send MOBILE push notification for staff
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
		except Exception as mobile_error:
			frappe.logger().error(f"❌ Failed to send mobile notification to {staff_email}: {str(mobile_error)}")

		# Use unified notification handler for PWA notifications
		from erp.utils.notification_handler import send_bulk_parent_notifications

		result = send_bulk_parent_notifications(
			recipient_type="attendance",
			recipients_data={
				"parent_emails": [staff_email]  # Direct email list for staff
			},
			title=title,
			body=message,
			data=notification_data
		)

		frappe.db.commit()
		frappe.logger().info(f"✅ Sent attendance notification to staff {staff_email}: {result}")

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
		# First, find the CRM Student record by student_code
		student_record = frappe.db.get_value("CRM Student", {"student_code": student_code}, "name")
		if not student_record:
			frappe.logger().warning(f"No CRM Student found for student_code: {student_code}")
			return []

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

		# Format results
		guardians = []
		for rel in relationships:
			if rel.guardian_email:
				# Use system email format for push notifications (guardian_id@parent.wellspring.edu.vn)
				system_email = f"{rel.guardian_id}@parent.wellspring.edu.vn" if hasattr(rel, 'guardian_id') and rel.guardian_id else rel.guardian_email

				guardians.append({
					"name": rel.guardian_name or rel.guardian,
					"email": system_email,  # Use system email for push notifications
					"personal_email": rel.guardian_email,  # Keep personal email for reference
					"relation": rel.relationship_type,
					"is_primary": rel.key_person
				})

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


def should_skip_due_to_debounce(employee_code, current_timestamp, check_in_time=None, check_out_time=None, total_check_ins=None):
	"""
	Check if notification should be skipped due to debounce
	Enhanced logic that considers attendance context, not just time window
	Returns True if notification should be skipped
	"""
	try:
		# Get guardians for this student first
		from erp.utils.notification_handler import get_guardians_for_students
		guardians = get_guardians_for_students([employee_code])

		if not guardians:
			frappe.logger().info(f"⏱️ [Debounce] {employee_code} - No guardians found, allowing notification")
			return False

		# Get guardian emails
		guardian_emails = [g['email'] for g in guardians]

		# Query database for recent notifications to any of these guardians
		recent_notifications = frappe.db.sql("""
			SELECT creation, data, recipient_user
			FROM `tabERP Notification`
			WHERE recipient_user IN %(guardian_emails)s
			AND notification_type = 'attendance'
			AND creation >= DATE_SUB(NOW(), INTERVAL 5 MINUTE)
			ORDER BY creation DESC
			LIMIT 5  -- Check last 5 notifications for context
		""", {"guardian_emails": guardian_emails}, as_dict=True)

		if recent_notifications:
			last_notif_time = recent_notifications[0].creation
			time_diff = (current_timestamp - last_notif_time).total_seconds() / 60

			frappe.logger().info(f"⏱️ [Debounce] {employee_code} - current: {current_timestamp}, last: {last_notif_time}, diff: {time_diff:.2f} min")

			# If last notification was very recent (< 1 minute), always skip
			if time_diff < 1:
				frappe.logger().info(f"⏭️ [Debounce] SKIPPING {employee_code} - too recent ({time_diff:.2f} min < 1 min)")
				return True

			# If within 5 minutes, check if attendance state has actually changed
			if time_diff < 5:
				# Parse the last notification's data to understand previous state
				try:
					last_data = json.loads(recent_notifications[0].data) if isinstance(recent_notifications[0].data, str) else recent_notifications[0].data

					last_check_ins = last_data.get('totalCheckIns', 0)
					last_is_checkin = last_data.get('isCheckIn', True)

					# If total check-ins haven't changed and it's the same type of event, skip
					if (total_check_ins and last_check_ins == total_check_ins and
						determine_checkin_or_checkout(current_timestamp, check_in_time, check_out_time) == last_is_checkin):
						frappe.logger().info(f"⏭️ [Debounce] SKIPPING {employee_code} - same attendance state (check_ins: {total_check_ins}, type: {'check-in' if last_is_checkin else 'check-out'})")
						return True

				except Exception as parse_error:
					frappe.logger().warning(f"⚠️ [Debounce] Could not parse last notification data: {str(parse_error)}")
					# If we can't parse the data, be conservative and skip
					return True

			frappe.logger().info(f"✅ [Debounce] ALLOWING {employee_code} - significant attendance change")
			return False

		frappe.logger().info(f"✅ [Debounce] ALLOWING {employee_code} - no recent notification")
		return False

	except Exception as e:
		frappe.logger().error(f"❌ [Debounce] Error checking debounce for {employee_code}: {str(e)}")
		return False  # On error, allow notification to be sent


def update_debounce_cache(employee_code, timestamp):
	"""
	Update debounce cache with timestamp of successful notification
	Now using database-based approach, so this function is kept for compatibility
	but doesn't need to do anything since we check from ERP Notification table
	"""
	try:
		# Database-based debounce doesn't need explicit cache update
		# The notification record itself serves as the debounce marker
		frappe.logger().info(f"📝 [Debounce] Notification sent for {employee_code} - database-based debounce active")

	except Exception as e:
		frappe.logger().error(f"❌ [Debounce] Error in update_debounce_cache for {employee_code}: {str(e)}")


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

