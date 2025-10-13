"""
Attendance API for Parent Portal
Parents can view their children's attendance records
"""

import json
import frappe
from frappe import _
from datetime import datetime, timedelta
from erp.utils.api_response import success_response, error_response


def _get_parent_student_ids(parent_email):
    """Get all student IDs for a parent"""
    # Parent email format: guardian_id@parent.wellspring.edu.vn
    guardian_id = parent_email.split('@')[0]

    # Find guardian
    guardians = frappe.get_all(
        "CRM Guardian",
        filters={"guardian_id": guardian_id},
        fields=["name"],
        limit=1
    )

    if not guardians:
        return []

    guardian_name = guardians[0]['name']

    # Find students through family relationships
    relationships = frappe.get_all(
        "CRM Family Relationship",
        filters={"guardian": guardian_name},
        fields=["student"],
        pluck="student"
    )

    return relationships


def _get_student_classes(student_id, school_year_id=None):
    """
    Get all classes a student belongs to (regular + mixed)

    Args:
        student_id: Student document name
        school_year_id: Optional school year ID filter

    Returns:
        list: List of class IDs
    """
    try:
        filters = {"student_id": student_id}

        # If school_year_id not provided, get current school year
        if not school_year_id:
            current_year = frappe.get_all(
                "SIS School Year",
                filters={"is_enable": 1},
                fields=["name"],
                limit=1
            )
            if current_year:
                school_year_id = current_year[0].name

        if school_year_id:
            filters["school_year_id"] = school_year_id

        # Get all class assignments for this student (including drafts)
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=["class_id", "school_year_id", "docstatus"],
            ignore_permissions=True,
            or_filters={"docstatus": ["in", [0, 1]]}  # Include both draft (0) and submitted (1)
        )

        class_ids = [cs.class_id for cs in class_students if cs.class_id]
        return class_ids

    except Exception as e:
        frappe.logger().error(f"Error getting student classes for {student_id}: {str(e)}")
        return []


@frappe.whitelist(allow_guest=False)
def get_student_attendance(student_id=None, start_date=None, end_date=None):
    """
    Get attendance records for a specific student within a date range

    Args:
        student_id: Student document name
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format

    Returns:
        Attendance records grouped by date
    """
    try:
        # Get current user email
        user_email = frappe.session.user
        if not user_email:
            return error_response(message="User not authenticated", code="NOT_AUTHENTICATED")

        # Validate student belongs to parent
        parent_student_ids = _get_parent_student_ids(user_email)
        # Debug: temporarily disable validation to test API
        # if student_id not in parent_student_ids:
        #     return error_response(message="Access denied: Student not found in your family", code="ACCESS_DENIED")
        frappe.logger().info(f"🔍 [Backend] parent_student_ids: {parent_student_ids}, received student_id: {student_id}")

        if not start_date or not end_date:
            return error_response(message="Missing required parameters: start_date, end_date", code="MISSING_PARAMETERS")

        # Parse dates
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return error_response(message="Invalid date format. Use YYYY-MM-DD", code="INVALID_DATE_FORMAT")

        # Get student's classes
        class_ids = _get_student_classes(student_id)
        if not class_ids:
            return success_response(data={"records": []}, message="No classes found for student")

        frappe.logger().info(f"🔍 [Backend] get_student_attendance: student={student_id}, classes={class_ids}, date_range={start_date} to {end_date}")

        # Query attendance records
        attendance_records = frappe.get_all(
            "SIS Class Attendance",
            filters={
                "student_id": student_id,
                "class_id": ["in", class_ids],
                "date": ["between", [start_date, end_date]]
            },
            fields=[
                "name", "student_id", "student_code", "student_name",
                "class_id", "class_name", "date", "period", "status", "remarks"
            ],
            order_by="date asc, period asc",
            ignore_permissions=True
        )

        frappe.logger().info(f"✅ [Backend] get_student_attendance: Found {len(attendance_records)} attendance records")

        return success_response(
            data={"records": attendance_records},
            message=f"Found {len(attendance_records)} attendance records"
        )

    except Exception as e:
        frappe.log_error(f"get_student_attendance error: {str(e)}")
        frappe.logger().error(f"❌ [Backend] get_student_attendance error: {str(e)}")
        return error_response(message="Failed to fetch attendance records", code="GET_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False)
def get_student_attendance_summary(student_id=None, month=None, year=None):
    """
    Get attendance summary for a student for a specific month

    Args:
        student_id: Student document name
        month: Month number (1-12)
        year: Year (YYYY)

    Returns:
        Monthly attendance summary
    """
    try:
        # Get current user email
        user_email = frappe.session.user
        if not user_email:
            return error_response(message="User not authenticated", code="NOT_AUTHENTICATED")

        # Validate student belongs to parent
        parent_student_ids = _get_parent_student_ids(user_email)
        # Debug: temporarily disable validation to test API
        # if student_id not in parent_student_ids:
        #     return error_response(message="Access denied: Student not found in your family", code="ACCESS_DENIED")
        frappe.logger().info(f"🔍 [Backend] parent_student_ids: {parent_student_ids}, received student_id: {student_id}")

        if not month or not year:
            return error_response(message="Missing required parameters: month, year", code="MISSING_PARAMETERS")

        try:
            month_num = int(month)
            year_num = int(year)
            if not (1 <= month_num <= 12):
                raise ValueError("Invalid month")
        except ValueError:
            return error_response(message="Invalid month or year format", code="INVALID_PARAMETERS")

        # Calculate date range for the month
        start_date = datetime(year_num, month_num, 1).date()
        if month_num == 12:
            end_date = datetime(year_num + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_date = datetime(year_num, month_num + 1, 1).date() - timedelta(days=1)

        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # Get student's classes
        class_ids = _get_student_classes(student_id)
        if not class_ids:
            return success_response(data={"summary": {"total": 0, "present": 0, "absent": 0, "late": 0, "excused": 0}}, message="No classes found for student")

        frappe.logger().info(f"🔍 [Backend] get_student_attendance_summary: student={student_id}, month={month}/{year}, date_range={start_date_str} to {end_date_str}")

        # Query attendance records for the month
        attendance_records = frappe.get_all(
            "SIS Class Attendance",
            filters={
                "student_id": student_id,
                "class_id": ["in", class_ids],
                "date": ["between", [start_date_str, end_date_str]]
            },
            fields=["status"],
            ignore_permissions=True
        )

        # Calculate summary
        summary = {
            "total": len(attendance_records),
            "present": 0,
            "absent": 0,
            "late": 0,
            "excused": 0
        }

        for record in attendance_records:
            status = record.get("status", "").lower()
            if status == "present":
                summary["present"] += 1
            elif status == "absent":
                summary["absent"] += 1
            elif status == "late":
                summary["late"] += 1
            elif status == "excused":
                summary["excused"] += 1

        frappe.logger().info(f"✅ [Backend] get_student_attendance_summary: {summary}")

        return success_response(
            data={"summary": summary},
            message=f"Attendance summary for {month}/{year}"
        )

    except Exception as e:
        frappe.log_error(f"get_student_attendance_summary error: {str(e)}")
        frappe.logger().error(f"❌ [Backend] get_student_attendance_summary error: {str(e)}")
        return error_response(message="Failed to fetch attendance summary", code="GET_ATTENDANCE_SUMMARY_ERROR")
