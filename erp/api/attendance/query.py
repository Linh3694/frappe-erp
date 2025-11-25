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
		
		# IMPORTANT FIX: Use same date comparison logic as get_employee_attendance_range
		# which works correctly. Query: date >= start_of_day AND date < start_of_next_day
		start_of_day = date_obj
		end_of_next_day = date_obj + timedelta(days=1)
		
		# Build date filter the same way as the working range API
		date_filter = {
			">=": start_of_day,
			"<": end_of_next_day
		}
		
		filters = {
			"employee_code": ["in", codes]
		}
		
		# Apply date filter separately (same as range API does it)
		if date_filter.get(">=") and date_filter.get("<"):
			filters["date"] = ["between", [date_filter[">="], date_filter["<"]]]
		
		frappe.logger().info(f"📊 [get_students_day_map] Query filters: {filters}")
		frappe.logger().info(f"📊 [get_students_day_map] date_obj: {date_obj} (type: {type(date_obj)})")
		frappe.logger().info(f"📊 [get_students_day_map] date range: {start_of_day} to < {end_of_next_day}")
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
	Get attendance records for an employee over a date range
	Used by Parent Portal attendance page to show monthly attendance
	
	Endpoint: /api/method/erp.api.attendance.query.get_employee_attendance_range
	
	Args (via query params):
		employee_code (str): Employee/student code
		start_date (str): Start date (YYYY-MM-DD), optional
		end_date (str): End date (YYYY-MM-DD), optional
		include_raw_data (str): "true" or "false", default "false"
		page (int): Page number for pagination, default 1
		limit (int): Records per page, default 100, max 500
	
	Returns:
		dict: {
			status: "success",
			data: {
				records: [...],
				pagination: {currentPage, totalPages, totalRecords, hasMore}
			},
			timestamp: current timestamp
		}
	"""
	try:
		# Debug: Log all incoming parameters from multiple sources
		frappe.logger().info(f"📥 [get_employee_attendance_range] kwargs: {kwargs}")
		frappe.logger().info(f"📥 [get_employee_attendance_range] form_dict: {frappe.local.form_dict}")
		frappe.logger().info(f"📥 [get_employee_attendance_range] request.args: {dict(frappe.request.args)}")
		frappe.logger().info(f"📥 [get_employee_attendance_range] request.values: {dict(frappe.request.values)}")
		
		# Try to get parameters from multiple sources
		# Priority: kwargs > form_dict > request.args > request.values
		employee_code = (
			kwargs.get('employee_code') or 
			frappe.local.form_dict.get('employee_code') or 
			frappe.request.args.get('employee_code') or
			frappe.request.values.get('employee_code')
		)
		
		start_date = (
			kwargs.get('start_date') or 
			frappe.local.form_dict.get('start_date') or 
			frappe.request.args.get('start_date') or
			frappe.request.values.get('start_date')
		)
		
		end_date = (
			kwargs.get('end_date') or 
			frappe.local.form_dict.get('end_date') or 
			frappe.request.args.get('end_date') or
			frappe.request.values.get('end_date')
		)
		
		include_raw_data = (
			kwargs.get('include_raw_data') or 
			frappe.local.form_dict.get('include_raw_data') or 
			frappe.request.args.get('include_raw_data') or
			frappe.request.values.get('include_raw_data') or
			'false'
		)
		
		# Parse page and limit as integers
		page_param = (
			kwargs.get('page') or 
			frappe.local.form_dict.get('page') or 
			frappe.request.args.get('page') or
			frappe.request.values.get('page')
		)
		page = int(page_param) if page_param else 1
		
		limit_param = (
			kwargs.get('limit') or 
			frappe.local.form_dict.get('limit') or 
			frappe.request.args.get('limit') or
			frappe.request.values.get('limit')
		)
		limit = int(limit_param) if limit_param else 100
		
		frappe.logger().info(f"📥 [get_employee_attendance_range] Final values - employee_code: {employee_code}, start_date: {start_date}, end_date: {end_date}, page: {page}, limit: {limit}")
		
		if not employee_code:
			return error_response(
				message="employee_code is required",
				code="MISSING_EMPLOYEE_CODE"
			)
		
		# Build filters
		filters = {"employee_code": employee_code}
		
		# Date range filters
		if start_date or end_date:
			date_filter = {}
			
			if start_date:
				try:
					start_date_obj = frappe.utils.getdate(start_date)
					date_filter[">="] = start_date_obj
				except:
					return error_response(
						message=f"Invalid start_date format: {start_date}",
						code="INVALID_START_DATE"
					)
			
			if end_date:
				try:
					end_date_obj = frappe.utils.getdate(end_date)
					# Add 1 day to include the end date
					end_date_inclusive = end_date_obj + timedelta(days=1)
					date_filter["<"] = end_date_inclusive
				except:
					return error_response(
						message=f"Invalid end_date format: {end_date}",
						code="INVALID_END_DATE"
					)
			
			if date_filter:
				filters["date"] = ["between", [date_filter.get(">="), date_filter.get("<")]] if ">=" in date_filter and "<" in date_filter else date_filter
		
		# Pagination
		page_num = max(1, int(page))
		limit_num = max(1, min(int(limit), 500))  # Max 500 records per page
		offset = (page_num - 1) * limit_num
		
		# Get total count for pagination
		total_records = frappe.db.count("ERP Time Attendance", filters=filters)
		total_pages = (total_records + limit_num - 1) // limit_num if total_records > 0 else 0
		has_more = page_num < total_pages
		
		# Query records
		fields = ["name", "employee_code", "employee_name", "date", "check_in_time", "check_out_time", "total_check_ins", "status"]
		if include_raw_data.lower() == "true":
			fields.append("raw_data")
		
		records = frappe.get_all(
			"ERP Time Attendance",
			filters=filters,
			fields=fields,
			order_by="date DESC",
			limit_start=offset,
			limit_page_length=limit_num
		)
		
		# Format records - ALWAYS recalculate from raw_data for consistency with get_students_day_map
		formatted_records = []
		for rec in records:
			# ALWAYS recalculate from raw_data for accuracy (same as get_students_day_map)
			check_in_time = rec.check_in_time
			check_out_time = rec.check_out_time
			total_check_ins = rec.total_check_ins or 0

			# ALWAYS recalculate from raw_data if available (fix inconsistency with get_students_day_map)
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
						frappe.logger().info(f"✅ Recalculated {rec.name}: {len(all_times)} events")
					else:
						frappe.logger().warning(f"⚠️ Empty raw_data for {rec.name}")
				except Exception as e:
					frappe.logger().warning(f"Failed to parse raw_data for record {rec.name}: {str(e)}")
			else:
				frappe.logger().warning(f"⚠️ No raw_data for {rec.name}")
			
			# Format date as YYYY-MM-DD string
			date_str = rec.date.strftime('%Y-%m-%d') if rec.date else None
			
			# Format times correctly for API response - use record date, not datetime date
			from erp.api.attendance.hikvision import format_vn_time

			def format_time_with_record_date(time_obj, record_date):
				if not time_obj:
					return None
				# Create datetime with record date but time from time_obj
				correct_dt = datetime.combine(record_date, time_obj.time())
				return correct_dt.isoformat()

			formatted_rec = {
				"_id": rec.name,
				"employeeCode": rec.employee_code,
				"date": date_str,
				"checkInTime": format_time_with_record_date(check_in_time, rec.date),
				"checkOutTime": format_time_with_record_date(check_out_time, rec.date),
				"totalCheckIns": total_check_ins,
				"status": rec.status
			}
			
			if rec.employee_name:
				formatted_rec["user"] = {
					"fullname": rec.employee_name,
					"employeeCode": rec.employee_code
				}
			
			if include_raw_data.lower() == "true" and rec.get("raw_data"):
				formatted_rec["rawData"] = json.loads(rec.raw_data) if isinstance(rec.raw_data, str) else rec.raw_data
			
			formatted_records.append(formatted_rec)
		
		frappe.logger().info(f"📊 Retrieved {len(formatted_records)} attendance records for employee {employee_code}")
		
		# Use response utility for consistent format
		return success_response(
			data={
				"records": formatted_records,
				"pagination": {
					"currentPage": page_num,
					"totalPages": total_pages,
					"totalRecords": total_records,
					"hasMore": has_more
				}
			},
			message="Attendance records retrieved successfully",
			meta={
				"employee_code": employee_code,
				"start_date": start_date,
				"end_date": end_date,
				"timestamp": frappe.utils.now()
			}
		)
		
	except Exception as e:
		frappe.logger().error(f"❌ Error retrieving employee attendance: {str(e)}")
		frappe.log_error(message=str(e), title="Get Employee Attendance Range Error")
		return error_response(
			message="Server error retrieving attendance data",
			code="SERVER_ERROR",
			debug_info={"error": str(e)}
		)


