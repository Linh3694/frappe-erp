# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from typing import Optional
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


@frappe.whitelist(allow_guest=False)
def create_event():
    """Create a new event with workflow"""
    try:
        data = frappe.local.form_dict

        # Debug: Store debug info for response
        debug_info = {
            "raw_form_data": dict(data),
            "data_keys": list(data.keys()),
            "data_types": [(k, str(type(v))) for k, v in data.items()]
        }

        # Try to get JSON data from request body if available
        try:
            import json
            request_data = frappe.local.request.get_json()
            if request_data:
                debug_info["json_request_body"] = request_data
                # Merge with form data
                data.update(request_data)
            else:
                debug_info["json_request_body"] = None
        except Exception as e:
            debug_info["json_request_body_error"] = str(e)



        # If frontend sends status, record it and remove to avoid conflicts; rely on DocType default instead
        if "status" in data:
            debug_info["incoming_status"] = data.get("status")
            try:
                del data["status"]
            except Exception:
                pass

        # Try to parse JSON fields if they exist as strings
        parsing_info = {}
        if data.get('dateSchedules'):
            if isinstance(data.get('dateSchedules'), str):
                try:
                    data['dateSchedules'] = frappe.parse_json(data['dateSchedules'])
                    parsing_info["dateSchedules"] = "parsed from string"
                except Exception as e:
                    parsing_info["dateSchedules"] = f"parse error: {str(e)}"
            else:
                parsing_info["dateSchedules"] = "already an object"

        if data.get('date_schedules'):
            if isinstance(data.get('date_schedules'), str):
                try:
                    data['date_schedules'] = frappe.parse_json(data['date_schedules'])
                    parsing_info["date_schedules"] = "parsed from string"
                except Exception as e:
                    parsing_info["date_schedules"] = f"parse error: {str(e)}"
            else:
                parsing_info["date_schedules"] = "already an object"

        # Handle array fields that might come as strings
        if data.get('student_ids'):
            if isinstance(data.get('student_ids'), str):
                try:
                    data['student_ids'] = frappe.parse_json(data['student_ids'])
                    parsing_info["student_ids"] = "parsed from string"
                except Exception as e:
                    parsing_info["student_ids"] = f"parse error: {str(e)}"
            else:
                parsing_info["student_ids"] = "already an array"

        if data.get('teacher_ids'):
            if isinstance(data.get('teacher_ids'), str):
                try:
                    data['teacher_ids'] = frappe.parse_json(data['teacher_ids'])
                    parsing_info["teacher_ids"] = "parsed from string"
                except Exception as e:
                    parsing_info["teacher_ids"] = f"parse error: {str(e)}"
            else:
                parsing_info["teacher_ids"] = "already an array"

        # Handle new date_times format
        if data.get('date_times'):
            if isinstance(data.get('date_times'), str):
                try:
                    data['date_times'] = frappe.parse_json(data['date_times'])
                    parsing_info["date_times"] = "parsed from string"
                except Exception as e:
                    parsing_info["date_times"] = f"parse error: {str(e)}"
            else:
                parsing_info["date_times"] = "already an object"

        if data.get('dateTimes'):
            if isinstance(data.get('dateTimes'), str):
                try:
                    data['dateTimes'] = frappe.parse_json(data['dateTimes'])
                    parsing_info["dateTimes"] = "parsed from string"
                except Exception as e:
                    parsing_info["dateTimes"] = f"parse error: {str(e)}"
            else:
                parsing_info["dateTimes"] = "already an object"

        debug_info["parsing_info"] = parsing_info
        try:
            debug_info["parsed_data"] = dict(data)
            debug_info["execution_reached_validation"] = True
        except Exception as e:
            debug_info["parsed_data_error"] = str(e)
            debug_info["parsed_data_error_type"] = str(type(e))
            # Try to create a safe dict representation
            try:
                debug_info["parsed_data_keys"] = list(data.keys())
                debug_info["parsed_data_safe"] = {k: str(v) for k, v in data.items()}
            except:
                debug_info["parsed_data_fallback"] = str(data)
            return error_response("Error creating dict representation", debug_info=debug_info)

        # Required fields validation - support old, schedule, and datetime formats
        start_time_value = data.get('start_time')
        end_time_value = data.get('end_time')
        has_old_format = bool(start_time_value and end_time_value)

        # Fix validation logic for date schedules
        date_schedules = data.get('date_schedules') or data.get('dateSchedules')
        has_schedule_format = bool(date_schedules and isinstance(date_schedules, list) and len(date_schedules) > 0)

        # Check for new datetime format
        date_times = data.get('date_times') or data.get('dateTimes')
        has_datetime_format = bool(date_times and isinstance(date_times, list) and len(date_times) > 0)

        debug_info["validation_check"] = {
            "has_old_format": has_old_format,
            "has_schedule_format": has_schedule_format,
            "has_datetime_format": has_datetime_format,
            "start_time_value": start_time_value,
            "end_time_value": end_time_value,
            "start_time_type": str(type(start_time_value)),
            "end_time_type": str(type(end_time_value)),
            "date_schedules_value": date_schedules,
            "date_schedules_type": str(type(date_schedules)),
            "date_times_value": date_times,
            "date_times_type": str(type(date_times)),
            "data_date_schedules": data.get('date_schedules'),
            "data_dateSchedules": data.get('dateSchedules'),
            "data_date_times": data.get('date_times'),
            "data_dateTimes": data.get('dateTimes'),
            "start_time": data.get('start_time'),
            "end_time": data.get('end_time')
        }

        if isinstance(date_schedules, list):
            debug_info["validation_check"]["date_schedules_length"] = len(date_schedules)

        if isinstance(date_times, list):
            debug_info["validation_check"]["date_times_length"] = len(date_times)

        # At least one format must be provided
        if not has_old_format and not has_schedule_format and not has_datetime_format:
            debug_info["validation_error"] = "No valid time format provided"
            return validation_error_response("Validation failed", {
                "time_info": ["Either start_time/end_time, dateSchedules, or dateTimes must be provided"],
                "debug_info": debug_info
            })

        # Check that only one format is used at a time - safe sum calculation
        try:
            format_count = sum([
                1 if has_old_format else 0,
                1 if has_schedule_format else 0, 
                1 if has_datetime_format else 0
            ])
        except (TypeError, ValueError):
            # Fallback: manual count if sum fails
            format_count = (1 if has_old_format else 0) + (1 if has_schedule_format else 0) + (1 if has_datetime_format else 0)
        
        debug_info["validation_condition_check"] = {
            "has_old_format": has_old_format,
            "has_schedule_format": has_schedule_format,
            "has_datetime_format": has_datetime_format,
            "format_count": format_count
        }

        if format_count > 1:
            debug_info["validation_error_triggered"] = "multiple_formats_detected"
            return validation_error_response("Validation failed", {
                "time_info": ["Cannot use multiple time formats simultaneously. Use only one of: start_time/end_time, dateSchedules, or dateTimes"]
            }, debug_info=debug_info)

        required_fields = ['title']
        if has_old_format:
            required_fields.extend(['start_time', 'end_time'])
        elif has_schedule_format:
            # For schedule format, we don't require any specific field name since we accept both dateSchedules and date_schedules
            pass
        elif has_datetime_format:
            # For datetime format, we don't require any specific field name since we accept both dateTimes and date_times
            pass

        missing_fields = [field for field in required_fields if not data.get(field)]

        # Additional validation for schedule and datetime formats
        if has_schedule_format or has_datetime_format:
            student_ids = data.get('student_ids') or []
            teacher_ids = data.get('teacher_ids') or []

            if not student_ids or len(student_ids) == 0:
                return validation_error_response("Validation failed", {
                    "students": ["At least one student is required"],
                    "debug_info": debug_info
                })

            if not teacher_ids or len(teacher_ids) == 0:
                return validation_error_response("Validation failed", {
                    "teachers": ["At least one teacher is required"],
                    "debug_info": debug_info
                })

        if missing_fields:
            return validation_error_response("Validation failed", {
                field: ["This field is required"] for field in missing_fields
            }, debug_info=debug_info)

        # Get campus from context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            return validation_error_response("Validation failed", {"campus_id": ["Campus context not found"]}, debug_info=debug_info)
        
        # Get current school year for the campus
        school_year_id = None
        try:
            current_sy = frappe.get_all(
                "SIS School Year",
                filters={"campus_id": campus_id, "is_enable": 1},
                fields=["name"],
                limit_page_length=1
            )
            if current_sy:
                school_year_id = current_sy[0].name
                debug_info["auto_assigned_school_year"] = school_year_id
        except Exception as e:
            debug_info["school_year_lookup_error"] = str(e)
            
        if not school_year_id:
            return validation_error_response("Validation failed", {"school_year_id": ["No active school year found for campus"]}, debug_info=debug_info)

        # Get current user as teacher
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")

        debug_info["teacher_lookup"] = {
            "current_user": current_user,
            "teacher_found": teacher,
            "teacher_type": str(type(teacher))
        }

        if not teacher:
            debug_info["teacher_lookup_error"] = "No teacher found for current user"
            return error_response("Only teachers can create events", debug_info=debug_info)

        # Create event - ensure create_by is a valid SIS Teacher
        event_data = {
            "doctype": "SIS Event",
            "campus_id": campus_id,
            "school_year_id": school_year_id,  # Auto-assign current school year
            "title": data.get("title"),
            "description": data.get("description"),
            "create_by": teacher,  # This should be a valid SIS Teacher name
            "create_at": frappe.utils.now(),
            "status": "approved",  # Auto-approve all events temporarily
            "approved_at": frappe.utils.now(),  # Set approved time
            "approved_by": teacher,  # Set approved by same teacher who created
        }

        # Will hold processed schedules for new format to be created after event insert
        processed_schedules = []

        # Handle old format
        if has_old_format:
            event_data.update({
                "start_time": data.get("start_time"),
                "end_time": data.get("end_time"),
                "timetable_column_id": data.get("timetable_column_id"),
            })

        # Handle schedule format  
        elif has_schedule_format:
            # For schedule format, use dates from schedules to set meaningful start/end times
            if date_schedules and len(date_schedules) > 0:
                try:
                    # Find earliest and latest dates
                    dates = []
                    for ds in date_schedules:
                        if isinstance(ds, dict) and ds.get('date'):
                            dates.append(ds.get('date'))
                    
                    if dates:
                        # Sort dates and use earliest as start, latest as end
                        dates.sort()
                        # Convert date strings to datetime for consistency
                        start_date_str = dates[0] + " 08:00:00"  # Default to 8 AM
                        end_date_str = dates[-1] + " 17:00:00"  # Default to 5 PM
                        
                        event_data["start_time"] = frappe.utils.get_datetime(start_date_str)
                        event_data["end_time"] = frappe.utils.get_datetime(end_date_str)
                    else:
                        # Fallback if no valid dates found
                        current_time = frappe.utils.now_datetime()
                        event_data["start_time"] = current_time
                        event_data["end_time"] = current_time
                except Exception as e:
                    debug_info["start_end_time_error"] = str(e)
                    current_time = frappe.utils.now_datetime()
                    event_data["start_time"] = current_time
                    event_data["end_time"] = current_time
            else:
                current_time = frappe.utils.now_datetime()
                event_data["start_time"] = current_time
                event_data["end_time"] = current_time
                
            event_data["timetable_column_id"] = None

            if date_schedules and isinstance(date_schedules, list):
                # Prepare date schedules for creation (do NOT attach to event doc child table)
                for ds in date_schedules:
                    try:
                        if not ds or not isinstance(ds, dict):
                            debug_info.setdefault("schedule_processing_warnings", []).append(f"Skipping invalid schedule data: {ds}")
                            continue
                            
                        event_date = ds.get('date') if isinstance(ds, dict) else None
                        if not event_date and isinstance(ds, dict):
                            event_date = ds.get('event_date')

                        schedule_ids_value = []
                        if isinstance(ds, dict):
                            schedule_ids_value = ds.get('scheduleIds') or ds.get('schedule_ids') or []

                        # Safe string conversion
                        if isinstance(schedule_ids_value, list):
                            schedule_ids_str = ','.join(str(x) for x in schedule_ids_value if x is not None)
                        else:
                            schedule_ids_str = str(schedule_ids_value) if schedule_ids_value is not None else ''

                        # Allow empty schedule_ids for date-only events
                        if not event_date:
                            debug_info.setdefault("schedule_processing_warnings", []).append(f"Skipping schedule with missing date: {ds}")
                            continue

                        # If no scheduleIds, try to create a meaningful schedule from start_time/end_time
                        if not schedule_ids_str:
                            start_time = ds.get('start_time')
                            end_time = ds.get('end_time')
                            if start_time and end_time:
                                schedule_ids_str = f"manual-{start_time}-{end_time}"  # Temporary identifier
                                debug_info.setdefault("schedule_processing_notes", []).append(f"Created manual schedule ID for {event_date}: {schedule_ids_str}")
                            else:
                                schedule_ids_str = ""  # Allow empty for date-only events
                        
                        processed_schedules.append({
                            "event_date": event_date,
                            "schedule_ids": schedule_ids_str
                        })
                    except Exception as se:
                        debug_info.setdefault("schedule_processing_errors", []).append(f"Error processing schedule: {str(se)}")
                        continue

        # Handle datetime format
        elif has_datetime_format:
            # For datetime format, use actual start/end times from the data
            if date_times and len(date_times) > 0:
                try:
                    # Find earliest start time and latest end time
                    earliest_start = None
                    latest_end = None
                    
                    for dt in date_times:
                        if isinstance(dt, dict):
                            date_val = dt.get('date')
                            start_time = dt.get('start_time') or dt.get('startTime')  
                            end_time = dt.get('end_time') or dt.get('endTime')
                            
                            if date_val and start_time and end_time:
                                # Combine date and time
                                start_datetime_str = f"{date_val} {start_time}:00"
                                end_datetime_str = f"{date_val} {end_time}:00"
                                
                                start_dt = frappe.utils.get_datetime(start_datetime_str)
                                end_dt = frappe.utils.get_datetime(end_datetime_str)
                                
                                if earliest_start is None or start_dt < earliest_start:
                                    earliest_start = start_dt
                                if latest_end is None or end_dt > latest_end:
                                    latest_end = end_dt
                    
                    if earliest_start and latest_end:
                        event_data["start_time"] = earliest_start
                        event_data["end_time"] = latest_end
                    else:
                        # Fallback
                        current_time = frappe.utils.now_datetime()
                        event_data["start_time"] = current_time
                        event_data["end_time"] = current_time
                        
                except Exception as e:
                    debug_info["datetime_start_end_error"] = str(e)
                    current_time = frappe.utils.now_datetime()
                    event_data["start_time"] = current_time
                    event_data["end_time"] = current_time
            else:
                current_time = frappe.utils.now_datetime()
                event_data["start_time"] = current_time
                event_data["end_time"] = current_time
                
            event_data["timetable_column_id"] = None

            if date_times and isinstance(date_times, list):
                # Prepare date times for creation
                for dt in date_times:
                    try:
                        if not dt or not isinstance(dt, dict):
                            debug_info.setdefault("datetime_processing_warnings", []).append(f"Skipping invalid datetime data: {dt}")
                            continue
                            
                        event_date = dt.get('date') if isinstance(dt, dict) else None
                        start_time = dt.get('start_time') if isinstance(dt, dict) else None
                        end_time = dt.get('end_time') if isinstance(dt, dict) else None

                        # Also support startTime/endTime naming
                        if not start_time and isinstance(dt, dict):
                            start_time = dt.get('startTime')
                        if not end_time and isinstance(dt, dict):
                            end_time = dt.get('endTime')

                        if not event_date or not start_time or not end_time:
                            debug_info.setdefault("datetime_processing_warnings", []).append(f"Skipping incomplete datetime: date={event_date}, start={start_time}, end={end_time}")
                            continue

                        processed_schedules.append({
                            "event_date": event_date,
                            "start_time": start_time,
                            "end_time": end_time
                        })
                    except Exception as de:
                        debug_info.setdefault("datetime_processing_errors", []).append(f"Error processing datetime: {str(de)}")
                        continue

        # Validate students are assigned to classes; build quick lookup to reuse later
        student_ids = data.get('student_ids') or []
        class_student_lookup = {}
        missing_students = []
        if isinstance(student_ids, list) and len(student_ids) > 0:
            for sid in student_ids:
                try:
                    class_student = frappe.get_all(
                        "SIS Class Student",
                        filters={"student_id": sid},
                        fields=["name", "class_id"],
                        order_by="creation desc",
                        limit_page_length=1
                    )
                    if class_student:
                        class_student_lookup[sid] = class_student[0]
                    else:
                        missing_students.append(sid)
                except Exception as _e:
                    missing_students.append(sid)
        if missing_students:
            return validation_error_response("Validation failed", {
                "students": [
                    f"Student(s) not assigned to any class: {', '.join(missing_students)}"
                ]
            }, debug_info=debug_info)

        # Do not auto-assign homeroom teacher at event level; approvals are per Event Student
        debug_info["homeroom_teacher_note"] = "Skipped setting homeroom_teacher_id at Event level; approvals handled per Event Student"

        # Capture status field meta for debugging
        try:
            meta = frappe.get_meta("SIS Event")
            status_field = meta.get_field("status")
            debug_info["status_meta"] = {
                "options": status_field.options if status_field else None,
                "default": status_field.default if status_field else None
            }
        except Exception as _e:
            debug_info["status_meta_error"] = str(_e)

        # Normalize and enforce a valid default status based on DocType meta to avoid option mismatch
        try:
            if status_field and status_field.options:
                options_raw = status_field.options
                # Robust split: try double-escaped, then single-escaped, then real newline
                parts = options_raw.split("\\\\n") if "\\\\n" in options_raw else []
                if not parts or len(parts) == 1:
                    parts = options_raw.split("\\n") if "\\n" in options_raw else parts
                if not parts or len(parts) == 1:
                    parts = options_raw.splitlines()

                # Keep tokens EXACTLY as defined in DocType (no trim) to avoid hidden char mismatch
                allowed_statuses = [opt for opt in parts if opt]
                forced_status = allowed_statuses[0] if len(allowed_statuses) > 0 else None
                
                # TEMPORARILY COMMENTED - Don't override approved status
                # if forced_status:
                #     event_data["status"] = forced_status
                #     debug_info["status_applied"] = forced_status
                #     debug_info["status_value_repr"] = repr(forced_status)
                #     debug_info["allowed_statuses_repr"] = [repr(x) for x in allowed_statuses]
                # else:
                #     debug_info["status_applied_error"] = {
                #         "reason": "no_allowed_statuses",
                #         "options_raw": options_raw
                #     }
                
                # Debug info for current status
                debug_info["status_kept"] = event_data.get("status")
                debug_info["status_would_be_forced_to"] = forced_status
                debug_info["allowed_statuses_available"] = allowed_statuses
        except Exception as _e:
            debug_info["status_apply_exception"] = str(_e)

        event = frappe.get_doc(event_data)

        # Set homeroom teacher if provided
        if data.get("homeroom_teacher_id"):
            event.homeroom_teacher_id = data.get("homeroom_teacher_id")
        else:
            # Auto-assign based on participants (TODO: implement logic)
            pass

        event.insert()
        frappe.db.commit()

        # Create date schedule records separately for schedule format to avoid child-table mandatory issues
        if has_schedule_format and processed_schedules:
            created_schedule_names = []
            for ds in processed_schedules:
                try:
                    event_date = ds.get("event_date") if ds else None
                    schedule_ids = ds.get("schedule_ids") if ds else ""
                    if not event_date:
                        debug_info.setdefault("schedule_creation_warnings", []).append(f"Skipping schedule due to missing date: {ds}")
                        continue
                    
                    # Allow empty schedule_ids - some events may be date-only

                    schedule_doc = frappe.get_doc({
                        "doctype": "SIS Event Date Schedule",
                        "event_id": event.name,
                        "event_date": event_date,
                        "schedule_ids": schedule_ids,
                        "create_at": frappe.utils.now()
                    })
                    schedule_doc.insert()
                    created_schedule_names.append(schedule_doc.name)
                except Exception as e:
                    # Collect but do not fail the whole request; these will be visible in debug_info
                    if "schedule_creation_errors" not in debug_info:
                        debug_info["schedule_creation_errors"] = []
                    debug_info["schedule_creation_errors"].append(str(e))

            if created_schedule_names:
                debug_info["created_schedule_names"] = created_schedule_names
                debug_info["schedule_creation_count"] = len(created_schedule_names)

        # Create date time records separately for datetime format
        elif has_datetime_format and processed_schedules:
            created_datetime_names = []
            for dt in processed_schedules:
                try:
                    event_date = dt.get("event_date") if dt else None
                    start_time = dt.get("start_time") if dt else None
                    end_time = dt.get("end_time") if dt else None
                    if not event_date or not start_time or not end_time:
                        debug_info.setdefault("datetime_creation_warnings", []).append(f"Skipping datetime due to missing data: date={event_date}, start={start_time}, end={end_time}")
                        continue

                    datetime_doc = frappe.get_doc({
                        "doctype": "SIS Event Date Time",
                        "event_id": event.name,
                        "event_date": event_date,
                        "start_time": start_time,
                        "end_time": end_time,
                        "create_at": frappe.utils.now()
                    })
                    datetime_doc.insert()
                    created_datetime_names.append(datetime_doc.name)
                except Exception as e:
                    # Collect but do not fail the whole request; these will be visible in debug_info
                    if "datetime_creation_errors" not in debug_info:
                        debug_info["datetime_creation_errors"] = []
                    debug_info["datetime_creation_errors"].append(str(e))

            if created_datetime_names:
                debug_info["created_datetime_names"] = created_datetime_names
                debug_info["datetime_creation_count"] = len(created_datetime_names)

        frappe.db.commit()

        # Prepare normalized default status for Event Student to avoid option mismatch
        event_student_status_default = None
        try:
            es_meta = frappe.get_meta("SIS Event Student")
            es_status_field = es_meta.get_field("status")
            if es_status_field and es_status_field.options:
                es_options_raw = es_status_field.options
                es_parts = es_options_raw.split("\\\\n") if "\\\\n" in es_options_raw else []
                if not es_parts or len(es_parts) == 1:
                    es_parts = es_options_raw.split("\\n") if "\\n" in es_options_raw else es_parts
                if not es_parts or len(es_parts) == 1:
                    es_parts = es_options_raw.splitlines()
                es_allowed = [opt for opt in es_parts if opt]
                pending_match = None
                for tok in es_allowed:
                    if tok.strip().lower() == "pending":
                        pending_match = tok  # keep original token
                        break
                event_student_status_default = pending_match or (es_allowed[0] if es_allowed else None)
            debug_info["event_student_status_meta"] = {
                "options_raw": es_status_field.options if es_status_field else None,
                "chosen_default": event_student_status_default
            }
        except Exception as _e:
            debug_info["event_student_status_meta_error"] = str(_e)

        # Create event student records for participants
        try:
            created_event_students = []
            if isinstance(student_ids, list) and len(student_ids) > 0:
                # Resolve class_student_id for each student (pick latest assignment)
                for sid in student_ids:
                    try:
                        # Safe access to student lookup data
                        cs = class_student_lookup.get(sid) if class_student_lookup else None
                        class_student_id = cs.get("name") if cs and isinstance(cs, dict) else None
                        
                        if not class_student_id:
                            debug_info.setdefault("student_creation_warnings", []).append(f"No class assignment found for student: {sid}")
                            continue
                            
                        doc = frappe.get_doc({
                            "doctype": "SIS Event Student",
                            "campus_id": campus_id,
                            "event_id": event.name,
                            "class_student_id": class_student_id,
                            "status": event_student_status_default or "pending"
                        })
                        doc.insert()
                        created_event_students.append(doc.name)
                    except Exception as _es:
                        if "event_student_creation_errors" not in debug_info:
                            debug_info["event_student_creation_errors"] = []
                        debug_info["event_student_creation_errors"].append(f"Error creating event student for {sid}: {str(_es)}")
            
            if created_event_students:
                frappe.db.commit()
                debug_info["event_students_created"] = created_event_students
                debug_info["event_students_count"] = len(created_event_students)
        except Exception as _e:
            debug_info["event_student_block_error"] = str(_e)

        # Create event teacher records for participants (separate from homeroom/vice roles)
        try:
            created_event_teachers = []
            teacher_ids = data.get('teacher_ids') or []
            if isinstance(teacher_ids, list) and len(teacher_ids) > 0:
                for tid in teacher_ids:
                    try:
                        # Validate teacher_id is not None or empty
                        if not tid or str(tid).strip() == '':
                            debug_info.setdefault("teacher_creation_warnings", []).append(f"Skipping empty teacher ID: {tid}")
                            continue
                            
                        teacher_doc = frappe.get_doc({
                            "doctype": "SIS Event Teacher",
                            "campus_id": campus_id,
                            "event_id": event.name,
                            "teacher_id": tid
                        })
                        teacher_doc.insert()
                        created_event_teachers.append(teacher_doc.name)
                    except Exception as _et:
                        if "event_teacher_creation_errors" not in debug_info:
                            debug_info["event_teacher_creation_errors"] = []
                        debug_info["event_teacher_creation_errors"].append(f"Error creating event teacher for {tid}: {str(_et)}")
            
            if created_event_teachers:
                frappe.db.commit()
                debug_info["event_teachers_created"] = created_event_teachers
                debug_info["event_teachers_count"] = len(created_event_teachers)
        except Exception as _e:
            debug_info["event_teacher_block_error"] = str(_e)

        debug_info["execution_reached_success"] = True
        return single_item_response({
            "name": event.name,
            "title": event.title,
            "status": event.status,
            "created_at": event.create_at,
            "debug_info": debug_info
        }, "Event created successfully")

    except Exception as e:
        frappe.log_error(f"Error creating event: {str(e)}")
        debug_info["exception_occurred"] = str(e)
        debug_info["exception_type"] = str(type(e))
        return error_response(f"Error creating event: {str(e)}", debug_info=debug_info)


