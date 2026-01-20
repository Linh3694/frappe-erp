"""
HiVision Attendance API
Handles real-time attendance events from HiVision Face ID devices

PERFORMANCE OPTIMIZED:
- Events được push vào Redis buffer thay vì xử lý trực tiếp
- Batch processor xử lý hàng loạt events mỗi 5 giây
- API response time < 100ms thay vì 2-5s
"""

import frappe
from frappe import _
import json
from datetime import datetime
import pytz
import logging
import os
from erp.common.doctype.erp_time_attendance.erp_time_attendance import find_or_create_day_record

# Redis key cho attendance buffer
ATTENDANCE_BUFFER_KEY = "hikvision:attendance_buffer"
# Batch size cho mỗi lần xử lý (tăng lên 200 để xử lý nhanh hơn)
BUFFER_BATCH_SIZE = 200

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
		# Quick heartbeat check trước khi log bất kỳ thứ gì
		is_multipart = (frappe.request.content_type and 'multipart/form-data' in frappe.request.content_type)
		if is_multipart and hasattr(frappe.request, 'form') and frappe.request.form:
			# Try to parse AccessControllerEvent quickly for heartbeat check
			access_event = frappe.request.form.get('AccessControllerEvent')
			if access_event and isinstance(access_event, str):
				try:
					import json
					parsed_quick = json.loads(access_event)
					if parsed_quick.get("eventType") == "heartBeat":
						# Heartbeat detected - return immediately without logging
						return {
							"status": "success",
							"message": "Heartbeat received",
							"event_type": "heartBeat",
							"device_ip": parsed_quick.get('ipAddress'),
							"timestamp": frappe.utils.now()
						}
				except:
					pass  # Continue with normal processing if parsing fails

		# LOG: Print raw request data với nhiều thông tin hơn (chỉ cho non-heartbeat)
		logger.info("=" * 80)
		logger.info("===== NEW REQUEST FROM HIKVISION DEVICE =====")
		logger.info(f"Request method: {frappe.request.method}")
		logger.info(f"Content-Type: {frappe.request.content_type}")
		logger.info(f"Request URL: {frappe.request.url}")
		logger.info(f"Remote IP: {frappe.request.remote_addr}")
		logger.info(f"Request headers: {dict(frappe.request.headers)}")

		# Get event data from request - xử lý cả multipart/form-data và JSON
		event_data = {}
		
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
								# Quick heartbeat check ngay sau khi parse - không log gì cả
								if parsed.get("eventType") == "heartBeat":
									return {
										"status": "success",
										"message": "Heartbeat received",
										"event_type": "heartBeat",
										"device_ip": parsed.get('ipAddress'),
										"timestamp": frappe.utils.now()
									}

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
		
		# PERFORMANCE FIX: Push events vào Redis buffer thay vì xử lý trực tiếp
		# Batch processor sẽ xử lý hàng loạt mỗi 5 giây
		logger.info(f"🚀 BUFFERING ATTENDANCE EVENT: {event_type}")
		events_buffered = 0
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
		
		# Push each post vào Redis buffer
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
				
				# Skip if no employee data
				if not employee_code or not timestamp:
					logger.warning(f"⚠️ Skipping post - missing employee_code or timestamp")
					continue
				
				# Tạo event data để push vào buffer
				buffer_event = {
					"employee_code": employee_code,
					"employee_name": employee_name,
					"timestamp": timestamp,
					"device_id": device_id,
					"device_name": device_name,
					"event_type": event_type,
					"similarity": post.get("similarity"),
					"face_id_name": post.get("name"),
					"received_at": frappe.utils.now()
				}
				
				# Push vào Redis buffer (O(1) operation - rất nhanh)
				push_to_attendance_buffer(buffer_event)
				events_buffered += 1
				
				logger.info(f"📥 Buffered event for {employee_code} at {timestamp}")
				
			except Exception as post_error:
				logger.error(f"❌ Error buffering post: {str(post_error)}")
				errors.append({
					"post": str(post)[:200],
					"error": str(post_error)
				})
		
		# Return response ngay lập tức - không đợi DB
		response = {
			"status": "success",
			"message": f"Buffered {events_buffered} attendance events for processing",
			"timestamp": frappe.utils.now(),
			"event_type": event_type or "unknown",
			"event_state": event_state or "unknown",
			"events_buffered": events_buffered,
			"total_errors": len(errors),
			"processing_mode": "async_buffer"
		}
		
		if errors and len(errors) > 0:
			response["errors"] = errors[:5]
		
		logger.info(f"📊 BUFFERED: {events_buffered} events, {len(errors)} errors")
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
	
	PERFORMANCE OPTIMIZED:
	- Push tất cả events vào Redis buffer
	- Batch processor sẽ xử lý sau
	- API response nhanh hơn nhiều
	"""
	# Get logger riêng cho HiVision
	logger = get_hikvision_logger()

	try:
		logger.info("=" * 80)
		logger.info("===== BATCH UPLOAD REQUEST (BUFFERED) =====")
		
		request_data = frappe.local.form_dict
		data = request_data.get("data")
		tracker_id = request_data.get("tracker_id")
		
		# Parse data nếu là string
		if isinstance(data, str):
			try:
				data = json.loads(data)
			except:
				pass
		
		logger.info(f"Batch size: {len(data) if isinstance(data, list) else 0}")
		logger.info(f"Tracker ID: {tracker_id}")
		
		if not data or not isinstance(data, list):
			return {
				"status": "error",
				"message": "Invalid data. Expected array of attendance records."
			}
		
		events_buffered = 0
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
						"record": str(record)[:100],
						"error": "fingerprintCode and dateTime are required"
					})
					continue
				
				# Tạo event data để push vào buffer
				buffer_event = {
					"employee_code": fingerprint_code,
					"employee_name": employee_name,
					"timestamp": date_time,
					"device_id": device_id,
					"device_name": device_name,
					"event_type": "batch_upload",
					"tracker_id": tracker_id,
					"received_at": frappe.utils.now()
				}
				
				# Push vào Redis buffer
				push_to_attendance_buffer(buffer_event)
				events_buffered += 1
				
			except Exception as record_error:
				logger.error(f"❌ Error buffering record: {str(record_error)}")
				errors.append({
					"record": str(record)[:100],
					"error": str(record_error)
				})
		
		logger.info(f"📊 BATCH BUFFERED: {events_buffered} events, {len(errors)} errors")
		logger.info("=" * 80)
		
		return {
			"status": "success",
			"message": f"Buffered {events_buffered} records for processing",
			"events_buffered": events_buffered,
			"total_errors": len(errors),
			"errors": errors[:10],
			"processing_mode": "async_buffer"
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


def get_historical_attendance_threshold_minutes():
	"""
	Get threshold in minutes for determining historical attendance data.
	Attendance older than this threshold will be silently synced without notification.
	Default: 1440 minutes (24 hours / 1 day)
	
	This prevents notifications for old data from newly connected devices
	while still allowing same-day delayed syncs to trigger notifications.
	"""
	try:
		# Allow configuration via site config
		threshold = frappe.get_system_settings("historical_attendance_threshold_minutes")
		if threshold:
			return int(threshold)
	except:
		pass
	return 1440  # Default 24 hours (1 day) - safe for same-day delayed syncs


def is_historical_attendance(attendance_timestamp, threshold_minutes=None):
	"""
	Check if attendance timestamp is historical (older than threshold).
	Used to determine if notification should be skipped for newly connected devices
	that are syncing old data.
	
	Args:
		attendance_timestamp: The parsed attendance timestamp (datetime)
		threshold_minutes: Optional threshold in minutes. If None, uses system config.
	
	Returns:
		True if attendance is historical and should be silently synced
		False if attendance is recent and should trigger notification
	"""
	if not attendance_timestamp:
		return False
	
	if threshold_minutes is None:
		threshold_minutes = get_historical_attendance_threshold_minutes()
	
	# Get current time in VN timezone
	vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
	now = datetime.now(vn_tz)
	
	# Ensure attendance_timestamp is timezone-aware
	if attendance_timestamp.tzinfo is None:
		# Assume VN time for naive datetime
		attendance_timestamp = vn_tz.localize(attendance_timestamp)
	
	# Calculate time difference
	time_diff = now - attendance_timestamp
	diff_minutes = time_diff.total_seconds() / 60
	
	# If attendance is older than threshold, it's historical
	return diff_minutes > threshold_minutes


# ============================================================================
# REDIS BUFFER FUNCTIONS - Performance optimization cho giờ tan học
# ============================================================================

def push_to_attendance_buffer(event_data):
	"""
	Push attendance event vào Redis buffer để xử lý batch sau.
	Operation này rất nhanh (O(1)) nên API có thể return ngay.
	
	Args:
		event_data: Dict chứa thông tin attendance event
			- employee_code
			- employee_name
			- timestamp
			- device_id
			- device_name
			- event_type
			- similarity (optional)
			- face_id_name (optional)
			- received_at
	"""
	try:
		# Serialize event data to JSON
		event_json = json.dumps(event_data, default=str)
		
		# Push vào Redis list (LPUSH - O(1))
		# Sử dụng frappe.cache() để lấy Redis connection
		cache = frappe.cache()
		
		# Dùng lpush để thêm vào đầu list
		# Batch processor sẽ dùng rpop để lấy từ cuối (FIFO order)
		if hasattr(cache, 'lpush'):
			cache.lpush(ATTENDANCE_BUFFER_KEY, event_json)
		else:
			# Fallback: dùng Redis connection trực tiếp
			redis_conn = cache.redis if hasattr(cache, 'redis') else None
			if redis_conn:
				redis_conn.lpush(ATTENDANCE_BUFFER_KEY, event_json)
			else:
				# Last fallback: xử lý synchronous nếu không có Redis
				get_hikvision_logger().warning("⚠️ Redis not available, falling back to sync processing")
				process_single_attendance_event(event_data)
				return
		
		get_hikvision_logger().debug(f"📥 Event pushed to buffer: {event_data.get('employee_code')}")
		
	except Exception as e:
		get_hikvision_logger().error(f"❌ Failed to push to buffer: {str(e)}")
		# Fallback: xử lý synchronous nếu push fail
		process_single_attendance_event(event_data)


def get_buffer_length():
	"""Lấy số lượng events đang chờ trong buffer"""
	try:
		cache = frappe.cache()
		if hasattr(cache, 'llen'):
			return cache.llen(ATTENDANCE_BUFFER_KEY) or 0
		else:
			redis_conn = cache.redis if hasattr(cache, 'redis') else None
			if redis_conn:
				return redis_conn.llen(ATTENDANCE_BUFFER_KEY) or 0
		return 0
	except Exception:
		return 0


def pop_from_attendance_buffer(count=None):
	"""
	Pop multiple events từ buffer để xử lý batch.
	
	Args:
		count: Số lượng events cần lấy. Mặc định là BUFFER_BATCH_SIZE.
	
	Returns:
		List of event dicts
	"""
	if count is None:
		count = BUFFER_BATCH_SIZE
	
	events = []
	try:
		cache = frappe.cache()
		redis_conn = None
		
		if hasattr(cache, 'rpop'):
			# Dùng frappe.cache() methods
			for _ in range(count):
				event_json = cache.rpop(ATTENDANCE_BUFFER_KEY)
				if not event_json:
					break
				if isinstance(event_json, bytes):
					event_json = event_json.decode('utf-8')
				events.append(json.loads(event_json))
		else:
			# Dùng Redis connection trực tiếp
			redis_conn = cache.redis if hasattr(cache, 'redis') else None
			if redis_conn:
				for _ in range(count):
					event_json = redis_conn.rpop(ATTENDANCE_BUFFER_KEY)
					if not event_json:
						break
					if isinstance(event_json, bytes):
						event_json = event_json.decode('utf-8')
					events.append(json.loads(event_json))
		
		return events
		
	except Exception as e:
		get_hikvision_logger().error(f"❌ Failed to pop from buffer: {str(e)}")
		return events


def process_single_attendance_event(event_data):
	"""
	Xử lý single attendance event (fallback khi Redis không available).
	Đây là logic cũ được tách ra thành function riêng.
	"""
	logger = get_hikvision_logger()
	
	try:
		employee_code = event_data.get("employee_code")
		employee_name = event_data.get("employee_name")
		timestamp = event_data.get("timestamp")
		device_id = event_data.get("device_id")
		device_name = event_data.get("device_name")
		event_type = event_data.get("event_type")
		
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
		if event_data.get("face_id_name"):
			notes_parts.append(f"Face ID: {event_data.get('face_id_name')}")
		if event_data.get("similarity"):
			notes_parts.append(f"Similarity: {event_data.get('similarity')}%")
		if event_type:
			notes_parts.append(f"Event: {event_type}")
		
		if notes_parts:
			existing_notes = attendance_doc.notes or ""
			attendance_doc.notes = existing_notes + "; ".join(notes_parts) + "; "
		
		# Update attendance time
		attendance_doc.update_attendance_time(parsed_timestamp, device_id, device_name, original_timestamp=timestamp)
		
		# Save to database
		attendance_doc.save(ignore_permissions=True)
		frappe.db.commit()
		
		logger.info(f"✅ [SYNC] Processed attendance for {employee_code}")
		
		# Enqueue notification nếu không phải historical data
		if not is_historical_attendance(parsed_timestamp):
			try:
				frappe.enqueue(
					"erp.api.attendance.notification.publish_attendance_notification",
					queue="short",
					job_id=f"attendance_notif_{employee_code}_{parsed_timestamp.strftime('%H%M%S')}",
					deduplicate=True,
					timeout=120,
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
				logger.error(f"❌ Failed to enqueue notification: {str(enqueue_error)}")
		
		return True
		
	except Exception as e:
		logger.error(f"❌ Error processing single event: {str(e)}")
		return False


@frappe.whitelist(allow_guest=False, methods=["GET"])
def get_buffer_status():
	"""
	API để check status của attendance buffer.
	Dùng cho monitoring và debugging.
	"""
	try:
		length = get_buffer_length()
		return {
			"status": "success",
			"buffer_key": ATTENDANCE_BUFFER_KEY,
			"pending_events": length,
			"batch_size": BUFFER_BATCH_SIZE,
			"timestamp": frappe.utils.now()
		}
	except Exception as e:
		return {
			"status": "error",
			"message": str(e),
			"timestamp": frappe.utils.now()
		}
