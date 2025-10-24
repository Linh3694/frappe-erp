# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, now
from datetime import datetime, time
import json

from erp.utils.api_response import success_response, error_response, single_item_response


def time_to_minutes(time_input):
    """Convert various time formats to minutes since midnight"""
    if not time_input:
        return 0
    try:
        # Handle different input types
        if isinstance(time_input, dict):
            frappe.logger().error(f"❌ time_to_minutes received dict instead of time: {time_input}")
            return 0

        # Handle timedelta objects (from database)
        if hasattr(time_input, 'total_seconds'):
            total_seconds = int(time_input.total_seconds())
            return total_seconds // 60  # Convert seconds to minutes

        # Handle datetime.time objects
        if hasattr(time_input, 'hour') and hasattr(time_input, 'minute'):
            return time_input.hour * 60 + time_input.minute

        # Handle string format
        time_str = str(time_input).strip()

        # Handle empty or invalid strings
        if not time_str or time_str == 'None':
            return 0

        # Remove seconds if present (HH:MM:SS -> HH:MM)
        if time_str.count(':') == 2:
            time_str = ':'.join(time_str.split(':')[:2])

        if ':' not in time_str:
            frappe.logger().error(f"❌ time_to_minutes: no ':' found in '{time_str}'")
            return 0

        parts = time_str.split(':')
        if len(parts) < 2:
            frappe.logger().error(f"❌ time_to_minutes: invalid time format '{time_str}'")
            return 0

        hours = int(parts[0])
        minutes = int(parts[1])
        return hours * 60 + minutes

    except Exception as e:
        frappe.logger().error(f"❌ Error in time_to_minutes with input '{time_input}' (type: {type(time_input)}): {str(e)}")
        return 0


def time_ranges_overlap(range1, range2):
    """Check if two time ranges overlap"""
    start1 = time_to_minutes(range1.get('startTime', ''))
    end1 = time_to_minutes(range1.get('endTime', ''))
    start2 = time_to_minutes(range2.get('start_time', ''))
    end2 = time_to_minutes(range2.get('end_time', ''))

    frappe.logger().info(f"🧮 [Backend] Time conversion: range1({range1.get('startTime')}->{start1}, {range1.get('endTime')}->{end1}), range2({range2.get('start_time')}->{start2}, {range2.get('end_time')}->{end2})")

    # Two ranges overlap if: start1 < end2 AND start2 < end1
    # Handle edge case where end time is 0 (invalid time)
    if end1 == 0 or end2 == 0:
        frappe.logger().info("🧮 [Backend] Invalid end time detected, cannot calculate overlap")
        return False

    overlap = start1 < end2 and start2 < end1
    frappe.logger().info(f"🧮 [Backend] Overlap calculation: {start1} < {end2} AND {start2} < {end1} = {overlap}")
    return overlap


def find_overlapping_schedules(event_time_range, schedules):
    """Find all schedules (periods) that overlap with the given time range"""
    overlapping = []
    for schedule in schedules:
        if time_ranges_overlap(event_time_range, schedule):
            overlapping.append(schedule)
    return overlapping


