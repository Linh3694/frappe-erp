# Copyright (c) 2024, Your Organization and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import datetime
import json


class ERPTimeAttendance(Document):
	def before_insert(self):
		# Tự động set thông tin audit khi tạo mới
		if hasattr(self, 'create_at'):
			self.create_at = frappe.utils.now()
		if hasattr(self, 'create_date'):
			self.create_date = frappe.utils.now()
		if hasattr(self, 'submitted_at') and not self.submitted_at:
			self.submitted_at = frappe.utils.now()
	
	def before_save(self):
		# Tự động set thông tin audit khi cập nhật
		if hasattr(self, 'update_at'):
			self.update_at = frappe.utils.now()
		if hasattr(self, 'update_by'):
			self.update_by = frappe.session.user
		if hasattr(self, 'last_update'):
			self.last_update = frappe.utils.now()
		if hasattr(self, 'last_updated'):
			self.last_updated = frappe.utils.now()
	
	def update_attendance_time(self, timestamp, device_id=None):
		"""Update attendance time with smart check-in/check-out logic"""
		check_time = frappe.utils.get_datetime(timestamp)
		device_id_to_use = device_id or self.device_id
		
		# Parse raw_data
		raw_data = json.loads(self.raw_data or "[]")
		
		# Check for duplicates within 30 seconds
		for item in raw_data:
			existing_time = frappe.utils.get_datetime(item.get('timestamp'))
			time_diff = abs((check_time - existing_time).total_seconds())
			same_device = item.get('device_id') == device_id_to_use
			
			if time_diff < 30 and same_device:
				frappe.log_error("Duplicate attendance detected within 30 seconds, skipping")
				return self
		
		# Add to raw data
		raw_data.append({
			'timestamp': check_time.isoformat(),
			'device_id': device_id_to_use,
			'recorded_at': frappe.utils.now()
		})
		
		# Update check-in/check-out times
		self._update_check_in_out_times(check_time)
		
		# Save raw data
		self.raw_data = json.dumps(raw_data)
		self.total_check_ins = len(raw_data)
		
		return self
	
	def _update_check_in_out_times(self, new_time):
		"""Smart logic to determine check-in vs check-out"""
		current_hour = new_time.hour
		
		# Logic based on time
		is_likely_check_in = 6 <= current_hour <= 12  # 6h-12h: check-in
		is_likely_check_out = 15 <= current_hour <= 22  # 15h-22h: check-out
		
		# If no check-in or new time is very early
		if not self.check_in_time or (is_likely_check_in and new_time < frappe.utils.get_datetime(self.check_in_time)):
			self.check_in_time = new_time
		# If no check-out or new time is very late
		elif not self.check_out_time or (is_likely_check_out and new_time > frappe.utils.get_datetime(self.check_out_time)):
			self.check_out_time = new_time
		# If both exist, update based on proximity
		elif self.check_in_time and self.check_out_time:
			check_in_time = frappe.utils.get_datetime(self.check_in_time)
			check_out_time = frappe.utils.get_datetime(self.check_out_time)
			
			distance_to_check_in = abs((new_time - check_in_time).total_seconds())
			distance_to_check_out = abs((new_time - check_out_time).total_seconds())
			
			if is_likely_check_in and distance_to_check_in < distance_to_check_out:
				self.check_in_time = new_time
			elif is_likely_check_out and distance_to_check_out < distance_to_check_in:
				self.check_out_time = new_time
		# Fallback: if only check-in exists
		elif self.check_in_time and not self.check_out_time:
			if new_time > frappe.utils.get_datetime(self.check_in_time):
				self.check_out_time = new_time
			else:
				self.check_in_time = new_time
		
		# Ensure check-in is always before check-out
		if self.check_in_time and self.check_out_time:
			check_in_time = frappe.utils.get_datetime(self.check_in_time)
			check_out_time = frappe.utils.get_datetime(self.check_out_time)
			if check_in_time > check_out_time:
				self.check_in_time, self.check_out_time = self.check_out_time, self.check_in_time


@frappe.whitelist()
def find_or_create_day_record(employee_code, date, device_id=None):
	"""Find or create attendance record for a specific day"""
	# Normalize date to start of day
	date_obj = frappe.utils.get_datetime(date).date()
	
	# Find existing record
	existing = frappe.db.get_value("ERP Time Attendance", {
		"employee_code": employee_code,
		"date": date_obj
	}, "name")
	
	if existing:
		return frappe.get_doc("ERP Time Attendance", existing)
	
	# Create new record
	doc = frappe.new_doc("ERP Time Attendance")
	doc.employee_code = employee_code
	doc.date = date_obj
	doc.device_id = device_id
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