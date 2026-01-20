# Copyright (c) 2024, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import datetime, timedelta
import json
import pytz


class ERPTimeAttendance(Document):
	"""
	Time Attendance Document
	Handles attendance records with proper timezone handling for VN timezone (+7)
	"""
	
	def update_attendance_time(self, timestamp, device_id=None, device_name=None, original_timestamp=None):
		"""
		Update attendance time with deduplication for rapid successive events
		This prevents duplicate records when student stands in front of camera for extended time
		"""
		check_time = frappe.utils.get_datetime(timestamp)

		# Ensure check_time is timezone-naive for consistent comparisons
		if check_time.tzinfo is not None:
			try:
				import pytz
				vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
				check_time = check_time.astimezone(vn_tz).replace(tzinfo=None)
			except ImportError:
				check_time = check_time.replace(tzinfo=None)

		device_id_to_use = device_id or self.device_id
		device_name_to_use = device_name or self.device_name

		# Parse raw_data
		raw_data = json.loads(self.raw_data or "[]")

		# Check for duplicate events within time threshold (30 seconds)
		# This prevents multiple records when student stands in front of camera
		DUP_THRESHOLD_SECONDS = 30

		# Check if this timestamp is too close to existing records
		is_duplicate = False
		for item in raw_data:
			ts_str = item['timestamp']
			existing_time = frappe.utils.get_datetime(ts_str)

			# Ensure both timestamps are timezone-naive for comparison
			if existing_time.tzinfo is not None:
				try:
					import pytz
					vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
					existing_time = existing_time.astimezone(vn_tz).replace(tzinfo=None)
				except ImportError:
					existing_time = existing_time.replace(tzinfo=None)

			# Calculate time difference
			time_diff = abs((check_time - existing_time).total_seconds())
			if time_diff < DUP_THRESHOLD_SECONDS:
				is_duplicate = True
				break

		if is_duplicate:
			# Skip adding duplicate record, but still recalculate times from existing data
			pass
		else:
			# Add to raw data (no duplicate check - we want all legitimate records)
			# Use original timestamp from device to preserve accuracy
			timestamp_to_store = original_timestamp if original_timestamp else check_time.isoformat()
			raw_data.append({
				'timestamp': timestamp_to_store,
				'device_id': device_id_to_use,
				'device_name': device_name_to_use,
				'recorded_at': frappe.utils.now()
			})

		# RECALCULATE check-in and check-out from ALL raw_data
		# This ensures accuracy even when records arrive out of order
		if len(raw_data) == 1:
			# First record
			self.check_in_time = check_time
			self.check_out_time = check_time
			self.total_check_ins = 1
		else:
			# Multiple records: parse timestamps correctly (they may be original device timestamps)
			all_times = []
			for item in raw_data:
				ts_str = item['timestamp']
				# If timestamp has timezone info, parse as device timestamp
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
			self.check_in_time = all_times[0]  # Earliest = check-in
			self.check_out_time = all_times[-1]  # Latest = check-out
			self.total_check_ins = len(raw_data)

		# Update device info if provided
		if device_id_to_use and not self.device_id:
			self.device_id = device_id_to_use
		if device_name_to_use and not self.device_name:
			self.device_name = device_name_to_use

		# Save raw data
		self.raw_data = json.dumps(raw_data)

		return self
	
	def recalculate_times(self):
		"""Recalculate check-in/check-out times from raw_data"""
		raw_data = json.loads(self.raw_data or "[]")
		
		if not raw_data:
			return self
		
		if len(raw_data) == 1:
			time = frappe.utils.get_datetime(raw_data[0]['timestamp'])
			self.check_in_time = time
			self.check_out_time = time
			self.total_check_ins = 1
		else:
			all_times = [frappe.utils.get_datetime(item['timestamp']) for item in raw_data]
			all_times.sort()
			
			self.check_in_time = all_times[0]
			self.check_out_time = all_times[-1]
			self.total_check_ins = len(raw_data)
		
		return self


