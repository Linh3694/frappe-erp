import json
import frappe
from frappe import _
import requests
from datetime import datetime
from erp.utils.api_response import success_response, error_response


ATTENDANCE_STATUSES = {"present", "absent", "late", "excused"}


def _to_bool(val):
	if isinstance(val, bool):
		return val
	if isinstance(val, (int, float)):
		return bool(val)
	if isinstance(val, str):
		return val.lower() in ("1", "true", "y", "yes")
	return False


def _get_json_body():
	try:
		if hasattr(frappe, 'request') and getattr(frappe.request, 'data', None):
			return json.loads(frappe.request.data.decode('utf-8'))
	except Exception:
		return None
	return None


@frappe.whitelist(allow_guest=False)
def check_homeroom_attendance_status(date=None, campus_id=None):
	"""
	Check homeroom attendance status for all classes on a specific date.

	Params:
		date: Date to check (YYYY-MM-DD). Defaults to today.
		campus_id: Optional campus filter

	Returns:
		{
			"date": "2024-01-15",
			"total_classes": 25,
			"completed_classes": 18,
			"pending_classes": 7,
			"completion_percentage": 72.0,
			"classes": [
				{
					"class_id": "CLASS-001",
					"class_name": "10A1",
					"status": "completed",  # completed, pending, not_started
					"student_count": 35,
					"attended_count": 32,
					"attendance_percentage": 91.4,
					"last_updated": "2024-01-15 08:30:00"
				}
			]
		}
	"""
	try:
		frappe.logger().info(f"🏫 Starting check_homeroom_attendance_status - date: {date}, campus_id: {campus_id}")

		if not date:
			date = frappe.utils.nowdate()
			frappe.logger().info(f"📅 Using current date: {date}")

		if not campus_id:
			try:
				from erp.utils.campus_utils import get_current_campus_from_context
				campus_id = get_current_campus_from_context()
				frappe.logger().info(f"🏫 Campus ID from context: {campus_id}")
			except Exception as campus_error:
				frappe.logger().warning(f"⚠️ Failed to get campus from context: {str(campus_error)}")
				campus_id = None

		# Default to CAMPUS-00001 if no campus found
		if not campus_id:
			campus_id = "CAMPUS-00001"
			frappe.logger().info(f"🏫 Using default campus: {campus_id}")

		# Get all active classes for the campus (only regular classes)
		class_filters = {"docstatus": 0, "class_type": "regular"}
		if campus_id:
			class_filters["campus_id"] = campus_id

		frappe.logger().info(f"🔍 Getting classes with filters: {class_filters}")

		try:
			classes = frappe.get_all("SIS Class",
				filters=class_filters,
				fields=["name", "title", "campus_id", "class_type"]
			)
			frappe.logger().info(f"✅ Found {len(classes)} classes")
		except Exception as class_error:
			frappe.logger().error(f"❌ Failed to get classes: {str(class_error)}")
			return error_response(message=f"Failed to get classes: {str(class_error)}", code="GET_CLASSES_ERROR")

		if not classes:
			frappe.logger().warning(f"⚠️ No classes found with filters: {class_filters}")
			return success_response({
				"date": date,
				"campus_id": campus_id,
				"total_classes": 0,
				"completed_classes": 0,
				"pending_classes": 0,
				"completion_percentage": 0,
				"classes": []
			}, message="No classes found")

		result_classes = []
		total_completed = 0

		for class_info in classes:
			class_id = class_info.name
			class_title = class_info.get('title') or class_info.get('name') or 'Unknown'
			frappe.logger().info(f"📚 Processing class: {class_id} ({class_title}) - Full info: {class_info}")

			try:
				# Check if homeroom attendance exists for this class/date
				attendance_count = frappe.db.count("SIS Class Attendance", {
					"class_id": class_id,
					"date": date,
					"period": "homeroom"
				})
				frappe.logger().info(f"   📊 Attendance count: {attendance_count}")

				# Get student count in class
				student_count = frappe.db.count("SIS Class Student", {
					"class_id": class_id
				})
				frappe.logger().info(f"   👥 Student count: {student_count}")

				# Get last update time
				last_updated = None
				if attendance_count > 0:
					last_record = frappe.get_all("SIS Class Attendance",
						filters={
							"class_id": class_id,
							"date": date,
							"period": "homeroom"
						},
						fields=["modified"],
						order_by="modified desc",
						limit=1
					)
					if last_record:
						last_updated = last_record[0].modified
						frappe.logger().info(f"   🕐 Last updated: {last_updated}")

				# Calculate status
				if attendance_count == 0:
					status = "not_started"
					attended_count = 0
					attendance_percentage = 0
				elif attendance_count < student_count:
					status = "pending"
					attended_count = attendance_count
					attendance_percentage = round((attendance_count / student_count) * 100, 1)
				else:
					status = "completed"
					attended_count = attendance_count
					attendance_percentage = round((attendance_count / student_count) * 100, 1)
					total_completed += 1

				frappe.logger().info(f"   📈 Status: {status}, Attended: {attended_count}/{student_count} ({attendance_percentage}%)")

				result_classes.append({
					"class_id": class_id,
					"class_name": class_title,
					"status": status,
					"student_count": student_count,
					"attended_count": attended_count,
					"attendance_percentage": attendance_percentage,
					"last_updated": last_updated.isoformat() if last_updated else None
				})

			except Exception as class_process_error:
				frappe.logger().error(f"❌ Error processing class {class_id}: {str(class_process_error)}")
				# Continue with other classes
				continue

		# Sort by status priority: not_started, pending, completed
		status_priority = {"not_started": 0, "pending": 1, "completed": 2}
		result_classes.sort(key=lambda x: (status_priority.get(x["status"], 3), x["class_name"] or ""))

		total_classes = len(classes)
		pending_classes = total_classes - total_completed
		completion_percentage = round((total_completed / total_classes) * 100, 1) if total_classes > 0 else 0

		result = {
			"date": date,
			"campus_id": campus_id,
			"total_classes": total_classes,
			"completed_classes": total_completed,
			"pending_classes": pending_classes,
			"completion_percentage": completion_percentage,
			"classes": result_classes
		}

		frappe.logger().info(f"✅ check_homeroom_attendance_status completed - {total_completed}/{total_classes} classes completed")
		return success_response(result, message="Homeroom attendance status retrieved successfully")

	except Exception as e:
		frappe.logger().error(f"❌ check_homeroom_attendance_status error: {str(e)}")
		import traceback
		frappe.logger().error(f"❌ Full traceback: {traceback.format_exc()}")
		return error_response(message=f"Failed to check homeroom attendance status: {str(e)}", code="CHECK_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False)
def get_class_attendance(class_id=None, date=None, period=None):
	"""Return attendance records for a class on a date and period.
	Params may be provided in query string or function args.
	
	⚡ Performance: Cached for 5 minutes (critical real-time data)
	"""
	try:
		if not class_id:
			class_id = frappe.request.args.get("class_id") if getattr(frappe, 'request', None) else None
		if not date:
			date = frappe.request.args.get("date") if getattr(frappe, 'request', None) else None
		if not period:
			period = frappe.request.args.get("period") if getattr(frappe, 'request', None) else None

		if not class_id or not date or not period:
			return error_response(message="Missing required parameters: class_id, date, period", code="MISSING_PARAMETERS")
		
		# ⚡ CACHE: Check Redis cache first (5 min TTL - critical real-time data)
		cache_key = f"attendance:{class_id}:{date}:{period}"
		
		try:
			cached_data = frappe.cache().get_value(cache_key)
			if cached_data:
				frappe.logger().info(f"✅ Cache HIT for attendance {class_id}/{date}/{period}")
				return success_response(
					data=cached_data,
					message="Attendance fetched successfully (cached)"
				)
		except Exception as cache_error:
			frappe.logger().warning(f"Cache read failed: {cache_error}")
		
		frappe.logger().info(f"❌ Cache MISS for attendance {class_id}/{date}/{period} - fetching from DB")

		rows = frappe.get_all(
			"SIS Class Attendance",
			filters={
				"class_id": class_id,
				"date": date,
				"period": period,
			},
			fields=[
				"name", "student_id", "student_code", "student_name", "class_id", "date", "period", "status", "remarks",
			]
		)
		
		# ⚡ CACHE: Store result in Redis (5 min = 300 sec)
		try:
			frappe.cache().set_value(cache_key, rows, expires_in_sec=300)
			frappe.logger().info(f"✅ Cached attendance for {class_id}/{date}/{period}")
		except Exception as cache_error:
			frappe.logger().warning(f"Cache write failed: {cache_error}")
		
		return success_response(data=rows, message="Attendance fetched successfully")
	except Exception as e:
		frappe.log_error(f"get_class_attendance error: {str(e)}")
		return error_response(message="Failed to fetch attendance", code="GET_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_get_class_attendance(class_id=None, date=None, periods=None):
	"""Get attendance for multiple periods in a single request.
	
	⚡ Performance: Cached for 5 minutes (critical real-time data)
	
	Request body:
	{
		"class_id": "CLASS-001",
		"date": "2024-01-15",
		"periods": ["1", "2", "3", ..., "homeroom"]
	}
	
	Returns:
	{
		"success": true,
		"data": {
			"1": [{student_id, status, ...}, ...],
			"2": [{student_id, status, ...}, ...],
			"homeroom": [{student_id, status, ...}, ...]
		}
	}
	"""
	try:
		body = _get_json_body() or {}
		if class_id is None:
			class_id = body.get('class_id') or frappe.request.args.get("class_id")
		if date is None:
			date = body.get('date') or frappe.request.args.get("date")
		if periods is None:
			periods = body.get('periods')
		
		if not class_id or not date or not periods:
			return error_response(message="Missing required parameters: class_id, date, periods", code="MISSING_PARAMETERS")
		
		if isinstance(periods, str):
			try:
				periods = json.loads(periods)
			except Exception:
				periods = []
		
		if not isinstance(periods, list) or not periods:
			return error_response(message="periods must be a non-empty array", code="INVALID_PERIODS")
		
		# ⚡ CACHE: Check Redis cache first (5 min TTL - critical real-time data)
		# Hash periods list for stable cache key
		import hashlib
		periods_hash = hashlib.md5(json.dumps(sorted(periods)).encode()).hexdigest()[:8]
		cache_key = f"attendance_batch:{class_id}:{date}:periods_{periods_hash}"
		
		try:
			cached_data = frappe.cache().get_value(cache_key)
			if cached_data:
				frappe.logger().info(f"✅ Cache HIT for batch_attendance {class_id}/{date} ({len(periods)} periods)")
				return success_response(
					data=cached_data,
					message="Batch attendance fetched successfully (cached)"
				)
		except Exception as cache_error:
			frappe.logger().warning(f"Cache read failed: {cache_error}")
		
		frappe.logger().info(f"❌ Cache MISS for batch_attendance {class_id}/{date} - fetching from DB")
		frappe.logger().info(f"🔍 [Backend] batch_get_class_attendance: class={class_id}, date={date}, periods={len(periods)}")
		
		# Batch query all periods at once
		rows = frappe.get_all(
			"SIS Class Attendance",
			filters={
				"class_id": class_id,
				"date": date,
				"period": ["in", periods]
			},
			fields=[
				"name", "student_id", "student_code", "student_name", 
				"class_id", "date", "period", "status", "remarks"
			]
		)
		
		# Group by period
		result = {}
		for period in periods:
			result[period] = []
		
		for row in rows:
			period = row.get('period')
			if period in result:
				result[period].append(row)
		
		frappe.logger().info(f"✅ [Backend] batch_get_class_attendance: Found {len(rows)} total records across {len(periods)} periods")
		
		# ⚡ CACHE: Store result in Redis (5 min = 300 sec)
		try:
			frappe.cache().set_value(cache_key, result, expires_in_sec=300)
			frappe.logger().info(f"✅ Cached batch_attendance for {class_id}/{date}")
		except Exception as cache_error:
			frappe.logger().warning(f"Cache write failed: {cache_error}")
		
		return success_response(data=result, message="Batch attendance fetched successfully")
	except Exception as e:
		frappe.log_error(f"batch_get_class_attendance error: {str(e)}")
		frappe.logger().error(f"❌ [Backend] batch_get_class_attendance error: {str(e)}")
		return error_response(message="Failed to fetch batch attendance", code="BATCH_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"]) 
def save_class_attendance(items=None, overwrite=None):
	"""Upsert class attendance records.
	- items: JSON array of {student_id, student_code?, student_name?, class_id, date, period, status, remarks?}
	- overwrite: if true, replace existing; otherwise just update status/remarks
	"""
	try:
		body = _get_json_body() or {}
		if items is None:
			items = body.get('items')
		if overwrite is None:
			overwrite = body.get('overwrite')
		overwrite = _to_bool(overwrite)

		if isinstance(items, str):
			try:
				items = json.loads(items)
			except Exception:
				items = []
		if not isinstance(items, list) or not items:
			return error_response(message="No attendance items provided", code="NO_ITEMS")

		user_id = frappe.session.user
		from erp.utils.campus_utils import get_current_campus_from_context
		campus_id = get_current_campus_from_context()

		# Validate and prepare items
		valid_items = []
		for it in items:
			student_id = (it or {}).get('student_id')
			class_id = (it or {}).get('class_id')
			date = (it or {}).get('date')
			period = (it or {}).get('period')
			status = ((it or {}).get('status') or 'present').lower()
			remarks = (it or {}).get('remarks')
			student_code = (it or {}).get('student_code')
			student_name = (it or {}).get('student_name')

			if not student_id or not class_id or not date or not period:
				continue
			if status not in ATTENDANCE_STATUSES:
				status = 'present'

			valid_items.append({
				'student_id': student_id,
				'class_id': class_id,
				'date': date,
				'period': period,
				'status': status,
				'remarks': remarks,
				'student_code': student_code,
				'student_name': student_name
			})

		if not valid_items:
			return error_response(message="No valid attendance items", code="NO_VALID_ITEMS")

		# Batch fetch all existing records in one query
		student_ids = [item['student_id'] for item in valid_items]
		class_ids = list(set([item['class_id'] for item in valid_items]))
		dates = list(set([item['date'] for item in valid_items]))
		periods = list(set([item['period'] for item in valid_items]))

		existing_records = frappe.get_all(
			"SIS Class Attendance",
			filters={
				"student_id": ["in", student_ids],
				"class_id": ["in", class_ids],
				"date": ["in", dates],
				"period": ["in", periods]
			},
			fields=["name", "student_id", "class_id", "date", "period"]
		)

		# Create a lookup map for existing records
		existing_map = {}
		for rec in existing_records:
			key = f"{rec['student_id']}|{rec['class_id']}|{rec['date']}|{rec['period']}"
			existing_map[key] = rec['name']

		# Process items with batch operations
		upserts = 0
		updates = 0
		for item in valid_items:
			key = f"{item['student_id']}|{item['class_id']}|{item['date']}|{item['period']}"
			
			if key in existing_map:
				# Update existing record
				name = existing_map[key]
				values = {
					"status": item['status'],
					"remarks": item['remarks'],
					"student_code": item['student_code'],
					"student_name": item['student_name']
				}
				if campus_id:
					values["campus_id"] = campus_id
				
				if overwrite:
					frappe.db.set_value("SIS Class Attendance", name, values, update_modified=True)
				else:
					# Partial update
					frappe.db.set_value("SIS Class Attendance", name, {
						"status": item['status'],
						"remarks": item['remarks']
					}, update_modified=True)
				updates += 1
			else:
				# Create new record
				doc = frappe.get_doc({
					"doctype": "SIS Class Attendance",
					"student_id": item['student_id'],
					"student_code": item['student_code'],
					"student_name": item['student_name'],
					"class_id": item['class_id'],
					"date": item['date'],
					"period": item['period'],
					"status": item['status'],
					"remarks": item['remarks'],
					"campus_id": campus_id,
					"recorded_by": user_id,
				})
				doc.insert()
				upserts += 1

		frappe.db.commit()
		
		# ⚡ CACHE: Clear attendance cache after save (both single and batch)
		try:
			cache = frappe.cache()
			redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
			
			if hasattr(redis_conn, 'scan_iter'):
				# Clear all affected cache keys
				cache_cleared = 0
				for item in valid_items:
					class_id = item['class_id']
					date = item['date']
					period = item['period']
					
					# Clear single period cache
					single_key = f"attendance:{class_id}:{date}:{period}"
					cache.delete_key(single_key)
					
					# Clear batch cache patterns for this class/date
					batch_pattern = f"*attendance_batch:{class_id}:{date}:*"
					batch_keys = list(redis_conn.scan_iter(match=batch_pattern, count=100))
					if batch_keys:
						redis_conn.delete(*batch_keys)
						cache_cleared += len(batch_keys)
				
				frappe.logger().info(f"✅ Cleared attendance cache after save ({cache_cleared} batch keys)")
		except Exception as cache_error:
			frappe.logger().warning(f"Cache clear failed: {cache_error}")
		
		return success_response(message=f"Saved attendance ({upserts} inserted, {updates} updated)")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(f"save_class_attendance error: {str(e)}")
		return error_response(message="Failed to save attendance", code="SAVE_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False)
def preview_homeroom_attendance_report(date=None):
	"""
	Preview homeroom attendance report content without sending email
	Returns the email content and data for testing
	"""
	try:
		if not date:
			date = frappe.utils.nowdate()

		# Get homeroom attendance status
		status_result = check_homeroom_attendance_status(date=date)
		if not status_result.get('success'):
			return error_response("Failed to check attendance status", code="CHECK_FAILED")

		attendance_data = status_result['data']

		# Generate email content
		email_content = generate_homeroom_report_email(attendance_data)

		# Format date for subject (DD/MM/YYYY)
		try:
			from datetime import datetime
			date_obj = datetime.strptime(date, '%Y-%m-%d')
			formatted_date = date_obj.strftime('%d/%m/%Y')
		except:
			formatted_date = date

		# Return preview data
		return success_response({
			"date": date,
			"formatted_date": formatted_date,
			"attendance_data": attendance_data,
			"email_subject": f"[WSHN] Báo cáo điểm danh chủ nhiệm ngày {formatted_date}",
			"email_recipient": "linh.nguyenhai@wellspring.edu.vn",
			"email_content_html": email_content,
			"email_content_preview": email_content.replace('<br>', '\n').replace('</p>', '\n\n').replace('<li>', '• ').replace('</li>', '\n')[:500] + "..."
		}, "Preview generated successfully")

	except Exception as e:
		frappe.log_error(f"preview_homeroom_attendance_report error: {str(e)}")
		return error_response("Failed to generate preview", code="PREVIEW_ERROR")


@frappe.whitelist(allow_guest=False)
def test_email_service_connection():
	"""
	Test connection to email service
	"""
	try:
		# Get email service URL
		email_service_url = frappe.conf.get('email_service_url') or 'http://172.16.20.113:5030'
		graphql_endpoint = f"{email_service_url}/graphql"

		# Simple GraphQL query to test connection
		graphql_query = """
		query {
			health
		}
		"""

		payload = {
			"query": graphql_query
		}

		response = requests.post(
			graphql_endpoint,
			json=payload,
			headers={'Content-Type': 'application/json'},
			timeout=10
		)

		if response.status_code == 200:
			result = response.json()
			if result.get('data', {}).get('health'):
				return success_response({
					"connected": True,
					"url": graphql_endpoint,
					"health": result['data']['health']
				}, "Email service connection successful")
			else:
				return error_response("Email service responded but health check failed", code="HEALTH_CHECK_FAILED")
		else:
			return error_response(f"HTTP {response.status_code}: {response.text}", code="CONNECTION_FAILED")

	except requests.exceptions.RequestException as e:
		return error_response(f"Request error: {str(e)}", code="REQUEST_ERROR")
	except Exception as e:
		return error_response(f"Error: {str(e)}", code="TEST_ERROR")


@frappe.whitelist(allow_guest=False)
def send_homeroom_attendance_report(date=None):
	"""
	Check homeroom attendance status and send email report to admin.

	Params:
		date: Date to check (YYYY-MM-DD). Defaults to today.

	Returns:
		Status of email sending
	"""
	try:
		if not date:
			date = frappe.utils.nowdate()

		# Get homeroom attendance status
		status_result = check_homeroom_attendance_status(date=date)
		if not status_result.get('success'):
			return error_response("Failed to check attendance status", code="CHECK_FAILED")

		attendance_data = status_result['data']

		# Generate email content
		email_content = generate_homeroom_report_email(attendance_data)

		# Format date for subject (DD/MM/YYYY)
		try:
			from datetime import datetime
			date_obj = datetime.strptime(date, '%Y-%m-%d')
			formatted_date = date_obj.strftime('%d/%m/%Y')
		except:
			formatted_date = date

		# Send email via email service
		email_result = send_email_via_service(
			to="linh.nguyenhai@wellspring.edu.vn",
			subject=f"[WSHN] Báo cáo điểm danh chủ nhiệm ngày {formatted_date}",
			body=email_content
		)

		if email_result.get('success'):
			return success_response({
				"email_sent": True,
				"recipient": "linh.nguyenhai@wellspring.edu.vn",
				"report_date": date
			}, "Homeroom attendance report sent successfully")
		else:
			return error_response(f"Failed to send email: {email_result.get('message')}", code="EMAIL_FAILED")

	except Exception as e:
		frappe.log_error(f"send_homeroom_attendance_report error: {str(e)}")
		return error_response("Failed to send attendance report", code="SEND_REPORT_ERROR")


def generate_homeroom_report_email(attendance_data):
	"""
	Generate HTML email content for homeroom attendance report
	"""
	date = attendance_data.get('date', frappe.utils.nowdate())

	# Group classes by education stage
	stage_data = {}

	for class_info in attendance_data.get('classes', []):
		# Get education stage from class
		education_stage = get_education_stage_from_class(class_info['class_id'])
		stage_name = get_stage_display_name(education_stage)
		class_title = class_info.get('class_name') or class_info.get('class_id') or 'Unknown'

		if stage_name not in stage_data:
			stage_data[stage_name] = {
				'total': 0,
				'completed': 0,
				'pending_classes': []
			}

		stage_data[stage_name]['total'] += 1
		if class_info['status'] == 'completed':
			stage_data[stage_name]['completed'] += 1
		else:
			stage_data[stage_name]['pending_classes'].append(class_title)

	# Generate HTML content
	html_content = f"""
	<div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto;">
		<h1 style="color: #2e7d32; text-align: center; border-bottom: 3px solid #2e7d32; padding-bottom: 10px;">
			📊 Báo cáo điểm danh chủ nhiệm - {date}
		</h1>

		<div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
			<h2 style="color: #1976d2; margin-top: 0;">Tổng quan</h2>
			<p><strong>Tổng số lớp:</strong> {attendance_data.get('total_classes', 0)} lớp</p>
			<p><strong>Đã hoàn thành:</strong> {attendance_data.get('completed_classes', 0)} lớp</p>
			<p><strong>Chưa hoàn thành:</strong> {attendance_data.get('pending_classes', 0)} lớp</p>
			<p><strong>Tỷ lệ hoàn thành:</strong> {attendance_data.get('completion_percentage', 0)}%</p>
		</div>

		<div style="margin: 30px 0;">
	"""

	# Add each education stage section
	for stage_name, stage_info in stage_data.items():
		completion_rate = round((stage_info['completed'] / stage_info['total']) * 100, 1) if stage_info['total'] > 0 else 0

		html_content += f"""
		<div style="background: #fff; border: 1px solid #ddd; border-radius: 8px; margin: 20px 0; padding: 20px;">
			<h3 style="color: #424242; margin-top: 0; border-bottom: 2px solid #1976d2; padding-bottom: 8px;">
				🏫 {stage_name}
			</h3>

			<div style="display: flex; gap: 20px; margin: 15px 0;">
				<div style="flex: 1;">
					<p><strong>Tổng số lớp:</strong> {stage_info['total']} lớp</p>
					<p><strong>Đã điểm danh:</strong> {stage_info['completed']} lớp</p>
					<p><strong>Tỷ lệ:</strong> {completion_rate}%</p>
				</div>

				<div style="flex: 2;">
					<p><strong>Chưa điểm danh:</strong></p>
					<div style="background: #fff3e0; padding: 10px; border-radius: 4px; border-left: 4px solid #ff9800;">
		"""

		if stage_info['pending_classes']:
			# Display all classes, break into multiple lines if too many
			classes_text = ", ".join(stage_info['pending_classes'])
			html_content += f"<p style='margin: 0; line-height: 1.4; word-wrap: break-word;'>{classes_text}</p>"
		else:
			html_content += "<p style='margin: 0; color: #4caf50; font-weight: bold;'>✅ Tất cả lớp đã hoàn thành</p>"

		html_content += """
					</div>
				</div>
			</div>
		</div>
		"""

	html_content += """
		</div>

		<div style="background: #e8f5e8; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4caf50;">
			<h4 style="color: #2e7d32; margin-top: 0;">📋 Hướng dẫn</h4>
			<ul style="margin: 10px 0; padding-left: 20px;">
				<li>Kiểm tra các lớp chưa hoàn thành điểm danh chủ nhiệm</li>
				<li>Liên hệ với giáo viên chủ nhiệm để cập nhật điểm danh</li>
				<li>Theo dõi tỷ lệ hoàn thành hàng ngày</li>
			</ul>
		</div>

		<hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

		<div style="text-align: center; color: #666; font-size: 14px;">
			<p><strong>Hệ thống quản lý trường học</strong></p>
			<p>Trường PTLC Song Ngữ Quốc tế Wellspring</p>
			<p>Email: it@wellspring.edu.vn | Thời gian tạo: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
		</div>
	</div>
	"""

	return html_content


def get_education_stage_from_class(class_id):
	"""Get education stage ID from class"""
	try:
		# Get education_grade from class
		grade_name = frappe.get_value("SIS Class", class_id, "education_grade")
		if not grade_name:
			return None

		# Get education_stage_id from education_grade
		stage_id = frappe.get_value("SIS Education Grade", grade_name, "education_stage_id")
		return stage_id

	except Exception as e:
		frappe.logger().warning(f"Error getting education stage for class {class_id}: {str(e)}")
		return None


def get_stage_display_name(stage_id):
	"""Convert education stage ID to display name using title_vn"""
	try:
		if not stage_id:
			return "Chưa phân loại"

		# Debug: Log what we're trying to get
		frappe.logger().info(f"🔍 Getting stage display name for: {stage_id}")

		# Try to get title_vn first, then fallback to stage_name
		stage_info = frappe.get_value("SIS Education Stage", stage_id, ["title_vn", "stage_name"], as_dict=True)

		frappe.logger().info(f"📊 Stage info retrieved: {stage_info}")

		if not stage_info:
			frappe.logger().warning(f"⚠️ No stage info found for {stage_id}")
			# Fallback to ID-based mapping
			return get_stage_name_from_id(stage_id)

		# Use title_vn if available, otherwise use stage_name with mapping
		if stage_info.get('title_vn'):
			frappe.logger().info(f"✅ Using title_vn: {stage_info['title_vn']}")
			return stage_info['title_vn']

		stage_name = stage_info.get('stage_name')
		frappe.logger().info(f"ℹ️ No title_vn found, using stage_name: {stage_name}")

		if not stage_name:
			return get_stage_name_from_id(stage_id)

		# Map to Vietnamese names as fallback
		name_mapping = {
			"Elementary": "Trường Tiểu học",
			"Middle School": "Trường Trung học Cơ sở",
			"High School": "Trường Trung học Phổ thông",
			"Primary": "Trường Tiểu học",
			"Secondary": "Trường Trung học Cơ sở",
			"Tiểu học": "Trường Tiểu học",
			"THCS": "Trường Trung học Cơ sở",
			"THPT": "Trường Trung học Phổ thông"
		}

		result = name_mapping.get(stage_name, stage_name)
		frappe.logger().info(f"🔄 Mapped stage_name '{stage_name}' to: {result}")
		return result

	except Exception as e:
		frappe.logger().error(f"❌ Error getting stage display name for {stage_id}: {str(e)}")
		return get_stage_name_from_id(stage_id)


def get_stage_name_from_id(stage_id):
	"""Fallback function to get Vietnamese name from stage ID pattern"""
	try:
		if not stage_id:
			return "Chưa phân loại"

		# Based on the IDs from the test output, map them to Vietnamese names
		id_mapping = {
			"SIS_EDUCATION_STAGE-00004": "Trường Tiểu học",
			"SIS_EDUCATION_STAGE-00005": "Trường Trung học Cơ sở",
			"SIS_EDUCATION_STAGE-00006": "Trường Trung học Phổ thông"
		}

		result = id_mapping.get(stage_id)
		if result:
			frappe.logger().info(f"🔄 Fallback mapping {stage_id} to: {result}")
			return result

		# If not found, return the ID
		frappe.logger().warning(f"⚠️ No fallback mapping found for {stage_id}")
		return stage_id

	except Exception as e:
		frappe.logger().error(f"❌ Error in fallback mapping for {stage_id}: {str(e)}")
		return stage_id or "Chưa phân loại"


def send_email_via_service(to, subject, body):
	"""
	Send email via email service GraphQL API
	"""
	try:
		# Get email service URL from site config or environment
		email_service_url = frappe.conf.get('email_service_url') or 'http://localhost:5030'

		# GraphQL endpoint (email service uses GraphQL at /graphql)
		graphql_endpoint = f"{email_service_url}/graphql"

		# GraphQL mutation for sending email
		graphql_query = """
		mutation SendEmail($input: SendEmailInput!) {
			sendEmail(input: $input) {
				success
				message
				messageId
			}
		}
		"""

		# Variables for GraphQL mutation
		variables = {
			"input": {
				"to": [to],
				"subject": subject,
				"body": body,
				"contentType": "HTML"
			}
		}

		# GraphQL request payload
		payload = {
			"query": graphql_query,
			"variables": variables
		}

		# Send GraphQL request to email service
		response = requests.post(
			graphql_endpoint,
			json=payload,
			headers={
				'Content-Type': 'application/json',
				# Add authentication if needed in future
				# 'Authorization': f'Bearer {frappe.conf.get("email_service_token")}'
			},
			timeout=30
		)

		if response.status_code == 200:
			result = response.json()

			# Check for GraphQL errors
			if result.get('errors'):
				error_messages = [err.get('message', 'Unknown error') for err in result['errors']]
				frappe.logger().error(f"GraphQL errors: {error_messages}")
				return {"success": False, "message": f"GraphQL errors: {', '.join(error_messages)}"}

			# Check mutation result
			send_email_result = result.get('data', {}).get('sendEmail')
			if send_email_result and send_email_result.get('success'):
				frappe.logger().info(f"Email sent successfully to {to} - MessageId: {send_email_result.get('messageId')}")
				return {"success": True, "message": send_email_result.get('message')}
			else:
				error_msg = send_email_result.get('message', 'Unknown error') if send_email_result else 'No response data'
				frappe.logger().error(f"Email service returned error: {error_msg}")
				return {"success": False, "message": error_msg}
		else:
			frappe.logger().error(f"Email service HTTP error: {response.status_code} - {response.text}")
			return {"success": False, "message": f"HTTP {response.status_code}: {response.text}"}

	except requests.exceptions.RequestException as e:
		frappe.logger().error(f"Request error sending email: {str(e)}")
		return {"success": False, "message": f"Request error: {str(e)}"}
	except Exception as e:
		frappe.logger().error(f"Error sending email: {str(e)}")
		return {"success": False, "message": f"Error: {str(e)}"}


# Simple test function (can be called without full frappe environment)
def test_basic_functionality():
	"""
	Test basic functionality without frappe dependencies
	"""
	print("🧪 Testing basic attendance functionality...")

	# Test default campus logic
	campus_id = None
	if not campus_id:
		campus_id = "CAMPUS-00001"
	print(f"✅ Default campus set to: {campus_id}")

	# Test date logic
	import datetime
	date = None
	if not date:
		date = datetime.date.today().strftime('%Y-%m-%d')
	print(f"✅ Default date set to: {date}")

	print("✅ Basic functionality test passed")
	return True


# Standalone test script that can be run directly
if __name__ == "__main__":
	# This allows running the file directly for testing
	import sys
	import os

	# Add the apps path so we can import
	sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

	try:
		test_basic_functionality()
		print("\n🎯 Standalone test completed successfully!")
	except Exception as e:
		print(f"\n❌ Standalone test failed: {e}")
		import traceback
		traceback.print_exc()


# Test function for bench console
def test_homeroom_report_console(date=None):
	"""
	Function to test homeroom report in bench console
	Run: bench execute erp.api.erp_sis.attendance.test_homeroom_report_console --kwargs '{"date": "2024-01-15"}'
	"""
	try:
		if not date:
			date = frappe.utils.nowdate()

		print(f"🏫 Testing homeroom attendance report for date: {date}")
		print("=" * 80)

		# Step 1: Check attendance status
		print("📊 Step 1: Getting attendance status...")
		status_result = check_homeroom_attendance_status(date=date)

		if not status_result.get('success'):
			print(f"❌ Failed to check attendance status: {status_result.get('message')}")
			return status_result

		attendance_data = status_result['data']
		print("✅ Attendance status retrieved successfully")
		print(f"   - Total classes: {attendance_data.get('total_classes', 0)}")
		print(f"   - Completed: {attendance_data.get('completed_classes', 0)}")
		print(f"   - Pending: {attendance_data.get('pending_classes', 0)}")
		print(f"   - Completion rate: {attendance_data.get('completion_percentage', 0):.1f}%")
		print()

		# Step 2: Show class details
		print("📋 Step 2: Class details by educational stage:")
		stage_summary = {}

		for class_info in attendance_data.get('classes', []):
			education_stage = get_education_stage_from_class(class_info['class_id'])
			stage_name = get_stage_display_name(education_stage)
			class_title = class_info.get('class_name') or class_info.get('class_id') or 'Unknown'

			if stage_name not in stage_summary:
				stage_summary[stage_name] = {
					'total': 0,
					'completed': 0,
					'classes': []
				}

			stage_summary[stage_name]['total'] += 1
			if class_info['status'] == 'completed':
				stage_summary[stage_name]['completed'] += 1
			else:
				stage_summary[stage_name]['classes'].append(class_title)

		for stage_name, stage_info in stage_summary.items():
			completion_rate = round((stage_info['completed'] / stage_info['total']) * 100, 1) if stage_info['total'] > 0 else 0
			print(f"   🏫 {stage_name}:")
			print(f"      - Tổng lớp: {stage_info['total']}")
			print(f"      - Đã hoàn thành: {stage_info['completed']}")
			print(".1f")
			if stage_info['classes']:
				classes_text = ", ".join(stage_info['classes'])
				# Break into multiple lines if too long
				if len(classes_text) > 100:
					# Split into chunks of ~80 chars
					words = classes_text.split(", ")
					lines = []
					current_line = ""
					for word in words:
						if len(current_line + word) > 80:
							lines.append(current_line.rstrip(", "))
							current_line = word + ", "
						else:
							current_line += word + ", "
					if current_line:
						lines.append(current_line.rstrip(", "))

					for i, line in enumerate(lines):
						prefix = "      - Chưa hoàn thành: " if i == 0 else "                        "
						print(f"{prefix}{line}")
				else:
					print(f"      - Chưa hoàn thành: {classes_text}")
			print()

		# Step 3: Generate email preview
		print("📧 Step 3: Generating email content...")
		email_content = generate_homeroom_report_email(attendance_data)
		print("✅ Email content generated successfully")
		# Format date for subject (DD/MM/YYYY)
		try:
			from datetime import datetime
			date_obj = datetime.strptime(date, '%Y-%m-%d')
			formatted_date = date_obj.strftime('%d/%m/%Y')
		except:
			formatted_date = date

		print(f"   - Subject: [WSHN] Báo cáo điểm danh chủ nhiệm ngày {formatted_date}")
		print(f"   - Recipient: linh.nguyenhai@wellspring.edu.vn")
		print(f"   - Content length: {len(email_content)} characters")
		print()

		# Step 4: Show email preview (first 1000 chars)
		print("📄 Step 4: Email preview (first 1000 characters):")
		print("-" * 80)
		# Remove HTML tags for console preview
		import re
		clean_preview = re.sub(r'<[^>]+>', '', email_content)
		clean_preview = re.sub(r'\s+', ' ', clean_preview).strip()
		print(clean_preview[:1000] + "..." if len(clean_preview) > 1000 else clean_preview)
		print("-" * 80)
		print()

		# Step 5: Test email service connection (optional)
		print("🔗 Step 5: Testing email service connection...")
		try:
			email_service_url = frappe.conf.get('email_service_url') or 'http://172.16.20.113:5030'
			print(f"   - Email service URL: {email_service_url}")

			import requests
			graphql_endpoint = f"{email_service_url}/graphql"
			graphql_query = """query { health }"""
			payload = {"query": graphql_query}

			response = requests.post(graphql_endpoint, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)

			if response.status_code == 200:
				result = response.json()
				if result.get('data', {}).get('health'):
					print("   ✅ Email service connection: OK")
					print(f"   ✅ Health check: {result['data']['health']}")
				else:
					print("   ⚠️ Email service responded but health check failed")
			else:
				print(f"   ❌ Email service HTTP error: {response.status_code}")

		except Exception as e:
			print(f"   ❌ Email service connection failed: {str(e)}")

		print()
		print("=" * 80)
		print("🎯 Test completed successfully!")
		print()
		print("💡 To send the actual email, run:")
		print(f"   frappe.call('erp.api.erp_sis.attendance.send_homeroom_attendance_report', {{'date': '{date}'}})")

		return success_response({
			"test_date": date,
			"attendance_data": attendance_data,
			"email_content_length": len(email_content),
			"email_service_url": frappe.conf.get('email_service_url') or 'http://172.16.20.113:5030'
		}, "Test completed successfully")

	except Exception as e:
		print(f"❌ Test failed with error: {str(e)}")
		import traceback
		traceback.print_exc()
		return error_response(f"Test failed: {str(e)}", code="TEST_ERROR")


# Scheduled job for daily homeroom attendance report
@frappe.whitelist()
def daily_homeroom_attendance_report():
	"""
	Daily scheduled job to send homeroom attendance report
	Called automatically every day at configured time
	"""
	try:
		# Get yesterday's date for the report
		from datetime import datetime, timedelta
		yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

		frappe.logger().info(f"🏫 Starting daily homeroom attendance report for {yesterday}")

		# Call the report endpoint
		result = send_homeroom_attendance_report(date=yesterday)

		if result.get('success'):
			frappe.logger().info("✅ Daily homeroom attendance report sent successfully")
		else:
			frappe.logger().error(f"❌ Failed to send daily homeroom attendance report: {result.get('message')}")

		return result

	except Exception as e:
		frappe.logger().error(f"❌ Error in daily_homeroom_attendance_report: {str(e)}")
		frappe.log_error(f"Daily homeroom attendance report error: {str(e)}")
		return {"success": False, "message": str(e)}
