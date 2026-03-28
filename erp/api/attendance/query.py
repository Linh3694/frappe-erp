"""
Attendance Query API
Provides attendance data query endpoints for Parent Portal and other clients
"""

import frappe
from frappe import _
import json
from datetime import datetime, timedelta
import pytz
from erp.common.doctype.erp_time_attendance.erp_time_attendance import normalize_date_to_vn_timezone
from erp.utils.api_response import success_response, error_response


@frappe.whitelist(methods=["POST"], allow_guest=False)
def get_students_day_map(date=None, codes=None):
	"""
	Get attendance data for multiple students on a specific date
	Used by Parent Portal dashboard for quick check-in/check-out display
	
	Endpoint: /api/method/erp.api.attendance.query.get_students_day_map
	
	Args:
		date (str): Date in YYYY-MM-DD format
		codes (list): List of student codes (can be JSON string or list)
	
	Returns:
		dict: {
			status: "success",
			data: {
				code1: {checkInTime, checkOutTime, totalCheckIns, employeeName},
				code2: {...},
				...
			},
			date: original date string,
			timestamp: current timestamp
		}
	"""
	try:
		# Debug: Log raw request data
		frappe.logger().info(f"📥 [get_students_day_map] Raw params - date: {date}, codes: {codes}")
		frappe.logger().info(f"📥 [get_students_day_map] form_dict: {frappe.local.form_dict}")
		frappe.logger().info(f"📥 [get_students_day_map] request.method: {frappe.request.method}")
		frappe.logger().info(f"📥 [get_students_day_map] request.content_type: {frappe.request.content_type}")
		
		# If parameters are None, try multiple methods to get data
		if date is None or codes is None:
			# Method 1: Try form_dict
			if date is None:
				date = frappe.local.form_dict.get('date')
			if codes is None:
				codes = frappe.local.form_dict.get('codes')
			
			# Method 2: If still None, try to parse JSON body directly
			if (date is None or codes is None) and frappe.request.content_type and 'json' in frappe.request.content_type.lower():
				try:
					raw_data = frappe.request.get_data(as_text=True)
					frappe.logger().info(f"📥 [get_students_day_map] Raw JSON body: {raw_data[:200]}")
					if raw_data:
						json_data = json.loads(raw_data)
						if date is None:
							date = json_data.get('date')
						if codes is None:
							codes = json_data.get('codes')
						frappe.logger().info(f"📥 [get_students_day_map] Parsed from JSON body - date: {date}, codes length: {len(codes) if isinstance(codes, list) else 'N/A'}")
				except Exception as e:
					frappe.logger().warning(f"⚠️ [get_students_day_map] Failed to parse JSON body: {str(e)}")
		
		frappe.logger().info(f"📥 [get_students_day_map] Final values - date: {date}, codes type: {type(codes)}, codes: {codes if isinstance(codes, list) else str(codes)[:100]}")
		
		# Parse codes if it's a JSON string
		if codes and isinstance(codes, str):
			try:
				codes = json.loads(codes)
				frappe.logger().info(f"📥 [get_students_day_map] Parsed codes from JSON string - length: {len(codes)}")
			except Exception as e:
				frappe.logger().warning(f"⚠️ [get_students_day_map] Failed to parse codes: {str(e)}")
				pass
		
		# Validate inputs
		if not date:
			return error_response(
				message="Date parameter is required (YYYY-MM-DD format)",
				code="MISSING_DATE"
			)
		
		if not codes or not isinstance(codes, list):
			return error_response(
				message="Codes parameter is required (array of student codes)",
				code="MISSING_CODES"
			)
		
		if len(codes) == 0:
			return success_response(
				data={},
				message="No codes provided",
				meta={"date": date, "timestamp": frappe.utils.now()}
			)
		
		# Limit batch size
		MAX_BATCH = 500
		if len(codes) > MAX_BATCH:
			return error_response(
				message=f"Number of codes exceeds maximum limit of {MAX_BATCH}",
				code="BATCH_SIZE_EXCEEDED"
			)
		
		frappe.logger().info(f"📥 [Attendance Batch] /students/day request: date={date}, codes_count={len(codes)}")
		
		# Parse and normalize date to VN timezone
		try:
			date_obj = frappe.utils.getdate(date)
		except Exception as e:
			return error_response(
				message=f"Invalid date format: {date}. Expected YYYY-MM-DD",
				code="INVALID_DATE_FORMAT"
			)
		
		# Query attendance records
		# Note: Frappe DB queries are case-sensitive by default
		# We need to query with all possible case variations or use SQL LOWER()
		
		# Use exact date match to avoid timezone/date range issues
		filters = {
			"employee_code": ["in", codes],
			"date": date_obj  # Exact date match
		}
		
		frappe.logger().info(f"📊 [get_students_day_map] Query filters: {filters}")
		frappe.logger().info(f"📊 [get_students_day_map] date_obj: {date_obj} (type: {type(date_obj)})")
		frappe.logger().info(f"📊 [get_students_day_map] Exact date match: {date_obj}")
		frappe.logger().info(f"📊 [get_students_day_map] Requesting codes: {codes}")
		
		records = frappe.get_all(
			"ERP Time Attendance",
			filters=filters,
			fields=["employee_code", "check_in_time", "check_out_time", "total_check_ins", "employee_name", "raw_data", "date"]
		)
		
		frappe.logger().info(f"📊 [Attendance Batch] Found {len(records)} records for {len(codes)} codes")
		
		# Log first record for debugging
		if len(records) > 0:
			frappe.logger().info(f"📊 [get_students_day_map] First record: {records[0]}")
		else:
			# Try to find ANY record for these codes to see what dates exist
			all_records = frappe.get_all(
				"ERP Time Attendance",
				filters={"employee_code": ["in", codes]},
				fields=["employee_code", "date"],
				order_by="date DESC",
				limit=5
			)
			frappe.logger().info(f"📊 [get_students_day_map] Recent records for these codes: {all_records}")
		
		# If no records found with exact case, try case-insensitive search
		if len(records) == 0 and len(codes) > 0:
			frappe.logger().info(f"📊 [Attendance Batch] No records with exact case, trying case-insensitive search")
			# Use SQL for case-insensitive search
			codes_upper = [c.upper() for c in codes]
			codes_lower = [c.lower() for c in codes]
			all_variants = list(set(codes + codes_upper + codes_lower))
			
			records = frappe.get_all(
				"ERP Time Attendance",
				filters={
					"employee_code": ["in", all_variants],
					"date": date_obj
				},
				fields=["employee_code", "check_in_time", "check_out_time", "total_check_ins", "employee_name", "raw_data"]
			)
			frappe.logger().info(f"📊 [Attendance Batch] Case-insensitive search found {len(records)} records")
		
		# Initialize result map with null values for all codes
		# Keep original case for keys to match frontend expectations
		result = {}
		for code in codes:
			result[code] = {
				"checkInTime": None,
				"checkOutTime": None,
				"totalCheckIns": 0,
				"employeeName": None
			}
		
		# Create a case-insensitive lookup map for matching
		codes_lower_map = {code.lower(): code for code in codes}
		
		frappe.logger().info(f"📥 [get_students_day_map] codes_lower_map: {codes_lower_map}")
		
		# Fill in data from found records
		for rec in records:
			# Try to match employee_code case-insensitively
			employee_code_from_db = rec.employee_code
			matched_code = codes_lower_map.get(employee_code_from_db.lower())
			
			if not matched_code:
				# If no match, try exact match as fallback
				matched_code = employee_code_from_db if employee_code_from_db in result else None
			
			if not matched_code:
				frappe.logger().warning(f"⚠️ [get_students_day_map] No match found for DB code: {employee_code_from_db}, requested codes: {codes}")
				continue
			
			frappe.logger().info(f"📥 [get_students_day_map] Matched DB code '{employee_code_from_db}' to request code '{matched_code}'")
			
			# Continue processing with matched_code
			rec.employee_code = matched_code  # Use the matched code for consistency
			# Recalculate from raw_data for accuracy
			check_in_time = rec.check_in_time
			check_out_time = rec.check_out_time
			total_check_ins = rec.total_check_ins or 0
			
			# Recalculate from raw_data if available
			if rec.raw_data:
				try:
					raw_data = json.loads(rec.raw_data) if isinstance(rec.raw_data, str) else rec.raw_data
					if raw_data and len(raw_data) > 0:
						# Parse timestamps from raw_data (may be original device timestamps or processed VN times)
						all_times = []
						for item in raw_data:
							ts_str = item['timestamp']
							# If timestamp has timezone info (original device format), parse correctly
							if '+' in ts_str or ts_str.endswith('Z'):
								parsed_ts = frappe.utils.get_datetime(ts_str)
								if parsed_ts.tzinfo is not None:
									try:
										import pytz
										vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
										parsed_ts = parsed_ts.astimezone(vn_tz)
									except ImportError:
										pass
								all_times.append(parsed_ts.replace(tzinfo=None) if parsed_ts.tzinfo else parsed_ts)
							else:
								# Legacy format - already processed VN time
								all_times.append(frappe.utils.get_datetime(ts_str))

						all_times.sort()
						check_in_time = all_times[0]
						check_out_time = all_times[-1]
						total_check_ins = len(all_times)
				except Exception as e:
					frappe.logger().warning(f"Failed to parse raw_data for {rec.employee_code}: {str(e)}")
			
			# Format times using record date, not datetime date
			def format_time_with_record_date(time_obj, record_date):
				if not time_obj:
					return None
				# Create datetime with record date but time from time_obj
				correct_dt = datetime.combine(record_date, time_obj.time())
				return correct_dt.isoformat()

			result[rec.employee_code] = {
				"checkInTime": format_time_with_record_date(check_in_time, rec.date),
				"checkOutTime": format_time_with_record_date(check_out_time, rec.date),
				"totalCheckIns": total_check_ins,
				"employeeName": rec.employee_name
			}
		
		frappe.logger().info(f"📤 [Attendance Batch] Responding with {len(result)} results")
		
		# Use response utility for consistent format
		return success_response(
			data=result,
			message="Attendance data retrieved successfully",
			meta={
				"date": date,
				"codes_count": len(codes),
				"records_found": len(records),
				"timestamp": frappe.utils.now()
			}
		)
		
	except Exception as e:
		frappe.logger().error(f"❌ Error in get_students_day_map: {str(e)}")
		frappe.log_error(message=str(e), title="Get Students Day Map Error")
		return error_response(
			message="Server error retrieving attendance data",
			code="SERVER_ERROR",
			debug_info={"error": str(e)}
		)