@frappe.whitelist(allow_guest=False, methods=["POST"])
def sync_event_to_class_attendance():
    """
    Đồng bộ attendance từ sự kiện sang lớp
    Gọi sau khi điểm danh sự kiện được lưu
    """
    try:
        # Parse request data
        if frappe.request.method == "POST":
            if hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
                data = frappe.local.form_dict
            else:
                data = frappe.request.get_json() or {}
        else:
            data = frappe.request.args or {}

        event_id = data.get('event_id')
        event_date = data.get('event_date')
        event_attendance_raw = data.get('event_attendance', [])
        
        if not event_id or not event_date:
            return error_response("Missing event_id or event_date", code="MISSING_PARAMS")

        # Parse event_attendance if it's a string
        if isinstance(event_attendance_raw, str):
            try:
                event_attendance = json.loads(event_attendance_raw)
            except:
                event_attendance = []
        else:
            event_attendance = event_attendance_raw if isinstance(event_attendance_raw, list) else []

        frappe.logger().info(f"🔄 [Backend] Syncing event attendance to class: event_id={event_id}, date={event_date}, attendance_count={len(event_attendance)}")

        # Lấy thông tin sự kiện để tính toán các tiết bị ảnh hưởng
        event = frappe.get_doc("SIS Event", event_id)
        if not event:
            return error_response("Event not found", code="EVENT_NOT_FOUND")

        # Lấy date_times của sự kiện
        event_date_times = []
        if hasattr(event, 'date_times') and event.date_times:
            try:
                if isinstance(event.date_times, str):
                    event_date_times = json.loads(event.date_times)
                else:
                    event_date_times = event.date_times
            except:
                event_date_times = []

        # Tìm date_time tương ứng với event_date
        target_date_time = None
        for dt in event_date_times:
            if dt.get('date') == event_date:
                target_date_time = dt
                break

        if not target_date_time:
            frappe.logger().warning(f"⚠️ No matching date_time found for event_date={event_date}")
            return success_response({"synced_count": 0}, "No matching date found")

        # Lấy education_stage_id của lớp để filter timetable column chính xác
        if class_id:
            # Lấy education_grade từ class
            class_info = frappe.get_all("SIS Class",
                                      filters={"name": class_id},
                                      fields=["education_grade"],
                                      limit=1)

            if class_info:
                education_grade = class_info[0].get("education_grade")
                if education_grade:
                    # Lấy education_stage_id từ education_grade
                    grade_info = frappe.get_all("SIS Education Grade",
                                              filters={"name": education_grade},
                                              fields=["education_stage_id"],
                                              limit=1)

                    if grade_info:
                        education_stage_id = grade_info[0].get("education_stage_id")

        # Lấy tất cả schedules (tiết học) theo education_stage_id
        schedule_filters = {"period_type": "study"}
        if education_stage_id:
            schedule_filters["education_stage_id"] = education_stage_id

        schedules = frappe.get_all("SIS Timetable Column",
                                 fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                                 filters=schedule_filters)

        # Tìm các tiết bị overlap
        event_time_range = {
            'startTime': target_date_time.get('startTime', ''),
            'endTime': target_date_time.get('endTime', '')
        }

        overlapping_schedules = find_overlapping_schedules(event_time_range, schedules)

        if not overlapping_schedules:
            frappe.logger().info("✅ No overlapping schedules found")
            return success_response({"synced_count": 0}, "No overlapping periods")

        # Lấy danh sách học sinh tham gia sự kiện
        event_students = frappe.get_all("SIS Event Student",
                                      filters={"parent": event_id, "status": "approved"},
                                      fields=["student_id", "student_code", "student_name"])

        synced_count = 0

        # Với mỗi học sinh và mỗi tiết bị ảnh hưởng, cập nhật class attendance
        for student in event_students:
            student_id = student.get('student_id')
            if not student_id:
                continue

            # Tìm lớp của học sinh 
            class_students = frappe.get_all("SIS Class Student",
                                          filters={"student_id": student_id},
                                          fields=["class_id"])

            if not class_students:
                frappe.logger().warning(f"⚠️ No class found for student {student_id}")
                continue

            class_id = class_students[0].get('class_id')

            # Tìm event attendance status của học sinh này
            student_event_attendance = None
            for att in event_attendance:
                if att.get('student_id') == student_id:
                    student_event_attendance = att
                    break

            if not student_event_attendance:
                frappe.logger().warning(f"⚠️ No event attendance found for student {student_id}")
                continue

            event_status = student_event_attendance.get('status', 'present')

            # Map event status to class status
            # present trong sự kiện -> excused trong lớp (đã tham gia sự kiện)
            # absent trong sự kiện -> absent trong lớp
            # late trong sự kiện -> late trong lớp  
            # excused trong sự kiện -> excused trong lớp
            if event_status == 'present':
                class_status = 'excused'  # Vắng có phép vì đã tham gia sự kiện
                remarks = f"Tham gia sự kiện: {event.title}"
            elif event_status == 'absent':
                class_status = 'absent'
                remarks = f"Vắng sự kiện: {event.title}"
            else:
                class_status = event_status
                remarks = f"Sự kiện: {event.title}"

            # Cập nhật attendance cho tất cả các tiết bị ảnh hưởng
            for schedule in overlapping_schedules:
                period = schedule.get('period_name') or str(schedule.get('period_priority', ''))

                try:
                    # Check if record exists
                    existing = frappe.get_all("SIS Class Attendance",
                                            filters={
                                                "student_id": student_id,
                                                "class_id": class_id,
                                                "date": event_date,
                                                "period": period
                                            },
                                            fields=["name"])

                    if existing:
                        # Update existing record
                        frappe.db.set_value("SIS Class Attendance", existing[0].name, {
                            "status": class_status,
                            "remarks": remarks
                        })
                        frappe.logger().info(f"✅ Updated class attendance: {student_id}, {class_id}, {event_date}, {period}")
                    else:
                        # Create new record
                        doc = frappe.get_doc({
                            "doctype": "SIS Class Attendance",
                            "student_id": student_id,
                            "student_code": student.get('student_code'),
                            "student_name": student.get('student_name'),
                            "class_id": class_id,
                            "date": event_date,
                            "period": period,
                            "status": class_status,
                            "remarks": remarks,
                            "recorded_by": frappe.session.user
                        })
                        doc.insert()
                        frappe.logger().info(f"✅ Created class attendance: {student_id}, {class_id}, {event_date}, {period}")

                    synced_count += 1

                except Exception as e:
                    frappe.logger().error(f"❌ Error syncing attendance for student {student_id}, period {period}: {str(e)}")
                    continue

        frappe.db.commit()

        frappe.logger().info(f"✅ [Backend] Successfully synced {synced_count} attendance records")
        return success_response({"synced_count": synced_count}, f"Synced {synced_count} attendance records")

    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"❌ [Backend] Error syncing event to class attendance: {str(e)}")
        frappe.log_error(f"sync_event_to_class_attendance error: {str(e)}")
        return error_response(f"Failed to sync attendance: {str(e)}", code="SYNC_ERROR")


