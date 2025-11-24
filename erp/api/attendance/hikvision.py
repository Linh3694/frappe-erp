"""
HiVision Attendance API
Handles real-time attendance events from HiVision Face ID devices
"""

import frappe
from frappe import _
import json
from datetime import datetime
import pytz
from erp.common.doctype.erp_time_attendance.erp_time_attendance import find_or_create_day_record


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle_hikvision_event():
	"""
	Handle real-time event from HiVision Face ID device
	Endpoint: /api/method/erp.api.attendance.hikvision.handle_hikvision_event
	
	This endpoint accepts multipart/form-data or JSON from HiVision devices
	No authentication required so devices can send events directly
	"""
	try:
		# Get event data from request
		event_data = frappe.local.form_dict
		
		# LOG: Print raw request data
		frappe.logger().info(f"🔍 [HIKVISION] Received request - form_dict keys: {list(event_data.keys()) if event_data else 'EMPTY'}")
		frappe.logger().info(f"🔍 [HIKVISION] Raw event_data: {str(event_data)[:500]}")
		
		# Handle empty body (heartbeat)
		if not event_data or len(event_data) == 0:
			return {
				"status": "success",
				"message": "Heartbeat received",
				"timestamp": frappe.utils.now()
			}
		
		# Extract event information from HiVision format
		event_type = None
		event_state = None
		date_time = None
		active_post = None
		access_controller_event = None
		
		# Try to parse nested structure
		if "EventNotificationAlert" in event_data:
			alert = event_data.get("EventNotificationAlert")
			if isinstance(alert, str):
				alert = json.loads(alert)
			event_type = alert.get("eventType")
			event_state = alert.get("eventState")
			date_time = alert.get("dateTime")
			active_post = alert.get("ActivePost")
			access_controller_event = alert.get("AccessControllerEvent")
		else:
			event_type = event_data.get("eventType")
			event_state = event_data.get("eventState")
			date_time = event_data.get("dateTime")
			active_post = event_data.get("ActivePost") or event_data.get("activePost")
			access_controller_event = event_data.get("AccessControllerEvent")
		
		# LOG: Print parsed fields
		frappe.logger().info(f"🔍 [HIKVISION] Parsed - eventType: {event_type}, eventState: {event_state}, dateTime: {date_time}")
		
		# Validate event type
		if not event_type:
			frappe.logger().warning(f"⚠️ [HIKVISION] No eventType found in request")
			return {
				"status": "success",
				"message": "No valid eventType found",
				"timestamp": frappe.utils.now()
			}
		
		# Only process face recognition events
		valid_event_types = ['faceSnapMatch', 'faceMatch', 'faceRecognition', 'accessControllerEvent', 'AccessControllerEvent']
		if event_type not in valid_event_types:
			frappe.logger().warning(f"⚠️ [HIKVISION] Event type '{event_type}' not in valid list: {valid_event_types}")
			return {
				"status": "success",
				"message": f"Event type '{event_type}' not processed",
				"event_type": event_type
			}
		
		# Only process active events
		if event_state != 'active':
			frappe.logger().warning(f"⚠️ [HIKVISION] Event state '{event_state}' is not 'active', skipping")
			return {
				"status": "success",
				"message": f"Event state '{event_state}' not processed",
				"event_state": event_state
			}
		
		# Process attendance records
		records_processed = 0
		errors = []
		
		# Collect posts to process
		posts_to_process = []
		
		# Ưu tiên AccessControllerEvent nếu có (định dạng mới)
		if access_controller_event:
			posts_to_process.append(access_controller_event)
		elif active_post and isinstance(active_post, list):
			posts_to_process.extend(active_post)
		elif active_post:
			posts_to_process.append(active_post)
		else:
			# Fallback: parse from root level
			posts_to_process.append(event_data)
		
		# Process each post
		for post in posts_to_process:
			try:
				# Extract employee information - prioritize employeeNoString
				employee_code = (
					post.get("employeeNoString") or 
					post.get("FPID") or 
					post.get("cardNo") or 
					post.get("employeeCode") or 
					post.get("userID")
				)
				employee_name = post.get("name")
				timestamp = post.get("dateTime") or date_time
				device_id = post.get("ipAddress") or event_data.get("ipAddress") or post.get("deviceID")
				device_name = post.get("deviceName") or event_data.get("deviceName") or "Unknown Device"
				
				frappe.logger().info(f"🔍 [HIKVISION] Processing post - employee_code: {employee_code}, timestamp: {timestamp}")
				
				# Skip if no employee data
				if not employee_code or not timestamp:
					frappe.logger().warning(f"⚠️ [HIKVISION] Skipping post - missing employee_code or timestamp")
					continue
				
				# Parse timestamp
				parsed_timestamp = parse_attendance_timestamp(timestamp)
				
				# Find or create attendance record
				attendance_doc = find_or_create_day_record(
					employee_code=employee_code,
					date=parsed_timestamp,
					device_id=device_id,
					employee_name=employee_name,
					device_name=device_name
				)
				
				# Add metadata to notes
				notes_parts = []
				if post.get("name"):
					notes_parts.append(f"Face ID: {post.get('name')}")
				if post.get("similarity"):
					notes_parts.append(f"Similarity: {post.get('similarity')}%")
				if event_type:
					notes_parts.append(f"Event: {event_type}")
				
				if notes_parts:
					existing_notes = attendance_doc.notes or ""
					attendance_doc.notes = existing_notes + "; ".join(notes_parts) + "; "
				
				# Update attendance time
				attendance_doc.update_attendance_time(parsed_timestamp, device_id, device_name)
				
				# Save to database
				frappe.logger().info(f"💾 [HIKVISION] Saving attendance record for {employee_code} - check_in: {attendance_doc.check_in_time}, check_out: {attendance_doc.check_out_time}")
				attendance_doc.save(ignore_permissions=True)
				frappe.db.commit()
				frappe.logger().info(f"✅ [HIKVISION] Record saved! ID: {attendance_doc.name}")
				
				records_processed += 1
				
				# Log success
				display_time = format_vn_time(parsed_timestamp)
				frappe.logger().info(f"✅ Nhân viên {employee_name or employee_code} đã chấm công lúc {display_time} tại máy {device_name}")
				
				# Trigger notification in background (enqueue to avoid blocking response)
				try:
					frappe.enqueue(
						"erp.api.attendance.notification.publish_attendance_notification",
						queue="default",
						timeout=300,
						employee_code=employee_code,
						employee_name=employee_name,
						timestamp=parsed_timestamp.isoformat(),
						device_id=device_id,
						device_name=device_name,
						check_in_time=attendance_doc.check_in_time.isoformat() if attendance_doc.check_in_time else None,
						check_out_time=attendance_doc.check_out_time.isoformat() if attendance_doc.check_out_time else None,
						total_check_ins=attendance_doc.total_check_ins,
						date=str(attendance_doc.date)
					)
				except Exception as enqueue_error:
					frappe.logger().warning(f"⚠️ Failed to enqueue notification: {str(enqueue_error)}")
				
			except Exception as post_error:
				frappe.logger().error(f"❌ Error processing post: {str(post_error)}")
				errors.append({
					"post": post,
					"error": str(post_error)
				})
		
		# Return response
		response = {
			"status": "success",
			"message": f"Processed {records_processed} attendance events",
			"timestamp": frappe.utils.now(),
			"event_type": event_type or "unknown",
			"event_state": event_state or "unknown",
			"records_processed": records_processed,
			"total_errors": len(errors)
		}
		
		if errors and len(errors) > 0:
			response["errors"] = errors[:5]  # Return first 5 errors only
		
		if records_processed > 0 or len(errors) > 0:
			frappe.logger().info(f"📊 Processed: {records_processed} attendance events, {len(errors)} errors")
		
		return response
		
	except Exception as e:
		frappe.logger().error(f"❌ Error processing HiVision event: {str(e)}")
		frappe.log_error(message=str(e), title="HiVision Event Processing Error")
		return {
			"status": "error",
			"message": "Server error processing HiVision event",
			"error": str(e),
			"timestamp": frappe.utils.now()
		}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def upload_attendance_batch():
	"""
	Upload batch attendance data from HiVision device
	Endpoint: /api/method/erp.api.attendance.hikvision.upload_attendance_batch
	
	Body: { data: [{ fingerprintCode, dateTime, device_id }], tracker_id }
	"""
	try:
		request_data = frappe.local.form_dict
		data = request_data.get("data")
		tracker_id = request_data.get("tracker_id")
		
		if not data or not isinstance(data, list):
			return {
				"status": "error",
				"message": "Invalid data. Expected array of attendance records."
			}
		
		records_processed = 0
		records_updated = 0
		errors = []
		
		for record in data:
			try:
				fingerprint_code = record.get("fingerprintCode")
				date_time = record.get("dateTime")
				device_id = record.get("device_id")
				employee_name = record.get("employeeName")
				device_name = record.get("deviceName")
				
				if not fingerprint_code or not date_time:
					errors.append({
						"record": record,
						"error": "fingerprintCode and dateTime are required"
					})
					continue
				
				# Parse timestamp
				timestamp = parse_attendance_timestamp(date_time)
				
				# Find or create record
				attendance_doc = find_or_create_day_record(
					employee_code=fingerprint_code,
					date=timestamp,
					device_id=device_id,
					employee_name=employee_name,
					device_name=device_name
				)
				
				# Update tracker_id if provided
				if tracker_id:
					attendance_doc.tracker_id = tracker_id
				
				# Update attendance time
				is_new = not attendance_doc.name
				attendance_doc.update_attendance_time(timestamp, device_id, device_name)
				
				# Save
				attendance_doc.save(ignore_permissions=True)
				frappe.db.commit()
				
				if is_new:
					records_processed += 1
				else:
					records_updated += 1
				
				# Log
				display_time = format_vn_time(timestamp)
				frappe.logger().info(f"✅ Nhân viên {employee_name or fingerprint_code} đã chấm công lúc {display_time} tại máy {device_name or 'Unknown Device'}")
				
				# Trigger notification
				try:
					frappe.enqueue(
						"erp.api.attendance.notification.publish_attendance_notification",
						queue="default",
						timeout=300,
						employee_code=fingerprint_code,
						employee_name=employee_name,
						timestamp=timestamp.isoformat(),
						device_id=device_id,
						device_name=device_name,
						check_in_time=attendance_doc.check_in_time.isoformat() if attendance_doc.check_in_time else None,
						check_out_time=attendance_doc.check_out_time.isoformat() if attendance_doc.check_out_time else None,
						total_check_ins=attendance_doc.total_check_ins,
						date=str(attendance_doc.date),
						event_type="batch_upload",
						tracker_id=tracker_id
					)
				except Exception as enqueue_error:
					frappe.logger().warning(f"⚠️ Failed to enqueue notification: {str(enqueue_error)}")
				
			except Exception as record_error:
				frappe.logger().error(f"❌ Error processing record: {str(record_error)}")
				errors.append({
					"record": record,
					"error": str(record_error)
				})
		
		return {
			"status": "success",
			"message": f"Processed {records_processed} new records, updated {records_updated} records",
			"records_processed": records_processed,
			"records_updated": records_updated,
			"total_errors": len(errors),
			"errors": errors[:10]  # Return first 10 errors
		}
		
	except Exception as e:
		frappe.logger().error(f"❌ Error in batch upload: {str(e)}")
		frappe.log_error(message=str(e), title="Attendance Batch Upload Error")
		return {
			"status": "error",
			"message": "Server error processing batch upload",
			"error": str(e)
		}


