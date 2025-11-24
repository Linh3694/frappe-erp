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


@frappe.whitelist(methods=["POST"])
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
		# Parse codes if it's a JSON string
		if codes and isinstance(codes, str):
			try:
				codes = json.loads(codes)
			except:
				pass
		
		# Validate inputs
		if not date:
			return {
				"status": "error",
				"message": "Date parameter is required (YYYY-MM-DD format)"
			}
		
		if not codes or not isinstance(codes, list):
			return {
				"status": "error",
				"message": "Codes parameter is required (array of student codes)"
			}
		
		if len(codes) == 0:
			return {
				"status": "success",
				"data": {},
				"timestamp": frappe.utils.now()
			}
		
		# Limit batch size
		MAX_BATCH = 500
		if len(codes) > MAX_BATCH:
			return {
				"status": "error",
				"message": f"Number of codes exceeds maximum limit of {MAX_BATCH}"
			}
		
		frappe.logger().info(f"📥 [Attendance Batch] /students/day request: date={date}, codes_count={len(codes)}")
		
		# Parse and normalize date to VN timezone
		try:
			date_obj = frappe.utils.getdate(date)
		except:
			return {
				"status": "error",
				"message": f"Invalid date format: {date}. Expected YYYY-MM-DD"
			}
		
		# Query attendance records
		records = frappe.get_all(
			"ERP Time Attendance",
			filters={
				"employee_code": ["in", codes],
				"date": date_obj
			},
			fields=["employee_code", "check_in_time", "check_out_time", "total_check_ins", "employee_name", "raw_data"]
		)
		
		frappe.logger().info(f"📊 [Attendance Batch] Found {len(records)} records for {len(codes)} codes")
		
		# Initialize result map with null values for all codes
		result = {}
		for code in codes:
			result[code] = {
				"checkInTime": None,
				"checkOutTime": None,
				"totalCheckIns": 0,
				"employeeName": None
			}
		
		# Fill in data from found records
		for rec in records:
			# Recalculate from raw_data for accuracy
			check_in_time = rec.check_in_time
			check_out_time = rec.check_out_time
			total_check_ins = rec.total_check_ins or 0
			
			# Recalculate from raw_data if available
			if rec.raw_data:
				try:
					raw_data = json.loads(rec.raw_data) if isinstance(rec.raw_data, str) else rec.raw_data
					if raw_data and len(raw_data) > 0:
						all_times = sorted([frappe.utils.get_datetime(item['timestamp']) for item in raw_data])
						check_in_time = all_times[0]
						check_out_time = all_times[-1]
						total_check_ins = len(all_times)
				except Exception as e:
					frappe.logger().warning(f"Failed to parse raw_data for {rec.employee_code}: {str(e)}")
			
			result[rec.employee_code] = {
				"checkInTime": check_in_time.isoformat() if check_in_time else None,
				"checkOutTime": check_out_time.isoformat() if check_out_time else None,
				"totalCheckIns": total_check_ins,
				"employeeName": rec.employee_name
			}
		
		frappe.logger().info(f"📤 [Attendance Batch] Responding with {len(result)} results")
		
		return {
			"status": "success",
			"data": result,
			"date": date,
			"timestamp": frappe.utils.now()
		}
		
	except Exception as e:
		frappe.logger().error(f"❌ Error in get_students_day_map: {str(e)}")
		frappe.log_error(message=str(e), title="Get Students Day Map Error")
		return {
			"status": "error",
			"message": "Server error retrieving attendance data",
			"error": str(e)
		}


