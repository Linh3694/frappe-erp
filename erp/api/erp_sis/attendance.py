import json
import frappe
from frappe import _
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
def get_class_attendance(class_id=None, date=None, period=None):
	"""Return attendance records for a class on a date and period.
	Params may be provided in query string or function args.
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
		return success_response(data=rows, message="Attendance fetched successfully")
	except Exception as e:
		frappe.log_error(f"get_class_attendance error: {str(e)}")
		return error_response(message="Failed to fetch attendance", code="GET_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_get_class_attendance(class_id=None, date=None, periods=None):
	"""Get attendance for multiple periods in a single request.
	
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

		frappe.logger().info(f"💾 [Backend] Saving {len(items)} attendance records")

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

		frappe.logger().info(f"🔍 [Backend] Fetching existing records for {len(student_ids)} students")
		
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

		frappe.logger().info(f"📊 [Backend] Found {len(existing_records)} existing records")

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
		frappe.logger().info(f"✅ [Backend] Saved attendance: {upserts} inserted, {updates} updated")
		return success_response(message=f"Saved attendance ({upserts} inserted, {updates} updated)")
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(f"save_class_attendance error: {str(e)}")
		return error_response(message="Failed to save attendance", code="SAVE_ATTENDANCE_ERROR")
