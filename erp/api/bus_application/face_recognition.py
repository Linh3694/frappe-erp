# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""Điểm danh học sinh trên chuyến xe bus.

Tên file là di sản: trước đây module này chứa cả phần nhận diện khuôn mặt
qua dịch vụ bên ngoài. Phần đó đã được gỡ; nay chỉ còn điểm danh thủ công.

Không đổi tên file vì hai lý do: `offline.py` import trực tiếp
`check_student_in_trip` và `mark_student_absent` từ đây, và app monitor
đã phát hành gọi đường dẫn API `erp.api.bus_application.face_recognition.*`.
"""

import frappe
from frappe.utils import now_datetime
import json
from erp.utils.api_response import (
    error_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)

@frappe.whitelist(allow_guest=False)
def check_student_in_trip():
    """
    Check-in a student to a trip (via face recognition or manual)
    Expected parameters (JSON):
    - student_id: Student ID
    - trip_id: Daily trip ID
    - method: "face_recognition" or "manual"
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

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

        student_id = data.get('student_id')
        trip_id = data.get('trip_id')
        method = data.get('method', 'manual')

        if not student_id:
            return validation_error_response({"student_id": ["Student ID is required"]})

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Verify monitor has access to this trip
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Find the trip student record
        trip_students = frappe.get_all(
            "SIS Bus Daily Trip Student",
            filters={
                "daily_trip_id": trip_id,
                "student_id": student_id
            },
            fields=["name", "student_status"]
        )

        if not trip_students:
            return not_found_response("Student not assigned to this trip")

        trip_student = frappe.get_doc("SIS Bus Daily Trip Student", trip_students[0].name)

        # Update status based on trip type
        current_time = now_datetime()
        
        # Tự động bắt đầu chuyến xe nếu chưa bắt đầu
        trip_auto_started = False
        if trip.trip_status == "Not Started":
            frappe.set_user("Administrator")
            try:
                trip.trip_status = "In Progress"
                trip.flags.ignore_permissions = True
                trip.save(ignore_permissions=True)
                frappe.db.commit()
                trip_auto_started = True
            finally:
                frappe.set_user("Guest")

        if trip.trip_type == "Đón":  # Pickup trip
            if trip_student.student_status == "Boarded":
                return validation_error_response({"student_id": ["Student already checked in"]})

            trip_student.student_status = "Boarded"
            trip_student.boarding_time = current_time
            trip_student.boarding_method = method

        elif trip.trip_type == "Trả":  # Drop-off trip
            if trip_student.student_status == "Dropped Off":
                return validation_error_response({"student_id": ["Student already checked out"]})

            trip_student.student_status = "Dropped Off"
            trip_student.drop_off_time = current_time
            trip_student.drop_off_method = method

        # Save with Administrator permissions
        frappe.set_user("Administrator")
        try:
            trip_student.flags.ignore_permissions = True
            trip_student.save(ignore_permissions=True)
            frappe.db.commit()
        finally:
            frappe.set_user("Guest")

        # Update trip statistics
        _update_trip_statistics(trip_id)

        # Log action
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"{method.upper()}: Student {student_id} checked in trip {trip_id}",
            "communication_date": now_datetime(),
            "full_communication_content": json.dumps({
                "monitor_id": monitor_id,
                "student_id": student_id,
                "trip_id": trip_id,
                "method": method,
                "status": trip_student.student_status,
                "timestamp": now_datetime().isoformat()
            })
        }).insert(ignore_permissions=True)

        message = "Student checked in successfully"
        if trip_auto_started:
            message += " (Trip auto-started)"
            
        return single_item_response({
            "student_id": student_id,
            "trip_id": trip_id,
            "status": trip_student.student_status,
            "timestamp": current_time,
            "method": method,
            "trip_auto_started": trip_auto_started
        }, message)

    except frappe.DoesNotExistError:
        return not_found_response("Trip or student not found")
    except Exception as e:
        frappe.log_error(f"Error checking student in: {str(e)}")
        return error_response(f"Check-in error: {str(e)}")