def normalize_date_to_vn_timezone(timestamp):
	"""
	Normalize timestamp to VN timezone date (start of day)
	Updated logic: check_in_time stored in DB is already VN time

	Example:
	- Input: 2025-11-24 17:02:29 (stored as VN time, naive datetime)
	- Return: 2025-11-24 (correct VN date)
	"""
	vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')

	if isinstance(timestamp, str):
		dt = frappe.utils.get_datetime(timestamp)
	else:
		dt = timestamp

	# CRITICAL FIX: check_in_time in DB is already VN time (naive datetime)
	# Just return its date directly, no timezone conversion needed
	if dt.tzinfo is None:
		return dt.date()

	# If has timezone info, convert to VN date (for future compatibility)
	vn_time = dt.astimezone(vn_tz)
	return vn_time.date()


@frappe.whitelist()
def find_or_create_day_record(employee_code, date, device_id=None, employee_name=None, device_name=None):
	"""
	Find or create attendance record for a specific day
	Date is normalized to VN timezone to match microservice behavior
	"""
	# Normalize date to VN timezone
	if isinstance(date, str):
		# Could be date string or datetime string
		try:
			date_obj = frappe.utils.get_datetime(date)
			date_only = normalize_date_to_vn_timezone(date_obj)
		except:
			# Already a date string YYYY-MM-DD
			date_only = frappe.utils.getdate(date)
	else:
		date_only = normalize_date_to_vn_timezone(date)
	
	# Find existing record
	existing = frappe.db.get_value("ERP Time Attendance", {
		"employee_code": employee_code,
		"date": date_only
	}, "name")
	
	if existing:
		doc = frappe.get_doc("ERP Time Attendance", existing)
		# Update employee_name and device_name if provided and not set
		if employee_name and not doc.employee_name:
			doc.employee_name = employee_name
		if device_name and not doc.device_name:
			doc.device_name = device_name
		return doc
	
	# Create new record
	doc = frappe.new_doc("ERP Time Attendance")
	doc.employee_code = employee_code
	doc.employee_name = employee_name
	doc.date = date_only
	doc.device_id = device_id
	doc.device_name = device_name
	doc.raw_data = "[]"
	doc.save(ignore_permissions=True)
	
	return doc


@frappe.whitelist()
def get_attendance_stats(start_date=None, end_date=None, employee_code=None):
	"""Get attendance statistics"""
	filters = {}
	
	if start_date and end_date:
		filters["date"] = ["between", [start_date, end_date]]
	
	if employee_code:
		filters["employee_code"] = employee_code
	
	records = frappe.get_all("ERP Time Attendance", 
		filters=filters,
		fields=["employee_code", "date", "total_check_ins", "check_in_time", "check_out_time"]
	)
	
	return records


# ============================================================================
# BATCH OPERATIONS - Performance optimization cho xử lý hàng loạt
# ============================================================================