# Temporarily commented out - auto-approve all events
# @frappe.whitelist(allow_guest=False)
def approve_event():
    """Approve an event (homeroom teacher only) - TEMPORARILY DISABLED"""
    try:
        data = frappe.local.form_dict
        event_id = data.get("event_id")

        if not event_id:
            return validation_error_response("Validation failed", {"event_id": ["Event ID is required"]})

        # Get current user as teacher
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")

        if not teacher:
            return forbidden_response("Only teachers can approve events")

        # Get event
        event = frappe.get_doc("SIS Event", event_id)

        # Check campus permission
        campus_id = get_current_campus_from_context()
        if campus_id and event.campus_id != campus_id:
            return forbidden_response("Access denied: Campus mismatch")

        # Check if user is the assigned homeroom teacher
        if event.homeroom_teacher_id != teacher:
            return forbidden_response("Only assigned homeroom teacher can approve this event")

        # Check if event is pending
        if event.status != "pending":
            return validation_error_response("Validation failed", {
                "status": [f"Event is already {event.status}"]
            })

        # Temporarily commented - auto-approve all events
        # Approve event
        event.status = "approved"
        event.approved_at = frappe.utils.now()
        event.approved_by = teacher
        event.update_by = teacher
        event.update_at = frappe.utils.now()

        event.save()
        frappe.db.commit()

        # Temporarily commented - skip timetable override creation
        # Create timetable override
        # create_timetable_override(event)

        return single_item_response({
            "name": event.name,
            "status": event.status,
            "approved_at": event.approved_at,
            "approved_by": event.approved_by
        }, "Event approved successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Event not found")
    except Exception as e:
        frappe.log_error(f"Error approving event: {str(e)}")
        return error_response(f"Error approving event: {str(e)}")


