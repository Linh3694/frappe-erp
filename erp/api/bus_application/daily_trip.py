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
        monitors = frappe.get_all(
            "Bus Monitor",
            filters={"user_id": user_email, "is_active": 1},
            fields=["name", "campus_id"]
        )

        if not monitors:
            return not_found_response("Bus monitor not found")

        monitor_id = monitors[0].name
        campus_id = monitors[0].campus_id

        # Get daily trips for this monitor on the specified date
        trips = frappe.get_all(
            "Daily Trip",
            filters={
                "monitor_id": monitor_id,
                "trip_date": date_param,
                "docstatus": ["!=", 2]  # Not cancelled
            },
            fields=[
                "name", "trip_date", "scheduled_time", "direction",
                "bus_route_id", "bus_id", "status", "total_students",
                "checked_in_count", "checked_out_count", "creation", "modified"
            ],
            order_by="scheduled_time asc"
        )

        # Enrich trip data with route information
        for trip in trips:
            if trip.bus_route_id:
                try:
                    route = frappe.get_doc("Bus Route", trip.bus_route_id)
                    trip.route_name = route.route_name
                    trip.route_short_name = route.short_name
                except frappe.DoesNotExistError:
                    trip.route_name = "Unknown Route"
                    trip.route_short_name = "Unknown"

            # Calculate completion percentage
            checked_in = trip.checked_in_count or 0
            checked_out = trip.checked_out_count or 0
            total = trip.total_students or 0

            if trip.direction == "to_school":
                trip.completion_percentage = (checked_in / total * 100) if total > 0 else 0
            else:  # from_school
                trip.completion_percentage = (checked_out / total * 100) if total > 0 else 0

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

        # Verify trip belongs to current monitor
        trip = frappe.get_doc("Daily Trip", trip_id)

        # Check if monitor has access to this trip
        monitors = frappe.get_all(
            "Bus Monitor",
            filters={"user_id": user_email, "is_active": 1},
            fields=["name"]
        )

        if not monitors or trip.monitor_id != monitors[0].name:
            return forbidden_response("Access denied to this trip")

        # Get trip basic information
        trip_data = {
            "trip_id": trip.name,
            "trip_date": trip.trip_date,
            "scheduled_time": trip.scheduled_time,
            "direction": trip.direction,
            "status": trip.status,
            "bus_route_id": trip.bus_route_id,
            "bus_id": trip.bus_id,
            "monitor_id": trip.monitor_id,
            "total_students": trip.total_students or 0,
            "checked_in_count": trip.checked_in_count or 0,
            "checked_out_count": trip.checked_out_count or 0,
        }

        # Get route information
        if trip.bus_route_id:
            try:
                route = frappe.get_doc("Bus Route", trip.bus_route_id)
                trip_data["route_name"] = route.route_name
                trip_data["route_short_name"] = route.short_name
                trip_data["route_description"] = route.description
            except frappe.DoesNotExistError:
                trip_data["route_name"] = "Unknown Route"

        # Get bus information
        if trip.bus_id:
            try:
                bus = frappe.get_doc("Bus Transportation", trip.bus_id)
                trip_data["bus_number"] = bus.bus_number
                trip_data["bus_model"] = bus.bus_model
                trip_data["license_plate"] = bus.license_plate
            except frappe.DoesNotExistError:
                trip_data["bus_number"] = "Unknown Bus"

        # Get student list with status
        students = frappe.get_all(
            "Daily Trip Student",
            filters={"parent": trip_id},
            fields=[
                "student_id", "student_name", "student_code", "class_name",
                "check_in_time", "check_out_time", "check_in_method",
                "check_out_method", "status", "emergency_contact", "medical_notes"
            ],
            order_by="student_name asc"
        )

        # Process student status
        processed_students = []
        checked_in_count = 0
        checked_out_count = 0

        for student in students:
            # Map status from database to API format
            status = student.status or "not_checked"

            # Count statistics
            if status == "checked_in":
                checked_in_count += 1
            elif status == "checked_out":
                checked_out_count += 1

            processed_student = {
                "student_id": student.student_id,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "class_name": student.class_name,
                "status": status,
                "check_in_time": student.check_in_time,
                "check_out_time": student.check_out_time,
                "check_in_method": student.check_in_method,
                "check_out_method": student.check_out_method,
                "emergency_contact": student.emergency_contact,
                "medical_notes": student.medical_notes,
            }
            processed_students.append(processed_student)

        trip_data["students"] = processed_students
        trip_data["checked_in_count"] = checked_in_count
        trip_data["checked_out_count"] = checked_out_count

        # Calculate completion percentage
        total_students = len(processed_students)
        if trip.direction == "to_school":
            completion_percentage = (checked_in_count / total_students * 100) if total_students > 0 else 0
        else:
            completion_percentage = (checked_out_count / total_students * 100) if total_students > 0 else 0

        trip_data["completion_percentage"] = round(completion_percentage, 1)

        # Check for warnings
        warnings = []
        if trip.direction == "to_school" and checked_in_count < total_students:
            missing_count = total_students - checked_in_count
            warnings.append(f"Còn {missing_count} học sinh chưa lên xe")

        if trip.direction == "from_school" and checked_out_count < total_students:
            missing_count = total_students - checked_out_count
            warnings.append(f"Còn {missing_count} học sinh chưa xuống xe")

        trip_data["warnings"] = warnings

        return single_item_response(trip_data, "Daily trip details retrieved successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Daily trip not found")
    except Exception as e:
        frappe.log_error(f"Error getting daily trip detail: {str(e)}")
        return error_response(f"Error getting trip details: {str(e)}")


@frappe.whitelist(allow_guest=False)
def complete_daily_trip():
    """
    Mark a daily trip as completed
    Expected parameters (JSON):
    - trip_id: Daily trip ID to complete
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

        # Verify trip belongs to current monitor and can be completed
        trip = frappe.get_doc("Daily Trip", trip_id)

        # Check if monitor has access to this trip
        monitors = frappe.get_all(
            "Bus Monitor",
            filters={"user_id": user_email, "is_active": 1},
            fields=["name"]
        )

        if not monitors or trip.monitor_id != monitors[0].name:
            return forbidden_response("Access denied to this trip")

        # Check if trip can be completed
        if trip.status == "completed":
            return validation_error_response({"trip_id": ["Trip is already completed"]})

        # Update trip status to completed
        trip.status = "completed"
        trip.completed_at = nowdate()
        trip.save()
        frappe.db.commit()

        return success_response("Daily trip completed successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Daily trip not found")
    except Exception as e:
        frappe.log_error(f"Error completing daily trip: {str(e)}")
        return error_response(f"Error completing trip: {str(e)}")
