"""
HiVision Attendance API
Handles real-time attendance events from HiVision Face ID devices
"""

import frappe
from frappe import _
import json
from datetime import datetime
import pytz
import logging
import os
from erp.common.doctype.erp_time_attendance.erp_time_attendance import find_or_create_day_record

# Tạo logger riêng cho HiVision với file log riêng
def get_hikvision_logger():
	"""Get or create HiVision logger với file handler riêng"""
	logger = logging.getLogger('hikvision_attendance')
	
	# Chỉ setup logger một lần
	if not logger.handlers:
		logger.setLevel(logging.DEBUG)
		
		# Tạo file handler - log vào file riêng
		log_dir = frappe.get_site_path('logs')
		if not os.path.exists(log_dir):
			os.makedirs(log_dir)
		
		log_file = os.path.join(log_dir, 'hikvision_realtime.log')
		file_handler = logging.FileHandler(log_file)
		file_handler.setLevel(logging.DEBUG)
		
		# Format với timestamp chi tiết
		formatter = logging.Formatter(
			'%(asctime)s - [HIKVISION] - %(levelname)s - %(message)s',
			datefmt='%Y-%m-%d %H:%M:%S'
		)
		file_handler.setFormatter(formatter)
		
		logger.addHandler(file_handler)
		
		# Tránh log duplicate lên parent logger
		logger.propagate = False
	
	return logger


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle_hikvision_event():
	"""
	Handle real-time event from HiVision Face ID device
	Endpoint: /api/method/erp.api.attendance.hikvision.handle_hikvision_event

	This endpoint accepts multipart/form-data or JSON from HiVision devices
	No authentication required so devices can send events directly
	"""
	# Get logger riêng cho HiVision
	logger = get_hikvision_logger()

	# Track processed students for this request to prevent duplicate notifications
	processed_students = set()

	try:
		# LOG: Print raw request data với nhiều thông tin hơn
		logger.info("=" * 80)
		logger.info("===== NEW REQUEST FROM HIKVISION DEVICE =====")
		logger.info(f"Request method: {frappe.request.method}")
		logger.info(f"Content-Type: {frappe.request.content_type}")
		logger.info(f"Request URL: {frappe.request.url}")
		logger.info(f"Remote IP: {frappe.request.remote_addr}")
		logger.info(f"Request headers: {dict(frappe.request.headers)}")
		
		# Get event data from request - xử lý cả multipart/form-data và JSON
		event_data = {}
		
		# Check if request is multipart/form-data (giống Node.js)
		is_multipart = (frappe.request.content_type and 'multipart/form-data' in frappe.request.content_type)
		
		logger.info(f"Is multipart: {is_multipart}")
		
		if is_multipart:
			# Method 1: Try frappe.request.form (Werkzeug's ImmutableMultiDict) - QUAN TRỌNG
			if hasattr(frappe.request, 'form') and frappe.request.form:
				logger.info(f"✅ Using frappe.request.form, keys: {list(frappe.request.form.keys())}")
				for key in frappe.request.form.keys():
					value = frappe.request.form.get(key)
					logger.info(f"   Form field [{key}] = {str(value)[:200]}")
					event_data[key] = value
			
			# Method 2: If request.form is empty, try form_dict
			if not event_data:
				logger.info("⚠️ request.form is empty, trying form_dict")
				event_data = dict(frappe.local.form_dict)
				logger.info(f"   form_dict keys: {list(event_data.keys())}")
			
			# Parse JSON trong form fields nếu có (giống Node.js parseHikvisionData)
			# HiVision có thể gửi JSON trong một field của multipart/form-data
			if event_data and isinstance(event_data, dict):
				for key, value in list(event_data.items()):
					if isinstance(value, str):
						try:
							parsed = json.loads(value)
							if isinstance(parsed, dict):
								logger.info(f"✅ Parsed JSON from field '{key}'")
								logger.info(f"   Parsed data keys: {list(parsed.keys())}")
								event_data = parsed
								break
						except:
							continue
		else:
			# Không phải multipart, sử dụng parsing tiêu chuẩn
			event_data = frappe.local.form_dict
			logger.info(f"Using form_dict (not multipart), keys: {list(event_data.keys()) if event_data else 'EMPTY'}")
			
			# Nếu event_data rỗng, thử đọc raw request body
			if not event_data or len(event_data) == 0:
				try:
					raw_data = frappe.request.get_data(as_text=True)
					logger.info(f"Raw request body (first 500 chars): {raw_data[:500]}")
					if raw_data:
						event_data = json.loads(raw_data)
						logger.info(f"✅ Parsed from raw body - keys: {list(event_data.keys())}")
				except Exception as parse_error:
					logger.warning(f"⚠️ Could not parse raw body: {str(parse_error)}")

		# Quick heartbeat check for AccessControllerEvent - không log gì cả để tránh spam
		if event_data and event_data.get("eventType") == "heartBeat":
			return {
				"status": "success",
				"message": "Heartbeat received",
				"event_type": "heartBeat",
				"device_ip": event_data.get('ipAddress'),
				"timestamp": frappe.utils.now()
			}

		# Handle empty body (heartbeat) - không log gì cả để tránh spam hoàn toàn
		if not event_data or len(event_data) == 0:
			return {
				"status": "success",
				"message": "Heartbeat received",
				"timestamp": frappe.utils.now()
			}

		# LOG: Print final parsed data (chỉ cho non-heartbeat events)
		logger.info(f"FINAL event_data keys: {list(event_data.keys()) if event_data else 'EMPTY'}")
		if event_data:
			logger.info(f"FINAL event_data (first 500 chars): {str(event_data)[:500]}")

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

		# Handle heartbeat events FIRST - không log gì cả để tránh spam hoàn toàn
		if event_type == 'heartBeat':
			return {
				"status": "success",
				"message": "Heartbeat received",
				"event_type": "heartBeat",
				"device_ip": event_data.get('ipAddress'),
				"timestamp": frappe.utils.now()
			}

		# LOG: Print parsed fields (chỉ cho non-heartbeat events)
		logger.info(f"Parsed - eventType: {event_type}, eventState: {event_state}, dateTime: {date_time}")

		# Validate event type
		if not event_type:
			logger.warning(f"⚠️ No eventType found in request")
			logger.info("=" * 80)
			return {
				"status": "success",
				"message": "No valid eventType found",
				"timestamp": frappe.utils.now()
			}
		
		# Only process face recognition events
		valid_event_types = ['faceSnapMatch', 'faceMatch', 'faceRecognition', 'accessControllerEvent', 'AccessControllerEvent']
		if event_type not in valid_event_types:
			logger.warning(f"⚠️ Event type '{event_type}' not in valid list: {valid_event_types}")
			logger.info("=" * 80)
			return {
				"status": "success",
				"message": f"Event type '{event_type}' not processed",
				"event_type": event_type
			}
		
		# Only process active events
		if event_state != 'active':
			logger.warning(f"⚠️ Event state '{event_state}' is not 'active', skipping")
			logger.info("=" * 80)
			return {
				"status": "success",
				"message": f"Event state '{event_state}' not processed",
				"event_state": event_state
			}
		
		# Process attendance records
		logger.info(f"🎯 PROCESSING ATTENDANCE EVENT: {event_type}")
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
				
				logger.info(f"Processing post - employee_code: {employee_code}, timestamp: {timestamp}")
				
				# Skip if no employee data
				if not employee_code or not timestamp:
					logger.warning(f"⚠️ Skipping post - missing employee_code or timestamp")
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
				
				# Update attendance time - pass original timestamp to preserve it
				attendance_doc.update_attendance_time(parsed_timestamp, device_id, device_name, original_timestamp=timestamp)
				
				# Save to database
				logger.info(f"💾 Saving attendance record for {employee_code} - check_in: {format_vn_time(attendance_doc.check_in_time)}, check_out: {format_vn_time(attendance_doc.check_out_time)}")
				attendance_doc.save(ignore_permissions=True)
				frappe.db.commit()
				logger.info(f"✅ Record saved! ID: {attendance_doc.name}")
				
				records_processed += 1
				
				# Log success
				display_time = format_vn_time(parsed_timestamp)
				logger.info(f"✅ Nhân viên {employee_name or employee_code} đã chấm công lúc {display_time} tại máy {device_name}")
				
				# Send notification immediately (no enqueue for instant push delivery)
				# Check per-request deduplication to prevent multiple notifications for same student
				if employee_code not in processed_students:
					processed_students.add(employee_code)

					try:
						# Import and call notification function directly
						from erp.api.attendance.notification import publish_attendance_notification

						# Call immediately for instant push notification
						publish_attendance_notification(
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

						logger.info(f"✅ Push notification sent immediately for {employee_code}")

					except Exception as notify_error:
						logger.warning(f"⚠️ Failed to send immediate notification: {str(notify_error)}")
						# Fallback to enqueue if immediate send fails
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
							logger.info(f"📋 Fallback: Notification enqueued for {employee_code}")
						except Exception as enqueue_error:
							logger.error(f"❌ Failed to enqueue notification: {str(enqueue_error)}")
				else:
					logger.info(f"⏭️ Skipping duplicate notification for {employee_code} in this request")
				
			except Exception as post_error:
				logger.error(f"❌ Error processing post: {str(post_error)}")
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
			logger.info(f"📊 SUMMARY: Processed {records_processed} attendance events, {len(errors)} errors")
		
		logger.info("=" * 80)
		return response
		
	except Exception as e:
		logger.error(f"❌ FATAL ERROR processing HiVision event: {str(e)}")
		logger.error("=" * 80)
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
	# Get logger riêng cho HiVision
	logger = get_hikvision_logger()

	# Track processed students for this request to prevent duplicate notifications
	processed_students = set()

	try:
		logger.info("=" * 80)
		logger.info("===== BATCH UPLOAD REQUEST =====")
		
		request_data = frappe.local.form_dict
		data = request_data.get("data")
		tracker_id = request_data.get("tracker_id")
		
		logger.info(f"Batch size: {len(data) if isinstance(data, list) else 0}")
		logger.info(f"Tracker ID: {tracker_id}")
		
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
				attendance_doc.update_attendance_time(timestamp, device_id, device_name, original_timestamp=date_time)
				
				# Save
				attendance_doc.save(ignore_permissions=True)
				frappe.db.commit()
				
				if is_new:
					records_processed += 1
				else:
					records_updated += 1
				
				# Log
				display_time = format_vn_time(timestamp)
				logger.info(f"✅ Nhân viên {employee_name or fingerprint_code} đã chấm công lúc {display_time} tại máy {device_name or 'Unknown Device'}")
				
				# Trigger notification with per-request deduplication
				if fingerprint_code not in processed_students:
					processed_students.add(fingerprint_code)

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
						logger.info(f"📋 Notification enqueued for {fingerprint_code} (batch)")
					except Exception as enqueue_error:
						logger.warning(f"⚠️ Failed to enqueue notification: {str(enqueue_error)}")
				else:
					logger.info(f"⏭️ Skipping duplicate notification for {fingerprint_code} in batch")
				
			except Exception as record_error:
				logger.error(f"❌ Error processing record: {str(record_error)}")
				errors.append({
					"record": record,
					"error": str(record_error)
				})
		
		logger.info(f"📊 BATCH SUMMARY: Processed {records_processed} new, updated {records_updated}, errors {len(errors)}")
		logger.info("=" * 80)
		
		return {
			"status": "success",
			"message": f"Processed {records_processed} new records, updated {records_updated} records",
			"records_processed": records_processed,
			"records_updated": records_updated,
			"total_errors": len(errors),
			"errors": errors[:10]  # Return first 10 errors
		}
		
	except Exception as e:
		logger.error(f"❌ FATAL ERROR in batch upload: {str(e)}")
		logger.error("=" * 80)
		frappe.log_error(message=str(e), title="Attendance Batch Upload Error")
		return {
			"status": "error",
			"message": "Server error processing batch upload",
			"error": str(e)
		}


def get_device_timezone_assumption():
	"""Get timezone assumption from site config, default to 'detect'"""
	try:
		return frappe.get_system_settings("hikvision_device_timezone") or "detect"
	except:
		return "detect"


def parse_attendance_timestamp(date_time_string, assume_device_timezone=None):
	"""
	SIMPLE FIX: Parse and return VN time directly (no UTC conversion)
	Device sends VN time, we store VN time, display VN time.
	"""
	if not date_time_string:
		raise ValueError("DateTime string is required")

	# Parse datetime
	if isinstance(date_time_string, str):
		timestamp = frappe.utils.get_datetime(date_time_string)
	else:
		timestamp = date_time_string

	# Convert to VN timezone if it has timezone info
	if timestamp.tzinfo is not None:
		vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
		timestamp = timestamp.astimezone(vn_tz)

	# Return VN time (naive for DB storage)
	return timestamp.replace(tzinfo=None) if timestamp.tzinfo else timestamp


def format_vn_time(dt):
	"""Format datetime to VN timezone string for display"""
	vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

	# Ensure datetime is timezone-aware
	if dt.tzinfo is None:
		# DB stores VN time as naive datetime, so treat it as VN time
		dt = vn_tz.localize(dt)

	# Convert to VN timezone (should be no-op if already VN)
	vn_time = dt.astimezone(vn_tz)

	return vn_time.strftime('%Y-%m-%d %H:%M:%S')