# Temporarily commented out - auto-approve all events  
# @frappe.whitelist(allow_guest=False)
def reject_event():
    """Reject an event (homeroom teacher only) - TEMPORARILY DISABLED"""
    try:
        data = frappe.local.form_dict
        event_id = data.get("event_id")
        rejection_reason = data.get("rejection_reason")

        if not event_id:
            return validation_error_response("Validation failed", {"event_id": ["Event ID is required"]})

        if not rejection_reason:
            return validation_error_response("Validation failed", {"rejection_reason": ["Rejection reason is required"]})

        # Get current user as teacher
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")

        if not teacher:
            return forbidden_response("Only teachers can reject events")

        # Get event
        event = frappe.get_doc("SIS Event", event_id)

        # Check campus permission
        campus_id = get_current_campus_from_context()
        if campus_id and event.campus_id != campus_id:
            return forbidden_response("Access denied: Campus mismatch")

        # Check if user is the assigned homeroom teacher
        if event.homeroom_teacher_id != teacher:
            return forbidden_response("Only assigned homeroom teacher can reject this event")

        # Check if event is pending
        if event.status != "pending":
            return validation_error_response("Validation failed", {
                "status": [f"Event is already {event.status}"]
            })

        # Reject event
        event.status = "rejected"
        event.rejection_reason = rejection_reason
        event.update_by = teacher
        event.update_at = frappe.utils.now()

        event.save()
        frappe.db.commit()

        return single_item_response({
            "name": event.name,
            "status": event.status,
            "rejection_reason": event.rejection_reason
        }, "Event rejected successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Event not found")
    except Exception as e:
        frappe.log_error(f"Error rejecting event: {str(e)}")
        return error_response(f"Error rejecting event: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_events():
    """Get events with filtering"""
    try:
        try:
            page = max(1, int(frappe.local.form_dict.get("page", 1)))
        except (ValueError, TypeError):
            page = 1
        try:
            limit = max(1, int(frappe.local.form_dict.get("limit", 20)))
        except (ValueError, TypeError):
            limit = 20
        status = frappe.local.form_dict.get("status")
        date_from = frappe.local.form_dict.get("date_from")
        date_to = frappe.local.form_dict.get("date_to")
        school_year = frappe.local.form_dict.get("school_year")
        for_approval_raw = frappe.local.form_dict.get("for_approval")
        for_approval = str(for_approval_raw).lower() in ("true", "1", "yes")

        # Build filters
        filters = {}

        # Get campus from user context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters["campus_id"] = campus_id

        if status:
            filters["status"] = status
            
        # Add school year filter
        if school_year:
            filters["school_year_id"] = school_year
            
        # If requesting approval list, restrict to events with participants in classes of current teacher (homeroom or vice)
        if for_approval:
            # Current user as teacher
            current_user = frappe.session.user
            teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")
            if not teacher:
                return forbidden_response("Only teachers can view approval list")

            # Find classes where user is homeroom or vice homeroom
            class_filters = {}
            if campus_id:
                class_filters["campus_id"] = campus_id
            classes = frappe.get_all(
                "SIS Class",
                filters=class_filters,
                or_filters=[{"homeroom_teacher": teacher}, {"vice_homeroom_teacher": teacher}],
                fields=["name"],
                limit_page_length=10000
            )
            class_ids = [c.name for c in classes]

            if not class_ids:
                # No classes under this teacher -> empty result
                return single_item_response({
                    "data": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0
                    }
                }, "Events fetched successfully")

            class_students = frappe.get_all(
                "SIS Class Student",
                filters={"class_id": ["in", class_ids]},
                fields=["name"],
                limit_page_length=100000
            )
            class_student_ids = [cs.name for cs in class_students]

            if not class_student_ids:
                return single_item_response({
                    "data": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0
                    }
                }, "Events fetched successfully")

            event_students = frappe.get_all(
                "SIS Event Student",
                filters={"class_student_id": ["in", class_student_ids]},
                fields=["event_id"],
                limit_page_length=100000
            )
            approval_event_ids = list({es.event_id for es in event_students})
            if approval_event_ids:
                filters["name"] = ["in", approval_event_ids]
            else:
                return single_item_response({
                    "data": [],
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": 0,
                        "pages": 0
                    }
                }, "Events fetched successfully")

        if date_from:
            filters["start_time"] = [">=", date_from]

        if date_to:
            if "start_time" not in filters:
                filters["start_time"] = []
            filters["start_time"].append(["<=", date_to])

        # Query events with safe pagination calculation
        try:
            start_offset = max(0, (page - 1) * limit)
        except (TypeError, ValueError):
            start_offset = 0
        events = frappe.get_all(
            "SIS Event",
            fields=[
                "name", "title", "description", "start_time", "end_time",
                "timetable_column_id", "status", "homeroom_teacher_id",
                "approved_at", "approved_by", "create_by", "create_at"
            ],
            filters=filters,
            start=start_offset,
            page_length=limit,
            order_by="create_at desc"
        )

        # Add date schedules information for each event
        for event in events:
            date_schedules = frappe.get_all(
                "SIS Event Date Schedule",
                filters={"event_id": event.name},
                fields=["event_date", "schedule_ids"]
            )

            if date_schedules:
                # Convert schedule_ids string to array and get schedule details
                processed_schedules = []
                for ds in date_schedules:
                    schedule_ids = ds.schedule_ids.split(',') if ds.schedule_ids else []

                    # Get schedule details
                    schedules = []
                    if schedule_ids:
                        schedule_details = frappe.get_all(
                            "SIS Timetable Column",
                            filters={"name": ["in", schedule_ids]},
                            fields=["name", "period_name", "start_time", "end_time", "period_type"]
                        )
                        schedules = schedule_details

                    processed_schedules.append({
                        "date": ds.event_date,
                        "scheduleIds": schedule_ids,
                        "schedules": schedules
                    })

                event["dateSchedules"] = processed_schedules

            date_times = frappe.get_all(
                "SIS Event Date Time",
                filters={"event_id": event.name},
                fields=["event_date", "start_time", "end_time"]
            )

            if date_times:
                # Process date times
                processed_times = []
                for dt in date_times:
                    processed_times.append({
                        "date": dt.event_date,
                        "startTime": dt.start_time,
                        "endTime": dt.end_time
                    })

                event["dateTimes"] = processed_times
        try:
            meta = frappe.get_meta("SIS Event")
            status_field = meta.get_field("status")
            options_raw = status_field.options if status_field else ""
            parts = []
            if options_raw:
                parts = options_raw.split("\\\\n") if "\\\\n" in options_raw else []
                if not parts or len(parts) == 1:
                    parts = options_raw.split("\\n") if "\\n" in options_raw else parts
                if not parts or len(parts) == 1:
                    parts = options_raw.splitlines()
            allowed_statuses = [opt.strip() for opt in parts if opt and opt.strip()]
            allowed_set = set(allowed_statuses)
            for event in events:
                if event.get("status") not in allowed_set and allowed_statuses:
                    event["status"] = allowed_statuses[0]
        except Exception:
            pass

        # Get total count with safe handling
        try:
            total_count = frappe.db.count("SIS Event", filters=filters)
            # Ensure total_count is not None to avoid arithmetic errors
            if total_count is None:
                total_count = 0
        except Exception as e:
            frappe.log_error(f"Error getting count: {str(e)}")
            total_count = len(events)  # Fallback to current page count

        # Safe pagination calculation
        try:
            pages_count = max(1, (total_count + limit - 1) // limit) if total_count > 0 else 1
        except (TypeError, ZeroDivisionError):
            pages_count = 1

        # Debug logging can be enabled here if needed for troubleshooting
        # frappe.log_error(f"EventService get_events: filters={filters}, total_count={total_count}, events_returned={len(events)}, page={page}", "Events Debug")

        result = {
            "data": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": pages_count
            }
        }

        return single_item_response(result, "Events fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching events: {str(e)}")
        return error_response(f"Error fetching events: {str(e)}")


