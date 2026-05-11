"""
Attendance Query API
Provides attendance data query endpoints for Parent Portal and other clients
"""

import frappe
from frappe import _
import json
import time
import hashlib
from datetime import datetime, timedelta
import pytz
from erp.common.doctype.erp_time_attendance.erp_time_attendance import normalize_date_to_vn_timezone
from erp.utils.api_response import success_response, error_response


# TTL cache (giây) — chỉ cache cho ngày KHÔNG phải hôm nay (data ngày cũ bất biến)
_DAY_MAP_CACHE_TTL = 300  # 5 phút
# Ngưỡng log slow query
_SLOW_QUERY_MS = 1000
# Chunk size — IN-list quá lớn làm planner MySQL chọn sai plan
_CHUNK_SIZE = 200


def _build_cache_key(date_str: str, codes_sorted: list[str]) -> str:
	"""Build cache key từ date + codes (đã sort + lower) — hash để tránh key dài."""
	codes_blob = ",".join(codes_sorted)
	digest = hashlib.md5(f"{date_str}|{codes_blob}".encode()).hexdigest()
	return f"attendance:day_map:{date_str}:{digest}"


def _fetch_day_records(codes: list[str], date_obj) -> list[dict]:
	"""
	Fetch records từ DB, chunk nếu IN-list lớn.
	Trả về list dict đã được merge từ tất cả chunks.
	"""
	if not codes:
		return []

	all_records: list[dict] = []
	for i in range(0, len(codes), _CHUNK_SIZE):
		chunk = codes[i:i + _CHUNK_SIZE]
		placeholders = ", ".join(["%s"] * len(chunk))
		# Order quan trọng cho covering index `idx_date_emp_cover (date, employee_code, ...)`:
		# date trước → seek 1 lần, sau đó range scan các employee_code cùng ngày → KHÔNG cần row lookup.
		rows = frappe.db.sql(
			f"""
			SELECT employee_code, employee_name,
			       check_in_time, check_out_time, total_check_ins
			FROM `tabERP Time Attendance`
			WHERE date = %s
			  AND employee_code IN ({placeholders})
			""",
			(date_obj, *chunk),
			as_dict=True,
		)
		all_records.extend(rows)
	return all_records


@frappe.whitelist(methods=["POST"], allow_guest=False)
def get_students_day_map(date=None, codes=None):
	"""
	Lấy attendance 1 ngày cho nhiều student — dùng SQL trực tiếp + cache Redis.
	Body JSON: {date: "YYYY-MM-DD", codes: ["WS..."]}

	Tối ưu p95:
	- Covering index `(date, employee_code, check_in_time, check_out_time, total_check_ins)`
	- Bỏ fallback case-insensitive (collation VARCHAR mặc định đã `_ci`)
	- Cache Redis 5 phút cho ngày KHÔNG phải hôm nay (data bất biến)
	- Chunk IN-list để tránh planner MySQL chọn sai plan
	- Slow-query log (>1s)
	"""
	t_start = time.perf_counter()
	cache_hit = False
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

		# Normalize codes upfront: strip + dedupe (giữ map về form gốc client gửi)
		# Collation VARCHAR đã case-insensitive nên không cần upper/lower ở SQL.
		original_by_norm: dict[str, str] = {}
		for c in codes:
			if not isinstance(c, str):
				continue
			norm = c.strip()
			if not norm:
				continue
			# Giữ representation đầu tiên gặp (ưu tiên form client gửi)
			original_by_norm.setdefault(norm.lower(), norm)
		unique_codes = list(original_by_norm.values())

		if not unique_codes:
			return success_response(data={}, message="No valid codes provided")

		date_obj = frappe.utils.getdate(date)
		date_str = str(date_obj)
		today_str = str(frappe.utils.today())
		is_historical = date_str < today_str  # ngày cũ → cacheable

		# Try cache cho ngày cũ
		cache_key = None
		if is_historical:
			# Sort codes để cache key ổn định bất kể thứ tự client gửi
			sorted_norms = sorted(original_by_norm.keys())
			cache_key = _build_cache_key(date_str, sorted_norms)
			try:
				cached = frappe.cache().get_value(cache_key)
				if cached is not None:
					cache_hit = True
					return success_response(
						data=cached,
						message="Attendance data retrieved successfully (cache)",
						meta={
							"date": date,
							"codes_count": len(unique_codes),
							"cache": "hit",
							"elapsed_ms": int((time.perf_counter() - t_start) * 1000),
						},
					)
			except Exception:
				# Cache fail không được phá API
				pass

		# Fetch từ DB
		records = _fetch_day_records(unique_codes, date_obj)

		# Build result map — key theo form gốc client gửi
		result = {
			code: {"checkInTime": None, "checkOutTime": None, "totalCheckIns": 0, "employeeName": None}
			for code in codes  # giữ nguyên codes gốc (kể cả duplicate) cho backward-compat
		}
		# Map từ lower-code → list các form gốc client gửi (handle duplicate)
		original_codes_by_norm: dict[str, list[str]] = {}
		for c in codes:
			if isinstance(c, str) and c.strip():
				original_codes_by_norm.setdefault(c.strip().lower(), []).append(c)

		def _fmt_time(time_obj, rec_date):
			if not time_obj:
				return None
			return datetime.combine(rec_date, time_obj.time()).isoformat()

		for rec in records:
			matched_keys = original_codes_by_norm.get(rec.employee_code.lower())
			if not matched_keys:
				continue

			ci = rec.check_in_time
			co = rec.check_out_time
			cnt = rec.total_check_ins or 0

			# Chỉ 1 lần quẹt → chưa có giờ ra, không nên hiển thị checkOut = checkIn
			if cnt <= 1 and ci and co and ci == co:
				co = None

			payload = {
				"checkInTime": _fmt_time(ci, date_obj),
				"checkOutTime": _fmt_time(co, date_obj),
				"totalCheckIns": cnt,
				"employeeName": rec.employee_name,
			}
			for k in matched_keys:
				result[k] = payload

		# Cache cho ngày cũ
		if is_historical and cache_key:
			try:
				frappe.cache().set_value(cache_key, result, expires_in_sec=_DAY_MAP_CACHE_TTL)
			except Exception:
				pass

		elapsed_ms = int((time.perf_counter() - t_start) * 1000)
		if elapsed_ms > _SLOW_QUERY_MS:
			# Log slow query để Loki/Grafana track được
			frappe.logger("attendance").warning(
				f"slow_get_students_day_map elapsed_ms={elapsed_ms} "
				f"date={date_str} codes={len(unique_codes)} found={len(records)}"
			)

		return success_response(
			data=result,
			message="Attendance data retrieved successfully",
			meta={
				"date": date,
				"codes_count": len(unique_codes),
				"records_found": len(records),
				"cache": "miss" if is_historical else "skip",
				"elapsed_ms": elapsed_ms,
			},
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