def parse_attendance_timestamp(date_time_string):
	"""
	Parse timestamp from HiVision device
	Handles various formats and timezone conversion
	"""
	if not date_time_string:
		raise ValueError("DateTime string is required")
	
	# Parse datetime
	if isinstance(date_time_string, str):
		timestamp = frappe.utils.get_datetime(date_time_string)
	else:
		timestamp = date_time_string
	
	# Handle timezone
	original_string = str(date_time_string)
	
	# Case 1: Input has +07:00 timezone (VN time)
	if '+07:00' in original_string or '+0700' in original_string:
		# Already in VN timezone, frappe.utils.get_datetime handles conversion to UTC
		return timestamp
	
	# Case 2: Input is UTC or naive time
	elif 'Z' in original_string or '+00:00' in original_string or ('+' not in original_string and '-' not in original_string[-6:]):
		# This is UTC or naive, treat as UTC
		return timestamp
	
	# Case 3: Other timezone formats
	else:
		# Let frappe handle it
		return timestamp


def format_vn_time(dt):
	"""Format datetime to VN timezone string for display"""
	vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
	
	# Ensure datetime is timezone-aware
	if dt.tzinfo is None:
		dt = pytz.UTC.localize(dt)
	
	# Convert to VN timezone
	vn_time = dt.astimezone(vn_tz)
	
	return vn_time.strftime('%Y-%m-%d %H:%M:%S')
