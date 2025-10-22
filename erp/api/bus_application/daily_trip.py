# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, add_days, getdate
import json
from datetime import datetime, date
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
                dt.started_at,
                dt.completed_at,
                dt.notes,
                br.route_name,
                br.short_name as route_short_name,
                bv.bus_number,
                bv.license_plate,
                COUNT(dts.name) as total_students,
                SUM(CASE WHEN dts.student_status = 'Boarded' THEN 1 ELSE 0 END) as boarded_count,
                SUM(CASE WHEN dts.student_status = 'Dropped Off' THEN 1 ELSE 0 END) as dropped_count,
                SUM(CASE WHEN dts.student_status = 'Absent' THEN 1 ELSE 0 END) as absent_count
            FROM `tabSIS Bus Daily Trip` dt
            LEFT JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
            LEFT JOIN `tabSIS Bus Transportation` bv ON dt.vehicle_id = bv.name
            LEFT JOIN `tabSIS Bus Daily Trip Student` dts ON dts.parent = dt.name
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
                    trip.completion_percentage = round((trip.boarded_count / total) * 100, 1)
                else:  # Trả
                    trip.completion_percentage = round((trip.dropped_count / total) * 100, 1)
            else:
                trip.completion_percentage = 0

            # Add warning flags
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
                br.route_name, br.short_name as route_short_name,
                br.description as route_description,
                bv.bus_number, bv.license_plate, bv.bus_model,
                bd.driver_name, bd.phone_number as driver_phone
            FROM `tabSIS Bus Daily Trip` dt
            LEFT JOIN `tabSIS Bus Route` br ON dt.route_id = br.name
            LEFT JOIN `tabSIS Bus Transportation` bv ON dt.vehicle_id = bv.name
            LEFT JOIN `tabSIS Bus Driver` bd ON dt.driver_id = bd.name
            WHERE dt.name = %s
        """, (trip_id,), as_dict=True)[0]


        # Get student list with CRM details
        students = frappe.db.sql("""
            SELECT
                dts.name,
                dts.student_id,
                dts.student_name,
                dts.student_code,
                dts.class_name,
                dts.student_status,
                dts.boarding_time,
                dts.boarding_method,
                dts.drop_off_time,
                dts.drop_off_method,
                dts.absent_reason,
                dts.emergency_contact,
                dts.medical_notes,
                cs.user_image as photo_url,
                cs.dob,
                cs.gender
            FROM `tabSIS Bus Daily Trip Student` dts
            LEFT JOIN `tabCRM Student` cs ON dts.student_id = cs.name
            WHERE dts.parent = %s
            ORDER BY dts.student_name ASC
        """, (trip_id,), as_dict=True)

        # Add fallback photo from SIS Photo if needed
        for student in students:
            if not student.photo_url:
                sis_photos = frappe.get_all(
                    "SIS Photo",
                    filters={"student_id": student.student_id, "type": "student", "status": "Active"},
                    fields=["photo"],
                    order_by="upload_date desc",
                    limit=1
                )
                if sis_photos:
                    student.photo_url = sis_photos[0].photo

        # Calculate statistics
        stats = {
            "total_students": len(students),
            "not_checked": sum(1 for s in students if s.student_status == "Not Checked"),
            "boarded": sum(1 for s in students if s.student_status == "Boarded"),
            "dropped_off": sum(1 for s in students if s.student_status == "Dropped Off"),
            "absent": sum(1 for s in students if s.student_status == "Absent")
        }

        # Generate warnings
        warnings = []
        if trip_data["trip_type"] == "Đón":
            if stats["not_checked"] > 0:
                warnings.append(f"Còn {stats['not_checked']} học sinh chưa lên xe")
            if stats["not_checked"] > stats["total_students"] * 0.2:
                warnings.append("⚠️ Hơn 20% học sinh chưa check-in")
        else:  # Trả
            if stats["not_checked"] + stats["boarded"] > 0:
                remaining = stats["not_checked"] + stats["boarded"]
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

        # Update trip status to In Progress
        trip.trip_status = "In Progress"
        trip.started_at = now_datetime()
        trip.save()
        frappe.db.commit()

        # Log action
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"Trip {trip_id} started by {monitor_id}",
            "communication_date": now_datetime()
        }).insert(ignore_permissions=True)

        return single_item_response({
            "trip_id": trip_id,
            "trip_status": "In Progress",
            "started_at": trip.started_at
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

        # Calculate completion stats
        students = trip.students  # Child table
        total = len(students)

        if trip.trip_type == "Đón":  # Pickup
            completed = sum(1 for s in students if s.student_status in ["Boarded", "Absent"])
            pending = sum(1 for s in students if s.student_status == "Not Checked")
        else:  # Drop-off
            completed = sum(1 for s in students if s.student_status in ["Dropped Off", "Absent"])
            pending = sum(1 for s in students if s.student_status in ["Not Checked", "Boarded"])

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

        # Complete trip
        trip.trip_status = "Completed"
        trip.completed_at = now_datetime()
        trip.save()
        frappe.db.commit()

        # Generate trip report
        report_data = {
            "trip_id": trip_id,
            "trip_date": trip.trip_date,
            "trip_type": trip.trip_type,
            "route": trip.route_id,
            "total_students": total,
            "boarded": sum(1 for s in students if s.student_status == "Boarded"),
            "dropped_off": sum(1 for s in students if s.student_status == "Dropped Off"),
            "absent": sum(1 for s in students if s.student_status == "Absent"),
            "completion_rate": completion_rate,
            "started_at": trip.started_at,
            "completed_at": trip.completed_at,
            "duration_minutes": (trip.completed_at - trip.started_at).total_seconds() / 60 if trip.started_at else 0
        }

        # Log action
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"Trip {trip_id} completed by {monitor_id}",
            "communication_date": now_datetime(),
            "full_communication_content": json.dumps(report_data)
        }).insert(ignore_permissions=True)

        # TODO: Send notifications (optional - future)
        # send_parent_notifications(trip, students)

        return single_item_response(report_data, "Trip completed successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Daily trip not found")
    except Exception as e:
        frappe.log_error(f"Error completing daily trip: {str(e)}")
        return error_response(f"Error completing trip: {str(e)}")
