# -*- coding: utf-8 -*-
# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Scheduled tasks cho Bus Daily Trips
- extend_daily_trips_job: Tạo daily trips cho ngày tiếp theo (chạy hàng ngày)
- archive_old_trips_job: Archive trips cũ > 30 ngày (chạy hàng tuần)
"""

import frappe
from datetime import datetime, timedelta
import json


def extend_daily_trips_job():
	"""
	Scheduled job: Tạo daily trips cho ngày tiếp theo.
	Chạy mỗi ngày lúc 00:30 AM.
	"""
	frappe.logger().info("🚌 [BUS TASK] Bắt đầu extend_daily_trips_job...")
	
	try:
		from erp.api.erp_sis.bus_route import extend_daily_trips_for_all_routes
		result = extend_daily_trips_for_all_routes()
		
		if result.get('success'):
			data = result.get('data', {})
			frappe.logger().info(f"✅ [BUS TASK] Hoàn thành: Tạo {data.get('created_count', 0)} daily trips cho {data.get('target_date')}")
		else:
			frappe.logger().error(f"❌ [BUS TASK] Lỗi: {result.get('message')}")
			
	except Exception as e:
		frappe.log_error(f"[BUS TASK] extend_daily_trips_job failed: {str(e)}")
		frappe.logger().error(f"❌ [BUS TASK] Exception: {str(e)}")


def archive_old_trips_job():
	"""
	Scheduled job: Archive daily trips cũ hơn 30 ngày.
	Chạy mỗi Chủ nhật lúc 01:00 AM.
	"""
	frappe.logger().info("🗄️ [BUS TASK] Bắt đầu archive_old_trips_job...")
	
	try:
		cutoff_date = (datetime.now().date() - timedelta(days=30)).strftime('%Y-%m-%d')
		
		# Đếm trips cần archive
		trips_to_archive = frappe.db.sql("""
			SELECT name FROM `tabSIS Bus Daily Trip`
			WHERE trip_date < %s AND trip_status = 'Completed'
		""", (cutoff_date,), as_dict=True)
		
		if not trips_to_archive:
			frappe.logger().info("✅ [BUS TASK] Không có trips nào cần archive")
			return
		
		frappe.logger().info(f"📋 [BUS TASK] Sẽ archive {len(trips_to_archive)} trips trước {cutoff_date}")
		
		archived_count = 0
		student_records_archived = 0
		
		for trip_data in trips_to_archive:
			trip_name = trip_data.name
			try:
				# Lấy trip info
				trip = frappe.get_doc("SIS Bus Daily Trip", trip_name)
				
				# Lấy students của trip
				students = frappe.get_all(
					"SIS Bus Daily Trip Student",
					filters={"daily_trip_id": trip_name},
					fields=["*"]
				)
				
				# Chuyển students thành serializable format
				students_data = []
				for s in students:
					student_dict = {}
					for key, value in s.items():
						if isinstance(value, (datetime,)):
							student_dict[key] = value.isoformat()
						elif hasattr(value, '__str__'):
							student_dict[key] = str(value)
						else:
							student_dict[key] = value
					students_data.append(student_dict)
				
				# Tạo archive record
				archive_doc = frappe.get_doc({
					"doctype": "SIS Bus Daily Trip Archive",
					"original_trip_id": trip.name,
					"route_id": trip.route_id,
					"trip_date": trip.trip_date,
					"weekday": trip.weekday,
					"trip_type": trip.trip_type,
					"vehicle_id": trip.vehicle_id,
					"driver_id": trip.driver_id,
					"monitor1_id": trip.monitor1_id,
					"monitor2_id": trip.monitor2_id,
					"trip_status": trip.trip_status,
					"campus_id": trip.campus_id,
					"school_year_id": trip.school_year_id,
					"student_count": len(students),
					"students_data": json.dumps(students_data, ensure_ascii=False),
					"archived_at": datetime.now()
				})
				archive_doc.insert(ignore_permissions=True)
				
				# Xóa students của trip gốc
				frappe.db.sql("""
					DELETE FROM `tabSIS Bus Daily Trip Student`
					WHERE daily_trip_id = %s
				""", (trip_name,))
				student_records_archived += len(students)
				
				# Xóa trip gốc
				frappe.delete_doc("SIS Bus Daily Trip", trip_name, ignore_permissions=True)
				archived_count += 1
				
			except Exception as e:
				frappe.log_error(f"[BUS TASK] Error archiving trip {trip_name}: {str(e)}")
				continue
		
		frappe.db.commit()
		frappe.logger().info(f"✅ [BUS TASK] Archive hoàn thành: {archived_count} trips, {student_records_archived} student records")
		
	except Exception as e:
		frappe.log_error(f"[BUS TASK] archive_old_trips_job failed: {str(e)}")
		frappe.logger().error(f"❌ [BUS TASK] Exception: {str(e)}")
		frappe.db.rollback()


def cleanup_orphan_daily_trip_students():
	"""
	Utility: Xóa các student records mồ côi (không có daily trip tương ứng).
	Chạy thủ công khi cần.
	"""
	try:
		result = frappe.db.sql("""
			DELETE dts FROM `tabSIS Bus Daily Trip Student` dts
			LEFT JOIN `tabSIS Bus Daily Trip` dt ON dts.daily_trip_id = dt.name
			WHERE dt.name IS NULL
		""")
		frappe.db.commit()
		frappe.logger().info(f"✅ [BUS TASK] Đã xóa student records mồ côi")
		return {"success": True, "message": "Cleanup completed"}
	except Exception as e:
		frappe.log_error(f"[BUS TASK] cleanup_orphan_students failed: {str(e)}")
		return {"success": False, "message": str(e)}

