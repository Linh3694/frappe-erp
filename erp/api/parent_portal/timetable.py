"""
Parent Portal Timetable API
Handles student timetable retrieval for parent portal
"""

import frappe
from frappe import _
from datetime import datetime, timedelta
import json
from erp.utils.api_response import validation_error_response, list_response, error_response


def _parse_iso_date(date_str):
    """Parse ISO date string to datetime object"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def _add_days(dt, days):
    """Add days to datetime object"""
    if not dt:
        return None
    return dt + timedelta(days=days)


def _get_student_classes(student_id, school_year_id=None):
    """
    Get all classes a student belongs to (regular + mixed)
    
    Args:
        student_id: Student document name
        school_year_id: Optional school year ID filter
        
    Returns:
        list: List of class IDs
    """
    logs = []
    
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
        
        logs.append(f"🔍 Looking for classes with filters: {filters}")
        
        # Get all class assignments for this student
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=["class_id", "school_year_id"],
            ignore_permissions=True
        )
        
        logs.append(f"✅ Found {len(class_students)} class assignments")
        
        class_ids = [cs.class_id for cs in class_students if cs.class_id]
        logs.append(f"📚 Class IDs: {class_ids}")
        
        return {
            "success": True,
            "class_ids": class_ids,
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"❌ Error getting student classes: {str(e)}")
        return {
            "success": False,
            "class_ids": [],
            "logs": logs,
            "error": str(e)
        }


def _get_class_timetable_for_date(class_id, target_date):
    """
    Get timetable for a specific class on a specific date
    
    Args:
        class_id: Class document name
        target_date: datetime object for target date
        
    Returns:
        list: List of timetable entries for that date
    """
    logs = []
    
    try:
        target_date_str = target_date.strftime("%Y-%m-%d")
        day_of_week = target_date.strftime("%A").lower()[:3]  # Convert to lowercase 3-letter format: tue, mon, etc.
        
        logs.append(f"📅 Getting timetable for class {class_id} on {target_date_str} ({day_of_week})")
        
        # Find timetable instances for this class that cover this date
        instance_filters = {
            "class_id": class_id,
            "start_date": ["<=", target_date_str],
            "end_date": [">=", target_date_str]
        }
        
        instances = frappe.get_all(
            "SIS Timetable Instance",
            fields=["name", "class_id", "start_date", "end_date"],
            filters=instance_filters,
            ignore_permissions=True
        )
        
        if not instances:
            logs.append(f"⚠️ No timetable instance found for class {class_id} on {target_date_str}")
            return {
                "success": True,
                "entries": [],
                "logs": logs
            }
        
        instance_ids = [i.name for i in instances]
        logs.append(f"✅ Found {len(instance_ids)} timetable instance(s): {instance_ids}")
        
        # Get timetable rows for this day of week - with fallback query
        rows = []
        try:
            # Try standard parent field first
            row_filters = {
                "parent": ["in", instance_ids],
                "parenttype": "SIS Timetable Instance",
                "parentfield": "weekly_pattern",
                "day_of_week": day_of_week
            }
            
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=[
                    "name",
                    "parent",
                    "day_of_week",
                    "timetable_column_id",
                    "subject_id",
                    "teacher_1_id",
                    "teacher_2_id",
                    "room_id"
                ],
                filters=row_filters,
                order_by="timetable_column_id asc",
                ignore_permissions=True
            )
            logs.append(f"✅ Queried with 'parent' field - found {len(rows)} rows")
        except Exception as e:
            logs.append(f"⚠️ Error with 'parent' field: {str(e)}")
        
        # Fallback: try parent_timetable_instance field
        if not rows:
            try:
                logs.append(f"🔄 Trying fallback with 'parent_timetable_instance' field")
                alt_rows = frappe.get_all(
                    "SIS Timetable Instance Row",
                    fields=[
                        "name",
                        "parent_timetable_instance",
                        "day_of_week",
                        "timetable_column_id",
                        "subject_id",
                        "teacher_1_id",
                        "teacher_2_id",
                        "room_id"
                    ],
                    filters={
                        "parent_timetable_instance": ["in", instance_ids],
                        "day_of_week": day_of_week
                    },
                    order_by="timetable_column_id asc",
                    ignore_permissions=True
                )
                # Normalize to same shape
                for r in alt_rows:
                    r["parent"] = r.get("parent_timetable_instance")
                rows = alt_rows
                logs.append(f"✅ Fallback query found {len(rows)} rows")
            except Exception as e2:
                logs.append(f"❌ Fallback query also failed: {str(e2)}")
        
        logs.append(f"✅ Found {len(rows)} timetable entries for {day_of_week}")
        
        # Enrich with subject titles, teacher names, and room info
        for row in rows:
            row["class_id"] = class_id

            # Get subject title
            if row.get("subject_id"):
                try:
                    subject = frappe.get_doc("SIS Subject", row["subject_id"])
                    row["subject_title"] = subject.title

                    # Get timetable subject if available
                    if subject.get("timetable_subject_id"):
                        try:
                            tt_subject = frappe.get_doc("SIS Timetable Subject", subject.timetable_subject_id)
                            row["timetable_subject_title"] = tt_subject.title_vn or tt_subject.title_en
                        except:
                            row["timetable_subject_title"] = ""
                    else:
                        row["timetable_subject_title"] = ""
                except:
                    row["subject_title"] = ""
                    row["timetable_subject_title"] = ""

            # Get teacher names
            teacher_names = []
            for teacher_field in ["teacher_1_id", "teacher_2_id"]:
                teacher_id = row.get(teacher_field)
                if teacher_id:
                    try:
                        teacher = frappe.get_doc("SIS Teacher", teacher_id)
                        if teacher.user_id:
                            user = frappe.get_doc("User", teacher.user_id)
                            teacher_names.append(user.full_name or user.first_name)
                    except:
                        pass
            row["teacher_names"] = ", ".join(teacher_names)

            # Get room info
            if row.get("room_id"):
                try:
                    room = frappe.get_doc("SIS Room", row["room_id"])
                    row["room_title"] = room.title
                except:
                    row["room_title"] = ""

            # Get timetable column info (period time and type)
            if row.get("timetable_column_id"):
                try:
                    column = frappe.get_doc("SIS Timetable Column", row["timetable_column_id"])
                    row["period_name"] = column.title
                    row["start_time"] = column.start_time.strftime("%H:%M") if column.start_time else None
                    row["end_time"] = column.end_time.strftime("%H:%M") if column.end_time else None
                    row["period_type"] = column.period_type  # Add period_type to response
                except:
                    row["period_name"] = ""
                    row["period_type"] = ""

        # Check for date-specific overrides (from custom table)
        overrides = []
        try:
            overrides = frappe.db.sql("""
                SELECT timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type
                FROM `tabTimetable_Date_Override`
                WHERE target_type = %s AND target_id = %s AND date = %s
            """, ("Class", class_id, target_date_str), as_dict=True)
        except Exception as override_error:
            # Table might not exist or no overrides - that's okay
            logs.append(f"ℹ️ No overrides table or no overrides found: {str(override_error)}")
        
        if overrides:
            logs.append(f"🔄 Found {len(overrides)} override(s) for {target_date_str}")
            
            # Apply overrides
            for override in overrides:
                column_id = override.get("timetable_column_id")
                override_type = override.get("override_type")
                
                # Find matching row
                matching_rows = [r for r in rows if r.get("timetable_column_id") == column_id]
                
                if override_type == "cancellation":
                    # Remove the period
                    rows = [r for r in rows if r.get("timetable_column_id") != column_id]
                elif override_type == "change" and matching_rows:
                    # Update the period
                    row = matching_rows[0]
                    if override.get("subject_id"):
                        row["subject_id"] = override["subject_id"]
                        # Re-fetch subject title
                        try:
                            subject = frappe.get_doc("SIS Subject", override["subject_id"])
                            row["subject_title"] = subject.title
                        except:
                            pass
                    
                    if override.get("teacher_1_id"):
                        row["teacher_1_id"] = override["teacher_1_id"]
                    if override.get("teacher_2_id"):
                        row["teacher_2_id"] = override["teacher_2_id"]
                    
                    # Re-fetch teacher names
                    teacher_names = []
                    for teacher_field in ["teacher_1_id", "teacher_2_id"]:
                        teacher_id = row.get(teacher_field)
                        if teacher_id:
                            try:
                                teacher = frappe.get_doc("SIS Teacher", teacher_id)
                                if teacher.user_id:
                                    user = frappe.get_doc("User", teacher.user_id)
                                    teacher_names.append(user.full_name or user.first_name)
                            except:
                                pass
                    row["teacher_names"] = ", ".join(teacher_names)
                    
                    if override.get("room_id"):
                        row["room_id"] = override["room_id"]
                        try:
                            room = frappe.get_doc("SIS Room", override["room_id"])
                            row["room_title"] = room.title
                        except:
                            row["room_title"] = ""
        
        return {
            "success": True,
            "entries": rows,
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"❌ Error getting class timetable: {str(e)}")
        frappe.log_error(f"Get Class Timetable Error: {str(e)}", "Parent Portal Timetable")
        return {
            "success": False,
            "entries": [],
            "logs": logs,
            "error": str(e)
        }


@frappe.whitelist()
def get_student_timetable_today(student_id=None):
    """
    Get student timetable for today
    Combines timetables from all classes (regular + mixed) the student belongs to
    
    Args:
        student_id: Student document name (optional, will use current user's students if not provided)
        
    Returns:
        dict: Combined timetable for today
    """
    logs = []
    
    try:
        # If student_id not provided, try to get from current user
        if not student_id:
            # Get guardian from current user
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
            
            # For now, use first student (in the future, frontend should pass student_id)
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
        
        logs.append(f"📚 Getting timetable for student: {student_id}")
        
        # Get today's date
        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")
        day_of_week_full = today.strftime("%A")  # For display: Tuesday
        day_of_week = day_of_week_full.lower()[:3]  # For query: tue
        
        logs.append(f"📅 Today: {today_str} ({day_of_week_full})")
        
        # Get all classes for this student
        class_result = _get_student_classes(student_id)
        logs.extend(class_result.get("logs", []))
        
        if not class_result.get("success"):
            return {
                "success": False,
                "message": "Không thể lấy danh sách lớp của học sinh",
                "logs": logs
            }
        
        class_ids = class_result.get("class_ids", [])
        
        if not class_ids:
            return {
                "success": True,
                "message": "Học sinh chưa được xếp vào lớp nào",
                "data": {
                    "date": today_str,
                    "day_of_week": day_of_week,
                    "entries": []
                },
                "logs": logs
            }
        
        # Get timetable for each class and combine
        all_entries = []
        for class_id in class_ids:
            class_result = _get_class_timetable_for_date(class_id, today)
            logs.extend(class_result.get("logs", []))
            
            if class_result.get("success"):
                entries = class_result.get("entries", [])
                all_entries.extend(entries)
        
        # Sort by period time
        all_entries.sort(key=lambda x: (x.get("start_time") or "", x.get("timetable_column_id") or ""))
        
        logs.append(f"✅ Combined {len(all_entries)} timetable entries from {len(class_ids)} classes")
        
        return {
            "success": True,
            "message": "Thời khóa biểu hôm nay",
            "data": {
                "date": today_str,
                "day_of_week": day_of_week_full,  # Return full name for display
                "entries": all_entries
            },
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(f"Get Student Timetable Today Error: {str(e)}\nLogs: {json.dumps(logs)}", "Parent Portal Timetable")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }


@frappe.whitelist()
def get_student_timetable_week(student_id=None, week_start=None, week_end=None):
    """
    Get student timetable for a week
    Combines timetables from all classes (regular + mixed) the student belongs to
    
    Args:
        student_id: Student document name (optional, will use current user's students if not provided)
        week_start: Week start date (YYYY-MM-DD), defaults to this Monday
        week_end: Week end date (YYYY-MM-DD), defaults to this Sunday
        
    Returns:
        dict: Combined timetable for the week
    """
    logs = []
    
    try:
        # If student_id not provided, try to get from current user
        if not student_id:
            # Get guardian from current user
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
            
            # For now, use first student (in the future, frontend should pass student_id)
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
        
        logs.append(f"📚 Getting weekly timetable for student: {student_id}")
        
        # Parse or default week dates
        if not week_start:
            today = datetime.now()
            # Get Monday of this week (weekday 0 = Monday)
            days_since_monday = today.weekday()
            monday = today - timedelta(days=days_since_monday)
            week_start = monday.strftime("%Y-%m-%d")
        
        ws = _parse_iso_date(week_start)
        we = _parse_iso_date(week_end) if week_end else _add_days(ws, 6)  # Sunday
        
        logs.append(f"📅 Week: {ws.strftime('%Y-%m-%d')} to {we.strftime('%Y-%m-%d')}")
        
        # Get all classes for this student
        class_result = _get_student_classes(student_id)
        logs.extend(class_result.get("logs", []))
        
        if not class_result.get("success"):
            return {
                "success": False,
                "message": "Không thể lấy danh sách lớp của học sinh",
                "logs": logs
            }
        
        class_ids = class_result.get("class_ids", [])
        
        if not class_ids:
            return {
                "success": True,
                "message": "Học sinh chưa được xếp vào lớp nào",
                "data": {
                    "week_start": ws.strftime("%Y-%m-%d"),
                    "week_end": we.strftime("%Y-%m-%d"),
                    "entries": []
                },
                "logs": logs
            }
        
        # Get timetable for each day of the week
        all_entries = []
        current_date = ws
        while current_date <= we:
            for class_id in class_ids:
                class_result = _get_class_timetable_for_date(class_id, current_date)
                
                if class_result.get("success"):
                    entries = class_result.get("entries", [])
                    # Add date to each entry
                    for entry in entries:
                        entry["date"] = current_date.strftime("%Y-%m-%d")
                    all_entries.extend(entries)
            
            current_date = _add_days(current_date, 1)
        
        # Sort by date, then by period time
        all_entries.sort(key=lambda x: (x.get("date") or "", x.get("start_time") or "", x.get("timetable_column_id") or ""))
        
        logs.append(f"✅ Combined {len(all_entries)} timetable entries from {len(class_ids)} classes for the week")
        
        return {
            "success": True,
            "message": "Thời khóa biểu trong tuần",
            "data": {
                "week_start": ws.strftime("%Y-%m-%d"),
                "week_end": we.strftime("%Y-%m-%d"),
                "entries": all_entries
            },
            "logs": logs
        }
        
    except Exception as e:
        logs.append(f"❌ Error: {str(e)}")
        frappe.log_error(f"Get Student Timetable Week Error: {str(e)}\nLogs: {json.dumps(logs)}", "Parent Portal Timetable")
        return {
            "success": False,
            "message": f"Lỗi hệ thống: {str(e)}",
            "logs": logs
        }

