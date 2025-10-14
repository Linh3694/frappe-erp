# -*- coding: utf-8 -*-
"""
Parent Portal Bus API
Handles student bus trip information for parent portal
"""

import frappe
from frappe import _
from datetime import datetime, date
from erp.utils.api_response import success_response, error_response


def _get_current_student_from_session():
    """Get current student ID from session context"""
    try:
        # Get from frappe session
        student_id = frappe.session.get('current_student_id')
        if student_id:
            return student_id

        # Fallback: get from request args
        student_id = frappe.local.form_dict.get('student_id') or frappe.request.args.get('student_id')
        if student_id:
            return student_id

        return None
    except Exception as e:
        frappe.logger().error(f"Error getting current student from session: {str(e)}")
        return None


@frappe.whitelist()
def get_student_bus_trips():
    """Get morning and afternoon bus trips for current student"""
    logs = []
    try:
        logs.append("🚍 Starting get_student_bus_trips")

        # Get current student
        student_id = _get_current_student_from_session()
        if not student_id:
            return error_response("Không tìm thấy thông tin học sinh hiện tại", logs=logs)

        logs.append(f"👤 Student ID: {student_id}")

        # Get today's date
        today = date.today().isoformat()
        logs.append(f"📅 Today: {today}")

        # Get daily trips for today
        daily_trips = frappe.db.sql("""
            SELECT
                dt.name, dt.route_id, dt.trip_date, dt.weekday, dt.trip_type,
                dt.vehicle_id, dt.driver_id, dt.monitor1_id, dt.monitor2_id,
                dt.trip_status, dt.campus_id, dt.school_year_id,
                r.route_name,
                v.vehicle_code, v.license_plate, v.vehicle_type,
                d.full_name as driver_name, d.phone_number as driver_phone,
                m1.full_name as monitor1_name, m1.phone_number as monitor1_phone,
                m2.full_name as monitor2_name, m2.phone_number as monitor2_phone
            FROM `tabSIS Bus Daily Trip` dt
            LEFT JOIN `tabSIS Bus Route` r ON dt.route_id = r.name
            LEFT JOIN `tabSIS Bus Transportation` v ON dt.vehicle_id = v.name
            LEFT JOIN `tabSIS Bus Driver` d ON dt.driver_id = d.name
            LEFT JOIN `tabSIS Bus Monitor` m1 ON dt.monitor1_id = m1.name
            LEFT JOIN `tabSIS Bus Monitor` m2 ON dt.monitor2_id = m2.name
            WHERE dt.trip_date = %s
            ORDER BY dt.trip_type, dt.route_id
        """, (today,), as_dict=True)

        logs.append(f"📋 Found {len(daily_trips)} daily trips for today")

        # Filter trips that include this student
        student_trips = []
        for trip in daily_trips:
            # Check if student is in this trip
            student_in_trip = frappe.db.sql("""
                SELECT
                    name, pickup_order, pickup_location, drop_off_location,
                    student_status, boarding_time, drop_off_time
                FROM `tabSIS Bus Daily Trip Student`
                WHERE daily_trip_id = %s AND student_id = %s
                LIMIT 1
            """, (trip.name, student_id), as_dict=True)

            if student_in_trip:
                student_info = student_in_trip[0]
                trip_info = {
                    "trip_id": trip.name,
                    "route_name": trip.route_name or "",
                    "vehicle_code": trip.vehicle_code or "",
                    "license_plate": trip.license_plate or "",
                    "vehicle_type": trip.vehicle_type or "",
                    "driver_name": trip.driver_name or "",
                    "driver_phone": trip.driver_phone or "",
                    "monitor1_name": trip.monitor1_name or "",
                    "monitor1_phone": trip.monitor1_phone or "",
                    "monitor2_name": trip.monitor2_name or "",
                    "monitor2_phone": trip.monitor2_phone or "",
                    "trip_date": trip.trip_date,
                    "weekday": trip.weekday,
                    "trip_type": trip.trip_type,
                    "trip_status": trip.trip_status,
                    "pickup_order": student_info.pickup_order,
                    "pickup_location": student_info.pickup_location or "",
                    "drop_off_location": student_info.drop_off_location or "",
                    "student_status": student_info.student_status,
                    "boarding_time": student_info.boarding_time,
                    "drop_off_time": student_info.drop_off_time
                }
                student_trips.append(trip_info)
                logs.append(f"✅ Found {trip.trip_type} trip: {trip.route_name}")

        # Separate morning and afternoon trips
        morning_trip = None
        afternoon_trip = None

        for trip in student_trips:
            if trip["trip_type"] == "Đón":
                morning_trip = trip
            elif trip["trip_type"] == "Trả":
                afternoon_trip = trip

        result_data = {
            "date": today,
            "morning_trip": morning_trip,
            "afternoon_trip": afternoon_trip,
            "total_trips": len(student_trips)
        }

        logs.append(f"🎉 Success: Found {len(student_trips)} trips for student")
        return success_response(
            data=result_data,
            message="Lấy thông tin chuyến xe thành công",
            logs=logs
        )

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logs.append(f"❌ ERROR: {str(e)}")
        logs.append(f"📜 Traceback: {error_trace}")
        frappe.log_error(f"Error getting student bus trips: {str(e)}\n{error_trace}")
        return error_response(f"Lỗi khi lấy thông tin chuyến xe: {str(e)}", logs=logs)