@frappe.whitelist(methods=["GET"], allow_guest=False)
def get_employee_attendance_range(**kwargs):
	"""
	Lấy attendance records theo khoảng ngày — dùng SQL trực tiếp (nhanh).
	Quyền truy cập đã được xác thực qua Frappe session (allow_guest=False).
	"""
	try:
		employee_code = (
			kwargs.get('employee_code')
			or frappe.local.form_dict.get('employee_code')
			or frappe.request.args.get('employee_code')
		)
		start_date = (
			kwargs.get('start_date')
			or frappe.local.form_dict.get('start_date')
			or frappe.request.args.get('start_date')
		)
		end_date = (
			kwargs.get('end_date')
			or frappe.local.form_dict.get('end_date')
			or frappe.request.args.get('end_date')
		)
		include_raw_str = (
			kwargs.get('include_raw_data')
			or frappe.local.form_dict.get('include_raw_data')
			or frappe.request.args.get('include_raw_data')
			or 'false'
		)
		include_raw = include_raw_str.lower() == 'true'

		limit_param = (
			kwargs.get('limit')
			or frappe.local.form_dict.get('limit')
			or frappe.request.args.get('limit')
		)
		limit_num = max(1, min(int(limit_param) if limit_param else 100, 500))

		if not employee_code:
			return error_response(message="employee_code is required", code="MISSING_EMPLOYEE_CODE")

		# Validate dates
		try:
			start_date_obj = frappe.utils.getdate(start_date) if start_date else None
			end_date_obj = frappe.utils.getdate(end_date) if end_date else None
		except Exception:
			return error_response(message="Invalid date format", code="INVALID_DATE")

		# SQL trực tiếp — bypass permission check (session đã xác thực)
		raw_field = ", raw_data" if include_raw else ""
		conditions = ["employee_code = %(employee_code)s"]
		params = {"employee_code": employee_code, "limit": limit_num}

		if start_date_obj:
			conditions.append("date >= %(start_date)s")
			params["start_date"] = start_date_obj
		if end_date_obj:
			conditions.append("date <= %(end_date)s")
			params["end_date"] = end_date_obj

		where = " AND ".join(conditions)

		records = frappe.db.sql(f"""
			SELECT name, employee_code, employee_name, date,
			       check_in_time, check_out_time, total_check_ins, status
			       {raw_field}
			FROM `tabERP Time Attendance`
			WHERE {where}
			ORDER BY date DESC
			LIMIT %(limit)s
		""", params, as_dict=True)

		vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

		def _parse_raw_times(raw_str):
			"""Parse raw_data → (check_in, check_out, count). Trả None nếu lỗi."""
			if not raw_str:
				return None, None, 0
			try:
				raw = json.loads(raw_str) if isinstance(raw_str, str) else raw_str
				if not raw:
					return None, None, 0
				times = []
				for item in raw:
					ts = item['timestamp']
					parsed = frappe.utils.get_datetime(ts)
					if parsed.tzinfo is not None:
						parsed = parsed.astimezone(vn_tz).replace(tzinfo=None)
					times.append(parsed)
				times.sort()
				return times[0], times[-1], len(times)
			except Exception:
				return None, None, 0

		def _fmt_time(time_obj, rec_date):
			if not time_obj:
				return None
			return datetime.combine(rec_date, time_obj.time()).isoformat()

		formatted = []
		for rec in records:
			ci, co, cnt = rec.check_in_time, rec.check_out_time, rec.total_check_ins or 0
			# Recalculate từ raw_data nếu có (chính xác hơn stored fields)
			if rec.get("raw_data"):
				rci, rco, rcnt = _parse_raw_times(rec.raw_data)
				if rcnt > 0:
					ci, co, cnt = rci, rco, rcnt

			date_str = rec.date.strftime('%Y-%m-%d') if rec.date else None
			item = {
				"_id": rec.name,
				"employeeCode": rec.employee_code,
				"date": date_str,
				"checkInTime": _fmt_time(ci, rec.date),
				"checkOutTime": _fmt_time(co, rec.date),
				"totalCheckIns": cnt,
				"status": rec.status,
			}
			if rec.employee_name:
				item["user"] = {"fullname": rec.employee_name, "employeeCode": rec.employee_code}
			if include_raw and rec.get("raw_data"):
				item["rawData"] = json.loads(rec.raw_data) if isinstance(rec.raw_data, str) else rec.raw_data
			formatted.append(item)

		return success_response(
			data={
				"records": formatted,
				"pagination": {
					"currentPage": 1,
					"totalPages": 1,
					"totalRecords": len(formatted),
					"hasMore": False,
				},
			},
			message="Attendance records retrieved successfully",
			meta={
				"employee_code": employee_code,
				"start_date": start_date,
				"end_date": end_date,
				"timestamp": frappe.utils.now(),
			},
		)

	except Exception as e:
		frappe.log_error(message=str(e)[:140], title="Get Employee Attendance Range Error")
		return error_response(
			message="Server error retrieving attendance data",
			code="SERVER_ERROR",
		)