# Temporarily disabled - skip timetable override creation
def create_timetable_override(event):
    """Create timetable override when event is approved - TEMPORARILY DISABLED"""
    # Function temporarily disabled for testing
    return
    try:
        # Get event participants
        participants = frappe.get_all(
            "SIS Event Student",
            filters={"event_id": event.name},
            fields=["student_id" if frappe.db.has_column("SIS Event Student", "student_id") else "student"]
        )

        if not participants:
            return

        # Prefer reading schedules from SIS Event Date Schedule entries (new format)
        date_schedules = frappe.get_all(
            "SIS Event Date Schedule",
            filters={"event_id": event.name},
            fields=["event_date", "schedule_ids"]
        )

        if date_schedules:
            # New format: multiple dates and schedules
            date_schedule_overrides = []

            for ds in date_schedules:
                event_date = ds.event_date
                schedule_ids = ds.schedule_ids.split(',') if ds.schedule_ids else []

                for schedule_id in schedule_ids:
                    date_schedule_overrides.append({
                        "date": event_date,
                        "schedule_id": schedule_id
                    })

            # Create overrides for each date-schedule combination
            for override_info in date_schedule_overrides:
                for participant in participants:
                    # Determine target type and ID
                    student_ref = participant.get("student_id") if isinstance(participant, dict) else getattr(participant, "student_id", None)
                    if not student_ref:
                        student_ref = participant.get("student") if isinstance(participant, dict) else getattr(participant, "student", None)
                    class_id = frappe.db.get_value("SIS Class Student",
                        {"student_id": student_ref, "status": "Active"}, "class_id")

                    if class_id:
                        override = frappe.get_doc({
                            "doctype": "SIS Timetable Override",
                            "event_id": event.name,
                            "date": override_info["date"],
                            "timetable_column_id": override_info["schedule_id"],
                            "target_type": "Class",
                            "target_id": class_id,
                            "subject_id": None,  # Event doesn't have subject
                            "override_type": "replace"
                        })
                        override.insert()

        elif event.start_time and event.timetable_column_id:
            # Old format: single date and schedule
            event_date = event.start_time.date()

            # Create override for each participant
            for participant in participants:
                # Determine target type and ID
                student_ref = participant.get("student_id") if isinstance(participant, dict) else getattr(participant, "student_id", None)
                if not student_ref:
                    student_ref = participant.get("student") if isinstance(participant, dict) else getattr(participant, "student", None)
                class_id = frappe.db.get_value("SIS Class Student",
                    {"student_id": student_ref, "status": "Active"}, "class_id")
                student_ref = participant.get("student_id") if isinstance(participant, dict) else getattr(participant, "student_id", None)
                if not student_ref:
                    student_ref = participant.get("student") if isinstance(participant, dict) else getattr(participant, "student", None)
                class_id = frappe.db.get_value("SIS Class Student",
                    {"student_id": student_ref, "status": "Active"}, "class_id")

                if class_id:
                    override = frappe.get_doc({
                        "doctype": "SIS Timetable Override",
                        "event_id": event.name,
                        "date": event_date,
                        "timetable_column_id": event.timetable_column_id,
                        "target_type": "Class",
                        "target_id": class_id,
                        "subject_id": None,  # Event doesn't have subject
                        "override_type": "replace"
                    })
                    override.insert()

        frappe.db.commit()

    except Exception as e:
        frappe.log_error(f"Error creating timetable override: {str(e)}")
        # Don't raise error to avoid breaking approval process