@frappe.whitelist(allow_guest=False)
def get_events_by_class_period():
    """
    Lấy thông tin sự kiện ảnh hưởng đến một tiết học cụ thể
    """
    debug_logs = []
    try:
        debug_logs.append("🚀 [Backend] Starting get_events_by_class_period")
        class_id = frappe.request.args.get('class_id')
        date = frappe.request.args.get('date')
        period = frappe.request.args.get('period')
        
        debug_logs.append(f"📝 [Backend] Parameters: class_id={class_id}, date={date}, period={period}")

        if not class_id or not date or not period:
            debug_logs.append("❌ [Backend] Missing required parameters")
            return error_response("Missing class_id, date, or period", code="MISSING_PARAMS", debug_info={"logs": debug_logs})

        debug_logs.append(f"🔍 [Backend] Getting events by class period: {class_id}, {date}, {period}")
        frappe.logger().info(f"🔍 [Backend] Getting events by class period: {class_id}, {date}, {period}")

        # Lấy tất cả sự kiện approved 
        try:
            debug_logs.append("🔍 [Backend] Querying SIS Event table...")
            events = frappe.get_all("SIS Event", 
                                  fields=["name", "title", "start_time", "end_time"],
                                  filters={"status": "approved"})  # Chỉ lấy sự kiện đã được approve
            
            debug_logs.append(f"✅ [Backend] Found {len(events)} approved events")
            frappe.logger().info(f"🔍 [Backend] Found {len(events)} approved events")
        except Exception as events_error:
            debug_logs.append(f"❌ [Backend] Error querying events: {str(events_error)}")
            return error_response(f"Failed to get events: {str(events_error)}", code="GET_EVENTS_ERROR", debug_info={"logs": debug_logs})

        # Chỉ lấy study periods matching với period requested
        try:
            debug_logs.append(f"🔍 [Backend] Querying schedules for period: {period}")
            # Query với 2 filters riêng rồi merge
            schedules_by_name = frappe.get_all("SIS Timetable Column", 
                                             fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                                             filters={
                                                 "period_type": "study",
                                                 "period_name": period
                                             })
            
            schedules_by_priority = frappe.get_all("SIS Timetable Column", 
                                                 fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                                                 filters={
                                                     "period_type": "study",
                                                     "period_priority": period
                                                 })
            
            # Merge và remove duplicates
            schedule_names = set()
            schedules = []
            
            for s in schedules_by_name + schedules_by_priority:
                if s['name'] not in schedule_names:
                    schedules.append(s)
                    schedule_names.add(s['name'])
            debug_logs.append(f"✅ [Backend] Found {len(schedules)} matching schedules")
        except Exception as schedules_error:
            debug_logs.append(f"❌ [Backend] Error querying schedules: {str(schedules_error)}")
            return error_response(f"Failed to get schedules: {str(schedules_error)}", code="GET_SCHEDULES_ERROR", debug_info={"logs": debug_logs})

        if not schedules:
            debug_logs.append(f"ℹ️ [Backend] No study schedules found for period {period}")
            frappe.logger().info(f"🔍 [Backend] No study schedules found for period {period}")
            return success_response([], debug_info={"logs": debug_logs})

        target_schedule = schedules[0]
        debug_logs.append(f"🎯 [Backend] Target schedule: {target_schedule}")
        debug_logs.append(f"🔍 [Backend] Processing {len(events)} events...")
        frappe.logger().info(f"🔍 [Backend] Target schedule: {target_schedule}")
        frappe.logger().info(f"🔍 [Backend] Processing {len(events)} events...")
        
        matching_events = []

        for event in events:
            try:
                event_name = event.get('name', 'unknown')
                debug_logs.append(f"🔍 [Backend] Processing event: {event_name}")
                frappe.logger().info(f"🔍 [Backend] Processing event: {event_name}")
                event_matches_date = False
                event_time_ranges = []

                # Try to get date times from SIS Event Date Time table first
                event_date_times = frappe.get_all("SIS Event Date Time",
                                                 filters={"event_id": event['name']},
                                                 fields=["event_date", "start_time", "end_time"])

                if event_date_times:
                    # Event has specific date-time records
                    for dt in event_date_times:
                        if str(dt.get('event_date')) == date:
                            event_matches_date = True
                            event_time_ranges.append({
                                'startTime': str(dt.get('start_time', '')),
                                'endTime': str(dt.get('end_time', ''))
                            })
                else:
                    # Fallback: Use event's main start_time/end_time
                    if event.get('start_time') and event.get('end_time'):
                        try:
                            # Handle both datetime objects and strings
                            start_time_obj = event['start_time']
                            end_time_obj = event['end_time']
                            
                            # Convert to datetime if it's a string
                            if isinstance(start_time_obj, str):
                                start_time_obj = frappe.utils.get_datetime(start_time_obj)
                            if isinstance(end_time_obj, str):
                                end_time_obj = frappe.utils.get_datetime(end_time_obj)
                                
                            event_start_date = start_time_obj.date() if start_time_obj else None
                            
                            if event_start_date and str(event_start_date) == date:
                                event_matches_date = True
                                event_time_ranges.append({
                                    'startTime': start_time_obj.strftime('%H:%M') if start_time_obj else '',
                                    'endTime': end_time_obj.strftime('%H:%M') if end_time_obj else ''
                                })
                        except Exception as date_parse_error:
                            frappe.logger().error(f"❌ Error parsing event dates for {event['name']}: {str(date_parse_error)}")
                            continue

                # Check if any event time range overlaps with target schedule
                if event_matches_date:
                    frappe.logger().info(f"🔍 [Backend] Event {event['name']} matches date {date}, checking {len(event_time_ranges)} time ranges")
                    for event_time_range in event_time_ranges:
                        debug_logs.append(f"🔍 [Backend] Checking overlap: event_range={event_time_range}, target_schedule={target_schedule}")
                        frappe.logger().info(f"🔍 [Backend] Checking overlap: event_range={event_time_range}, target_schedule={target_schedule}")
                        try:
                            overlap_result = time_ranges_overlap(event_time_range, target_schedule)
                            debug_logs.append(f"🧮 [Backend] Overlap result: {overlap_result}")
                        except Exception as overlap_error:
                            debug_logs.append(f"❌ [Backend] Error in time_ranges_overlap: {str(overlap_error)}")
                            debug_logs.append(f"❌ [Backend] event_time_range type: {type(event_time_range)}")
                            debug_logs.append(f"❌ [Backend] target_schedule type: {type(target_schedule)}")
                            return error_response(f"Failed to check overlap: {str(overlap_error)}", code="OVERLAP_ERROR", debug_info={"logs": debug_logs})
                        
                        if overlap_result:
                            frappe.logger().info(f"🎯 [Backend] Event {event['name']} overlaps with period {period}")
                            
                            # Lấy danh sách học sinh tham gia event (via class_student_id)
                            # Try multiple filter approaches
                            event_students = []
                            
                            # Try 1: event_id field
                            try:
                                event_students = frappe.get_all("SIS Event Student",
                                                               filters={"event_id": event['name']},
                                                               fields=["class_student_id", "status"])
                                debug_logs.append(f"🔍 [Backend] Try 1 - event_id filter: {len(event_students)} students")
                            except Exception as e1:
                                debug_logs.append(f"❌ [Backend] Try 1 failed: {str(e1)}")
                            
                            # Try 2: parent field if first failed
                            if not event_students:
                                try:
                                    event_students = frappe.get_all("SIS Event Student",
                                                                   filters={"parent": event['name']},
                                                                   fields=["class_student_id", "status"])
                                    debug_logs.append(f"🔍 [Backend] Try 2 - parent filter: {len(event_students)} students")
                                except Exception as e2:
                                    debug_logs.append(f"❌ [Backend] Try 2 failed: {str(e2)}")
                            
                            # Try 3: No field filter, get all and debug
                            if not event_students:
                                try:
                                    all_event_students = frappe.get_all("SIS Event Student", 
                                                                       fields=["name", "event_id", "parent", "class_student_id", "status"],
                                                                       limit=10)
                                    debug_logs.append(f"🔍 [Backend] Try 3 - All event students sample: {all_event_students[:3]}")
                                except Exception as e3:
                                    debug_logs.append(f"❌ [Backend] Try 3 failed: {str(e3)}")
                            
                            # Filter by status if we found students
                            if event_students:
                                debug_logs.append(f"🔍 [Backend] Before status filter: {len(event_students)} students")
                                approved_students = [es for es in event_students if es.get('status') == 'approved']
                                debug_logs.append(f"🔍 [Backend] Approved students: {len(approved_students)}")
                                
                                # If no approved, try all statuses
                                if not approved_students:
                                    debug_logs.append(f"⚠️ [Backend] No approved students, using all statuses")
                                    event_students = [{"class_student_id": es["class_student_id"]} for es in event_students]
                                else:
                                    event_students = [{"class_student_id": es["class_student_id"]} for es in approved_students]

                            debug_logs.append(f"🔍 [Backend] Found {len(event_students)} event students")

                            # Lấy danh sách học sinh trong lớp
                            class_students = frappe.get_all("SIS Class Student",
                                                           filters={"class_id": class_id},
                                                           fields=["name", "student_id"])

                            debug_logs.append(f"🔍 [Backend] Found {len(class_students)} class students")

                            # Match event students với class students
                            class_student_dict = {cs['name']: cs['student_id'] for cs in class_students}
                            matching_student_ids = []
                            
                            for es in event_students:
                                class_student_id = es['class_student_id']
                                if class_student_id in class_student_dict:
                                    student_id = class_student_dict[class_student_id]
                                    matching_student_ids.append(student_id)
                                    debug_logs.append(f"✅ [Backend] Matched class_student {class_student_id} → student {student_id}")

                            if matching_student_ids:
                                debug_logs.append(f"✅ [Backend] Found {len(matching_student_ids)} students from class {class_id} in event {event['name']}")
                                frappe.logger().info(f"✅ [Backend] Found {len(matching_student_ids)} students from class {class_id} in event {event['name']}")
                                matching_events.append({
                                    "eventId": event['name'],
                                    "eventTitle": event['title'],
                                    "studentIds": matching_student_ids
                                })
                            else:
                                debug_logs.append(f"⚠️ [Backend] No matching students found for event {event['name']} in class {class_id}")

                            break  # Found overlap, no need to check other time ranges

            except Exception as e:
                error_msg = f"❌ Error processing event {event.get('name', '')}: {str(e)}"
                debug_logs.append(error_msg)
                frappe.logger().error(error_msg)
                continue

        debug_logs.append(f"✅ [Backend] Found {len(matching_events)} matching events")
        frappe.logger().info(f"✅ [Backend] Found {len(matching_events)} matching events")
        return success_response(matching_events, debug_info={"logs": debug_logs})

    except Exception as e:
        debug_logs.append(f"❌ [Backend] Error getting events by class period: {str(e)}")
        frappe.logger().error(f"❌ [Backend] Error getting events by class period: {str(e)}")
        frappe.log_error(f"get_events_by_class_period error: {str(e)}")
        return error_response(f"Failed to get events: {str(e)}", code="GET_EVENTS_ERROR", debug_info={"logs": debug_logs})


