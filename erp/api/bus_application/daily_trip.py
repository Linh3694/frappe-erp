# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, add_days, getdate, now_datetime
import json
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)
from erp.api.bus_application.bus_monitor import get_request_param


@frappe.whitelist(allow_guest=False)
def get_monitor_daily_trips():
    """
    Get daily trips for current bus monitor
    Expected parameters (optional):
    - date: Specific date (YYYY-MM-DD), defaults to today
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get date parameter
        date_param = get_request_param('date') or nowdate()

        # Find bus monitor by user email
        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name", "campus_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name
        campus_id = monitors[0].campus_id

        # Get daily trips for this monitor on the specified date using SQL JOIN (optimize N+1)
        trips = frappe.db.sql("""
            SELECT
                dt.name,
                dt.trip_date,
                dt.trip_type,
                dt.trip_status,
                dt.notes,
                br.route_name,
                bv.vehicle_code as bus_number,
                bv.license_plate,
                COUNT(dts.name) as total_students,
                SUM(CASE WHEN dts.student_status = 'Boarded' THEN 1 ELSE 0 END) as boarded_count,
                SUM(CASE WHEN dts.student_status = 'Dropped Off' THEN 1 ELSE 0 END) as dropped_count,
                SUM(CASE WHEN dts.student_status = 'Absent' THEN 1 ELSE 0 END) as absent_count
            FROM `tabSIS Bus Daily Trip` dt
            LEFT JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
            LEFT JOIN `tabSIS Bus Transportation` bv ON dt.vehicle_id = bv.name
            LEFT JOIN `tabSIS Bus Daily Trip Student` dts ON dts.daily_trip_id = dt.name
            WHERE (dt.monitor1_id = %s OR dt.monitor2_id = %s)
              AND dt.trip_date = %s
              AND dt.docstatus != 2
            GROUP BY dt.name
            ORDER BY dt.trip_type DESC, br.route_name ASC
        """, (monitor_id, monitor_id, date_param), as_dict=True)

        # Calculate completion percentage for each trip
        for trip in trips:
            total = trip.total_students or 0
            if total > 0:
                if trip.trip_type == "Đón":
                    completed = trip.boarded_count or 0
                    trip.completion_percentage = round((completed / total) * 100, 1)
                else:  # Trả
                    completed = trip.dropped_count or 0
                    trip.completion_percentage = round((completed / total) * 100, 1)
            else:
                trip.completion_percentage = 0

            # Add warning flags - cảnh báo nếu completion < 80% và đang In Progress
            trip.has_warning = (
                trip.trip_status == "In Progress" and
                trip.completion_percentage < 80
            )

        return list_response(trips, f"Daily trips for {date_param} retrieved successfully")

    except Exception as e:
        frappe.log_error(f"Error getting monitor daily trips: {str(e)}")
        return error_response(f"Error getting daily trips: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_daily_trip_detail(trip_id=None):
    """
    Get detailed information for a specific daily trip
    Expected parameters:
    - trip_id: Daily trip ID
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get trip_id from parameter or request
        if not trip_id:
            trip_id = get_request_param('trip_id')

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Get current monitor
        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name", "campus_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Verify trip belongs to current monitor
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        # Check if monitor has access to this trip (monitor1_id or monitor2_id)
        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Get trip basic info with JOINs
        trip_data = frappe.db.sql("""
            SELECT
                dt.*,
                br.route_name,
                bv.vehicle_code as bus_number, bv.license_plate, bv.vehicle_type as bus_model,
                bd.full_name as driver_name, bd.phone_number as driver_phone
            FROM `tabSIS Bus Daily Trip` dt
            LEFT JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
            LEFT JOIN `tabSIS Bus Transportation` bv ON dt.vehicle_id = bv.name
            LEFT JOIN `tabSIS Bus Driver` bd ON dt.driver_id = bd.name
            WHERE dt.name = %s
        """, (trip_id,), as_dict=True)[0]


        # Get student list
        students = frappe.db.sql("""
            SELECT
                dts.name,
                dts.student_id,
                dts.student_name,
                dts.student_code,
                dts.class_name,
                dts.student_status,
                dts.boarding_time,
                dts.drop_off_time,
                dts.absent_reason,
                dts.pickup_location,
                dts.drop_off_location,
                dts.pickup_order,
                dts.notes
            FROM `tabSIS Bus Daily Trip Student` dts
            WHERE dts.daily_trip_id = %s
            ORDER BY dts.pickup_order ASC
        """, (trip_id,), as_dict=True)

        # Add photo from SIS Photo
        for student in students:
            student.photo_url = None
            try:
                sis_photos = frappe.get_all(
                    "SIS Photo",
                    filters={"student_id": student.student_id, "type": "student", "status": "Active"},
                    fields=["photo"],
                    order_by="upload_date desc",
                    limit=1
                )
                if sis_photos:
                    student.photo_url = sis_photos[0].photo
            except:
                pass

        # Calculate statistics
        stats = {
            "total_students": len(students),
            "not_boarded": sum(1 for s in students if s.student_status == "Not Boarded"),
            "boarded": sum(1 for s in students if s.student_status == "Boarded"),
            "dropped_off": sum(1 for s in students if s.student_status == "Dropped Off"),
            "absent": sum(1 for s in students if s.student_status == "Absent")
        }

        # Generate warnings
        warnings = []
        if trip_data["trip_type"] == "Đón":
            if stats["not_boarded"] > 0:
                warnings.append(f"Còn {stats['not_boarded']} học sinh chưa lên xe")
            if stats["not_boarded"] > stats["total_students"] * 0.2:
                warnings.append("⚠️ Hơn 20% học sinh chưa check-in")
        else:  # Trả
            if stats["not_boarded"] + stats["boarded"] > 0:
                remaining = stats["not_boarded"] + stats["boarded"]
                warnings.append(f"Còn {remaining} học sinh chưa xuống xe")

        trip_data["students"] = students
        trip_data["statistics"] = stats
        trip_data["warnings"] = warnings

        return single_item_response(trip_data, "Daily trip details retrieved successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Daily trip not found")
    except Exception as e:
        frappe.log_error(f"Error getting daily trip detail: {str(e)}")
        return error_response(f"Error getting trip details: {str(e)}")


