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
        
        # DEBUG: Try direct SQL query to compare
        try:
            sql_result = frappe.db.sql(f"""
                SELECT name, class_id, school_year_id, docstatus 
                FROM `tabSIS Class Student` 
                WHERE student_id = %(student_id)s 
                AND school_year_id = %(school_year_id)s
                LIMIT 5
            """, filters, as_dict=True)
            logs.append(f"🔍 DEBUG SQL query returned {len(sql_result)} rows: {sql_result}")
        except Exception as e:
            logs.append(f"⚠️ DEBUG SQL query failed: {str(e)}")
        
        # Get all class assignments for this student (including drafts)
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=["class_id", "school_year_id", "docstatus"],
            ignore_permissions=True,
            or_filters={"docstatus": ["in", [0, 1]]}  # Include both draft (0) and submitted (1)
        )
        
        logs.append(f"✅ Found {len(class_students)} class assignments via get_all: {class_students}")
        
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
        
        # Get all timetable columns for this day from timetable instances
        # Include both study periods (with subject) and non-study periods (breaks)
        all_columns = []

        try:
            # First, get class info and find education_stage through education_grade
            class_doc = frappe.get_doc("SIS Class", class_id)
            education_grade_id = class_doc.education_grade
            campus_id = class_doc.campus_id
            
            # Get education_stage from education_grade
            education_grade_doc = frappe.get_doc("SIS Education Grade", education_grade_id)
            education_stage_id = education_grade_doc.education_stage_id
            
            logs.append(f"📋 Class: {class_id}, Grade: {education_grade_id}, Stage: {education_stage_id}, Campus: {campus_id}")
            
            # Get columns actually used in this instance for this day (study periods)
            study_columns_sql = """
                SELECT DISTINCT
                    tir.timetable_column_id
                FROM `tabSIS Timetable Instance Row` tir
                WHERE tir.parent IN %(instance_ids)s
                AND tir.day_of_week = %(day_of_week)s
            """
            
            study_columns = frappe.db.sql(study_columns_sql, {
                "instance_ids": tuple(instance_ids),
                "day_of_week": day_of_week
            }, as_dict=True)
            
            study_column_ids = {row['timetable_column_id'] for row in study_columns}
            logs.append(f"✅ Found {len(study_column_ids)} study columns for {day_of_week}")
            
            # ⚡ FIX: Lấy non-study columns theo schedule active cho ngày target
            # Tìm schedule active cho ngày này
            active_schedule = frappe.db.get_value(
                "SIS Schedule",
                {
                    "education_stage_id": education_stage_id,
                    "campus_id": campus_id,
                    "is_active": 1,
                    "start_date": ["<=", target_date_str],
                    "end_date": [">=", target_date_str]
                },
                "name"
            )
            
            if active_schedule:
                # Có schedule active → chỉ lấy non-study từ schedule này
                non_study_columns_sql = """
                    SELECT DISTINCT
                        tc.name as timetable_column_id,
                        tc.period_name,
                        tc.start_time,
                        tc.end_time,
                        tc.period_type,
                        tc.period_priority
                    FROM `tabSIS Timetable Column` tc
                    WHERE tc.schedule_id = %(schedule_id)s
                    AND tc.period_type = 'non-study'
                    ORDER BY tc.period_priority ASC, tc.start_time ASC
                """
                non_study_columns = frappe.db.sql(non_study_columns_sql, {
                    "schedule_id": active_schedule
                }, as_dict=True)
                logs.append(f"✅ Found {len(non_study_columns)} non-study columns from schedule {active_schedule}")
            else:
                # Không có schedule active → lấy legacy (schedule_id IS NULL)
                non_study_columns_sql = """
                    SELECT DISTINCT
                        tc.name as timetable_column_id,
                        tc.period_name,
                        tc.start_time,
                        tc.end_time,
                        tc.period_type,
                        tc.period_priority
                    FROM `tabSIS Timetable Column` tc
                    WHERE tc.education_stage_id = %(education_stage_id)s
                    AND tc.campus_id = %(campus_id)s
                    AND tc.period_type = 'non-study'
                    AND (tc.schedule_id IS NULL OR tc.schedule_id = '')
                    ORDER BY tc.period_priority ASC, tc.start_time ASC
                """
                non_study_columns = frappe.db.sql(non_study_columns_sql, {
                    "education_stage_id": education_stage_id,
                    "campus_id": campus_id
                }, as_dict=True)
                logs.append(f"✅ Found {len(non_study_columns)} legacy non-study columns")
            
            # Log đã được thêm ở trên trong logic schedule
            
            # Get study column details
            study_columns_detail_sql = """
                SELECT DISTINCT
                    tc.name as timetable_column_id,
                    tc.period_name,
                    tc.start_time,
                    tc.end_time,
                    tc.period_type,
                    tc.period_priority
                FROM `tabSIS Timetable Column` tc
                WHERE tc.name IN %(column_ids)s
                ORDER BY tc.period_priority ASC, tc.start_time ASC
            """
            
            if study_column_ids:
                study_columns_detail = frappe.db.sql(study_columns_detail_sql, {
                    "column_ids": tuple(study_column_ids)
                }, as_dict=True)
            else:
                study_columns_detail = []
            
            # ⚡ FIX: Loại bỏ non-study periods nếu đã có study period ở cùng time slot
            # Helper function to convert time to string
            def time_to_str(t):
                if t is None:
                    return None
                if hasattr(t, 'total_seconds'):
                    total_seconds = int(t.total_seconds())
                    return f"{total_seconds // 3600:02d}:{(total_seconds % 3600) // 60:02d}"
                if isinstance(t, str):
                    # Handle "HH:MM:SS" format - strip seconds
                    parts = t.split(':')
                    if len(parts) >= 2:
                        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
                return str(t)
            
            # Tạo set các time slots đã có study periods
            study_time_slots = set()
            for col in study_columns_detail:
                start = time_to_str(col.get('start_time'))
                end = time_to_str(col.get('end_time'))
                if start and end:
                    study_time_slots.add((start, end))
            
            logs.append(f"🔍 DEBUG: Study time slots = {study_time_slots}")
            
            # Filter non-study columns - loại bỏ nếu trùng time slot với study period
            filtered_non_study = []
            for col in non_study_columns:
                start = time_to_str(col.get('start_time'))
                end = time_to_str(col.get('end_time'))
                
                if start and end and (start, end) in study_time_slots:
                    logs.append(f"⏭️ Skipping non-study '{col.get('period_name')}' - overlaps with study period at {start}-{end}")
                    continue
                
                filtered_non_study.append(col)
            
            logs.append(f"🔍 DEBUG: Filtered non-study from {len(non_study_columns)} to {len(filtered_non_study)}")
            
            # Combine study and filtered non-study columns
            all_day_columns = study_columns_detail + filtered_non_study
            # Sort by priority and time
            all_day_columns.sort(key=lambda x: (x.get('period_priority', 999), x.get('start_time', '')))
            
            logs.append(f"✅ Total {len(all_day_columns)} columns for {day_of_week} (study + non-study)")
            
            # Get existing rows with subject data for this specific day
            existing_rows_sql = """
                SELECT DISTINCT
                    tir.timetable_column_id,
                    tir.subject_id,
                    tir.teacher_1_id,
                    tir.teacher_2_id,
                    tir.room_id,
                    tir.day_of_week
                FROM `tabSIS Timetable Instance Row` tir
                WHERE tir.parent IN %(instance_ids)s
                AND tir.day_of_week = %(day_of_week)s
                AND tir.subject_id IS NOT NULL
                ORDER BY tir.timetable_column_id
            """

            existing_rows = frappe.db.sql(existing_rows_sql, {
                "instance_ids": tuple(instance_ids),
                "day_of_week": day_of_week
            }, as_dict=True)

            logs.append(f"✅ Found {len(existing_rows)} study period rows for {day_of_week}")

            # Create rows for all columns, filling in data where available
            for col in all_day_columns:
                column_id = col.get('timetable_column_id')

                # Find if there's an existing row for this column and day
                existing_row = next((r for r in existing_rows if r.get('timetable_column_id') == column_id), None)

                # Convert timedelta to HH:MM format for start_time and end_time
                start_time = None
                if col.get('start_time'):
                    total_seconds = int(col['start_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    start_time = f"{hours:02d}:{minutes:02d}"
                
                end_time = None
                if col.get('end_time'):
                    total_seconds = int(col['end_time'].total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    end_time = f"{hours:02d}:{minutes:02d}"

                if existing_row:
                    # Use existing row data (study period)
                    row = {
                        "name": f"row_{column_id}",
                        "timetable_column_id": column_id,
                        "subject_id": existing_row.get('subject_id'),
                        "teacher_1_id": existing_row.get('teacher_1_id'),
                        "teacher_2_id": existing_row.get('teacher_2_id'),
                        "room_id": existing_row.get('room_id'),
                        "day_of_week": day_of_week,
                        "date": target_date_str,
                        # Add column info directly
                        "period_name": col.get('period_name', ''),
                        "start_time": start_time,
                        "end_time": end_time,
                        "period_type": col.get('period_type', 'study'),
                        "period_priority": col.get('period_priority', 0)
                    }
                else:
                    # Create row for non-study periods (breaks) or empty slots
                    row = {
                        "name": f"row_{column_id}",
                        "timetable_column_id": column_id,
                        "subject_id": None,  # No subject for breaks
                        "teacher_1_id": None,
                        "teacher_2_id": None,
                        "room_id": None,
                        "day_of_week": day_of_week,
                        "date": target_date_str,
                        # Add column info directly
                        "period_name": col.get('period_name', ''),
                        "start_time": start_time,
                        "end_time": end_time,
                        "period_type": col.get('period_type', 'study'),
                        "period_priority": col.get('period_priority', 0)
                    }

                all_columns.append(row)

            logs.append(f"✅ Created {len(all_columns)} column entries (including non-study periods)")

        except Exception as e:
            logs.append(f"❌ Error getting timetable columns: {str(e)}")
            # Fallback to old logic
            try:
                row_filters = {
                    "parent": ["in", instance_ids],
                    "parenttype": "SIS Timetable Instance",
                    "parentfield": "weekly_pattern",
                    "day_of_week": day_of_week
                }

                all_columns = frappe.get_all(
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
                logs.append(f"✅ Fallback query found {len(all_columns)} rows")
            except Exception as e2:
                logs.append(f"❌ Fallback query also failed: {str(e2)}")
                all_columns = []
        
        logs.append(f"✅ Found {len(all_columns)} timetable entries for {day_of_week}")

        # Enrich with subject titles, teacher names, and room info
        for row in all_columns:
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

                    # Get curriculum ID from SIS Actual Subject (correct source)
                    # Use actual_subject_id from SIS Subject to get curriculum
                    try:
                        if subject.get("actual_subject_id"):
                            actual_subject = frappe.get_doc("SIS Actual Subject", subject.actual_subject_id)
                            row["curriculum_id"] = actual_subject.curriculum_id or ""
                        else:
                            row["curriculum_id"] = ""
                    except Exception as curriculum_error:
                        logs.append(f"⚠️ Could not get curriculum from actual subject: {str(curriculum_error)}")
                        row["curriculum_id"] = ""
                except:
                    row["subject_title"] = ""
                    row["timetable_subject_title"] = ""
                    row["curriculum_id"] = ""

            # Get teacher names from SIS Subject Assignment (more accurate than timetable row data)
            teacher_names = []
            teacher_ids = []

            if row.get("subject_id"):
                try:
                    # Query SIS Subject Assignment to find teacher for this subject and class
                    subject = frappe.get_doc("SIS Subject", row["subject_id"])
                    assignments = frappe.get_all(
                        "SIS Subject Assignment",
                        filters={
                            "actual_subject_id": subject.actual_subject_id,
                            "class_id": class_id
                        },
                        fields=["teacher_id"]
                    )

                    for assignment in assignments:
                        if assignment.teacher_id:
                            teacher_ids.append(assignment.teacher_id)
                            try:
                                teacher = frappe.get_doc("SIS Teacher", assignment.teacher_id)
                                if teacher.user_id:
                                    # Get teacher name from User table
                                    try:
                                        user = frappe.get_doc("User", teacher.user_id)
                                        teacher_name = user.full_name or f"{user.first_name or ''} {user.last_name or ''}".strip()
                                        if teacher_name:
                                            teacher_names.append(teacher_name)
                                    except Exception as user_e:
                                        logs.append(f"⚠️ Could not get user name for teacher {assignment.teacher_id}: {str(user_e)}")
                                else:
                                    logs.append(f"⚠️ Teacher {assignment.teacher_id} has no user_id")
                            except Exception as e:
                                logs.append(f"⚠️ Could not get teacher {assignment.teacher_id}: {str(e)}")
                except Exception as e:
                    logs.append(f"⚠️ Could not get subject assignments for subject {row['subject_id']}: {str(e)}")

            row["teacher_names"] = ", ".join(teacher_names)
            row["teacher_ids"] = teacher_ids

            # Get room info using new room assignment logic
            try:
                from erp.api.erp_administrative.room import get_room_for_class_subject
                # Use timetable_subject_title if available, otherwise use subject_title
                subject_title_for_room = row.get("timetable_subject_title") or row.get("subject_title") or None
                room_info = get_room_for_class_subject(class_id, subject_title_for_room)
                row["room_id"] = room_info.get("room_id")
                row["room_name"] = room_info.get("room_name")
                row["room_type"] = room_info.get("room_type")
                # Keep room_title for backward compatibility
                row["room_title"] = room_info.get("room_name") or ""
            except Exception as room_error:
                logs.append(f"⚠️ Could not get room info for class {class_id}, subject {row.get('subject_title')}: {str(room_error)}")
                row["room_id"] = None
                row["room_name"] = "Chưa có phòng"
                row["room_type"] = None
                row["room_title"] = ""

            # Column info (period_name, start_time, end_time, period_type) is already set
            # during row creation above, so no need to fetch again
            # Ensure defaults if not set
            if "period_name" not in row:
                row["period_name"] = ""
            if "start_time" not in row:
                row["start_time"] = None
            if "end_time" not in row:
                row["end_time"] = None
            if "period_type" not in row:
                row["period_type"] = "study"
            
            # Ensure empty fields for non-study periods
            if not row.get("subject_id"):
                row["subject_title"] = ""
                row["timetable_subject_title"] = ""
                row["curriculum_id"] = ""
                row["teacher_names"] = ""
                row["teacher_ids"] = []
                # For non-study periods, still try to get homeroom room
                if not row.get("room_id"):
                    try:
                        from erp.api.erp_administrative.room import get_room_for_class_subject
                        room_info = get_room_for_class_subject(class_id, None)
                        row["room_id"] = room_info.get("room_id")
                        row["room_name"] = room_info.get("room_name")
                        row["room_type"] = room_info.get("room_type")
                        row["room_title"] = room_info.get("room_name") or ""
                    except Exception:
                        row["room_id"] = None
                        row["room_name"] = "Chưa có phòng"
                        row["room_type"] = None
                        row["room_title"] = ""

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
                matching_rows = [r for r in all_columns if r.get("timetable_column_id") == column_id]
                
                if override_type == "cancellation":
                    # Remove the period
                    all_columns = [r for r in all_columns if r.get("timetable_column_id") != column_id]
                elif override_type == "change" and matching_rows:
                    # Update the period
                    row = matching_rows[0]
                    if override.get("subject_id"):
                        row["subject_id"] = override["subject_id"]
                        # Re-fetch subject title and curriculum
                        try:
                            subject = frappe.get_doc("SIS Subject", override["subject_id"])
                            row["subject_title"] = subject.title

                            # Update curriculum ID from SIS Actual Subject (correct source)
                            try:
                                if subject.get("actual_subject_id"):
                                    actual_subject = frappe.get_doc("SIS Actual Subject", subject.actual_subject_id)
                                    row["curriculum_id"] = actual_subject.curriculum_id or ""
                                else:
                                    row["curriculum_id"] = ""
                            except Exception as curriculum_error:
                                logs.append(f"⚠️ Could not get curriculum from override actual subject: {str(curriculum_error)}")
                                row["curriculum_id"] = ""
                        except:
                            row["curriculum_id"] = ""
                    
                    if override.get("teacher_1_id"):
                        row["teacher_1_id"] = override["teacher_1_id"]
                    if override.get("teacher_2_id"):
                        row["teacher_2_id"] = override["teacher_2_id"]
                    
                    # Re-fetch teacher names - use override teacher data first, then fallback to subject assignment
                    teacher_names = []
                    teacher_ids = []

                    # First, try to use teacher data from the override itself
                    for teacher_field in ["teacher_1_id", "teacher_2_id"]:
                        teacher_id = override.get(teacher_field)
                        if teacher_id:
                            teacher_ids.append(teacher_id)
                            try:
                                teacher = frappe.get_doc("SIS Teacher", teacher_id)
                                if teacher.user_id:
                                    # Get teacher name from User table
                                    try:
                                        user = frappe.get_doc("User", teacher.user_id)
                                        teacher_name = user.full_name or f"{user.first_name or ''} {user.last_name or ''}".strip()
                                        if teacher_name:
                                            teacher_names.append(teacher_name)
                                    except Exception as user_e:
                                        logs.append(f"⚠️ Could not get user name for override teacher {teacher_id}: {str(user_e)}")
                                else:
                                    logs.append(f"⚠️ Override teacher {teacher_id} has no user_id")
                            except Exception as e:
                                logs.append(f"⚠️ Could not get override teacher {teacher_id}: {str(e)}")

                    # If no teachers found from override, fallback to subject assignment
                    if not teacher_names and row.get("subject_id"):
                        try:
                            # Query SIS Subject Assignment to find teacher for this subject and class
                            subject = frappe.get_doc("SIS Subject", row["subject_id"])
                            assignments = frappe.get_all(
                                "SIS Subject Assignment",
                                filters={
                                    "actual_subject_id": subject.actual_subject_id,
                                    "class_id": class_id
                                },
                                fields=["teacher_id"]
                            )

                            for assignment in assignments:
                                if assignment.teacher_id:
                                    teacher_ids.append(assignment.teacher_id)
                                    try:
                                        teacher = frappe.get_doc("SIS Teacher", assignment.teacher_id)
                                        if teacher.user_id:
                                            # Get teacher name from User table
                                            try:
                                                user = frappe.get_doc("User", teacher.user_id)
                                                teacher_name = user.full_name or f"{user.first_name or ''} {user.last_name or ''}".strip()
                                                if teacher_name:
                                                    teacher_names.append(teacher_name)
                                            except Exception as user_e:
                                                logs.append(f"⚠️ Could not get user name for override assignment {assignment.teacher_id}: {str(user_e)}")
                                        else:
                                            logs.append(f"⚠️ Assignment teacher {assignment.teacher_id} has no user_id")
                                    except Exception as e:
                                        logs.append(f"⚠️ Could not get override assignment teacher {assignment.teacher_id}: {str(e)}")
                        except Exception as e:
                            logs.append(f"⚠️ Could not get subject assignments for override subject {row['subject_id']}: {str(e)}")

                    row["teacher_names"] = ", ".join(teacher_names)
                    row["teacher_ids"] = teacher_ids
                    
                    # Update room info using new room assignment logic (after override subject is updated)
                    try:
                        from erp.api.erp_administrative.room import get_room_for_class_subject
                        # Use timetable_subject_title if available, otherwise use subject_title
                        subject_title_for_room = row.get("timetable_subject_title") or row.get("subject_title") or None
                        room_info = get_room_for_class_subject(class_id, subject_title_for_room)
                        row["room_id"] = room_info.get("room_id")
                        row["room_name"] = room_info.get("room_name")
                        row["room_type"] = room_info.get("room_type")
                        # Keep room_title for backward compatibility
                        row["room_title"] = room_info.get("room_name") or ""
                    except Exception as room_error:
                        logs.append(f"⚠️ Could not get room info for override: {str(room_error)}")
                        # Fallback to override room_id if provided
                        if override.get("room_id"):
                            row["room_id"] = override["room_id"]
                            try:
                                from erp.api.erp_administrative.room import get_room_for_class_subject
                                # Try to get room name from ERP Administrative Room
                                try:
                                    room_doc = frappe.get_doc("ERP Administrative Room", override["room_id"])
                                    row["room_name"] = room_doc.title_vn or room_doc.title_en or room_doc.name
                                    row["room_type"] = "homeroom"  # Default assumption
                                    row["room_title"] = row["room_name"]
                                except:
                                    row["room_name"] = ""
                                    row["room_type"] = None
                                    row["room_title"] = ""
                            except:
                                row["room_id"] = None
                                row["room_name"] = "Chưa có phòng"
                                row["room_type"] = None
                                row["room_title"] = ""
                        else:
                            row["room_id"] = None
                            row["room_name"] = "Chưa có phòng"
                            row["room_type"] = None
                            row["room_title"] = ""
        
        return {
            "success": True,
            "entries": all_columns,
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
        # Get student_id from request args if not provided as parameter (Frappe GET request handling)
        if not student_id:
            # Try multiple ways to get the parameter
            student_id = (
                frappe.request.args.get('student_id') or 
                frappe.form_dict.get('student_id') or 
                frappe.local.form_dict.get('student_id')
            )
        
        # DEBUG: Log received student_id
        logs.append(f"🔍 DEBUG: Received student_id parameter: '{student_id}' (type: {type(student_id).__name__})")
        logs.append(f"🔍 DEBUG: frappe.request.args: {dict(frappe.request.args)}")
        logs.append(f"🔍 DEBUG: frappe.form_dict: {frappe.form_dict}")
        
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
def get_teacher_info():
    """
    Get teacher information including names and avatars

    Args:
        teacher_ids: JSON array of teacher IDs (SIS Teacher) from form_dict

    Returns:
        dict: Teacher information with names and avatars
    """
    logs = []

    try:
        import json

        teacher_ids = []

        # Try to parse from raw request data (JSON body)
        if hasattr(frappe.request, 'data') and frappe.request.data:
            try:
                # Parse JSON data
                data_str = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else str(frappe.request.data)
                logs.append(f"DEBUG: Raw request data: {data_str[:200]}...")  # First 200 chars

                # Try to parse as JSON first
                try:
                    parsed_json = json.loads(data_str)
                    logs.append(f"DEBUG: Parsed JSON keys: {list(parsed_json.keys()) if isinstance(parsed_json, dict) else 'not a dict'}")
                    
                    if isinstance(parsed_json, dict) and 'teacher_ids' in parsed_json:
                        teacher_ids = parsed_json['teacher_ids']
                        logs.append(f"DEBUG: Found teacher_ids in JSON body: {teacher_ids}")
                except json.JSONDecodeError:
                    logs.append(f"DEBUG: Not valid JSON, trying URL-encoded parsing")
                    # Fallback to URL-encoded parsing
                    from urllib.parse import parse_qs
                    parsed_data = parse_qs(data_str)
                    logs.append(f"DEBUG: Parsed data keys: {list(parsed_data.keys())}")

                    # Extract teacher_ids
                    teacher_ids_params = []
                    for key, values in parsed_data.items():
                        if key.startswith('teacher_ids[') and key.endswith(']'):
                            teacher_ids_params.extend(values)

                    if teacher_ids_params:
                        teacher_ids = teacher_ids_params
                        logs.append(f"DEBUG: Found teacher_ids in URL-encoded data: {teacher_ids}")

            except Exception as e:
                logs.append(f"DEBUG: Failed to parse raw request data: {e}")

        # Try to get teacher_ids as array from query parameters like teacher_ids[0], teacher_ids[1], etc.
        if not teacher_ids:
            teacher_count = frappe.form_dict.get('teacher_ids_count')
            if teacher_count:
                try:
                    count = int(teacher_count)
                    for i in range(count):
                        param_key = f'teacher_ids[{i}]'
                        teacher_id = frappe.form_dict.get(param_key)
                        if teacher_id:
                            teacher_ids.append(teacher_id)
                    logs.append(f"DEBUG: Parsed teacher_ids from array params: {teacher_ids}")
                except Exception as e:
                    logs.append(f"DEBUG: Failed to parse array params: {e}")

        # Fallback: check for JSON string
        if not teacher_ids:
            teacher_ids_json = frappe.form_dict.get('teacher_ids')
            if teacher_ids_json:
                if isinstance(teacher_ids_json, str):
                    try:
                        teacher_ids = json.loads(teacher_ids_json)
                        logs.append(f"DEBUG: Parsed teacher_ids from JSON: {teacher_ids}")
                    except Exception as e:
                        logs.append(f"DEBUG: Failed to parse JSON: {e}, treating as single ID")
                        teacher_ids = [teacher_ids_json]

        # Also check if it's passed as array/list
        if not teacher_ids:
            teacher_ids = frappe.form_dict.get('teacher_ids[]') or []
            logs.append(f"DEBUG: Using teacher_ids[]: {teacher_ids}")

        logs.append(f"DEBUG: Final teacher_ids: {teacher_ids}, type: {type(teacher_ids)}")

        if not teacher_ids or not isinstance(teacher_ids, list):
            return {
                "success": False,
                "message": "Teacher IDs are required as a list",
                "logs": logs
            }

        teachers_info = {}

        for teacher_id in teacher_ids:
            if not teacher_id:
                continue

            try:
                teacher = frappe.get_doc("SIS Teacher", teacher_id)
                teacher_info = {
                    "teacher_id": teacher_id,
                    "teacher_name": "",
                    "avatar_url": None,
                    "gender": teacher.get("gender") 
                }

                if teacher.user_id:
                    try:
                        user = frappe.get_doc("User", teacher.user_id)
                        teacher_info["teacher_name"] = user.full_name or f"{user.first_name or ''} {user.last_name or ''}".strip()

                        # Get user avatar if available
                        if user.user_image:
                            teacher_info["avatar_url"] = user.user_image
                        elif hasattr(user, 'photo') and user.photo:
                            teacher_info["avatar_url"] = user.photo

                    except Exception as user_e:
                        logs.append(f"⚠️ Could not get user info for teacher {teacher_id}: {str(user_e)}")

                teachers_info[teacher_id] = teacher_info

            except Exception as e:
                logs.append(f"⚠️ Could not get teacher {teacher_id}: {str(e)}")

        return {
            "success": True,
            "message": "Teacher information retrieved successfully",
            "data": teachers_info,
            "logs": logs
        }

    except Exception as e:
        logs.append(f"❌ Error getting teacher info: {str(e)}")
        return {
            "success": False,
            "message": f"Error getting teacher info: {str(e)}",
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
        # Get student_id from request args if not provided as parameter (Frappe GET request handling)
        if not student_id:
            # Try multiple ways to get the parameter
            student_id = (
                frappe.request.args.get('student_id') or
                frappe.form_dict.get('student_id') or
                frappe.local.form_dict.get('student_id')
            )

        # Get week_start and week_end from request args if not provided as parameters
        if not week_start:
            week_start = (
                frappe.request.args.get('week_start') or
                frappe.form_dict.get('week_start') or
                frappe.local.form_dict.get('week_start')
            )

        if not week_end:
            week_end = (
                frappe.request.args.get('week_end') or
                frappe.form_dict.get('week_end') or
                frappe.local.form_dict.get('week_end')
            )

        logs.append(f"🔍 DEBUG: Received student_id parameter: '{student_id}' (type: {type(student_id).__name__})")
        logs.append(f"🔍 DEBUG: Received week_start parameter: '{week_start}' (type: {type(week_start).__name__})")
        logs.append(f"🔍 DEBUG: Received week_end parameter: '{week_end}' (type: {type(week_end).__name__})")
        logs.append(f"🔍 DEBUG: frappe.request.args: {dict(frappe.request.args)}")
        logs.append(f"🔍 DEBUG: frappe.form_dict: {frappe.form_dict}")

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

        logs.append(f"🔍 Student {student_id} has class_ids: {class_result.get('class_ids', [])}")

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