@frappe.whitelist(methods=["GET"])
def get_employee_attendance_range(employee_code, start_date=None, end_date=None, include_raw_data="false", page=1, limit=100):
	"""
	Get attendance records for an employee over a date range
	Used by Parent Portal attendance page to show monthly attendance
	
	Endpoint: /api/method/erp.api.attendance.query.get_employee_attendance_range
	
	Args:
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
		if not employee_code:
			return {
				"status": "error",
				"message": "employee_code is required"
			}
		
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
					return {
						"status": "error",
						"message": f"Invalid start_date format: {start_date}"
					}
			
			if end_date:
				try:
					end_date_obj = frappe.utils.getdate(end_date)
					# Add 1 day to include the end date
					end_date_inclusive = end_date_obj + timedelta(days=1)
					date_filter["<"] = end_date_inclusive
				except:
					return {
						"status": "error",
						"message": f"Invalid end_date format: {end_date}"
					}
			
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
		
		# Format records
		formatted_records = []
		for rec in records:
			# Recalculate check-in/check-out from raw_data for accuracy
			check_in_time = rec.check_in_time
			check_out_time = rec.check_out_time
			total_check_ins = rec.total_check_ins or 0
			
			# Get raw_data if needed for recalculation
			if include_raw_data.lower() == "true" and rec.get("raw_data"):
				try:
					raw_data = json.loads(rec.raw_data) if isinstance(rec.raw_data, str) else rec.raw_data
					if raw_data and len(raw_data) > 0:
						all_times = sorted([frappe.utils.get_datetime(item['timestamp']) for item in raw_data])
						check_in_time = all_times[0]
						check_out_time = all_times[-1]
						total_check_ins = len(all_times)
				except Exception as e:
					frappe.logger().warning(f"Failed to parse raw_data for record {rec.name}: {str(e)}")
			
			# Format date as YYYY-MM-DD string
			date_str = rec.date.strftime('%Y-%m-%d') if rec.date else None
			
			formatted_rec = {
				"_id": rec.name,
				"employeeCode": rec.employee_code,
				"date": date_str,
				"checkInTime": check_in_time.isoformat() if check_in_time else None,
				"checkOutTime": check_out_time.isoformat() if check_out_time else None,
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
		
		return {
			"status": "success",
			"data": {
				"records": formatted_records,
				"pagination": {
					"currentPage": page_num,
					"totalPages": total_pages,
					"totalRecords": total_records,
					"hasMore": has_more
				}
			},
			"timestamp": frappe.utils.now()
		}
		
	except Exception as e:
		frappe.logger().error(f"❌ Error retrieving employee attendance: {str(e)}")
		frappe.log_error(message=str(e), title="Get Employee Attendance Range Error")
		return {
			"status": "error",
			"message": "Server error retrieving attendance data",
			"error": str(e),
			"timestamp": frappe.utils.now()
		}


@frappe.whitelist(methods=["GET"])
def debug_employee_attendance(employee_code, date):
	"""
	Debug endpoint to show all raw timestamps for an employee on a specific date
	Helpful for troubleshooting attendance issues
	
	Endpoint: /api/method/erp.api.attendance.query.debug_employee_attendance
	"""
	try:
		if not employee_code or not date:
			return {
				"status": "error",
				"message": "employee_code and date are required"
			}
		
		date_obj = frappe.utils.getdate(date)
		
		# Get attendance record
		record = frappe.get_all(
			"ERP Time Attendance",
			filters={
				"employee_code": employee_code,
				"date": date_obj
			},
			fields=["name", "employee_code", "employee_name", "date", "check_in_time", "check_out_time", "total_check_ins", "raw_data"],
			limit=1
		)
		
		if not record:
			return {
				"status": "error",
				"message": "No attendance record found for this date"
			}
		
		rec = record[0]
		
		# Parse raw_data
		raw_data = json.loads(rec.raw_data) if isinstance(rec.raw_data, str) else rec.raw_data
		
		# Sort and format timestamps
		all_timestamps = []
		if raw_data:
			for item in raw_data:
				timestamp = frappe.utils.get_datetime(item['timestamp'])
				vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
				if timestamp.tzinfo is None:
					timestamp = pytz.UTC.localize(timestamp)
				vn_time = timestamp.astimezone(vn_tz)
				
				all_timestamps.append({
					"timestamp": item['timestamp'],
					"deviceId": item.get('device_id'),
					"deviceName": item.get('device_name'),
					"recordedAt": item.get('recorded_at'),
					"vnTime": vn_time.strftime('%Y-%m-%d %H:%M:%S')
				})
		
		all_timestamps.sort(key=lambda x: x['timestamp'])
		
		# Calculate summary
		check_in = all_timestamps[0] if all_timestamps else None
		check_out = all_timestamps[-1] if all_timestamps else None
		
		return {
			"status": "success",
			"employeeCode": employee_code,
			"date": str(date_obj),
			"summary": {
				"totalCheckIns": len(all_timestamps),
				"checkInTime": {
					"utc": rec.check_in_time.isoformat() if rec.check_in_time else None,
					"vnTime": check_in['vnTime'] if check_in else None
				},
				"checkOutTime": {
					"utc": rec.check_out_time.isoformat() if rec.check_out_time else None,
					"vnTime": check_out['vnTime'] if check_out else None
				},
				"storedCheckIn": rec.check_in_time.isoformat() if rec.check_in_time else None,
				"storedCheckOut": rec.check_out_time.isoformat() if rec.check_out_time else None
			},
			"allTimestamps": all_timestamps,
			"duplicateAnalysis": {
				"uniqueTimestamps": len(set([t['timestamp'] for t in all_timestamps])),
				"hasDuplicates": len(all_timestamps) > len(set([t['timestamp'] for t in all_timestamps]))
			}
		}
		
	except Exception as e:
		frappe.logger().error(f"Debug endpoint error: {str(e)}")
		return {
			"status": "error",
			"message": "Failed to debug attendance data",
			"error": str(e)
		}