@frappe.whitelist(allow_guest=False, methods=["POST"])
def remove_automatic_attendance():
    """
    Xóa điểm danh tự động khi sự kiện bị hủy
    """
    try:
        # Parse request data
        if frappe.request.method == "POST":
            if hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
                data = frappe.local.form_dict
            else:
                data = frappe.request.get_json() or {}
        else:
            data = frappe.request.args or {}

        event_id = data.get('event_id')
        
        if not event_id:
            return error_response("Missing event_id", code="MISSING_PARAMS")

        frappe.logger().info(f"🗑️ [Backend] Removing automatic attendance for event: {event_id}")

        # Lấy thông tin sự kiện
        try:
            event = frappe.get_doc("SIS Event", event_id)
        except:
            return error_response("Event not found", code="EVENT_NOT_FOUND")

        # Xóa tất cả class attendance có remarks chứa tên sự kiện
        attendance_records = frappe.get_all("SIS Class Attendance",
                                          filters={
                                              "remarks": ["like", f"%{event.title}%"]
                                          },
                                          fields=["name"])

        deleted_count = 0
        for record in attendance_records:
            try:
                frappe.delete_doc("SIS Class Attendance", record['name'])
                deleted_count += 1
            except Exception as e:
                frappe.logger().error(f"❌ Error deleting attendance record {record['name']}: {str(e)}")
                continue

        frappe.db.commit()

        frappe.logger().info(f"✅ [Backend] Successfully removed {deleted_count} automatic attendance records")
        return success_response({"deleted_count": deleted_count}, f"Removed {deleted_count} attendance records")

    except Exception as e:
        frappe.db.rollback()
        frappe.logger().error(f"❌ [Backend] Error removing automatic attendance: {str(e)}")
        frappe.log_error(f"remove_automatic_attendance error: {str(e)}")
        return error_response(f"Failed to remove attendance: {str(e)}", code="REMOVE_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False)
def get_event_attendance_statuses():
    """
    Get event attendance statuses for students in a class period
    Returns actual attendance status (present/absent/late/excused) for each student
    """
    debug_logs = []
    try:
        debug_logs.append("🚀 [Backend] Starting get_event_attendance_statuses")
        
        class_id = frappe.request.args.get('class_id')
        date = frappe.request.args.get('date')
        period = frappe.request.args.get('period')
        
        debug_logs.append(f"📝 [Backend] Parameters: class_id={class_id}, date={date}, period={period}")

        if not class_id or not date or not period:
            debug_logs.append("❌ [Backend] Missing required parameters")
            return error_response("Missing class_id, date, or period", code="MISSING_PARAMS", debug_info={"logs": debug_logs})

        # Get events affecting this class/period (reuse existing logic)
        events_response = get_events_by_class_period()
        if not events_response.get('success') or not events_response.get('data'):
            debug_logs.append("ℹ️ [Backend] No events found for this period")
            return success_response({}, debug_info={"logs": debug_logs})

        events = events_response['data']
        debug_logs.append(f"🔍 [Backend] Found {len(events)} events affecting this period")
        
        student_statuses = {}  # student_id -> status
        
        for event in events:
            event_id = event['eventId']
            student_ids = event['studentIds']
            
            debug_logs.append(f"📊 [Backend] Processing event {event_id} with {len(student_ids)} students")
            
            # Get event attendance records for these students on this date
            for student_id in student_ids:
                try:
                    attendance_records = frappe.get_all("SIS Event Attendance",
                                                       filters={
                                                           "event_id": event_id,
                                                           "student_id": student_id,
                                                           "attendance_date": date
                                                       },
                                                       fields=["status"],
                                                       limit=1)
                    
                    if attendance_records:
                        status = attendance_records[0].get('status', 'excused')
                        student_statuses[student_id] = status
                        debug_logs.append(f"✅ [Backend] Student {student_id}: {status} (from event attendance)")
                    else:
                        # No event attendance record found, default to excused
                        student_statuses[student_id] = 'excused'
                        debug_logs.append(f"⚠️ [Backend] Student {student_id}: excused (no event attendance record)")
                        
                except Exception as student_error:
                    debug_logs.append(f"❌ [Backend] Error getting attendance for student {student_id}: {str(student_error)}")
                    student_statuses[student_id] = 'excused'  # Default fallback
        
        debug_logs.append(f"✅ [Backend] Final student statuses: {student_statuses}")
        return success_response(student_statuses, debug_info={"logs": debug_logs})
        
    except Exception as e:
        debug_logs.append(f"❌ [Backend] Error getting event attendance statuses: {str(e)}")
        frappe.logger().error(f"❌ [Backend] Error getting event attendance statuses: {str(e)}")
        frappe.log_error(f"get_event_attendance_statuses error: {str(e)}")
        return error_response(f"Failed to get event attendance statuses: {str(e)}", code="GET_EVENT_ATTENDANCE_STATUSES_ERROR", debug_info={"logs": debug_logs})


@frappe.whitelist(allow_guest=False, methods=["POST"])
def batch_get_event_attendance():
    """
    Get event attendance data for multiple periods in a single request.
    Optimized to minimize database queries.
    
    Request body:
    {
        "class_id": "CLASS-001",
        "date": "2024-01-15", 
        "periods": ["Tiết 1", "Tiết 2", ...],
        "education_stage_id": "EDU-STAGE-001"
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "Tiết 1": {
                "events": [{eventId, eventTitle, studentIds}],
                "statuses": {student_id: status}
            },
            "Tiết 2": {...}
        }
    }
    """
    try:
        frappe.logger().info("🚀 [Backend] batch_get_event_attendance called")
        
        # Parse request data
        data = {}
        if frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body) if body else {}
            except Exception as e:
                frappe.logger().error(f"❌ [Backend] JSON parse failed: {str(e)}")
                return error_response("Invalid JSON data", code="INVALID_JSON")
        
        class_id = data.get('class_id')
        date = data.get('date')
        periods = data.get('periods', [])
        education_stage_id = data.get('education_stage_id')
        
        if not class_id or not date or not periods:
            return error_response("Missing class_id, date, or periods", code="MISSING_PARAMS")
        
        frappe.logger().info(f"📝 [Backend] Parameters: class_id={class_id}, date={date}, periods={len(periods)}, education_stage_id={education_stage_id}")
        
        # Get ALL approved events (once)
        all_events = frappe.get_all("SIS Event",
                                   fields=["name", "title", "start_time", "end_time"],
                                   filters={"status": "approved"})
        
        frappe.logger().info(f"📊 [Backend] Found {len(all_events)} approved events total")
        
        # Get timetable columns for these periods (once)
        schedule_filters = {"period_type": "study", "period_name": ["in", periods]}
        if education_stage_id:
            schedule_filters["education_stage_id"] = education_stage_id

        frappe.logger().info(f"🔍 [Debug] Schedule filters: {schedule_filters}")

        schedules = frappe.get_all("SIS Timetable Column",
                                  fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                                  filters=schedule_filters)

        frappe.logger().info(f"📚 [Debug] Raw schedules found: {schedules}")

        # Debug: Check all available schedules for this education stage
        if education_stage_id:
            all_schedules_for_stage = frappe.get_all("SIS Timetable Column",
                                                   filters={"education_stage_id": education_stage_id},
                                                   fields=["name", "period_name", "period_type", "period_priority"])
            frappe.logger().info(f"📚 [Debug] All schedules for education_stage {education_stage_id}: {all_schedules_for_stage}")

        # Create period_name -> schedule mapping
        schedule_map = {}
        for s in schedules:
            period_name = s.get('period_name')
            if period_name:
                schedule_map[period_name] = s

        frappe.logger().info(f"📚 [Backend] Loaded {len(schedules)} schedules for {len(periods)} periods")
        frappe.logger().info(f"📋 [Debug] Schedule map: {schedule_map}")
        frappe.logger().info(f"📋 [Debug] Requested periods: {periods}")
        
        # Get class students (once)
        class_students = frappe.get_all("SIS Class Student",
                                       filters={"class_id": class_id},
                                       fields=["name", "student_id"])
        class_student_dict = {cs['name']: cs['student_id'] for cs in class_students}
        
        frappe.logger().info(f"👥 [Backend] Class has {len(class_students)} students")
        
        # Result structure
        result = {}
        overlap_debug = []  # Track overlap checking results
        for period in periods:
            result[period] = {"events": [], "statuses": {}}
        
        # Process each event once
        for event in all_events:
            try:
                # Get event date times
                event_date_times = frappe.get_all("SIS Event Date Time",
                                                 filters={"event_id": event['name']},
                                                 fields=["event_date", "start_time", "end_time"])
                
                # Check if event affects our date
                matching_dt = None
                for dt in event_date_times:
                    if str(dt.get('event_date')) == date:
                        matching_dt = dt
                        break
                
                if not matching_dt:
                    continue
                
                # Get event students (once per event)
                event_students = frappe.get_all("SIS Event Student",
                                               filters={"parent": event['name']},
                                               fields=["class_student_id", "status"])
                
                # Match with class students
                matching_student_ids = []
                for es in event_students:
                    class_student_id = es['class_student_id']
                    if class_student_id in class_student_dict:
                        student_id = class_student_dict[class_student_id]
                        matching_student_ids.append(student_id)
                
                if not matching_student_ids:
                    continue
                
                # Check which periods this event overlaps with
                event_time_range = {
                    'startTime': str(matching_dt.get('start_time', '')),
                    'endTime': str(matching_dt.get('end_time', ''))
                }

                frappe.logger().info(f"🎯 [Debug] Event {event['name']} time range: {event_time_range}")

                # Track if this event overlaps with any period
                event_has_overlap = False

                for period_name in periods:
                    schedule = schedule_map.get(period_name)
                    if not schedule:
                        frappe.logger().info(f"⚠️ [Debug] No schedule found for period {period_name}")
                        continue

                    schedule_time = {
                        'start_time': schedule.get('start_time'),
                        'end_time': schedule.get('end_time')
                    }

                    frappe.logger().info(f"📅 [Debug] Checking {period_name}: event={event_time_range}, schedule={schedule_time}")

                    overlap = time_ranges_overlap(event_time_range, schedule)
                    frappe.logger().info(f"🧮 [Debug] Overlap result for {period_name}: {overlap}")

                    if overlap:
                        frappe.logger().info(f"✅ [Debug] OVERLAP FOUND! Event {event['name']} overlaps with {period_name}")
                        event_has_overlap = True
                        # Event affects this period!
                        result[period_name]["events"].append({
                            "eventId": event['name'],
                            "eventTitle": event['title'],
                            "studentIds": matching_student_ids
                        })
                    else:
                        frappe.logger().info(f"❌ [Debug] NO OVERLAP: Event {event['name']} does not overlap with {period_name}")

                # Debug: Log if event has no overlaps but has participants
                if not event_has_overlap and matching_student_ids:
                    frappe.logger().warning(f"⚠️ [Debug] Event {event['name']} has {len(matching_student_ids)} participants but no overlapping periods found!")
                    frappe.logger().warning(f"⚠️ [Debug] Event time: {event_time_range}, Available periods: {list(schedule_map.keys())}")
                
            except Exception as event_error:
                frappe.logger().warning(f"⚠️ [Backend] Error processing event {event.get('name')}: {str(event_error)}")
                continue
        
        # Now batch query ALL event attendance records at once
        all_event_ids = set()
        all_student_ids = set()
        for period_data in result.values():
            for event in period_data["events"]:
                all_event_ids.add(event["eventId"])
                all_student_ids.update(event["studentIds"])
        
        if all_event_ids and all_student_ids:
            frappe.logger().info(f"📊 [Backend] Batch querying attendance for {len(all_event_ids)} events and {len(all_student_ids)} students")
            
            attendance_records = frappe.db.sql("""
                SELECT event_id, student_id, status
                FROM `tabSIS Event Attendance`
                WHERE event_id IN %(event_ids)s
                    AND student_id IN %(student_ids)s
                    AND attendance_date = %(date)s
            """, {
                "event_ids": list(all_event_ids),
                "student_ids": list(all_student_ids),
                "date": date
            }, as_dict=True)
            
            # Create lookup: (event_id, student_id) -> status
            attendance_lookup = {}
            for record in attendance_records:
                key = (record['event_id'], record['student_id'])
                attendance_lookup[key] = record['status']
            
            frappe.logger().info(f"✅ [Backend] Found {len(attendance_records)} attendance records")
            
            # Apply statuses to results
            for period_name, period_data in result.items():
                for event in period_data["events"]:
                    event_id = event["eventId"]
                    for student_id in event["studentIds"]:
                        key = (event_id, student_id)
                        status = attendance_lookup.get(key, 'excused')  # Default to excused
                        period_data["statuses"][student_id] = status
        
        frappe.logger().info(f"✅ [Backend] batch_get_event_attendance completed successfully")

        # Include debug info in response
        debug_info = {
            "events_found": len(all_events),
            "schedules_found": len(schedules),
            "schedule_filters": schedule_filters,
            "requested_periods": periods,
            "education_stage_id": education_stage_id,
            "class_students_count": len(class_students),
            "schedule_map_keys": list(schedule_map.keys()) if schedule_map else [],
            "schedule_samples": list(schedule_map.values())[:2] if schedule_map else [],  # Show first 2 schedules as sample
            "overlap_check_results": overlap_debug[:10]  # Show first 10 overlap checks
        }

        return success_response(result, debug_info=debug_info)
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        frappe.logger().error(f"❌ [Backend] batch_get_event_attendance error: {str(e)}")
        frappe.logger().error(f"❌ [Backend] Full traceback: {error_detail}")
        frappe.log_error(f"batch_get_event_attendance: {str(e)[:100]}", "Batch Event Attendance Error")
        return error_response(f"Failed to get batch event attendance: {str(e)}", code="BATCH_EVENT_ATTENDANCE_ERROR")