@frappe.whitelist(allow_guest=False)
def start_daily_trip():
    """
    Start a daily trip
    Expected parameters (JSON):
    - trip_id: Daily trip ID to start
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get request data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        trip_id = data.get('trip_id')
        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Get current monitor
        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name", "campus_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Verify trip belongs to current monitor and can be started
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        # Check if monitor has access to this trip (monitor1_id or monitor2_id)
        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Check if trip can be started
        if trip.trip_status != "Not Started":
            return validation_error_response({"trip_id": [f"Trip already {trip.trip_status}"]})

        # Update trip status to In Progress (run as Administrator to bypass permissions)
        frappe.set_user("Administrator")
        try:
            trip.trip_status = "In Progress"
            trip.flags.ignore_permissions = True
            trip.save(ignore_permissions=True)
            frappe.db.commit()

            started_time = now_datetime()

            # Log action
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"Trip {trip_id} started by {monitor_id}",
                "communication_date": started_time
            }).insert(ignore_permissions=True)
        finally:
            frappe.set_user("Guest")

        return single_item_response({
            "trip_id": trip_id,
            "trip_status": "In Progress",
            "started_at": str(started_time)
        }, "Trip started successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Daily trip not found")
    except Exception as e:
        frappe.log_error(f"Error starting daily trip: {str(e)}")
        return error_response(f"Error starting trip: {str(e)}")


@frappe.whitelist(allow_guest=False)
def complete_daily_trip():
    """
    Mark a daily trip as completed with warnings validation
    Expected parameters (JSON):
    - trip_id: Daily trip ID to complete
    - force: Boolean to bypass warnings (optional, default: false)
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get request data
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        trip_id = data.get('trip_id')
        force = data.get('force', False)

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Get current monitor
        # Extract monitor_code from email (format: monitor_code@busmonitor.wellspring.edu.vn)
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Verify trip belongs to current monitor
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        # Check if monitor has access to this trip (monitor1_id or monitor2_id)
        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Check if trip can be completed
        if trip.trip_status == "Completed":
            return validation_error_response({"trip_id": ["Trip is already completed"]})

        # Calculate completion stats - get students from database
        students = frappe.get_all(
            "SIS Bus Daily Trip Student",
            filters={"daily_trip_id": trip_id},
            fields=["name", "student_id", "student_status"]
        )
        total = len(students)

        if trip.trip_type == "Đón":  # Pickup
            completed = sum(1 for s in students if s.student_status in ["Boarded", "Absent"])
            pending = sum(1 for s in students if s.student_status == "Not Boarded")
        else:  # Drop-off
            completed = sum(1 for s in students if s.student_status in ["Dropped Off", "Absent"])
            pending = sum(1 for s in students if s.student_status in ["Not Boarded", "Boarded"])

        completion_rate = (completed / total * 100) if total > 0 else 0

        # Check warnings (bypass if force=true)
        if not force:
            warnings = []
            if pending > 0:
                warnings.append(f"Còn {pending} học sinh chưa hoàn thành điểm danh")

            if completion_rate < 80:
                warnings.append(f"Tỷ lệ hoàn thành chỉ {completion_rate:.1f}%")

            if warnings:
                return {
                    "success": False,
                    "message": "Trip có cảnh báo chưa xử lý",
                    "warnings": warnings,
                    "completion_rate": completion_rate,
                    "pending_students": pending,
                    "can_force": True
                }

        # Complete trip (run as Administrator to bypass permissions)
        frappe.set_user("Administrator")
        try:
            trip.trip_status = "Completed"
            trip.flags.ignore_permissions = True
            trip.save(ignore_permissions=True)
            frappe.db.commit()

            completed_time = now_datetime()

            # Log action
            frappe.get_doc({
                "doctype": "Activity Log",
                "subject": f"Trip {trip_id} completed by {monitor_id}",
                "communication_date": completed_time
            }).insert(ignore_permissions=True)
        finally:
            frappe.set_user("Guest")

        # Generate trip report
        report_data = {
            "trip_id": trip_id,
            "trip_date": str(trip.trip_date),
            "trip_type": trip.trip_type,
            "route": trip.route_id,
            "total_students": total,
            "boarded": sum(1 for s in students if s.student_status == "Boarded"),
            "dropped_off": sum(1 for s in students if s.student_status == "Dropped Off"),
            "absent": sum(1 for s in students if s.student_status == "Absent"),
            "completion_rate": completion_rate,
            "completed_at": str(completed_time)
        }

        # TODO: Send notifications (optional - future)
        # send_parent_notifications(trip, students)

        return single_item_response(report_data, "Trip completed successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Daily trip not found")
    except Exception as e:
        frappe.log_error(f"Error completing daily trip: {str(e)}")
        return error_response(f"Error completing trip: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_monitor_trips_by_date_range():
    """
    Get daily trips for current bus monitor within a date range
    Expected parameters (optional):
    - start_date: Start date (YYYY-MM-DD), defaults to today
    - end_date: End date (YYYY-MM-DD), defaults to 7 days from start_date
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get date parameters
        start_date = get_request_param('start_date') or nowdate()
        end_date = get_request_param('end_date') or add_days(start_date, 7)

        # Validate dates
        start_date = getdate(start_date)
        end_date = getdate(end_date)

        if end_date < start_date:
            return validation_error_response({"end_date": ["End date must be after start date"]})

        # Find bus monitor by user email
        if "@busmonitor.wellspring.edu.vn" not in user_email:
            return error_response("Invalid user account format", code="INVALID_USER")

        monitor_code = user_email.split("@")[0]

        monitors = frappe.get_all(
            "SIS Bus Monitor",
            filters={"monitor_code": monitor_code, "status": "Active"},
            fields=["name", "campus_id", "full_name"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name

        # Get daily trips for this monitor in date range
        trips = frappe.db.sql("""
            SELECT
                dt.name,
                dt.trip_date,
                dt.weekday,
                dt.trip_type,
                dt.trip_status,
                dt.notes,
                br.name as route_id,
                br.route_name,
                bv.vehicle_code as bus_number,
                bv.license_plate,
                bd.full_name as driver_name,
                bd.phone_number as driver_phone,
                COUNT(dts.name) as total_students,
                SUM(CASE WHEN dts.student_status = 'Boarded' THEN 1 ELSE 0 END) as boarded_count,
                SUM(CASE WHEN dts.student_status = 'Dropped Off' THEN 1 ELSE 0 END) as dropped_count,
                SUM(CASE WHEN dts.student_status = 'Absent' THEN 1 ELSE 0 END) as absent_count,
                SUM(CASE WHEN dts.student_status = 'Not Boarded' THEN 1 ELSE 0 END) as not_boarded_count
            FROM `tabSIS Bus Daily Trip` dt
            LEFT JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
            LEFT JOIN `tabSIS Bus Transportation` bv ON dt.vehicle_id = bv.name
            LEFT JOIN `tabSIS Bus Driver` bd ON dt.driver_id = bd.name
            LEFT JOIN `tabSIS Bus Daily Trip Student` dts ON dts.daily_trip_id = dt.name
            WHERE (dt.monitor1_id = %s OR dt.monitor2_id = %s)
              AND dt.trip_date BETWEEN %s AND %s
              AND dt.docstatus != 2
            GROUP BY dt.name
            ORDER BY dt.trip_date ASC, dt.trip_type DESC
        """, (monitor_id, monitor_id, start_date, end_date), as_dict=True)

        # Group trips by date
        trips_by_date = {}
        for trip in trips:
            date_str = str(trip.trip_date)
            if date_str not in trips_by_date:
                trips_by_date[date_str] = {
                    "date": date_str,
                    "weekday": trip.weekday,
                    "trips": []
                }

            # Calculate completion percentage
            total = trip.total_students or 0
            if total > 0:
                if trip.trip_type == "Đón":
                    completed = (trip.boarded_count or 0) + (trip.absent_count or 0)
                else:
                    completed = (trip.dropped_count or 0) + (trip.absent_count or 0)
                trip.completion_percentage = round((completed / total) * 100, 1)
            else:
                trip.completion_percentage = 0

            trips_by_date[date_str]["trips"].append(trip)

        # Convert to list and sort by date
        result = list(trips_by_date.values())
        result.sort(key=lambda x: x["date"])

        return list_response(result, f"Found {len(trips)} trips from {start_date} to {end_date}")

    except Exception as e:
        frappe.log_error(f"Error getting monitor trips by date range: {str(e)}")
        return error_response(f"Error getting trips: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_student_status():
    """
    Update student status in a daily trip (for both mobile and web)
    Expected parameters (JSON):
    - daily_trip_student_id: The ID of the daily trip student record
    - student_status: New status (Not Boarded, Boarded, Dropped Off, Absent)
    - absent_reason: Reason if marking as absent (Nghỉ học, Nghỉ ốm, Nghỉ phép, Lý do khác)
    - notes: Optional notes
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get request data - support both JSON body and form data
        data = {}
        if frappe.request.data:
            try:
                if isinstance(frappe.request.data, bytes):
                    json_data = json.loads(frappe.request.data.decode('utf-8'))
                else:
                    json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
        
        frappe.logger().info(f"🔍 update_student_status data: {data}")

        daily_trip_student_id = data.get('daily_trip_student_id')
        student_status = data.get('student_status')
        absent_reason = data.get('absent_reason')
        notes = data.get('notes')

        if not daily_trip_student_id:
            return error_response("Daily trip student ID is required")

        if not student_status:
            return error_response("Student status is required")

        valid_statuses = ['Not Boarded', 'Boarded', 'Dropped Off', 'Absent']
        if student_status not in valid_statuses:
            return error_response(f"Invalid student status. Must be one of: {', '.join(valid_statuses)}")

        # Get the trip student record
        trip_student = frappe.get_doc("SIS Bus Daily Trip Student", daily_trip_student_id)
        trip_id = trip_student.daily_trip_id
        
        # Lấy thông tin trip
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        # Check permissions (monitor or web user)
        is_monitor = "@busmonitor.wellspring.edu.vn" in user_email

        if is_monitor:
            monitor_code = user_email.split("@")[0]
            monitors = frappe.get_all(
                "SIS Bus Monitor",
                filters={"monitor_code": monitor_code, "status": "Active"},
                fields=["name"]
            )
            if not monitors:
                return not_found_response("Bus monitor not found")

            monitor_id = monitors[0].name

            if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
                return forbidden_response("Access denied to this trip")

        # Update the record (run as Administrator to bypass permissions)
        current_time = now_datetime()
        trip_auto_started = False
        
        # Lưu user hiện tại để restore sau
        original_user = frappe.session.user
        
        frappe.set_user("Administrator")
        try:
            # Tự động bắt đầu chuyến xe nếu chưa bắt đầu và đang cập nhật trạng thái điểm danh
            if trip.trip_status == "Not Started" and student_status in ['Boarded', 'Dropped Off']:
                trip.trip_status = "In Progress"
                trip.flags.ignore_permissions = True
                trip.save(ignore_permissions=True)
                trip_auto_started = True
            
            trip_student.student_status = student_status

            if student_status == 'Boarded':
                trip_student.boarding_time = current_time
                trip_student.boarding_method = 'manual'
            elif student_status == 'Dropped Off':
                trip_student.drop_off_time = current_time
                trip_student.drop_off_method = 'manual'
            elif student_status == 'Absent':
                # Map Vietnamese to English absent reasons (doctype uses English options)
                reason_mapping = {
                    'Nghỉ học': 'School Leave',
                    'Nghỉ ốm': 'Sick Leave',
                    'Nghỉ phép': 'Permission',
                    'Lý do khác': 'Other'
                }
                if absent_reason:
                    trip_student.absent_reason = reason_mapping.get(absent_reason, absent_reason)
                else:
                    trip_student.absent_reason = 'School Leave'  # Default reason

            if notes:
                trip_student.notes = notes

            trip_student.flags.ignore_permissions = True
            trip_student.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as save_error:
            frappe.log_error(f"Error saving student status: {str(save_error)}")
            frappe.set_user(original_user)
            return error_response(f"Error saving: {str(save_error)}")
        finally:
            frappe.set_user(original_user)

        message = f"Đã cập nhật trạng thái học sinh thành {student_status}"
        if trip_auto_started:
            message += " (Chuyến xe đã tự động bắt đầu)"
            
        return single_item_response({
            "daily_trip_student_id": daily_trip_student_id,
            "student_id": trip_student.student_id,
            "student_name": trip_student.student_name,
            "student_status": student_status,
            "updated_at": str(current_time),
            "trip_auto_started": trip_auto_started,
            "trip_status": trip.trip_status
        }, message)

    except frappe.DoesNotExistError:
        return not_found_response("Record not found")
    except Exception as e:
        frappe.log_error(f"Error updating student status: {str(e)}")
        return error_response(f"Error updating status: {str(e)}")
