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
def get_calendar_events(school_year_id=None, start_date=None, end_date=None, student_id=None):
    """
    Get calendar events for parent portal

    Args:
        school_year_id: Optional school year filter
        start_date: Optional start date filter
        end_date: Optional end date filter
        student_id: Optional student ID to get education stage (if not provided, uses first student)

    Returns:
        dict: Calendar events with success status
    """
    logs = []

    try:
        # Get parameters from request (fallback to function args)
        student_id = _get_request_arg("student_id", student_id)
        school_year_id = _get_request_arg("school_year_id", school_year_id)
        start_date = _get_request_arg("start_date", start_date)
        end_date = _get_request_arg("end_date", end_date)
        
        logs.append(f"Received parameters - student_id: {student_id}, school_year_id: {school_year_id}, start_date: {start_date}, end_date: {end_date}")
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

        # If student_id is provided, use it; otherwise get first student
        if not student_id:
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
        
        logs.append(f"Using student_id: {student_id}")

        # Get student's current class, school year, and education stage
        education_stage_id = None
        
        # Always get student's class info to determine education_stage
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"student_id": student_id},
            fields=["class_id", "school_year_id"],
            ignore_permissions=True,
            order_by="creation desc",  # Get the most recent one
            limit=1
        )

        if class_students:
            # Set school_year_id if not provided
            if not school_year_id:
                school_year_id = class_students[0].school_year_id
                logs.append(f"Auto-detected school_year_id from student's class: {school_year_id}")
            
            class_id = class_students[0].class_id
            logs.append(f"Student class_id: {class_id}")
            
            # Get class education_grade to determine education_stage
            class_info = frappe.get_value(
                "SIS Class",
                class_id,
                ["education_grade"],
                as_dict=True
            )
            
            if class_info and class_info.education_grade:
                logs.append(f"Education grade: {class_info.education_grade}")
                # Get education_stage from education_grade
                grade_info = frappe.get_value(
                    "SIS Education Grade",
                    class_info.education_grade,
                    ["education_stage_id"],
                    as_dict=True
                )
                if grade_info:
                    education_stage_id = grade_info.education_stage_id
                    logs.append(f"Student education stage: {education_stage_id}")
                else:
                    logs.append(f"No grade_info found for education_grade: {class_info.education_grade}")
            else:
                logs.append(f"No class_info or education_grade found for class_id: {class_id}")
        else:
            logs.append(f"No class_students found for student_id: {student_id}")

        # Build filters
        # Chỉ filter theo school_year_id nếu KHÔNG có date range được cung cấp
        # Nếu có date range thì ưu tiên lấy tất cả events trong khoảng thời gian đó
        filters = {}
        has_date_range = start_date or end_date
        
        if school_year_id and not has_date_range:
            # Chỉ filter theo school_year khi không có date range
            filters["school_year_id"] = school_year_id
            logs.append(f"Filtering by school_year_id: {school_year_id} (no date range provided)")
        elif has_date_range:
            logs.append(f"Filtering by date range only (ignoring school_year_id to get all events in period)")

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
        
        logs.append(f"SQL query returned {len(events)} total events before education stage filtering")

        # Filter events by education_stage if available
        if education_stage_id:
            filtered_events = []
            for event in events:
                # Get education stages for this event
                event_stages = frappe.get_all(
                    "SIS Calendar Education Stage",
                    filters={"parent": event["name"]},
                    fields=["education_stage_id"],
                    pluck="education_stage_id"
                )
                
                # Debug log for first few events
                if len(filtered_events) < 3:
                    logs.append(f"Event '{event['title']}' ({event['name']}) has stages: {event_stages}, looking for: {education_stage_id}")
                
                # Include event if it has the student's education stage
                # Hoặc nếu event không có education_stages (event toàn trường)
                if not event_stages or education_stage_id in event_stages:
                    event["education_stages"] = event_stages
                    filtered_events.append(event)
            
            events = filtered_events
            logs.append(f"Filtered to {len(events)} events for education stage {education_stage_id}")
        else:
            # If no education stage, still add education_stages to each event
            for event in events:
                event_stages = frappe.get_all(
                    "SIS Calendar Education Stage",
                    filters={"parent": event["name"]},
                    fields=["education_stage_id"],
                    pluck="education_stage_id"
                )
                event["education_stages"] = event_stages

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