@frappe.whitelist(allow_guest=False)
def validate_period_for_education_stage():
    """
    Validate if a period exists for a given education stage
    """
    try:
        period_name = frappe.request.args.get('period_name')
        education_stage_id = frappe.request.args.get('education_stage_id')

        if not period_name or not education_stage_id:
            return error_response("Missing period_name or education_stage_id", code="MISSING_PARAMS")

        period_exists = frappe.db.exists("SIS Timetable Column", {
            "period_name": period_name,
            "education_stage_id": education_stage_id,
            "period_type": "study"
        })

        exists = bool(period_exists)
        return success_response({"exists": exists})

    except Exception as e:
        frappe.logger().error(f"❌ [Backend] Error validating period for education stage: {str(e)}")
        frappe.log_error(f"validate_period_for_education_stage error: {str(e)}")
        return error_response(f"Failed to validate period: {str(e)}", code="VALIDATE_PERIOD_ERROR")


@frappe.whitelist(allow_guest=False)
def get_education_stage():
    """
    Get education_stage_id from education_grade
    """
    try:
        grade_name = frappe.request.args.get('name')

        if not grade_name:
            return error_response("Missing name parameter", code="MISSING_PARAMS")

        # Get education_stage_id from education_grade
        grade_info = frappe.get_all("SIS Education Grade",
                                  filters={"name": grade_name},
                                  fields=["education_stage_id"],
                                  limit=1)

        if not grade_info:
            return error_response("Education grade not found", code="GRADE_NOT_FOUND")

        education_stage_id = grade_info[0].get("education_stage_id")

        if not education_stage_id:
            return error_response("No education_stage_id found for this grade", code="NO_STAGE_ID")

        return success_response({"education_stage_id": education_stage_id})

    except Exception as e:
        frappe.logger().error(f"❌ [Backend] Error getting education_stage_id: {str(e)}")
        frappe.log_error(f"get_education_stage error: {str(e)}")
        return error_response(f"Failed to get education stage: {str(e)}", code="GET_STAGE_ERROR")


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_events_by_date_with_attendance():
    """
    Get all events for a specific date with attendance information for a class.

    Request params:
    - class_id: string (required)
    - date: string (YYYY-MM-DD) (required)

    Returns:
    [
        {
            "eventId": "EVENT-001",
            "eventTitle": "Đá bóng",
            "startTime": "18:00",
            "endTime": "19:00",
            "students": [
                {
                    "studentId": "STU-001",
                    "studentName": "Nguyễn Văn A",
                    "studentCode": "HS001",
                    "status": "present",  // present, absent, late, excused
                    "userImage": "/files/avatar.jpg"
                }
            ],
            "totalParticipants": 25,
            "attendedCount": 23
        }
    ]
    """
    try:
        frappe.logger().info("🚀 [Backend] get_events_by_date_with_attendance called")

        # Initialize debug info
        debug_info = {}

        # Get request parameters - try multiple sources
        class_id = (frappe.form_dict.get("class_id") or
                   frappe.request.args.get("class_id") or
                   frappe.local.form_dict.get("class_id"))

        date = (frappe.form_dict.get("date") or
                frappe.request.args.get("date") or
                frappe.local.form_dict.get("date"))

        if not class_id or not date:
            debug_info["extracted_class_id"] = class_id
            debug_info["extracted_date"] = date
            return error_response("Missing class_id or date", code="MISSING_PARAMS", debug_info=debug_info)

        frappe.logger().info(f"📝 [Backend] Parameters: class_id={class_id}, date={date}")

        # Get all approved events
        events = frappe.get_all("SIS Event",
                               fields=["name", "title", "status"],
                               filters={"status": "approved"})

        frappe.logger().info(f"📊 [Backend] Found {len(events)} approved events")

        result_events = []
        event_filter_debug = []  # Track why events are filtered out

        # Get class students for filtering
        class_students = frappe.get_all("SIS Class Student",
                                       filters={"class_id": class_id},
                                       fields=["name", "student_id"])

        class_student_ids = [cs['name'] for cs in class_students]
        class_student_dict = {cs['name']: cs['student_id'] for cs in class_students}

        frappe.logger().info(f"👥 [Backend] Class has {len(class_students)} students")

        # Process each event
        for event in events:
            try:
                event_id = event['name']


                # Get event date times for this specific date
                event_date_times = frappe.get_all("SIS Event Date Time",
                                                 filters={
                                                     "event_id": event_id,
                                                     "event_date": date
                                                 },
                                                 fields=["start_time", "end_time"])


                event_debug = {
                    "event_id": event_id,
                    "event_title": event['title'],
                    "date_times_count": len(event_date_times),
                    "total_event_students": 0,
                    "class_event_students": 0,
                    "reason_filtered": None
                }

                if event_id == "SIS-EVENT-3261554":
                    frappe.logger().info(f"🎯 [Debug] Event debug created: {event_debug}")
                    event_debug["date_times_details"] = event_date_times  # Show actual date times

                if not event_date_times:
                    event_debug["reason_filtered"] = f"No date_times for date {date}"
                    event_filter_debug.append(event_debug)
                    continue  # Event doesn't happen on this date

                # Get event students who belong to this class
                event_students = frappe.get_all("SIS Event Student",
                                               filters={"event_id": event_id},
                                               fields=["class_student_id", "status"])

                event_debug["total_event_students"] = len(event_students)
                frappe.logger().info(f"👥 [Debug] Event {event_id} - total event_students: {len(event_students)}")

                # Filter students who are in the specified class
                class_event_students = [
                    es for es in event_students
                    if es['class_student_id'] in class_student_ids
                ]

                event_debug["class_event_students"] = len(class_event_students)
                frappe.logger().info(f"✅ [Debug] Event {event_id} - class_event_students: {len(class_event_students)} (class has {len(class_student_ids)} students)")

                if not class_event_students:
                    event_debug["reason_filtered"] = f"No students from class {class_id} (class has {len(class_student_ids)} students, event has {len(event_students)} total students)"
                    event_filter_debug.append(event_debug)
                    continue  # No students from this class participate

                frappe.logger().info(f"🎯 [Backend] Found event {event_id} with {len(class_event_students)} students from class {class_id}")

                # Get student details and attendance status
                students_info = []
                attended_count = 0

                for es in class_event_students:
                    student_id = class_student_dict[es['class_student_id']]

                    # Get student details - try different DocTypes
                    try:
                        student_doc = frappe.get_doc("SIS Student", student_id)
                    except:
                        try:
                            student_doc = frappe.get_doc("CRM Student", student_id)
                        except:
                            # If both fail, create minimal student info
                            student_doc = type('MockStudent', (), {
                                'student_name': f'Student {student_id}',
                                'student_code': student_id.split('-')[-1] if '-' in student_id else student_id,
                                'user_image': None,
                                'image': None
                            })()

                    # Get attendance status for this event on this date
                    attendance_status = frappe.db.get_value("SIS Event Attendance",
                                                          {
                                                              "event_id": event_id,
                                                              "student_id": student_id,
                                                              "attendance_date": date
                                                          },
                                                          "status")

                    # Default to 'excused' if no attendance record (for events)
                    status = attendance_status or 'excused'

                    if status in ['present', 'late']:
                        attended_count += 1

                    # Get student image from SIS Photo table
                    user_image = None
                    try:
                        # Query SIS Photo table for this student
                        photo_record = frappe.get_all("SIS Photo",
                                                     filters={"student_id": student_id, "status": "Active"},
                                                     fields=["name", "photo"],
                                                     order_by="creation desc",
                                                     limit_page_length=1)
                        if photo_record and photo_record[0].get("photo"):
                            user_image = photo_record[0]["photo"]
                            frappe.logger().info(f"📸 [Debug] Found photo for student {student_id}: {user_image}")
                        else:
                            frappe.logger().info(f"📸 [Debug] No photo found for student {student_id}")
                    except Exception as photo_error:
                        frappe.logger().warning(f"⚠️ [Debug] Error getting photo for student {student_id}: {str(photo_error)}")
                        # Fallback to student record fields if SIS Photo fails
                        user_image = (getattr(student_doc, 'user_image', None) or
                                    getattr(student_doc, 'image', None) or
                                    getattr(student_doc, 'photo', None) or
                                    getattr(student_doc, 'avatar', None))

                    students_info.append({
                        "studentId": student_id,
                        "studentName": getattr(student_doc, 'student_name', '') or getattr(student_doc, 'full_name', '') or '',
                        "studentCode": getattr(student_doc, 'student_code', '') or '',
                        "status": status,
                        "userImage": user_image
                    })

                # Use the first date time (assuming events have only one time slot per day)
                dt = event_date_times[0]

                # Format time to HH:MM format
                start_time = str(dt.get('start_time', ''))
                end_time = str(dt.get('end_time', ''))

                # Extract HH:MM from time strings like "08:00:00" or "8:00:00"
                try:
                    if start_time and ':' in start_time:
                        start_time = start_time.split(':')[0].zfill(2) + ':' + start_time.split(':')[1]
                    if end_time and ':' in end_time:
                        end_time = end_time.split(':')[0].zfill(2) + ':' + end_time.split(':')[1]
                except:
                    pass  # Keep original format if parsing fails

                result_events.append({
                    "eventId": event_id,
                    "eventTitle": event['title'],
                    "startTime": start_time,
                    "endTime": end_time,
                    "students": students_info,
                    "totalParticipants": len(students_info),
                    "attendedCount": attended_count
                })

                # Mark as passed all filters
                event_debug["passed_all_filters"] = True
                if event_id == "SIS-EVENT-3261554":
                    frappe.logger().info(f"✅ [Debug] Event SIS-EVENT-3261554 PASSED ALL FILTERS!")
                    frappe.logger().info(f"✅ [Debug] Final event data: {event_debug}")
                event_filter_debug.append(event_debug)

            except Exception as event_error:
                frappe.logger().warning(f"⚠️ [Backend] Error processing event {event.get('name')}: {str(event_error)}")
                if event.get('name') == "SIS-EVENT-3261554":
                    frappe.logger().error(f"❌ [Debug] CRITICAL ERROR processing SIS-EVENT-3261554: {str(event_error)}")
                    debug_info["error_processing_SIS-EVENT-3261554"] = str(event_error)
                continue

        # Sort events by start time
        result_events.sort(key=lambda x: x['startTime'])

        frappe.logger().info(f"✅ [Backend] get_events_by_date_with_attendance completed: {len(result_events)} events")

        # Include debug info in response
        debug_info["events_found"] = len(events)
        debug_info["result_events_count"] = len(result_events)
        debug_info["event_names"] = [e['name'] for e in events]  # All event names found
        debug_info["class_student_ids_sample"] = list(class_student_ids)[:5]  # Show first 5 class student IDs
        debug_info["event_filter_debug"] = event_filter_debug[:10]  # Show first 10 filtered events
        debug_info["events_processed_count"] = len(event_filter_debug)  # How many events were processed

        return success_response(result_events, debug_info=debug_info)

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        frappe.logger().error(f"❌ [Backend] get_events_by_date_with_attendance error: {str(e)}")
        frappe.logger().error(f"❌ [Backend] Full traceback: {error_detail}")
        frappe.log_error(f"get_events_by_date_with_attendance: {str(e)[:100]}", "Events By Date Error")
        return error_response(f"Failed to get events by date: {str(e)}", code="GET_EVENTS_BY_DATE_ERROR")
