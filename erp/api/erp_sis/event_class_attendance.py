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
        
        # Remove seconds if present (HH:MM:SS -> HH:MM)
        if time_str.count(':') == 2:
            time_str = ':'.join(time_str.split(':')[:2])
        
        if ':' not in time_str:
            frappe.logger().error(f"❌ time_to_minutes: no ':' found in '{time_str}'")
            return 0
            
        parts = time_str.split(':')
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
        education_stage_id = None
        if class_id:
            frappe.logger().info(f"🔍 [Backend] Getting education info for class: {class_id}")

            # Lấy education_grade từ class
            class_info = frappe.get_all("SIS Class",
                                      filters={"name": class_id},
                                      fields=["education_grade", "title_vn"],
                                      limit=1)

            frappe.logger().info(f"🔍 [Backend] Class info query result: {class_info}")

            if class_info:
                education_grade = class_info[0].get("education_grade")
                frappe.logger().info(f"🔍 [Backend] Found education_grade: {education_grade} for class: {class_id}")

                if education_grade:
                    # Lấy education_stage_id từ education_grade
                    grade_info = frappe.get_all("SIS Education Grade",
                                              filters={"name": education_grade},
                                              fields=["education_stage_id", "title_vn"],
                                              limit=1)

                    frappe.logger().info(f"🔍 [Backend] Grade info query result: {grade_info}")

                    if grade_info:
                        education_stage_id = grade_info[0].get("education_stage_id")
                        frappe.logger().info(f"✅ [Backend] Found education_stage_id: {education_stage_id} for grade: {education_grade}")
                    else:
                        frappe.logger().warning(f"⚠️ [Backend] No grade info found for: {education_grade}")
                else:
                    frappe.logger().warning(f"⚠️ [Backend] No education_grade found for class: {class_id}")
            else:
                frappe.logger().warning(f"⚠️ [Backend] No class info found for: {class_id}")

        # Lấy tất cả schedules (tiết học) theo education_stage_id
        schedule_filters = {"period_type": "study"}
        if education_stage_id:
            schedule_filters["education_stage_id"] = education_stage_id

        frappe.logger().info(f"🔍 [Backend] Querying schedules with filters: {schedule_filters}")

        schedules = frappe.get_all("SIS Timetable Column",
                                 fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type", "education_stage_id"],
                                 filters=schedule_filters)

        frappe.logger().info(f"🔍 [Backend] Found {len(schedules)} schedules for education_stage_id: {education_stage_id}")

        # Tìm các tiết bị overlap
        event_time_range = {
            'startTime': target_date_time.get('startTime', ''),
            'endTime': target_date_time.get('endTime', '')
        }

        frappe.logger().info(f"🔍 [Backend] Event time range: {event_time_range}")
        frappe.logger().info(f"🔍 [Backend] Checking overlap with {len(schedules)} schedules")

        overlapping_schedules = find_overlapping_schedules(event_time_range, schedules)

        frappe.logger().info(f"🔍 [Backend] Found {len(overlapping_schedules)} overlapping schedules")

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

        frappe.logger().info(f"🔍 [Backend] Validating period '{period_name}' for education stage '{education_stage_id}'")

        # Check if period exists for this education stage
        period_exists = frappe.db.exists("SIS Timetable Column", {
            "period_name": period_name,
            "education_stage_id": education_stage_id,
            "period_type": "study"
        })

        frappe.logger().info(f"🔍 [Backend] Period query result for period '{period_name}' and stage '{education_stage_id}': {period_exists}")

        exists = bool(period_exists)

        frappe.logger().info(f"✅ [Backend] Period validation result: {exists}")
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

        frappe.logger().info(f"🔍 [Backend] Getting education_stage_id for grade '{grade_name}'")

        # Get education_stage_id from education_grade
        grade_info = frappe.get_all("SIS Education Grade",
                                  filters={"name": grade_name},
                                  fields=["education_stage_id", "title_vn", "title_en"],
                                  limit=1)

        frappe.logger().info(f"🔍 [Backend] Grade info query result: {grade_info}")

        if not grade_info:
            frappe.logger().warning(f"⚠️ [Backend] Education grade not found: {grade_name}")
            return error_response("Education grade not found", code="GRADE_NOT_FOUND")

        education_stage_id = grade_info[0].get("education_stage_id")

        if not education_stage_id:
            frappe.logger().warning(f"⚠️ [Backend] No education_stage_id found for grade: {grade_name}")
            return error_response("No education_stage_id found for this grade", code="NO_STAGE_ID")

        frappe.logger().info(f"✅ [Backend] Found education_stage_id: {education_stage_id} for grade: {grade_name}")
        return success_response({"education_stage_id": education_stage_id})

    except Exception as e:
        frappe.logger().error(f"❌ [Backend] Error getting education_stage_id: {str(e)}")
        frappe.log_error(f"get_education_stage error: {str(e)}")
        return error_response(f"Failed to get education stage: {str(e)}", code="GET_STAGE_ERROR")
