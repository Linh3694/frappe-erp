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
	Lấy attendance 1 ngày cho nhiều student — dùng SQL trực tiếp (nhanh).
	Body JSON: {date: "YYYY-MM-DD", codes: ["WS..."]}
	"""
	try:
		# Parse params từ nhiều nguồn (backward compatible)
		if date is None:
			date = frappe.local.form_dict.get('date')
		if codes is None:
			codes = frappe.local.form_dict.get('codes')

		if (date is None or codes is None) and frappe.request.content_type and 'json' in frappe.request.content_type.lower():
			try:
				raw = frappe.request.get_data(as_text=True)
				if raw:
					body = json.loads(raw)
					date = date or body.get('date')
					codes = codes or body.get('codes')
			except Exception:
				pass

		if codes and isinstance(codes, str):
			try:
				codes = json.loads(codes)
			except Exception:
				pass

		if not date:
			return error_response(message="Date parameter is required", code="MISSING_DATE")
		if not codes or not isinstance(codes, list) or len(codes) == 0:
			return success_response(data={}, message="No codes provided")
		if len(codes) > 500:
			return error_response(message="Batch size exceeded (max 500)", code="BATCH_SIZE_EXCEEDED")

		date_obj = frappe.utils.getdate(date)

		# SQL trực tiếp — không load raw_data (nặng), dùng stored fields
		placeholders = ", ".join(["%s"] * len(codes))
		records = frappe.db.sql(f"""
			SELECT employee_code, employee_name, date,
			       check_in_time, check_out_time, total_check_ins
			FROM `tabERP Time Attendance`
			WHERE employee_code IN ({placeholders})
			  AND date = %s
		""", (*codes, date_obj), as_dict=True)

		# Case-insensitive fallback
		if not records:
			all_variants = list({c for code in codes for c in (code, code.upper(), code.lower())})
			placeholders2 = ", ".join(["%s"] * len(all_variants))
			records = frappe.db.sql(f"""
				SELECT employee_code, employee_name, date,
				       check_in_time, check_out_time, total_check_ins
				FROM `tabERP Time Attendance`
				WHERE employee_code IN ({placeholders2})
				  AND date = %s
			""", (*all_variants, date_obj), as_dict=True)

		result = {code: {"checkInTime": None, "checkOutTime": None, "totalCheckIns": 0, "employeeName": None} for code in codes}
		codes_lower_map = {code.lower(): code for code in codes}

		def _fmt_time(time_obj, rec_date):
			if not time_obj:
				return None
			return datetime.combine(rec_date, time_obj.time()).isoformat()

		for rec in records:
			matched = codes_lower_map.get(rec.employee_code.lower())
			if not matched:
				continue

			ci = rec.check_in_time
			co = rec.check_out_time
			cnt = rec.total_check_ins or 0

			# Chỉ 1 lần quẹt → chưa có giờ ra, không nên hiển thị checkOut = checkIn
			if cnt <= 1 and ci and co and ci == co:
				co = None

			result[matched] = {
				"checkInTime": _fmt_time(ci, rec.date),
				"checkOutTime": _fmt_time(co, rec.date),
				"totalCheckIns": cnt,
				"employeeName": rec.employee_name,
			}

		return success_response(
			data=result,
			message="Attendance data retrieved successfully",
			meta={"date": date, "codes_count": len(codes), "records_found": len(records)},
		)

	except Exception as e:
		frappe.log_error(message=str(e)[:140], title="Get Students Day Map Error")
		return error_response(message="Server error retrieving attendance data", code="SERVER_ERROR")


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
			# Recalculate từ raw_data chỉ khi explicitly requested
			if include_raw and rec.get("raw_data"):
				rci, rco, rcnt = _parse_raw_times(rec.raw_data)
				if rcnt > 0:
					ci, co, cnt = rci, rco, rcnt

			# Chỉ 1 lần quẹt → chưa có giờ ra
			if cnt <= 1 and ci and co and ci == co:
				co = None

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


