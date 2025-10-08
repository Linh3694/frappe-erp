import frappe
from typing import Optional, Dict, Any, List


# Utilities
def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _get_request_arg(name: str, fallback: Optional[Any] = None) -> Optional[str]:
    # Try both form_dict and request.args to be robust
    if hasattr(frappe, "local") and getattr(frappe.local, "form_dict", None):
        val = frappe.local.form_dict.get(name)
        if val is not None:
            return val
    if hasattr(frappe, "request") and getattr(frappe.request, "args", None):
        val = frappe.request.args.get(name)
        if val is not None:
            return val
    return fallback


@frappe.whitelist()
def get_calendar_events(school_year_id=None, start_date=None, end_date=None):
    """
    Get calendar events for parent portal

    Args:
        school_year_id: Optional school year filter
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        dict: Calendar events with success status
    """
    logs = []

    try:
        # Get current user's guardian and students to determine school year
        user_email = frappe.session.user
        if "@parent.wellspring.edu.vn" not in user_email:
            return {
                "success": False,
                "message": "Tài khoản không hợp lệ",
                "logs": logs
            }

        guardian_id = user_email.split("@")[0]

        # Get guardian's students
        guardian_list = frappe.db.get_list(
            "CRM Guardian",
            filters={"guardian_id": guardian_id},
            fields=["name"],
            ignore_permissions=True
        )

        if not guardian_list:
            return {
                "success": False,
                "message": "Không tìm thấy thông tin phụ huynh",
                "logs": logs
            }

        # Get first student's class to determine school year if not provided
        relationships = frappe.get_all(
            "CRM Family Relationship",
            filters={"guardian": guardian_list[0].name},
            fields=["student"],
            ignore_permissions=True,
            limit=1
        )

        if not relationships:
            return {
                "success": False,
                "message": "Không tìm thấy học sinh",
                "logs": logs
            }

        student_id = relationships[0].student

        # Get student's current class and school year
        if not school_year_id:
            class_students = frappe.get_all(
                "SIS Class Student",
                filters={"student_id": student_id},
                fields=["class_id", "school_year_id"],
                ignore_permissions=True,
                order_by="creation desc",  # Get the most recent one
                limit=1
            )

            if class_students:
                school_year_id = class_students[0].school_year_id

        # Build filters
        filters = {}
        if school_year_id:
            filters["school_year_id"] = school_year_id

        # Date range filtering
        conditions = []
        params = {}

        if start_date and end_date:
            conditions.append("(start_date <= %(end_date)s AND end_date >= %(start_date)s)")
            params.update({"start_date": start_date, "end_date": end_date})
        elif start_date:
            conditions.append("end_date >= %(start_date)s")
            params.update({"start_date": start_date})
        elif end_date:
            conditions.append("start_date <= %(end_date)s")
            params.update({"end_date": end_date})

        # Add filters to conditions
        for key, value in filters.items():
            conditions.append(f"{key} = %({key})s")
            params[key] = value

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Query calendar events
        events = frappe.db.sql(f"""
            SELECT
                name,
                title,
                type,
                start_date,
                end_date,
                description,
                school_year_id
            FROM `tabSIS Calendar`
            {where_clause}
            ORDER BY start_date ASC
        """, params, as_dict=True)

        logs.append(f"Found {len(events)} calendar events")

        return {
            "success": True,
            "message": "Lấy dữ liệu lịch thành công",
            "data": events,
            "logs": logs
        }

    except Exception as e:
        logs.append(f"Error getting calendar events: {str(e)}")
        frappe.log_error(f"Parent Portal Calendar Error: {str(e)}", "Parent Portal Calendar")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }
