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

        # Required fields validation - support both old and new format
        has_old_format = data.get('start_time') and data.get('end_time')
        has_new_format = data.get('date_schedules') or data.get('dateSchedules')

        if not has_old_format and not has_new_format:
            return validation_error_response("Validation failed", {
                "time_info": ["Either start_time/end_time or dateSchedules must be provided"]
            })

        if has_old_format and has_new_format:
            return validation_error_response("Validation failed", {
                "time_info": ["Cannot use both old format (start_time/end_time) and new format (dateSchedules) simultaneously"]
            })

        required_fields = ['title']
        if has_old_format:
            required_fields.extend(['start_time', 'end_time'])
        elif has_new_format:
            required_fields.append('dateSchedules')

        missing_fields = [field for field in required_fields if not data.get(field)]

        if missing_fields:
            return validation_error_response("Validation failed", {
                field: ["This field is required"] for field in missing_fields
            })

        # Get campus from context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            return validation_error_response("Validation failed", {"campus_id": ["Campus context not found"]})

        # Get current user as teacher
        current_user = frappe.session.user
        teacher = frappe.db.get_value("SIS Teacher", {"user": current_user}, "name")

        if not teacher:
            return forbidden_response("Only teachers can create events")

        # Create event
        event_data = {
            "doctype": "SIS Event",
            "campus_id": campus_id,
            "title": data.get("title"),
            "description": data.get("description"),
            "status": "pending",
            "create_by": teacher,
            "create_at": frappe.utils.now(),
        }

        # Handle old format
        if has_old_format:
            event_data.update({
                "start_time": data.get("start_time"),
                "end_time": data.get("end_time"),
                "timetable_column_id": data.get("timetable_column_id"),
            })

        # Handle new format
        elif has_new_format:
            date_schedules = data.get('dateSchedules') or data.get('date_schedules')
            if date_schedules:
                # Prepare date schedules for creation
                processed_schedules = []
                for ds in date_schedules:
                    processed_schedules.append({
                        "event_date": ds.get('date'),
                        "schedule_ids": ','.join(ds.get('scheduleIds', []))
                    })
                event_data["date_schedules"] = processed_schedules

        event = frappe.get_doc(event_data)

        # Set homeroom teacher if provided
        if data.get("homeroom_teacher_id"):
            event.homeroom_teacher_id = data.get("homeroom_teacher_id")
        else:
            # Auto-assign based on participants (TODO: implement logic)
            pass

        event.insert()
        frappe.db.commit()

        return single_item_response({
            "name": event.name,
            "title": event.title,
            "status": event.status,
            "created_at": event.create_at
        }, "Event created successfully")

    except Exception as e:
        frappe.log_error(f"Error creating event: {str(e)}")
        return error_response(f"Error creating event: {str(e)}")


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
        teacher = frappe.db.get_value("SIS Teacher", {"user": current_user}, "name")

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
        teacher = frappe.db.get_value("SIS Teacher", {"user": current_user}, "name")

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

        # Build filters
        filters = {}

        # Get campus from user context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters["campus_id"] = campus_id

        if status:
            filters["status"] = status

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
            filters={"parent": event.name},
            fields=["student"]
        )

        if not participants:
            return

        # Handle different date formats
        if hasattr(event, 'date_schedules') and event.date_schedules:
            # New format: multiple dates and schedules
            date_schedule_overrides = []

            for ds in event.date_schedules:
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
                    student_doc = frappe.get_doc("SIS Student", participant.student)
                    class_id = frappe.db.get_value("SIS Class Student",
                        {"student": participant.student, "status": "Active"}, "parent")

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
                student_doc = frappe.get_doc("SIS Student", participant.student)
                class_id = frappe.db.get_value("SIS Class Student",
                    {"student": participant.student, "status": "Active"}, "parent")

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
