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


# TODO: tạm chặn dữ liệu bus cho parent portal (web + mobile) theo yêu cầu vận hành.
# Bỏ cờ này (và block return sớm trong get_student_bus_trips) khi mở lại tính năng.
BUS_TEMPORARILY_DISABLED = True


@frappe.whitelist()
def get_student_bus_trips():
    """Get morning and afternoon bus trips for current student"""
    logs = []
    try:
        logs.append("🚍 Starting get_student_bus_trips")

        if BUS_TEMPORARILY_DISABLED:
            # Trả payload rỗng đúng shape FE mong đợi để web/mobile hiện empty state,
            # không trả trip nào vì FE gọi license_plate.split() trên từng trip.
            logs.append("⛔ Bus data tạm bị chặn (BUS_TEMPORARILY_DISABLED)")
            return success_response(
                data={
                    "date": date.today().isoformat(),
                    "morning_trip": None,
                    "afternoon_trip": None,
                    "total_trips": 0,
                },
                message="Lấy thông tin chuyến xe thành công",
                logs=logs
            )

        student_id = _get_current_student_from_session()
        if not student_id:
            return error_response("Không tìm thấy thông tin học sinh hiện tại", logs=logs)

        logs.append(f"👤 Student ID: {student_id}")

        today = date.today().isoformat()
        logs.append(f"📅 Today: {today}")

        # Lấy chuyến xe của học sinh bằng 1 query duy nhất thay vì N+1 queries
        student_trips = frappe.db.sql("""
            SELECT
                dt.name as trip_id,
                dt.trip_date, dt.weekday, dt.trip_type, dt.trip_status,
                r.route_name, r.vehicle_code,
                v.license_plate, v.vehicle_type,
                d.full_name as driver_name, d.phone_number as driver_phone,
                m1.full_name as monitor1_name, m1.phone_number as monitor1_phone,
                m2.full_name as monitor2_name, m2.phone_number as monitor2_phone,
                dts.pickup_order, dts.pickup_location, dts.drop_off_location,
                dts.student_status, dts.boarding_time, dts.drop_off_time
            FROM `tabSIS Bus Daily Trip Student` dts
            INNER JOIN `tabSIS Bus Daily Trip` dt ON dts.daily_trip_id = dt.name
            LEFT JOIN `tabSIS Bus Route` r ON dt.route_id = r.name
            LEFT JOIN `tabSIS Bus Transportation` v ON dt.vehicle_id = v.name
            LEFT JOIN `tabSIS Bus Driver` d ON dt.driver_id = d.name
            LEFT JOIN `tabSIS Bus Monitor` m1 ON dt.monitor1_id = m1.name
            LEFT JOIN `tabSIS Bus Monitor` m2 ON dt.monitor2_id = m2.name
            WHERE dts.student_id = %s AND dt.trip_date = %s
            ORDER BY dt.trip_type
        """, (student_id, today), as_dict=True)

        logs.append(f"📋 Found {len(student_trips)} trips for student")

        morning_trip = None
        afternoon_trip = None

        for trip in student_trips:
            trip_info = {
                "trip_id": trip.trip_id,
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
                "pickup_order": trip.pickup_order,
                "pickup_location": trip.pickup_location or "",
                "drop_off_location": trip.drop_off_location or "",
                "student_status": trip.student_status,
                "boarding_time": trip.boarding_time,
                "drop_off_time": trip.drop_off_time
            }

            if trip.trip_type == "Đón":
                morning_trip = trip_info
            elif trip.trip_type == "Trả":
                afternoon_trip = trip_info

            logs.append(f"✅ Found {trip.trip_type} trip: {trip.route_name}")

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
