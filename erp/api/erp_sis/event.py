# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
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

        debug_info["final_data_after_merge"] = dict(data)
        debug_info["final_data_keys"] = list(data.keys())
        debug_info["final_data_types"] = [(k, str(type(v))) for k, v in data.items()]

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

        # Required fields validation - support both old and new format
        start_time_value = data.get('start_time')
        end_time_value = data.get('end_time')
        has_old_format = bool(start_time_value and end_time_value)

        # Fix validation logic for date schedules
        date_schedules = data.get('date_schedules') or data.get('dateSchedules')
        has_new_format = date_schedules and isinstance(date_schedules, list) and len(date_schedules) > 0

        debug_info["validation_check"] = {
            "has_old_format": has_old_format,
            "has_new_format": has_new_format,
            "start_time_value": start_time_value,
            "end_time_value": end_time_value,
            "start_time_type": str(type(start_time_value)),
            "end_time_type": str(type(end_time_value)),
            "date_schedules_value": date_schedules,
            "date_schedules_type": str(type(date_schedules)),
            "data_date_schedules": data.get('date_schedules'),
            "data_dateSchedules": data.get('dateSchedules'),
            "start_time": data.get('start_time'),
            "end_time": data.get('end_time')
        }

        if isinstance(date_schedules, list):
            debug_info["validation_check"]["date_schedules_length"] = len(date_schedules)

        if not has_old_format and not has_new_format:
            debug_info["validation_error"] = "Neither old nor new format provided"
            return validation_error_response("Validation failed", {
                "time_info": ["Either start_time/end_time or dateSchedules must be provided"],
                "debug_info": debug_info
            })

        debug_info["validation_condition_check"] = {
            "condition_old_and_new": has_old_format and has_new_format,
            "condition_old_format": has_old_format,
            "condition_new_format": has_new_format,
            "old_and_new_evaluation": f"{has_old_format} and {has_new_format} = {has_old_format and has_new_format}"
        }

        if has_old_format and has_new_format:
            debug_info["validation_error_triggered"] = "both_formats_detected"
            return validation_error_response("Validation failed", {
                "time_info": ["Cannot use both old format (start_time/end_time) and new format (dateSchedules) simultaneously"]
            }, debug_info=debug_info)

        required_fields = ['title']
        if has_old_format:
            required_fields.extend(['start_time', 'end_time'])
        elif has_new_format:
            # For new format, we don't require any specific field name since we accept both dateSchedules and date_schedules
            pass

        missing_fields = [field for field in required_fields if not data.get(field)]

        # Additional validation for new format
        if has_new_format:
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
            "title": data.get("title"),
            "description": data.get("description"),
            "create_by": teacher,  # This should be a valid SIS Teacher name
            "create_at": frappe.utils.now(),
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

        # Handle new format
        elif has_new_format:
            # For new format, set required datetime fields to current time (they won't be used)
            current_time = frappe.utils.now_datetime()
            event_data["start_time"] = current_time
            event_data["end_time"] = current_time
            event_data["timetable_column_id"] = None

            if date_schedules:
                # Prepare date schedules for creation (do NOT attach to event doc child table)
                for ds in date_schedules:
                    event_date = ds.get('date') if isinstance(ds, dict) else None
                    if not event_date and isinstance(ds, dict):
                        event_date = ds.get('event_date')

                    schedule_ids_value = []
                    if isinstance(ds, dict):
                        schedule_ids_value = ds.get('scheduleIds') or ds.get('schedule_ids') or []

                    if isinstance(schedule_ids_value, list):
                        schedule_ids_str = ','.join(schedule_ids_value)
                    else:
                        schedule_ids_str = str(schedule_ids_value) if schedule_ids_value else ''

                    processed_schedules.append({
                        "event_date": event_date,
                        "schedule_ids": schedule_ids_str
                    })

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
                if forced_status:
                    event_data["status"] = forced_status
                    debug_info["status_applied"] = forced_status
                    debug_info["status_value_repr"] = repr(forced_status)
                    debug_info["allowed_statuses_repr"] = [repr(x) for x in allowed_statuses]
                else:
                    debug_info["status_applied_error"] = {
                        "reason": "no_allowed_statuses",
                        "options_raw": options_raw
                    }
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

        # Create date schedule records separately for new format to avoid child-table mandatory issues
        if has_new_format and processed_schedules:
            created_schedule_names = []
            for ds in processed_schedules:
                try:
                    event_date = ds.get("event_date")
                    schedule_ids = ds.get("schedule_ids")
                    if not event_date or not schedule_ids:
                        continue

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

            frappe.db.commit()
            debug_info["schedules_created"] = created_schedule_names

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
                        cs = class_student_lookup.get(sid)
                        class_student_id = cs["name"] if cs else None
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
                        debug_info["event_student_creation_errors"].append(str(_es))
            if created_event_students:
                frappe.db.commit()
                debug_info["event_students_created"] = created_event_students
        except Exception as _e:
            debug_info["event_student_block_error"] = str(_e)

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