@frappe.whitelist(allow_guest=False)
def mark_student_absent():
    """
    Mark a student as absent for a trip
    Expected parameters (JSON):
    - student_id: Student ID
    - trip_id: Daily trip ID
    - reason: Absent reason (Nghỉ học, Nghỉ ốm, Nghỉ phép, Lý do khác)
    """
    try:
        user_email = frappe.session.user

        if not user_email or user_email == 'Guest':
            return error_response("Authentication required", code="AUTH_REQUIRED")

        # Get current monitor
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

        student_id = data.get('student_id')
        trip_id = data.get('trip_id')
        reason = data.get('reason', 'Lý do khác')

        if not student_id:
            return validation_error_response({"student_id": ["Student ID is required"]})

        if not trip_id:
            return validation_error_response({"trip_id": ["Trip ID is required"]})

        # Verify monitor has access to this trip
        trip = frappe.get_doc("SIS Bus Daily Trip", trip_id)

        if trip.monitor1_id != monitor_id and trip.monitor2_id != monitor_id:
            return forbidden_response("Access denied to this trip")

        # Find the trip student record
        trip_students = frappe.get_all(
            "SIS Bus Daily Trip Student",
            filters={
                "daily_trip_id": trip_id,
                "student_id": student_id
            },
            fields=["name"]
        )

        if not trip_students:
            return not_found_response("Student not assigned to this trip")

        trip_student = frappe.get_doc("SIS Bus Daily Trip Student", trip_students[0].name)

        # Mark as absent (with Administrator permissions)
        trip_student.student_status = "Absent"
        trip_student.absent_reason = reason

        frappe.set_user("Administrator")
        try:
            trip_student.flags.ignore_permissions = True
            trip_student.save(ignore_permissions=True)
            frappe.db.commit()
        finally:
            frappe.set_user("Guest")

        # Update trip statistics
        _update_trip_statistics(trip_id)

        # Log action
        frappe.get_doc({
            "doctype": "Activity Log",
            "subject": f"ABSENT: Student {student_id} marked absent in trip {trip_id}",
            "communication_date": now_datetime(),
            "full_communication_content": json.dumps({
                "monitor_id": monitor_id,
                "student_id": student_id,
                "trip_id": trip_id,
                "reason": reason,
                "status": "Absent",
                "timestamp": now_datetime().isoformat()
            })
        }).insert(ignore_permissions=True)

        return single_item_response({
            "student_id": student_id,
            "trip_id": trip_id,
            "status": "Absent",
            "reason": reason
        }, "Student marked as absent")

    except frappe.DoesNotExistError:
        return not_found_response("Trip or student not found")
    except Exception as e:
        frappe.log_error(f"Error marking student absent: {str(e)}")
        return error_response(f"Absent marking error: {str(e)}")


def _update_trip_statistics(trip_id):
    """
    Update trip statistics (checked_in_count, checked_out_count)
    """
    try:
        # Count boarded students (for pickup trips)
        boarded_count = frappe.db.sql("""
            SELECT COUNT(*) FROM `tabSIS Bus Daily Trip Student`
            WHERE daily_trip_id = %s AND student_status = 'Boarded'
        """, (trip_id,))[0][0]

        # Count dropped off students (for drop-off trips)
        dropped_count = frappe.db.sql("""
            SELECT COUNT(*) FROM `tabSIS Bus Daily Trip Student`
            WHERE daily_trip_id = %s AND student_status = 'Dropped Off'
        """, (trip_id,))[0][0]

        # Update trip
        frappe.db.set_value("SIS Bus Daily Trip", trip_id, {
            "checked_in_count": boarded_count,
            "checked_out_count": dropped_count
        })
        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error updating trip statistics: {str(e)}")


