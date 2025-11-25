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
	
	def update_attendance_time(self, timestamp, device_id=None, device_name=None):
		"""
		Update attendance time - recalculate from ALL raw_data for accuracy
		This matches the logic from MongoDB microservice
		"""
		check_time = frappe.utils.get_datetime(timestamp)
		device_id_to_use = device_id or self.device_id
		device_name_to_use = device_name or self.device_name
		
		# Parse raw_data
		raw_data = json.loads(self.raw_data or "[]")
		
		# Add to raw data (no duplicate check - we want all records)
		raw_data.append({
			'timestamp': check_time.isoformat(),
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
			# Multiple records: get earliest and latest
			all_times = [frappe.utils.get_datetime(item['timestamp']) for item in raw_data]
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