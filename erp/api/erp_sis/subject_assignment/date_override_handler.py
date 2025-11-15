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
        
        # Determine teacher assignment
        pattern_teacher_1 = pattern_row.get("teacher_1_id")
        pattern_teacher_2 = pattern_row.get("teacher_2_id")
        
        # Assign new teacher to appropriate slot
        if not pattern_teacher_1:
            # Slot 1 is free, assign new teacher there
            override_teacher_1 = teacher_id
            override_teacher_2 = pattern_teacher_2
        elif not pattern_teacher_2:
            # Slot 1 is taken but slot 2 is free, assign new teacher to slot 2
            override_teacher_1 = pattern_teacher_1
            override_teacher_2 = teacher_id
        else:
            # Both slots taken, but still assign to slot 1 (override pattern assignment)
            override_teacher_1 = teacher_id
            override_teacher_2 = pattern_teacher_2
        
        import frappe
        frappe.logger().info(f"📝 CREATE OVERRIDE ROW - date={specific_date}, pattern_teacher_1={pattern_teacher_1}, pattern_teacher_2={pattern_teacher_2}")
        frappe.logger().info(f"                       override_teacher_1={override_teacher_1}, override_teacher_2={override_teacher_2}")
        
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
            "room_id": pattern_row.get("room_id")
        })
        
        # Populate teachers child table
        # Collect all teachers (new teacher + pattern teachers)
        teachers_to_assign = []
        if override_teacher_1:
            teachers_to_assign.append(override_teacher_1)
        if override_teacher_2 and override_teacher_2 != override_teacher_1:
            teachers_to_assign.append(override_teacher_2)
        
        for idx, teacher_id_val in enumerate(teachers_to_assign):
            override_doc.append("teachers", {
                "teacher_id": teacher_id_val,
                "sort_order": idx
            })
        
        override_doc.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.logger().info(f"✅ Created override row {override_doc.name} for date {specific_date} with teacher_1={override_teacher_1}, teacher_2={override_teacher_2}")
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
        subject_ids: List of SIS Subject IDs (not Actual Subject IDs)
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
            frappe.logger().info(f"🗑️ DELETE OVERRIDE ROWS - No instances found for classes {class_ids}")
            return 0
        
        instance_ids = [i.name for i in instances]
        
        frappe.logger().info(f"🗑️ DELETE OVERRIDE ROWS - Found {len(instances)} instances")
        frappe.logger().info(f"   - instance_ids: {instance_ids}")
        frappe.logger().info(f"   - subject_ids: {subject_ids}")
        frappe.logger().info(f"   - teacher_id: {teacher_id}")
        
        # Delete override rows (date IS NOT NULL) for this teacher and subject
        # Method 1: Delete rows where teacher is assigned (teacher_1_id or teacher_2_id)
        deleted_count_by_teacher = frappe.db.sql("""
            DELETE FROM `tabSIS Timetable Instance Row`
            WHERE date IS NOT NULL
              AND parent IN ({})
              AND subject_id IN ({})
              AND (teacher_1_id = %s OR teacher_2_id = %s)
        """.format(
            ','.join(['%s'] * len(instance_ids)),
            ','.join(['%s'] * len(subject_ids))
        ), tuple(instance_ids + subject_ids + [teacher_id, teacher_id]))
        
        frappe.logger().info(f"🗑️ DELETE OVERRIDE ROWS - Deleted {deleted_count_by_teacher} rows with teacher assignment")
        
        # Method 2: Also delete orphaned override rows (date IS NOT NULL) with no teacher
        # This handles override rows created but not properly assigned
        deleted_count_orphaned = frappe.db.sql("""
            DELETE FROM `tabSIS Timetable Instance Row`
            WHERE date IS NOT NULL
              AND parent IN ({})
              AND subject_id IN ({})
              AND teacher_1_id IS NULL
              AND teacher_2_id IS NULL
        """.format(
            ','.join(['%s'] * len(instance_ids)),
            ','.join(['%s'] * len(subject_ids))
        ), tuple(instance_ids + subject_ids))
        
        frappe.logger().info(f"🗑️ DELETE OVERRIDE ROWS - Deleted {deleted_count_orphaned} orphaned override rows (no teacher)")
        
        total_deleted = deleted_count_by_teacher + deleted_count_orphaned
        frappe.logger().info(f"✅ Total override rows deleted: {total_deleted}")
        return total_deleted
        
    except Exception as e:
        frappe.logger().error(f"❌ Error deleting override rows: {str(e)}")
        return 0

