# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Date-specific override row handler for Subject Assignment.

Xử lý các phân công giáo viên theo ngày cụ thể (date-specific overrides)
cho các trường hợp phân công có thời hạn (from_date assignments).
"""

import frappe
from datetime import timedelta


def create_date_override_row(instance_id, pattern_row, specific_date, teacher_id, campus_id):
    """
    🎯 Create a date-specific override row from a pattern row.
    
    Args:
        instance_id: Parent timetable instance
        pattern_row: Source pattern row (date=NULL)
        specific_date: Specific date for this override (date or datetime)
        teacher_id: Teacher to assign
        campus_id: Campus ID
    
    Returns:
        str: Created row name or None if failed
    """
    try:
        # Ensure specific_date is a date object (not datetime)
        if hasattr(specific_date, 'date'):
            specific_date = specific_date.date()
        
        # Get data from pattern_row (should already have all fields from query)
        period_priority = pattern_row.get("period_priority")
        period_name = pattern_row.get("period_name")
        timetable_column_id = pattern_row.get("timetable_column_id")
        
        # Clone pattern row data
        override_doc = frappe.get_doc({
            "doctype": "SIS Timetable Instance Row",
            "parent": instance_id,
            "parenttype": "SIS Timetable Instance",
            "parentfield": "weekly_pattern",
            "day_of_week": pattern_row.get("day_of_week"),
            "date": specific_date,  # ✅ KEY: Specific date
            "timetable_column_id": timetable_column_id,
            "period_priority": period_priority,
            "period_name": period_name,
            "subject_id": pattern_row.get("subject_id"),
            "room_id": pattern_row.get("room_id"),
            # Assign teacher
            "teacher_1_id": pattern_row.get("teacher_1_id") or teacher_id,
            "teacher_2_id": teacher_id if pattern_row.get("teacher_1_id") else pattern_row.get("teacher_2_id")
        })
        
        override_doc.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.logger().info(f"✅ Created override row {override_doc.name} for date {specific_date}")
        return override_doc.name
        
    except Exception as e:
        frappe.logger().error(f"❌ Failed to create override row for date {specific_date}: {str(e)}")
        return None


def calculate_dates_in_range(start_date, end_date, day_of_week, instance_start, instance_end):
    """
    Calculate all dates matching day_of_week within the assignment range.
    
    Args:
        start_date: Assignment start date
        end_date: Assignment end date (None = no end)
        day_of_week: "mon", "tue", etc
        instance_start: Instance start date
        instance_end: Instance end date
    
    Returns:
        list: List of date objects
    """
    import frappe
    
    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    target_weekday = day_map.get(day_of_week)
    
    if target_weekday is None:
        frappe.logger().error(f"❌ Invalid day_of_week: {day_of_week}")
        return []
    
    # Validate inputs
    if not start_date or not instance_start or not instance_end:
        frappe.logger().error(f"❌ Missing required dates: start_date={start_date}, instance_start={instance_start}, instance_end={instance_end}")
        return []
    
    # Find first occurrence of this weekday in instance
    current_date = instance_start
    current_weekday = current_date.weekday()
    days_ahead = target_weekday - current_weekday
    if days_ahead < 0:
        days_ahead += 7
    first_occurrence = current_date + timedelta(days=days_ahead)
    
    frappe.logger().info(f"📅 DATE CALC: day_of_week={day_of_week}, target_weekday={target_weekday}, current_weekday={current_weekday}")
    frappe.logger().info(f"📅 DATE CALC: First occurrence of {day_of_week}: {first_occurrence}")
    frappe.logger().info(f"📅 DATE CALC: Assignment range: {start_date} to {end_date if end_date else 'no end'}")
    frappe.logger().info(f"📅 DATE CALC: Instance range: {instance_start} to {instance_end}")
    
    # Collect all dates in range
    dates = []
    check_date = first_occurrence
    
    while check_date <= instance_end:
        # Check if within assignment range
        if check_date >= start_date:
            if end_date:
                if check_date <= end_date:
                    dates.append(check_date)
            else:
                dates.append(check_date)
        
        check_date += timedelta(days=7)  # Next week
    
    frappe.logger().info(f"✅ DATE CALC: Calculated {len(dates)} dates for {day_of_week}")
    if len(dates) > 0:
        frappe.logger().info(f"   - First date: {dates[0]}, Last date: {dates[-1]}")
    
    return dates


def delete_teacher_override_rows(teacher_id, subject_ids, class_ids, campus_id):
    """
    Delete date-specific override rows for a teacher's assignments.
    
    This is called when:
    1. Assignment is deleted
    2. Assignment date range is changed (will recreate with new dates)
    
    Args:
        teacher_id: Teacher ID
        subject_ids: List of subject IDs
        class_ids: List of class IDs
        campus_id: Campus ID
        
    Returns:
        int: Number of rows deleted
    """
    try:
        # Get all instances for affected classes
        instances = frappe.get_all(
            "SIS Timetable Instance",
            fields=["name"],
            filters={
                "campus_id": campus_id,
                "class_id": ["in", class_ids]
            }
        )
        
        if not instances:
            return 0
        
        instance_ids = [i.name for i in instances]
        
        # Delete override rows (date IS NOT NULL) for this teacher
        deleted_count = frappe.db.sql("""
            DELETE FROM `tabSIS Timetable Instance Row`
            WHERE date IS NOT NULL
              AND parent IN ({})
              AND subject_id IN ({})
              AND (teacher_1_id = %s OR teacher_2_id = %s)
        """.format(
            ','.join(['%s'] * len(instance_ids)),
            ','.join(['%s'] * len(subject_ids))
        ), tuple(instance_ids + subject_ids + [teacher_id, teacher_id]))
        
        frappe.logger().info(f"🗑️ Deleted {deleted_count} override rows for teacher {teacher_id}")
        return deleted_count
        
    except Exception as e:
        frappe.logger().error(f"❌ Error deleting override rows: {str(e)}")
        return 0