@frappe.whitelist(allow_guest=False)
def approve_event():
    """Approve an event (homeroom teacher only)"""
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

        # Approve event
        event.status = "approved"
        event.approved_at = frappe.utils.now()
        event.approved_by = teacher
        event.update_by = teacher
        event.update_at = frappe.utils.now()

        event.save()
        frappe.db.commit()

        # Create timetable override
        create_timetable_override(event)

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


@frappe.whitelist(allow_guest=False)
def reject_event():
    """Reject an event (homeroom teacher only)"""
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
        # Get query parameters
        page = int(frappe.local.form_dict.get("page", 1))
        limit = int(frappe.local.form_dict.get("limit", 20))
        status = frappe.local.form_dict.get("status")
        date_from = frappe.local.form_dict.get("date_from")
        date_to = frappe.local.form_dict.get("date_to")
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

        # Query events
        events = frappe.get_all(
            "SIS Event",
            fields=[
                "name", "title", "description", "start_time", "end_time",
                "timetable_column_id", "status", "homeroom_teacher_id",
                "approved_at", "approved_by", "create_by", "create_at"
            ],
            filters=filters,
            start=(page - 1) * limit,
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

        # Normalize status to a valid option in case options contained literal newlines
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

        # Get total count
        total_count = frappe.db.count("SIS Event", filters=filters)

        result = {
            "data": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit
            }
        }

        return single_item_response(result, "Events fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching events: {str(e)}")
        return error_response(f"Error fetching events: {str(e)}")


def create_timetable_override(event):
    """Create timetable override when event is approved"""
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

        # Participants (event students + class/student info minimal)
        event_students = frappe.get_all(
            "SIS Event Student",
            filters={"event_id": event_id},
            fields=["name", "class_student_id", "status", "approved_at", "note"]
        )
        participants = []
        for es in event_students:
            cs = frappe.get_all(
                "SIS Class Student",
                filters={"name": es.class_student_id},
                fields=["student_id", "class_id", "school_year_id"],
                limit_page_length=1
            )
            student_id = cs[0]["student_id"] if cs else None
            class_id = cs[0]["class_id"] if cs else None
            student = frappe.get_all("CRM Student", filters={"name": student_id}, fields=["student_name", "student_code"], limit_page_length=1)
            student_name = student[0]["student_name"] if student else None
            student_code = student[0]["student_code"] if student else None
            participants.append({
                "event_student_id": es.name,
                "class_student_id": es.class_student_id,
                "student_id": student_id,
                "student_name": student_name,
                "student_code": student_code,
                "class_id": class_id,
                "status": es.status,
                "approved_at": es.approved_at,
                "note": es.note,
            })
        result["participants"] = participants

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
        data = frappe.local.form_dict
        event_student_id = data.get("event_student_id")
        status = data.get("status")  # approved | rejected
        note = data.get("note")

        if not event_student_id:
            return validation_error_response("Validation failed", {"event_student_id": ["Required"]})
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
