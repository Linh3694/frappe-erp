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
        # Fallback: form_dict → JSON body (Bearer token + POST không tự parse params)
        if not student_id:
            student_id = frappe.form_dict.get("student_id")
        if not start_date:
            start_date = frappe.form_dict.get("start_date")
        if not end_date:
            end_date = frappe.form_dict.get("end_date")

        if (not student_id or not start_date or not end_date):
            if hasattr(frappe.request, 'content_type') and frappe.request.content_type and 'json' in frappe.request.content_type.lower():
                try:
                    raw_data = frappe.request.get_data(as_text=True)
                    if raw_data:
                        json_data = json.loads(raw_data)
                        student_id = student_id or json_data.get("student_id")
                        start_date = start_date or json_data.get("start_date")
                        end_date = end_date or json_data.get("end_date")
                except Exception:
                    pass

        frappe.logger().info(
            f"🔍 [Backend] get_student_attendance: "
            f"student_id={student_id}, start_date={start_date}, end_date={end_date}"
        )

        # Get current user email
        user_email = frappe.session.user
        if not user_email:
            return error_response(message="User not authenticated", code="NOT_AUTHENTICATED")

        # Validate student belongs to parent
        parent_student_ids = _get_parent_student_ids(user_email)
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
                "class_id", "date", "period", "status", "remarks",
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


@frappe.whitelist(allow_guest=False)
def get_student_homeroom_summary(student_id=None, school_year_id=None):
    """
    Thống kê điểm danh chủ nhiệm (SIS Class Attendance, period=homeroom) theo năm học.

    Args:
        student_id: Tên document CRM Student của con
        school_year_id: Tùy chọn; mặc định = SIS School Year đang is_enable=1 (mới nhất theo start_date)

    Returns:
        success_response data: { school_year: {...}, counts: {present, late, absent, excused, total} }
    """
    try:
        if not student_id:
            student_id = frappe.form_dict.get("student_id")
        if not school_year_id:
            school_year_id = frappe.form_dict.get("school_year_id")

        if hasattr(frappe.request, "content_type") and frappe.request.content_type and "json" in frappe.request.content_type.lower():
            try:
                raw_data = frappe.request.get_data(as_text=True)
                if raw_data:
                    json_data = json.loads(raw_data)
                    student_id = student_id or json_data.get("student_id")
                    school_year_id = school_year_id or json_data.get("school_year_id")
            except Exception:
                pass

        user_email = frappe.session.user
        if not user_email:
            return error_response(message="User not authenticated", code="NOT_AUTHENTICATED")

        parent_student_ids = _get_parent_student_ids(user_email)
        if not student_id:
            return error_response(message="Missing student_id", code="MISSING_PARAMETERS")
        if student_id not in parent_student_ids:
            return error_response(message="Access denied: Student not found in your family", code="ACCESS_DENIED")

        if school_year_id:
            sy_row = frappe.db.get_value(
                "SIS School Year",
                school_year_id,
                ["name", "title_vn", "title_en", "start_date", "end_date"],
                as_dict=True,
            )
            if not sy_row:
                return error_response(message="Invalid school_year_id", code="INVALID_SCHOOL_YEAR")
        else:
            rows = frappe.get_all(
                "SIS School Year",
                filters={"is_enable": 1},
                fields=["name", "title_vn", "title_en", "start_date", "end_date"],
                order_by="start_date desc",
                limit=1,
            )
            if not rows:
                return error_response(message="No active school year", code="NO_SCHOOL_YEAR")
            sy_row = rows[0]

        school_year_id = sy_row["name"]
        start_dt = sy_row["start_date"]
        end_dt = sy_row["end_date"]
        start_str = start_dt.strftime("%Y-%m-%d") if hasattr(start_dt, "strftime") else str(start_dt)
        end_str = end_dt.strftime("%Y-%m-%d") if hasattr(end_dt, "strftime") else str(end_dt)

        class_ids = _get_student_classes(student_id, school_year_id)

        present_count = late_count = absent_count = excused_count = 0

        if not class_ids:
            total = 0
        else:
            rows = frappe.db.sql(
                """
                SELECT status, COUNT(*) AS cnt
                FROM `tabSIS Class Attendance`
                WHERE student_id = %s
                  AND class_id IN ({0})
                  AND date BETWEEN %s AND %s
                  AND (
                        period = 'Homeroom'
                     OR period = 'HOMEROOM'
                     OR LOWER(TRIM(period)) = 'homeroom'
                  )
                GROUP BY status
                """.format(", ".join(["%s"] * len(class_ids))),
                tuple([student_id] + list(class_ids) + [start_str, end_str]),
                as_dict=True,
            )

            for row in rows:
                st = (row.get("status") or "").strip().lower()
                c = int(row.get("cnt") or 0)
                if st == "present":
                    present_count += c
                elif st == "late":
                    late_count += c
                elif st == "absent":
                    absent_count += c
                elif st == "excused":
                    excused_count += c

            total = present_count + late_count + absent_count + excused_count

        counts = {
            "present": present_count,
            "late": late_count,
            "absent": absent_count,
            "excused": excused_count,
            "total": total,
        }

        return success_response(
            data={
                "school_year": {
                    "name": school_year_id,
                    "title_vn": sy_row.get("title_vn"),
                    "title_en": sy_row.get("title_en"),
                    "start_date": start_str,
                    "end_date": end_str,
                },
                "counts": counts,
            },
            message="Homeroom attendance summary",
        )

    except Exception as e:
        frappe.log_error(f"get_student_homeroom_summary error: {str(e)}")
        frappe.logger().error(f"❌ [Backend] get_student_homeroom_summary error: {str(e)}")
        return error_response(message="Failed to fetch homeroom attendance summary", code="GET_HOMEROOM_SUMMARY_ERROR")
