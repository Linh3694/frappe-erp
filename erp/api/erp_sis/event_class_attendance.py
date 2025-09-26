# Copyright (c) 2024, Wellspring and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, now
from datetime import datetime, time
import json

from erp.utils.api_response import success_response, error_response, single_item_response


def time_to_minutes(time_str):
    """Convert HH:MM time string to minutes since midnight"""
    if not time_str:
        return 0
    try:
        hours, minutes = map(int, time_str.split(':'))
        return hours * 60 + minutes
    except:
        return 0


def time_ranges_overlap(range1, range2):
    """Check if two time ranges overlap"""
    start1 = time_to_minutes(range1.get('startTime', ''))
    end1 = time_to_minutes(range1.get('endTime', ''))
    start2 = time_to_minutes(range2.get('start_time', ''))
    end2 = time_to_minutes(range2.get('end_time', ''))
    
    # Two ranges overlap if: start1 < end2 AND start2 < end1
    return start1 < end2 and start2 < end1


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
            return error_response("Missing event_id or event_date", "MISSING_PARAMS")

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
            return error_response("Event not found", "EVENT_NOT_FOUND")

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

        # Lấy tất cả schedules (tiết học)
        schedules = frappe.get_all("SIS Timetable Column", 
                                 fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                                 filters={"period_type": "study"})

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
        return error_response(f"Failed to sync attendance: {str(e)}", "SYNC_ERROR")


@frappe.whitelist(allow_guest=False)
def get_events_by_class_period():
    """
    Lấy thông tin sự kiện ảnh hưởng đến một tiết học cụ thể
    """
    try:
        class_id = frappe.request.args.get('class_id')
        date = frappe.request.args.get('date')
        period = frappe.request.args.get('period')

        if not class_id or not date or not period:
            return error_response("Missing class_id, date, or period", "MISSING_PARAMS")

        frappe.logger().info(f"🔍 [Backend] Getting events by class period: {class_id}, {date}, {period}")

        # Lấy tất cả sự kiện có ngày trùng với date
        events = frappe.get_all("SIS Event", 
                              fields=["name", "title", "date_times"],
                              filters={"docstatus": 1})  # Chỉ lấy sự kiện đã được approve

        # Lấy tất cả schedules để tính toán overlap
        schedules = frappe.get_all("SIS Timetable Column", 
                                 fields=["name", "period_priority", "period_name", "start_time", "end_time", "period_type"],
                                 filters={
                                     "period_type": "study",
                                     "$or": [
                                         {"period_name": period},
                                         {"period_priority": period}
                                     ]
                                 })

        if not schedules:
            return success_response([])

        target_schedule = schedules[0]
        
        matching_events = []

        for event in events:
            try:
                # Parse date_times
                event_date_times = []
                if event.get('date_times'):
                    if isinstance(event.date_times, str):
                        event_date_times = json.loads(event.date_times)
                    else:
                        event_date_times = event.date_times

                # Tìm date_time matching với date và overlap với period
                for dt in event_date_times:
                    if dt.get('date') == date:
                        event_time_range = {
                            'startTime': dt.get('startTime', ''),
                            'endTime': dt.get('endTime', '')
                        }

                        if time_ranges_overlap(event_time_range, target_schedule):
                            # Lấy danh sách học sinh tham gia từ lớp này
                            event_students = frappe.get_all("SIS Event Student",
                                                           filters={
                                                               "parent": event['name'],
                                                               "status": "approved"
                                                           },
                                                           fields=["student_id"])

                            # Filter students theo class
                            class_students = frappe.get_all("SIS Class Student",
                                                           filters={"class_id": class_id},
                                                           fields=["student_id"])

                            class_student_ids = [cs['student_id'] for cs in class_students]
                            matching_student_ids = [es['student_id'] for es in event_students if es['student_id'] in class_student_ids]

                            if matching_student_ids:
                                matching_events.append({
                                    "eventId": event['name'],
                                    "eventTitle": event['title'],
                                    "studentIds": matching_student_ids
                                })

                            break

            except Exception as e:
                frappe.logger().error(f"❌ Error processing event {event.get('name', '')}: {str(e)}")
                continue

        frappe.logger().info(f"✅ [Backend] Found {len(matching_events)} matching events")
        return success_response(matching_events)

    except Exception as e:
        frappe.logger().error(f"❌ [Backend] Error getting events by class period: {str(e)}")
        frappe.log_error(f"get_events_by_class_period error: {str(e)}")
        return error_response(f"Failed to get events: {str(e)}", "GET_EVENTS_ERROR")


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
            return error_response("Missing event_id", "MISSING_PARAMS")

        frappe.logger().info(f"🗑️ [Backend] Removing automatic attendance for event: {event_id}")

        # Lấy thông tin sự kiện
        try:
            event = frappe.get_doc("SIS Event", event_id)
        except:
            return error_response("Event not found", "EVENT_NOT_FOUND")

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
        return error_response(f"Failed to remove attendance: {str(e)}", "REMOVE_ATTENDANCE_ERROR")