@frappe.whitelist(allow_guest=False)
def get_event_detail():
    """Get event detail with participants for approval page"""
    try:
        # Be robust in retrieving event_id from different sources
        debug_info = {}
        form_dict = frappe.local.form_dict
        try:
            debug_info["form_dict_keys"] = list(form_dict.keys())
            debug_info["form_dict_preview"] = {k: form_dict.get(k) for k in list(form_dict.keys())[:10]}
        except Exception:
            pass

        event_id = form_dict.get("event_id") or form_dict.get("id") or form_dict.get("name")
        # Determine participant visibility mode
        include_all_participants = False
        try:
            # Support snake_case and camelCase flags from frontend
            raw_flag = form_dict.get("include_all_participants")
            if raw_flag is None:
                raw_flag = form_dict.get("includeAllParticipants")
            include_all_participants = str(raw_flag or "0").lower() in ("1", "true", "yes")

            mode_value = str(form_dict.get("mode") or "").lower()
            if mode_value == "list":
                include_all_participants = True

            # Treat readonly=1 as list mode (view-only)
            readonly_flag = str(form_dict.get("readonly") or "0").lower() in ("1", "true", "yes")
            if readonly_flag:
                include_all_participants = True
        except Exception as _e:
            debug_info["include_all_flag_error"] = str(_e)
        if not event_id:
            try:
                # Fallback to query args if available
                args = getattr(frappe.local.request, "args", None)
                if args:
                    debug_info["request_args_keys"] = list(args.keys())
                    event_id = args.get("event_id") or args.get("id") or args.get("name")
            except Exception as e:
                debug_info["request_args_error"] = str(e)

        if not event_id:
            return validation_error_response("Validation failed", {"event_id": ["Event ID is required"]}, debug_info=debug_info)

        # Load basic event fields without auto-loading child tables
        event_rows = frappe.get_all(
            "SIS Event",
            filters={"name": event_id},
            fields=["name", "title", "description", "status", "create_by", "create_at", "campus_id"],
            limit_page_length=1
        )
        if not event_rows:
            return not_found_response("Event not found")
        event_basic = event_rows[0]

        campus_id = get_current_campus_from_context()
        if campus_id and event_basic.get("campus_id") != campus_id:
            return forbidden_response("Access denied: Campus mismatch")

        # Basic info
        result = {
            "name": event_basic.get("name"),
            "title": event_basic.get("title"),
            "description": event_basic.get("description"),
            "status": event_basic.get("status"),
            "create_by": event_basic.get("create_by"),
            "create_at": event_basic.get("create_at"),
        }

        # Date schedules
        date_schedules = frappe.get_all(
            "SIS Event Date Schedule",
            filters={"event_id": event_id},
            fields=["event_date", "schedule_ids"]
        )
        processed_schedules = []
        for ds in date_schedules:
            schedule_ids = ds.schedule_ids.split(',') if ds.schedule_ids else []
            schedules = []
            if schedule_ids:
                schedule_details = frappe.get_all(
                    "SIS Timetable Column",
                    filters={"name": ["in", schedule_ids]},
                    fields=["name", "period_name", "start_time", "end_time", "period_type"]
                )
                schedules = schedule_details
            processed_schedules.append({
                "date": ds.event_date,
                "scheduleIds": schedule_ids,
                "schedules": schedules
            })
        result["dateSchedules"] = processed_schedules

        # Date times
        date_times = frappe.get_all(
            "SIS Event Date Time",
            filters={"event_id": event_id},
            fields=["event_date", "start_time", "end_time"]
        )
        processed_times = []
        for dt in date_times:
            processed_times.append({
                "date": dt.event_date,
                "startTime": dt.start_time,
                "endTime": dt.end_time
            })
        result["dateTimes"] = processed_times

        # Participants (event students + class/student info minimal)
        # Always return all participants for event details
        allowed_class_ids = set()  # Empty set means no filtering
        include_all_participants = True  # Force include all participants
        
        # Get current user info for attendance permission check
        current_user = frappe.session.user
        current_teacher = None
        try:
            current_teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")
        except Exception:
            pass

        # Fetch event students; include student field if present (student_id or student)
        try:
            student_field_name = "student_id" if frappe.db.has_column("SIS Event Student", "student_id") else ("student" if frappe.db.has_column("SIS Event Student", "student") else None)
        except Exception:
            student_field_name = None

        es_fields = ["name", "class_student_id", "status", "approved_at", "note"]
        if student_field_name:
            es_fields.append(student_field_name)

        event_students = frappe.get_all(
            "SIS Event Student",
            filters={"event_id": event_id},
            fields=es_fields,
            ignore_permissions=True if include_all_participants else False,
            limit_page_length=100000
        )
        # Fallback: some deployments may use field name 'event' instead of 'event_id'
        if not event_students:
            try:
                event_students = frappe.get_all(
                    "SIS Event Student",
                    filters={"event": event_id},
                    fields=es_fields,
                    ignore_permissions=True if include_all_participants else False,
                    limit_page_length=100000
                )
            except Exception:
                pass
        # Last-resort fallback: direct SQL (bypass any query-layer filters)
        if not event_students:
            try:
                columns = ", ".join(es_fields)
                rows = frappe.db.sql(f"select {columns} from `tabSIS Event Student` where event_id=%s", (event_id,), as_dict=True)
                if not rows:
                    rows = frappe.db.sql(f"select {columns} from `tabSIS Event Student` where event=%s", (event_id,), as_dict=True)
                if rows:
                    event_students = rows
            except Exception:
                pass

        # Build Class Student map in bulk
        class_student_ids = [es.class_student_id for es in event_students if es.class_student_id]
        cs_map = {}
        if class_student_ids:
            cs_rows = frappe.get_all(
                "SIS Class Student",
                filters={"name": ["in", class_student_ids]},
                fields=["name", "student_id", "class_id", "school_year_id"],
                limit_page_length=100000,
                ignore_permissions=True if include_all_participants else False
            )
            cs_map = {row.name: row for row in cs_rows}

        # Build Class map for homeroom, vice-homeroom and title info (bulk)
        class_map = {}
        try:
            class_ids_needed = list({row.get("class_id") for row in cs_map.values() if row.get("class_id")})
            if class_ids_needed:
                class_rows = frappe.get_all(
                    "SIS Class",
                    filters={"name": ["in", class_ids_needed]},
                    fields=["name", "homeroom_teacher", "vice_homeroom_teacher", "title", "short_title"],
                    limit_page_length=100000
                )
                class_map = {row.name: row for row in class_rows}
        except Exception as _e:
            debug_info["class_map_error"] = str(_e)

        # Helper to get value from dict or object uniformly
        def _get(obj, key):
            try:
                return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
            except Exception:
                return None

        participants = []
        for es in event_students:
            # Resolve class student and class
            cs_key = _get(es, "class_student_id")
            cs = cs_map.get(cs_key) if cs_key else None
            if not cs and cs_key:
                try:
                    fallback_cs = frappe.get_all(
                        "SIS Class Student",
                        filters={"name": cs_key},
                        fields=["name", "student_id", "class_id", "school_year_id"],
                        limit_page_length=1,
                        ignore_permissions=True if include_all_participants else False
                    )
                    if fallback_cs:
                        cs = fallback_cs[0]
                except Exception:
                    cs = None
            class_id = cs.get("class_id") if cs else None

            # Approval mode: restrict to allowed classes
            if allowed_class_ids and class_id not in allowed_class_ids:
                continue

            # Resolve student id: prefer from class student; fall back to ES.student field
            student_id = cs.get("student_id") if cs else None
            if not student_id and 'student_field_name' in locals() and student_field_name:
                student_id = _get(es, student_field_name)

            student_name = None
            student_code = None
            if student_id:
                student_row = frappe.get_all(
                    "CRM Student",
                    filters={"name": student_id},
                    fields=["student_name", "student_code"],
                    limit_page_length=1,
                    ignore_permissions=True if include_all_participants else False
                )
                if student_row:
                    student_name = student_row[0]["student_name"]
                    student_code = student_row[0]["student_code"]

            klass_info = class_map.get(class_id) if class_id else {}
            if not isinstance(klass_info, dict):
                klass_info = {}
            homeroom_teacher_id = klass_info.get("homeroom_teacher")
            vice_homeroom_teacher_id = klass_info.get("vice_homeroom_teacher")
            class_title = klass_info.get("title")
            class_short_title = klass_info.get("short_title")

            participants.append({
                "event_student_id": _get(es, "name"),
                "class_student_id": _get(es, "class_student_id"),
                "student_id": student_id,
                "student_name": student_name,
                "student_code": student_code,
                "class_id": class_id,
                "class_title": class_title,
                "class_name": class_title or class_short_title,
                "status": _get(es, "status"),
                "approved_at": _get(es, "approved_at"),
                "note": _get(es, "note"),
                "homeroom_teacher_id": homeroom_teacher_id,
                "vice_homeroom_teacher_id": vice_homeroom_teacher_id,
            })
        result["participants"] = participants

        # Optional debug info for troubleshooting empty participants in list mode
        try:
            if include_all_participants:
                debug_part = {
                    "include_all_participants": include_all_participants,
                    "event_students_count": len(event_students),
                    "event_students_sample": [getattr(es, "name", None) for es in event_students[:5]],
                    "class_student_ids_sample": [getattr(es, "class_student_id", None) for es in event_students[:5]],
                    "cs_map_count": len(cs_map or {}),
                    "allowed_class_ids_count": len(allowed_class_ids or []),
                }
                result["debug_info"] = debug_part
        except Exception:
            pass

        # Event teachers list (participants distinct from homeroom/vice approvers)
        try:
            event_teacher_rows = frappe.get_all(
                "SIS Event Teacher",
                filters={"event_id": event_id},
                fields=["name", "teacher_id"],
                limit_page_length=100000
            )
            teacher_ids = [row.teacher_id for row in event_teacher_rows if row.get("teacher_id")]
            teacher_user_map = {}
            if teacher_ids:
                t_rows = frappe.get_all(
                    "SIS Teacher",
                    filters={"name": ["in", teacher_ids]},
                    fields=["name", "user_id"],
                    limit_page_length=100000
                )
                teacher_user_map = {row.name: row.get("user_id") for row in t_rows}
            result["teachers"] = [
                {
                    "event_teacher_id": row.name,
                    "teacher_id": row.teacher_id,
                    "user_id": teacher_user_map.get(row.teacher_id)
                }
                for row in event_teacher_rows
            ]
            except Exception as _e:
                debug_info["event_teacher_list_error"] = str(_e)

        # Add attendance permission check
        can_take_attendance = False
        attendance_debug = {
            "current_user": current_user,
            "current_teacher": current_teacher,
            "event_creator": event_basic.get("create_by"),
            "teachers_list": [t.get("teacher_id") for t in result.get("teachers", [])],
        }
        
        if current_teacher:
            # Can take attendance if user is creator or in teachers list
            is_creator = event_basic.get("create_by") == current_teacher
            is_event_teacher = any(t.get("teacher_id") == current_teacher for t in result.get("teachers", []))
            can_take_attendance = is_creator or is_event_teacher
            
            attendance_debug.update({
                "is_creator": is_creator,
                "is_event_teacher": is_event_teacher,
                "can_take_attendance": can_take_attendance
            })
            
        result["can_take_attendance"] = can_take_attendance
        result["current_teacher_id"] = current_teacher
        result["attendance_debug"] = attendance_debug

        return single_item_response(result, "Event detail fetched successfully")
    except frappe.DoesNotExistError:
        return not_found_response("Event not found")
    except Exception as e:
        frappe.log_error(f"Error fetching event detail: {str(e)}")
        return error_response(f"Error fetching event detail: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_event_student_status():
    """Approve/Reject a single event student"""
    try:
        debug_info = {}
        data = frappe.local.form_dict
        try:
            debug_info["form_dict_keys"] = list(data.keys())
            debug_info["form_dict_preview"] = {k: data.get(k) for k in list(data.keys())[:10]}
        except Exception:
            pass

        # Try to merge JSON body if present
        try:
            request_json = frappe.local.request.get_json()
            if request_json and isinstance(request_json, dict):
                data.update(request_json)
                debug_info["json_body_keys"] = list(request_json.keys())
        except Exception as e:
            debug_info["json_body_error"] = str(e)

        # Fallback to URL args if missing
        try:
            args = getattr(frappe.local.request, "args", None)
            if args and isinstance(args, dict):
                for k, v in args.items():
                    if k not in data:
                        data[k] = v
                debug_info["request_args_keys"] = list(args.keys())
        except Exception as e:
            debug_info["request_args_error"] = str(e)

        # Fallback: parse raw body (URL-encoded) if still missing
        try:
            # frappe.local.request.get_data(as_text=True) may not exist in all versions; handle robustly
            raw_body = None
            try:
                raw_body = frappe.local.request.get_data(as_text=True)  # type: ignore[attr-defined]
            except Exception:
                pass
            if not raw_body:
                try:
                    raw_body = getattr(frappe.local.request, 'data', None)
                    if isinstance(raw_body, (bytes, bytearray)):
                        raw_body = raw_body.decode('utf-8', errors='ignore')
                except Exception:
                    raw_body = None
            if raw_body and isinstance(raw_body, str) and '=' in raw_body:
                from urllib.parse import parse_qs
                parsed = parse_qs(raw_body, keep_blank_values=True)
                # parse_qs returns values as lists
                for k, vlist in parsed.items():
                    if k not in data and vlist:
                        data[k] = vlist[0]
                debug_info["raw_body_parsed_keys"] = list(parsed.keys())
        except Exception as e:
            debug_info["raw_body_parse_error"] = str(e)

        # Accept common aliases
        event_student_id = data.get("event_student_id") or data.get("id") or data.get("name")
        status = data.get("status")  # approved | rejected | pending
        note = data.get("note")

        if not event_student_id:
            return validation_error_response("Validation failed", {"event_student_id": ["Required"]}, debug_info=debug_info)
        if status not in ("approved", "rejected", "pending"):
            return validation_error_response("Validation failed", {"status": ["Invalid status"]})

        es = frappe.get_doc("SIS Event Student", event_student_id)

        # Permission: only homeroom/vice homeroom of the student's class can update
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")
        if not teacher:
            return forbidden_response("Only teachers can approve/reject")

        cls = frappe.get_doc("SIS Class Student", es.class_student_id)
        klass = frappe.get_doc("SIS Class", cls.class_id)
        if teacher not in (klass.homeroom_teacher, klass.vice_homeroom_teacher):
            return forbidden_response("Only homeroom or vice homeroom teacher can update")

        es.status = status
        es.note = note
        es.approved_at = frappe.utils.now() if status in ("approved", "rejected") else None
        es.save()
        frappe.db.commit()

        return single_item_response({"event_student_id": es.name, "status": es.status, "approved_at": es.approved_at}, "Updated successfully")
    except Exception as e:
        frappe.log_error(f"Error updating event student: {str(e)}")
        return error_response(f"Error updating event student: {str(e)}")


def _get_request_arg(name: str, fallback: Optional[str] = None) -> Optional[str]:
    """Helper function to get request argument from multiple sources"""
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


@frappe.whitelist(allow_guest=False)
def delete_event():
    """Delete an event (only creator can delete)"""
    try:
        # Get event_id from multiple sources (form data or JSON) - following education_stage.py pattern
        event_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        event_id = frappe.form_dict.get('event_id')  # Note: frappe.form_dict NOT frappe.local.form_dict

        # If not found, try from JSON payload
        if not event_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                event_id = json_data.get('event_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                # If JSON fails, try parsing as form-encoded data
                try:
                    from urllib.parse import parse_qs
                    # Handle bytes data
                    if isinstance(frappe.request.data, bytes):
                        data_str = frappe.request.data.decode('utf-8')
                    else:
                        data_str = str(frappe.request.data)
                    
                    # Parse form-encoded data
                    parsed_data = parse_qs(data_str)
                    if 'event_id' in parsed_data:
                        event_id = parsed_data['event_id'][0]  # parse_qs returns lists
                except Exception:
                    pass

        if not event_id:
            return validation_error_response(
                message="Validation failed",
                errors={
                    "event_id": ["Event ID is required"],
                    "debug_info": {
                        "form_dict": dict(frappe.form_dict),
                        "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                        "event_id_value": repr(event_id)
                    }
                }
            )

        # Get current user as teacher
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")

        if not teacher:
            return forbidden_response("Only teachers can delete events")

        # Get event details using SQL to avoid child table loading issues
        event_data = frappe.db.sql("""
            SELECT campus_id, create_by, status 
            FROM `tabSIS Event` 
            WHERE name = %s
        """, (event_id,), as_dict=True)
        
        if not event_data:
            return not_found_response("Event not found")
        
        event = event_data[0]

        # Check campus permission
        campus_id = get_current_campus_from_context()
        if campus_id and event.campus_id != campus_id:
            return forbidden_response("Access denied: Campus mismatch")

        # Check if user is the creator
        if event.create_by != teacher:
            return forbidden_response("Only event creator can delete this event")

        # Check if event can be deleted (not approved/in progress)
        if event.status == "approved":
            return validation_error_response("Validation failed", {
                "status": ["Cannot delete approved events"]
            })

        # Delete related records first using safer approach
        try:
            # Delete event students - use direct SQL to avoid parent column issues
            frappe.db.sql("""DELETE FROM `tabSIS Event Student` WHERE event_id = %s""", (event_id,))
        except Exception as e:
            frappe.log_error(f"Error deleting event students: {str(e)}", "Delete Event")
            # No fallback needed - if SQL fails, continue with other deletions
            pass
        
        try:
            # Delete event teachers - use direct SQL to avoid parent column issues  
            frappe.db.sql("""DELETE FROM `tabSIS Event Teacher` WHERE event_id = %s""", (event_id,))
        except Exception as e:
            frappe.log_error(f"Error deleting event teachers: {str(e)}", "Delete Event")
            # No fallback needed - if SQL fails, continue with other deletions
            pass
        
        try:
            # Delete event date schedules - use direct SQL to avoid parent column issues
            frappe.db.sql("""DELETE FROM `tabSIS Event Date Schedule` WHERE event_id = %s""", (event_id,))
        except Exception as e:
            frappe.log_error(f"Error deleting event date schedules: {str(e)}", "Delete Event")
            # No fallback needed - if SQL fails, continue with other deletions
            pass

        try:
            # Delete event date times - use direct SQL to avoid parent column issues
            frappe.db.sql("""DELETE FROM `tabSIS Event Date Time` WHERE event_id = %s""", (event_id,))
        except Exception as e:
            frappe.log_error(f"Error deleting event date times: {str(e)}", "Delete Event")
            # No fallback needed - if SQL fails, continue with other deletions
            pass
        
        try:
            # Delete timetable overrides if any - use direct SQL to avoid parent column issues
            frappe.db.sql("""DELETE FROM `tabSIS Timetable Override` WHERE event_id = %s""", (event_id,))
        except Exception as e:
            frappe.log_error(f"Error deleting timetable overrides: {str(e)}", "Delete Event")
            # No fallback needed - if SQL fails, continue with other deletions
            pass

        # Delete the event using SQL to avoid child table issues
        try:
            frappe.db.sql("""DELETE FROM `tabSIS Event` WHERE name = %s""", (event_id,))
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(f"Error deleting main event record: {str(e)}", "Delete Event")
            return error_response(f"Error deleting event: {str(e)}")

        return single_item_response({
            "name": event_id,
            "deleted": True
        }, "Event deleted successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Event not found")
    except Exception as e:
        frappe.log_error(f"Error deleting event: {str(e)}")
        return error_response(f"Error deleting event: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_event_attendance():
    """Get event attendance for a specific date"""
    try:
        data = frappe.local.form_dict
        event_id = data.get("event_id")
        attendance_date = data.get("date")
        
        if not event_id or not attendance_date:
            return validation_error_response("Validation failed", {
                "event_id": ["Event ID is required"] if not event_id else [],
                "date": ["Date is required"] if not attendance_date else []
            })
        
        # Get current user as teacher
        current_user = frappe.session.user
        current_teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")
        
        if not current_teacher:
            return forbidden_response("Only teachers can access event attendance")
        
        # Verify permission to take attendance for this event
        event = frappe.get_doc("SIS Event", event_id)
        
        # Check if user is creator or in teachers list
        is_creator = event.create_by == current_teacher
        event_teachers = frappe.get_all("SIS Event Teacher", 
                                      filters={"event_id": event_id}, 
                                      fields=["teacher_id"])
        is_event_teacher = any(t.teacher_id == current_teacher for t in event_teachers)
        
        if not (is_creator or is_event_teacher):
            return forbidden_response("Only event creator or assigned teachers can take attendance")
        
        # Get event students/participants
        event_students = frappe.get_all("SIS Event Student",
                                      filters={"event_id": event_id},
                                      fields=["name", "class_student_id", "status"])
        
        # Build participant list with student info
        participants = []
        for es in event_students:
            # Get class student info
            try:
                cs = frappe.get_doc("SIS Class Student", es.class_student_id)
                student = frappe.get_doc("CRM Student", cs.student_id)
                
                participants.append({
                    "event_student_id": es.name,
                    "class_student_id": es.class_student_id,
                    "student_id": cs.student_id,
                    "student_name": student.student_name,
                    "student_code": student.student_code,
                    "user_image": getattr(student, 'user_image', None)
                })
            except Exception:
                continue
        
        # Get existing attendance records for this date
        attendance_records = frappe.get_all("SIS Event Attendance",
                                          filters={
                                              "event_id": event_id,
                                              "attendance_date": attendance_date
                                          },
                                          fields=["student_id", "status"])
        
        attendance_map = {record.student_id: record.status for record in attendance_records}
        
        # Add attendance status to participants
        for p in participants:
            p["attendance_status"] = attendance_map.get(p["student_id"], "present")
        
        result = {
            "event": {
                "name": event.name,
                "title": event.title,
                "description": event.description
            },
            "date": attendance_date,
            "participants": participants
        }
        
        return single_item_response(result, "Event attendance fetched successfully")
        
    except frappe.DoesNotExistError:
        return not_found_response("Event not found")
    except Exception as e:
        frappe.log_error(f"Error fetching event attendance: {str(e)}")
        return error_response(f"Error fetching event attendance: {str(e)}")


@frappe.whitelist(allow_guest=False) 
def save_event_attendance():
    """Save event attendance for a specific date"""
    try:
        data = frappe.local.form_dict
        
        # Try to get JSON data from request body
        try:
            request_data = frappe.local.request.get_json()
            if request_data:
                data.update(request_data)
        except Exception:
            pass
        
        event_id = data.get("event_id")
        attendance_date = data.get("date")
        attendance_data = data.get("attendance", [])
        
        if not event_id or not attendance_date or not attendance_data:
            return validation_error_response("Validation failed", {
                "event_id": ["Event ID is required"] if not event_id else [],
                "date": ["Date is required"] if not attendance_date else [],
                "attendance": ["Attendance data is required"] if not attendance_data else []
            })
        
        # Parse attendance_data if it's a string
        if isinstance(attendance_data, str):
            try:
                attendance_data = frappe.parse_json(attendance_data)
            except Exception:
                return validation_error_response("Validation failed", {
                    "attendance": ["Invalid attendance data format"]
                })
        
        # Get current user as teacher
        current_user = frappe.session.user
        current_teacher = frappe.db.get_value("SIS Teacher", {"user_id": current_user}, "name")
        
        if not current_teacher:
            return forbidden_response("Only teachers can save event attendance")
        
        # Verify permission
        event = frappe.get_doc("SIS Event", event_id)
        is_creator = event.create_by == current_teacher
        event_teachers = frappe.get_all("SIS Event Teacher", 
                                      filters={"event_id": event_id}, 
                                      fields=["teacher_id"])
        is_event_teacher = any(t.teacher_id == current_teacher for t in event_teachers)
        
        if not (is_creator or is_event_teacher):
            return forbidden_response("Only event creator or assigned teachers can save attendance")
        
        # Save attendance records
        saved_count = 0
        for item in attendance_data:
            student_id = item.get("student_id")
            status = item.get("status", "present")
            
            if not student_id:
                continue
            
            # Check if record exists
            existing = frappe.get_all("SIS Event Attendance",
                                    filters={
                                        "event_id": event_id,
                                        "attendance_date": attendance_date,
                                        "student_id": student_id
                                    },
                                    fields=["name"])
            
            if existing:
                # Update existing record
                doc = frappe.get_doc("SIS Event Attendance", existing[0].name)
                doc.status = status
                doc.recorded_by = current_teacher
                doc.recorded_at = frappe.utils.now()
                doc.save()
            else:
                # Create new record
                doc = frappe.get_doc({
                    "doctype": "SIS Event Attendance",
                    "event_id": event_id,
                    "attendance_date": attendance_date,
                    "student_id": student_id,
                    "status": status,
                    "recorded_by": current_teacher,
                    "recorded_at": frappe.utils.now()
                })
                doc.insert()
            
            saved_count += 1
        
        frappe.db.commit()
        
        return single_item_response({
            "saved_count": saved_count,
            "event_id": event_id,
            "date": attendance_date
        }, "Event attendance saved successfully")
        
    except frappe.DoesNotExistError:
        return not_found_response("Event not found")
    except Exception as e:
        frappe.log_error(f"Error saving event attendance: {str(e)}")
        return error_response(f"Error saving event attendance: {str(e)}")
