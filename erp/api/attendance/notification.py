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
		
		frappe.logger().info(f"✅ [Attendance Notif] Notification sent for {employee_code}")
		
	except Exception as e:
		frappe.logger().error(f"❌ [Attendance Notif] Error sending notification for {employee_code}: {str(e)}")
		frappe.log_error(message=str(e), title="Attendance Notification Error")


def check_if_student(employee_code):
	"""Check if employee_code belongs to a student"""
	try:
		# Query CRM Student table
		student = frappe.db.exists("CRM Student", {"student_code": employee_code})
		return bool(student)
	except Exception as e:
		frappe.logger().warning(f"Failed to check if {employee_code} is student: {str(e)}")
		return False


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
	Send attendance notification to student's guardians
	"""
	try:
		# Get guardians from CRM Family Relationship
		guardians = get_student_guardians(employee_code)
		
		if not guardians or len(guardians) == 0:
			frappe.logger().warning(f"No guardians found for student {employee_code}")
			return
		
		frappe.logger().info(f"📧 [Student Attendance] Sending to {len(guardians)} guardians for student {employee_code}")
		
		# Format timestamp to VN timezone
		vn_time = format_datetime_vn(timestamp)
		
		# Determine if check-in or check-out
		is_check_in = determine_checkin_or_checkout(timestamp, check_in_time, check_out_time)
		
		# Build notification title and message (bilingual)
		if is_check_in:
			title = {
				"vi": f"✅ {employee_name} đã đến trường",
				"en": f"✅ {employee_name} arrived at school"
			}
			message = {
				"vi": f"{employee_name} đã check-in lúc {vn_time} tại {device_name or 'thiết bị'}",
				"en": f"{employee_name} checked in at {vn_time} at {device_name or 'device'}"
			}
		else:
			title = {
				"vi": f"👋 {employee_name} đã về nhà",
				"en": f"👋 {employee_name} left school"
			}
			message = {
				"vi": f"{employee_name} đã check-out lúc {vn_time} tại {device_name or 'thiết bị'}",
				"en": f"{employee_name} checked out at {vn_time} at {device_name or 'device'}"
			}
		
		# Additional data
		notification_data = {
			"type": "student_attendance",
			"notificationType": "attendance",
			"student_id": employee_code,
			"student_name": employee_name,
			"studentId": employee_code,
			"studentName": employee_name,
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
		
		# Create notification for each guardian
		for guardian in guardians:
			try:
				# Create notification record in DB
				notification_doc = create_notification(
					title=title,
					message=message,
					recipient_user=guardian["email"],
					recipients=[guardian["email"]],
					notification_type="attendance",
					priority="normal",
					data=notification_data,
					channel="push",
					event_timestamp=timestamp,
					reference_doctype="CRM Student",
					reference_name=employee_code
				)
				
				# Send realtime notification via SocketIO
				emit_notification_to_user(guardian["email"], {
					"id": notification_doc.name,
					"type": "attendance",
					"title": title,
					"message": message,
					"status": "unread",
					"priority": "normal",
					"created_at": timestamp.isoformat(),
					"student_id": employee_code,
					"student_name": employee_name,
					"data": notification_data
				})
				
				# Update unread count
				from erp.common.doctype.erp_notification.erp_notification import get_unread_count
				unread_count = get_unread_count(guardian["email"])
				emit_unread_count_update(guardian["email"], unread_count)
				
				# Send push notification (enqueue for background)
				frappe.enqueue(
					send_push_notification,
					queue="default",
					timeout=300,
					user_email=guardian["email"],
					title=title.get("vi"),  # Use Vietnamese for push
					body=message.get("vi"),
					icon="/icon.png",
					data=notification_data,
					tag="attendance"
				)
				
				frappe.logger().info(f"✅ Sent attendance notification to guardian {guardian['email']}")
				
			except Exception as guardian_error:
				frappe.logger().error(f"Failed to send notification to guardian {guardian.get('email')}: {str(guardian_error)}")
		
		frappe.db.commit()
		
	except Exception as e:
		frappe.logger().error(f"Error in send_student_attendance_notification: {str(e)}")
		frappe.log_error(message=str(e), title="Student Attendance Notification Error")


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
		
		# Build notification
		if is_check_in:
			title = {
				"vi": f"✅ Bạn đã check-in",
				"en": f"✅ You checked in"
			}
			message = {
				"vi": f"Bạn đã check-in lúc {vn_time} tại {device_name or 'thiết bị'}",
				"en": f"You checked in at {vn_time} at {device_name or 'device'}"
			}
		else:
			title = {
				"vi": f"👋 Bạn đã check-out",
				"en": f"👋 You checked out"
			}
			message = {
				"vi": f"Bạn đã check-out lúc {vn_time} tại {device_name or 'thiết bị'}",
				"en": f"You checked out at {vn_time} at {device_name or 'device'}"
			}
		
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
		
		# Create notification record
		notification_doc = create_notification(
			title=title,
			message=message,
			recipient_user=staff_email,
			recipients=[staff_email],
			notification_type="attendance",
			priority="low",
			data=notification_data,
			channel="push",
			event_timestamp=timestamp
		)
		
		# Send realtime notification
		emit_notification_to_user(staff_email, {
			"id": notification_doc.name,
			"type": "attendance",
			"title": title,
			"message": message,
			"status": "unread",
			"priority": "low",
			"created_at": timestamp.isoformat(),
			"data": notification_data
		})
		
		# Send push notification (enqueue)
		frappe.enqueue(
			send_push_notification,
			queue="default",
			timeout=300,
			user_email=staff_email,
			title=title.get("vi"),
			body=message.get("vi"),
			icon="/icon.png",
			data=notification_data,
			tag="attendance"
		)
		
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
		# Query CRM Family Relationship
		relationships = frappe.get_all(
			"CRM Family Relationship",
			filters={
				"student_code": student_code,
				"is_primary_guardian": 1
			},
			fields=["guardian_name", "guardian_email", "relation"]
		)
		
		if not relationships:
			# Fallback: get all guardians if no primary guardian
			relationships = frappe.get_all(
				"CRM Family Relationship",
				filters={"student_code": student_code},
				fields=["guardian_name", "guardian_email", "relation"]
			)
		
		# Format results
		guardians = []
		for rel in relationships:
			if rel.guardian_email:
				guardians.append({
					"name": rel.guardian_name,
					"email": rel.guardian_email,
					"relation": rel.relation
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
	Based on time of day and proximity to check_in_time vs check_out_time
	"""
	if isinstance(timestamp, str):
		timestamp = frappe.utils.get_datetime(timestamp)
	
	hour = timestamp.hour
	
	# Simple heuristic: morning hours = check-in, afternoon/evening = check-out
	if hour < 12:
		return True  # Check-in
	else:
		return False  # Check-out


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