def batch_find_or_create_records(employee_date_list):
	"""
	Batch find or create attendance records cho nhiều employee-date combinations.
	Giảm số lượng queries từ N xuống còn 2 (1 query tìm existing + 1 bulk insert).
	
	Args:
		employee_date_list: List of tuples [(employee_code, date, employee_name, device_id, device_name), ...]
	
	Returns:
		Dict: {(employee_code, date_str): ERPTimeAttendance doc}
	"""
	if not employee_date_list:
		return {}
	
	result = {}
	
	# Normalize dates và build lookup keys
	normalized_list = []
	for item in employee_date_list:
		employee_code = item[0]
		date = item[1]
		employee_name = item[2] if len(item) > 2 else None
		device_id = item[3] if len(item) > 3 else None
		device_name = item[4] if len(item) > 4 else None
		
		# Normalize date
		if isinstance(date, str):
			try:
				date_obj = frappe.utils.get_datetime(date)
				date_only = normalize_date_to_vn_timezone(date_obj)
			except:
				date_only = frappe.utils.getdate(date)
		else:
			date_only = normalize_date_to_vn_timezone(date)
		
		normalized_list.append({
			"employee_code": employee_code,
			"date": date_only,
			"date_str": str(date_only),
			"employee_name": employee_name,
			"device_id": device_id,
			"device_name": device_name
		})
	
	# Build list of employee_codes và dates để query
	employee_codes = list(set([item["employee_code"] for item in normalized_list]))
	dates = list(set([item["date"] for item in normalized_list]))
	
	# Batch query existing records
	existing_records = frappe.get_all(
		"ERP Time Attendance",
		filters={
			"employee_code": ["in", employee_codes],
			"date": ["in", dates]
		},
		fields=["name", "employee_code", "date"]
	)
	
	# Build lookup map: (employee_code, date_str) -> name
	existing_map = {}
	for rec in existing_records:
		key = (rec.employee_code, str(rec.date))
		existing_map[key] = rec.name
	
	# Process each item
	to_create = []
	
	for item in normalized_list:
		key = (item["employee_code"], item["date_str"])
		
		if key in existing_map:
			# Existing record - load it
			doc = frappe.get_doc("ERP Time Attendance", existing_map[key])
			
			# Update employee_name and device_name if provided and not set
			if item["employee_name"] and not doc.employee_name:
				doc.employee_name = item["employee_name"]
			if item["device_name"] and not doc.device_name:
				doc.device_name = item["device_name"]
			
			result[key] = doc
		else:
			# Need to create
			to_create.append(item)
	
	# Bulk create new records
	for item in to_create:
		key = (item["employee_code"], item["date_str"])
		
		doc = frappe.new_doc("ERP Time Attendance")
		doc.employee_code = item["employee_code"]
		doc.employee_name = item["employee_name"]
		doc.date = item["date"]
		doc.device_id = item["device_id"]
		doc.device_name = item["device_name"]
		doc.raw_data = "[]"
		doc.save(ignore_permissions=True)
		
		result[key] = doc
	
	return result


def batch_update_attendance_times(records_data):
	"""
	Batch update attendance times cho nhiều records.
	
	Args:
		records_data: List of dicts:
			[{
				"doc": ERPTimeAttendance doc,
				"events": [{timestamp, device_id, device_name, original_timestamp}, ...]
			}, ...]
	
	Returns:
		List of updated docs
	"""
	updated_docs = []
	
	for record_data in records_data:
		doc = record_data.get("doc")
		events = record_data.get("events", [])
		
		if not doc or not events:
			continue
		
		# Sort events by timestamp
		sorted_events = sorted(events, key=lambda x: frappe.utils.get_datetime(x.get("timestamp")))
		
		# Update với tất cả events
		for evt in sorted_events:
			doc.update_attendance_time(
				evt.get("timestamp"),
				evt.get("device_id"),
				evt.get("device_name"),
				original_timestamp=evt.get("original_timestamp")
			)
		
		# Save (không commit - caller sẽ commit batch)
		doc.save(ignore_permissions=True)
		updated_docs.append(doc)
	
	return updated_docs


def get_existing_records_map(employee_codes, dates):
	"""
	Lấy map của existing records cho batch lookup.
	
	Args:
		employee_codes: List of employee codes
		dates: List of dates
	
	Returns:
		Dict: {(employee_code, date_str): record_name}
	"""
	if not employee_codes or not dates:
		return {}
	
	# Convert dates to strings for consistent lookup
	date_strs = [str(d) if not isinstance(d, str) else d for d in dates]
	
	existing_records = frappe.get_all(
		"ERP Time Attendance",
		filters={
			"employee_code": ["in", employee_codes],
			"date": ["in", date_strs]
		},
		fields=["name", "employee_code", "date"]
	)
	
	result = {}
	for rec in existing_records:
		key = (rec.employee_code, str(rec.date))
		result[key] = rec.name
	
	return result