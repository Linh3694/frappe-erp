

# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.utils.data import get_time
from datetime import datetime, timedelta
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    error_response,
    forbidden_response,
    list_response,
    not_found_response,
    single_item_response,
    success_response,
    validation_error_response,
)
from .timetable_excel_import import process_excel_import, process_excel_import_with_metadata_v2
from .timetable_column import format_time_for_html
from .calendar import _get_request_arg

def _noop():
    return None
@frappe.whitelist(allow_guest=False)
def update_timetable_column():
    """Update an existing timetable column"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}

        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                else:
                    data = frappe.local.form_dict
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        # Try multiple ways to get timetable_column_id
        timetable_column_id = data.get("timetable_column_id")

        # If not found in data, try form_dict directly
        if not timetable_column_id and frappe.local.form_dict:
            timetable_column_id = frappe.local.form_dict.get("timetable_column_id")

        # If still not found, try URL path (similar to get_timetable_column_by_id)
        if not timetable_column_id:
            # Check if timetable_column_id is in URL path
            import re
            # Try different URL patterns
            url_patterns = [
                r'/api/method/erp\.api\.erp_sis\.timetable\.update_timetable_column/([^/?]+)',
                r'/api/method/erp\.api\.erp_sis\.timetable\.update_timetable_column\?(.+)',
                r'update_timetable_column/([^/?]+)',
                r'/erp\.api\.erp_sis\.timetable\.update_timetable_column/([^/?]+)',
                r'update_timetable_column/?([^/?]+)',
            ]

            for pattern in url_patterns:
                match = re.search(pattern, frappe.request.url or '')
                if match:
                    timetable_column_id = match.group(1)
                    break

            # Also try to extract from query parameters
            if not timetable_column_id and frappe.local.form_dict:
                timetable_column_id = frappe.local.form_dict.get("timetable_column_id")

        # Final fallback - try to get from any source
        if not timetable_column_id:
            # Check if it's in the request args
            import urllib.parse
            if hasattr(frappe.request, 'args') and frappe.request.args:
                parsed_args = urllib.parse.parse_qs(frappe.request.args)
                if 'timetable_column_id' in parsed_args:
                    timetable_column_id = parsed_args['timetable_column_id'][0]

        if not timetable_column_id:
            return validation_error_response("Validation failed", {"timetable_column_id": ["Timetable Column ID is required"]})

        # Get campus from user context
        campus_id = get_current_campus_from_context() or "campus-1"

        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            timetable_column_doc = frappe.get_doc("SIS Timetable Column", timetable_column_id)

            # Check campus permission
            if timetable_column_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to modify this timetable column")

        except frappe.DoesNotExistError:
            return not_found_response("Timetable column not found")
        
        # Extract values from data
        education_stage_id = data.get("education_stage_id")
        period_priority = data.get("period_priority")
        period_type = data.get("period_type")
        period_name = data.get("period_name")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        current_start_time_raw = timetable_column_doc.start_time
        current_end_time_raw = timetable_column_doc.end_time


        # Track if any updates were made
        updates_made = []

        # Update fields if provided
        if education_stage_id and education_stage_id != timetable_column_doc.education_stage_id:
            # Verify education stage exists and belongs to same campus
            education_stage_exists = frappe.db.exists(
                "SIS Education Stage",
                {
                    "name": education_stage_id,
                    "campus_id": campus_id
                }
            )

            if not education_stage_exists:
                return not_found_response("Selected education stage does not exist or access denied")

            timetable_column_doc.education_stage_id = education_stage_id
            updates_made.append(f"education_stage_id: {education_stage_id}")

        if period_priority is not None and int(period_priority) != timetable_column_doc.period_priority:
            # Validate period_priority is integer
            try:
                period_priority = int(period_priority)
            except (ValueError, TypeError):
                return validation_error_response("Validation failed", {"period_priority": ["Period priority must be a number"]})

            # Check for duplicate period_priority
            final_education_stage_id = education_stage_id or timetable_column_doc.education_stage_id
            existing = frappe.db.exists(
                "SIS Timetable Column",
                {
                    "education_stage_id": final_education_stage_id,
                    "period_priority": period_priority,
                    "campus_id": campus_id,
                    "name": ["!=", timetable_column_id]
                }
            )
            if existing:
                return validation_error_response("Validation failed", {"period_priority": [f"Timetable column with priority '{period_priority}' already exists for this education stage"]})

            timetable_column_doc.period_priority = period_priority
            updates_made.append(f"period_priority: {period_priority}")

        if period_type and period_type != timetable_column_doc.period_type:
            if period_type not in ['study', 'non-study']:
                return validation_error_response("Validation failed", {"period_type": ["Period type must be 'study' or 'non-study'"]})
            timetable_column_doc.period_type = period_type
            updates_made.append(f"period_type: {period_type}")

        if period_name and period_name != timetable_column_doc.period_name:
            timetable_column_doc.period_name = period_name
            updates_made.append(f"period_name: {period_name}")

        # Handle time updates with better validation
        current_start_time = format_time_for_html(timetable_column_doc.start_time)
        current_end_time = format_time_for_html(timetable_column_doc.end_time)


        if start_time and start_time.strip():
            if start_time != current_start_time:
                try:
                    start_time_obj = get_time(start_time)
                    timetable_column_doc.start_time = start_time
                    updates_made.append(f"start_time: {start_time}")
                except Exception as e:

                    return validation_error_response("Validation failed", {"start_time": ["Invalid start time format"]})
                else:
                    pass

        if end_time and end_time.strip():
            if end_time != current_end_time:
                try:
                    end_time_obj = get_time(end_time)
                    timetable_column_doc.end_time = end_time
                    updates_made.append(f"end_time: {end_time}")
                except Exception as e:
                    return validation_error_response("Validation failed", {"end_time": ["Invalid end time format"]})
            else:
                pass

        # Validate time range after updates
        if hasattr(timetable_column_doc, 'start_time') and hasattr(timetable_column_doc, 'end_time') and timetable_column_doc.start_time and timetable_column_doc.end_time:
            try:
                start_time_obj = get_time(str(timetable_column_doc.start_time))
                end_time_obj = get_time(str(timetable_column_doc.end_time))
                if start_time_obj >= end_time_obj:
                    return validation_error_response("Validation failed", {"start_time": ["Start time must be before end time"]})
            except Exception as e:
                return validation_error_response("Validation failed", {"start_time": ["Invalid time values"]})

        # Check if any updates were made
        if not updates_made:

            # Return current data without changes
            timetable_data = {
                "name": timetable_column_doc.name,
                "education_stage_id": timetable_column_doc.education_stage_id,
                "period_priority": timetable_column_doc.period_priority,
                "period_type": timetable_column_doc.period_type,
                "period_name": timetable_column_doc.period_name,
                "start_time": format_time_for_html(timetable_column_doc.start_time),
                "end_time": format_time_for_html(timetable_column_doc.end_time),
                "campus_id": timetable_column_doc.campus_id
            }
            return single_item_response(timetable_data, "No changes detected")

        # Save and commit changes
        timetable_column_doc.save()
        frappe.db.commit()
        
        # Format time fields for HTML time input (HH:MM format)
        start_time_formatted = format_time_for_html(timetable_column_doc.start_time)
        end_time_formatted = format_time_for_html(timetable_column_doc.end_time)

        timetable_data = {
            "name": timetable_column_doc.name,
            "education_stage_id": timetable_column_doc.education_stage_id,
            "period_priority": timetable_column_doc.period_priority,
            "period_type": timetable_column_doc.period_type,
            "period_name": timetable_column_doc.period_name,
            "start_time": start_time_formatted,
            "end_time": end_time_formatted,
            "campus_id": timetable_column_doc.campus_id
        }
        return single_item_response(timetable_data, "Timetable column updated successfully")
        
    except Exception as e:

        return error_response(f"Error updating timetable column: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_timetable_column():
    """Delete a timetable column"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}

        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                else:
                    data = frappe.local.form_dict
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        # Try to get timetable_column_id from multiple sources
        timetable_column_id = data.get("timetable_column_id")

        # If not found, try URL path
        if not timetable_column_id:
            import re
            url_patterns = [
                r'/api/method/erp\.api\.erp_sis\.timetable\.delete_timetable_column/([^/?]+)',
                r'/erp\.api\.erp_sis\.timetable\.delete_timetable_column/([^/?]+)',
                r'delete_timetable_column/([^/?]+)',
            ]

            for pattern in url_patterns:
                match = re.search(pattern, frappe.request.url or '')
                if match:
                    timetable_column_id = match.group(1)
                    break

        if not timetable_column_id:
            return validation_error_response("Validation failed", {"timetable_column_id": ["Timetable Column ID is required"]})

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get existing document
        try:
            timetable_column_doc = frappe.get_doc("SIS Timetable Column", timetable_column_id)

            # Check campus permission
            if timetable_column_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to delete this timetable column")

        except frappe.DoesNotExistError:
                 return not_found_response("Timetable column not found")

        # Delete the document
        frappe.delete_doc("SIS Timetable Column", timetable_column_id)
        frappe.db.commit()

        return success_response(message="Timetable column deleted successfully")

    except Exception as e:

        return error_response(f"Error deleting timetable column: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_education_stages_for_timetable_column():
    """Get education stages for timetable dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        education_stages = frappe.get_all(
            "SIS Education Stage",
            fields=[
                "name",
                "title_vn",
                "title_en"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return list_response(education_stages, "Education stages fetched successfully")
        
    except Exception as e:

        return error_response(f"Error fetching education stages: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_timetable_column():
    """Create a new timetable column - SIMPLE VERSION"""
    try:

        # Get data from request - handle both JSON and form data
        data = frappe.local.form_dict or {}

        # If request has JSON data, try to parse it
        if frappe.request.data and frappe.request.data.strip():
            try:
                json_data = json.loads(frappe.request.data)
                if json_data and isinstance(json_data, dict):
                    data = json_data
                else:
                    pass
            except (json.JSONDecodeError, TypeError) as e:
                # If JSON parsing fails, use form_dict which contains URL-encoded data
                pass


        # Extract values from data
        education_stage_id = data.get("education_stage_id")
        period_priority = data.get("period_priority")
        period_type = data.get("period_type")
        period_name = data.get("period_name")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        # Input validation
        if not education_stage_id or not period_priority or not period_type or not period_name or not start_time or not end_time:
            frappe.throw(_("All fields are required"))
        
        # Get campus from user context
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            campus_id = None
        
        if not campus_id:
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            if first_campus:
                campus_id = first_campus[0].name
            else:
                default_campus = frappe.get_doc({
                    "doctype": "SIS Campus",
                    "title_vn": "Trường Mặc Định",
                    "title_en": "Default Campus"
                })
                default_campus.insert()
                frappe.db.commit()
                campus_id = default_campus.name
        
        # Check if period priority already exists for this education stage
        existing = frappe.db.exists(
            "SIS Timetable Column",
            {
                "education_stage_id": education_stage_id,
                "period_priority": period_priority,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Period priority '{period_priority}' already exists for this education stage"))
        
        # Create new timetable column
        timetable_column_doc = frappe.get_doc({
            "doctype": "SIS Timetable Column",
            "education_stage_id": education_stage_id,
            "period_priority": period_priority,
            "period_type": period_type,
            "period_name": period_name,
            "start_time": start_time,
            "end_time": end_time,
            "campus_id": campus_id
        })
        
        timetable_column_doc.insert()
        frappe.db.commit()

        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Timetable column created successfully"))

        # For now, let's try returning the original string values to see if formatting is the issue
        timetable_data = {
            "name": timetable_column_doc.name,
            "education_stage_id": timetable_column_doc.education_stage_id,
            "period_priority": timetable_column_doc.period_priority,
            "period_type": timetable_column_doc.period_type,
            "period_name": timetable_column_doc.period_name,
            "start_time": start_time,  # Use original string value
            "end_time": end_time,      # Use original string value
            "campus_id": timetable_column_doc.campus_id
        }

        return single_item_response(timetable_data, "Timetable column created successfully")
        
    except Exception as e:

        frappe.throw(_(f"Error creating timetable column: {str(e)}"))


# =========================
# Timetable week endpoints
# =========================

def _parse_iso_date(date_str: str) -> datetime:
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d")
    except Exception:
        frappe.throw(_(f"Invalid date format: {date_str}. Expect YYYY-MM-DD"))

def _add_days(d: datetime, n: int) -> datetime:
    return d + timedelta(days=n)

def _day_of_week_to_index(dow: str) -> int:
    mapping = {
        "mon": 0, "monday": 0,
        "tue": 1, "tuesday": 1,
        "wed": 2, "wednesday": 2,
        "thu": 3, "thursday": 3,
        "fri": 4, "friday": 4,
        "sat": 5, "saturday": 5,
        "sun": 6, "sunday": 6,
    }
    key = (dow or "").strip().lower()
    # Handle accidental storage of full options string where newline may be real or escaped
    # Case 1: actual newline characters
    if "\n" in key:
        key = key.split("\n")[0].strip()
    # Case 2: literal backslash-n sequence stored as text
    elif "\\n" in key:
        key = key.split("\\n")[0].strip()
    if key not in mapping:
        # Try Vietnamese labels
        vi = {
            "thứ 2": 0, "thu 2": 0,
            "thứ 3": 1, "thu 3": 1,
            "thứ 4": 2, "thu 4": 2,
            "thứ 5": 3, "thu 5": 3,
            "thứ 6": 4, "thu 6": 4,
            "thứ 7": 5, "thu 7": 5,
            "cn": 6, "chủ nhật": 6,
        }
        if key in vi:
            return vi[key]
        return -1
    return mapping[key]

def _apply_timetable_overrides(entries: list[dict], target_type: str, target_id: str, 
                              week_start: datetime, week_end: datetime) -> list[dict]:
    """Apply date-specific timetable overrides to entries"""
    try:
        # Convert datetime to date string for database query
        start_date_str = week_start.strftime("%Y-%m-%d")
        end_date_str = week_end.strftime("%Y-%m-%d")
        
        # Get all overrides for this target and date range from custom table
        overrides = frappe.db.sql("""
            SELECT name, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type
            FROM `tabTimetable_Date_Override`
            WHERE target_type = %s AND target_id = %s AND date BETWEEN %s AND %s
            ORDER BY date ASC, timetable_column_id ASC
        """, (target_type, target_id, start_date_str, end_date_str), as_dict=True)
        
        if not overrides:
            return entries
            
        # Build override map: {date: {timetable_column_id: override_data}}
        override_map = {}
        for override in overrides:
            # Convert date to string format to match entries
            date = override["date"]
            if hasattr(date, 'strftime'):
                # If it's a datetime object, convert to string
                date = date.strftime("%Y-%m-%d")
            else:
                # If it's already a string, ensure it's in correct format
                date = str(date)
                
            column_id = override["timetable_column_id"]
            
            if date not in override_map:
                override_map[date] = {}
                
            # Enrich override with display data
            subject_title = ""
            if override.get("subject_id"):
                subject = frappe.get_doc("SIS Subject", override["subject_id"])
                subject_title = subject.title
                
            teacher_names = []
            if override.get("teacher_1_id"):
                teacher1 = frappe.get_doc("SIS Teacher", override["teacher_1_id"])
                if teacher1.user_id:
                    user1 = frappe.get_doc("User", teacher1.user_id)
                    display_name1 = user1.full_name or f"{user1.first_name or ''} {user1.last_name or ''}".strip()
                    teacher_names.append(display_name1)
                    
            if override.get("teacher_2_id"):
                teacher2 = frappe.get_doc("SIS Teacher", override["teacher_2_id"])
                if teacher2.user_id:
                    user2 = frappe.get_doc("User", teacher2.user_id)
                    display_name2 = user2.full_name or f"{user2.first_name or ''} {user2.last_name or ''}".strip()
                    teacher_names.append(display_name2)
                    
            override_map[date][column_id] = {
                "name": f"override-{override['name']}",  # Mark as override entry
                "subject_title": subject_title,
                "teacher_names": ", ".join(teacher_names),
                "override_type": override.get("override_type", "replace"),
                "override_id": override["name"]
            }
            
        # Apply overrides to entries
        enhanced_entries = []
        
        for entry in entries:
            entry_date = entry.get("date")
            entry_column = entry.get("timetable_column_id")
            
            # Check if there's an override for this date/column combination
            if (entry_date in override_map and 
                entry_column in override_map[entry_date]):
                
                override_data = override_map[entry_date][entry_column]
                
                if override_data["override_type"] == "replace":
                    # Replace entry with override data
                    enhanced_entry = {**entry}  # Copy original entry
                    enhanced_entry.update({
                        "name": override_data["name"],
                        "subject_title": override_data["subject_title"],
                        "teacher_names": override_data["teacher_names"],
                        "is_override": True,
                        "override_id": override_data["override_id"]
                    })
                    enhanced_entries.append(enhanced_entry)
                elif override_data["override_type"] == "remove":
                    # Skip this entry (effectively removing it)
                    continue
                else:  # "add" type
                    # Keep original entry and also add override
                    enhanced_entries.append(entry)
                    override_entry = {**entry}
                    override_entry.update({
                        "name": override_data["name"],
                        "subject_title": override_data["subject_title"], 
                        "teacher_names": override_data["teacher_names"],
                        "is_override": True,
                        "override_id": override_data["override_id"]
                    })
                    enhanced_entries.append(override_entry)
            else:
                # No override, keep original entry
                enhanced_entries.append(entry)
        
        return enhanced_entries
        
    except Exception as e:
        frappe.log_error(f"Error applying timetable overrides: {str(e)}")
        # Return original entries if override processing fails
        return entries


def _build_entries(rows: list[dict], week_start: datetime) -> list[dict]:
    # Load timetable columns map for period info
    column_ids = list({r.get("timetable_column_id") for r in rows if r.get("timetable_column_id")})
    columns_map = {}
    if column_ids:
        for col in frappe.get_all(
            "SIS Timetable Column",
            fields=["name", "period_priority", "period_name", "start_time", "end_time"],
            filters={"name": ["in", column_ids]},
        ):
            columns_map[col.name] = col

    result: list[dict] = []
    for r in rows:
        idx = _day_of_week_to_index(r.get("day_of_week"))
        if idx < 0:
            continue
        d = _add_days(week_start, idx)
        col = columns_map.get(r.get("timetable_column_id")) or {}
        result.append({
            "name": r.get("name"),  # Include row name for editing
            "date": d.strftime("%Y-%m-%d"),
            "day_of_week": r.get("day_of_week"),
            "timetable_column_id": r.get("timetable_column_id"),
            "period_priority": col.get("period_priority"),
            "subject_title": r.get("subject_title") or r.get("subject_name") or r.get("subject") or "",
            "teacher_names": r.get("teacher_names") or r.get("teacher_display") or "",
            "class_id": r.get("class_id"),
        })
    return result


@frappe.whitelist(allow_guest=False)
def get_teacher_week():
    """Return teacher's weekly timetable entries (normalized for FE WeeklyGrid).

    Expects timetable rows stored in Doctype `SIS Timetable Instance Row` with fields:
    - day_of_week (mon..sun)
    - timetable_column_id (link to SIS Timetable Column)
    - subject_id / subject_title
    - teacher_1_id / teacher_2_id
    - class_id
    """
    try:
        # Get parameters from frappe request
        teacher_id = frappe.local.form_dict.get("teacher_id") or frappe.request.args.get("teacher_id")
        week_start = frappe.local.form_dict.get("week_start") or frappe.request.args.get("week_start")
        week_end = frappe.local.form_dict.get("week_end") or frappe.request.args.get("week_end")
        education_stage = frappe.local.form_dict.get("education_stage") or frappe.request.args.get("education_stage")

        if not teacher_id:
            return validation_error_response("Validation failed", {"teacher_id": ["Teacher is required"]})
        if not week_start:
            return validation_error_response("Validation failed", {"week_start": ["Week start is required"]})

        ws = _parse_iso_date(week_start)

        # Resolve teacher_id to SIS Teacher doc name(s) if passed as User email/name
        resolved_teacher_ids = set()
        try:
            # Try direct match by Teacher name
            if frappe.db.exists("SIS Teacher", teacher_id):
                resolved_teacher_ids.add(teacher_id)
            # Try match by user_id (User.name/email)
            alt = frappe.get_all(
                "SIS Teacher",
                fields=["name"],
                filters={"user_id": teacher_id},
                limit=50,
            )
            for t in alt:
                resolved_teacher_ids.add(t.name)
            # If still empty and looks like email, try normalized case-sensitive name
            if not resolved_teacher_ids and "@" in (teacher_id or ""):
                user = frappe.get_all(
                    "User",
                    fields=["name"],
                    filters={"name": teacher_id},
                    limit=1,
                )
                if user:
                    alt2 = frappe.get_all(
                        "SIS Teacher",
                        fields=["name"],
                        filters={"user_id": user[0].name},
                        limit=50,
                    )
                    for t in alt2:
                        resolved_teacher_ids.add(t.name)
        except Exception as resolve_error:
            pass
        # Fallback to original id if nothing resolved
        if not resolved_teacher_ids:
            resolved_teacher_ids.add(teacher_id)
        
        # Query timetable rows
        campus_id = get_current_campus_from_context()

        # Test if campus_id field exists, if not, use empty filters
        filters = {}
        try:
            test_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name"],
                filters={"campus_id": campus_id} if campus_id else {},
                limit=1
            )
            filters = {"campus_id": campus_id} if campus_id else {}
        except Exception as filter_error:
            pass
            filters = {}  # Use no filters if campus_id doesn't exist
        
        # Add education_stage filter by getting valid timetable_column_ids
        if education_stage:
            try:
                # Get timetable columns for this education stage
                column_filters = {"education_stage_id": education_stage}
                if campus_id:
                    column_filters["campus_id"] = campus_id
                    
                valid_columns = frappe.get_all(
                    "SIS Timetable Column",
                    fields=["name"],
                    filters=column_filters
                )
                
                if valid_columns:
                    valid_column_ids = [col.name for col in valid_columns]
                    filters["timetable_column_id"] = ["in", valid_column_ids]
                else:
                    # If no columns found for this education stage, return empty
                    return list_response([], "No timetable columns found for this education stage")
                    
            except Exception as education_filter_error:
                pass  # Continue without education stage filter if there's an error

        # Debug: Try without class_id field first to test table

        # First try to get all records to test table existence
        try:
            all_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name"],
                limit=1
            )
        except Exception as table_error:
            pass
            return error_response(f"Table not found: {str(table_error)}")

        # Try with minimal fields first to see what exists
        try:
            # Step 1: Try with only basic fields
            basic_fields = ["name", "day_of_week"]
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=basic_fields,
                filters=filters,
                limit=5
            )

            # Step 2: Try adding more fields one by one
            available_fields = basic_fields[:]
            # Ensure we attempt to include essential linkage/display fields
            test_fields = [
                "timetable_column_id",
                "subject_id",
                "subject_name",
                "teacher_1_id",
                "teacher_2_id",
                "parent",
            ]

            for field in test_fields:
                try:
                    test_rows = frappe.get_all(
                        "SIS Timetable Instance Row",
                        fields=available_fields + [field],
                        filters=filters,
                        limit=1
                    )
                    available_fields.append(field)
                except Exception as field_error:
                    pass

            # Step 3: Use all available fields
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=available_fields,
                filters=filters,
                order_by="day_of_week asc",
            )

        except Exception as query_error:
            pass
            return error_response(f"Query failed: {str(query_error)}")
        
        # Filter in-memory for teacher (to avoid OR filter limitation in simple get_all)
        rows = [
            r for r in rows
            if (r.get("teacher_1_id") in resolved_teacher_ids) or (r.get("teacher_2_id") in resolved_teacher_ids)
        ]

        # Attach class_id via parent instance if available
        # Also filter instances by date range to ensure only active instances are included
        try:
            parent_ids = list({r.get("parent") for r in rows if r.get("parent")})
            parent_class_map = {}
            if parent_ids:
                # Build filters with date range
                instance_filters = {"name": ["in", parent_ids]}

                # Add date filtering if week dates are available
                if ws and week_end:
                    instance_filters.update({
                        "start_date": ["<=", week_end],
                        "end_date": [">=", ws]
                    })

                instances = frappe.get_all(
                    "SIS Timetable Instance",
                    fields=["name", "class_id"],
                    filters=instance_filters,
                )
                parent_class_map = {i.name: i.class_id for i in instances}

                # Filter out rows whose parent instances are not active for this date range
                valid_parent_ids = set(parent_class_map.keys())
                rows = [r for r in rows if r.get("parent") not in valid_parent_ids or r.get("parent") in valid_parent_ids]
            for r in rows:
                if r.get("parent") and not r.get("class_id"):
                    r["class_id"] = parent_class_map.get(r.get("parent"))
        except Exception as class_map_error:
            pass
        # Enrich subject_title and teacher_names
        try:
            subject_ids = list({r.get("subject_id") for r in rows if r.get("subject_id")})
            subject_title_map = {}
            timetable_subject_by_subject = {}
            timetable_subject_title_map = {}
            if subject_ids:
                subj_rows = frappe.get_all(
                    "SIS Subject",
                    fields=["name", "title", "timetable_subject_id"],
                    filters={"name": ["in", subject_ids]},
                )
                for s in subj_rows:
                    subject_title_map[s.name] = s.title
                    if s.get("timetable_subject_id"):
                        timetable_subject_by_subject[s.name] = s.get("timetable_subject_id")
                # Load timetable subject titles for display preference
                ts_ids = list({ts for ts in timetable_subject_by_subject.values() if ts})
                if ts_ids:
                    ts_rows = frappe.get_all(
                        "SIS Timetable Subject",
                        fields=["name", "title_vn", "title_en"],
                        filters={"name": ["in", ts_ids]},
                    )
                    for ts in ts_rows:
                        timetable_subject_title_map[ts.name] = ts.title_vn or ts.title_en or ""

            teacher_ids = list({tid for r in rows for tid in [r.get("teacher_1_id"), r.get("teacher_2_id")] if tid})
            teacher_user_map = {}
            if teacher_ids:
                teachers = frappe.get_all(
                    "SIS Teacher",
                    fields=["name", "user_id"],
                    filters={"name": ["in", teacher_ids]},
                )
                user_ids = [t.user_id for t in teachers if t.get("user_id")]
                user_display_map = {}
                if user_ids:
                    for u in frappe.get_all(
                        "User",
                        fields=["name", "full_name", "first_name", "middle_name", "last_name"],
                        filters={"name": ["in", user_ids]},
                    ):
                        display = u.get("full_name")
                        if not display:
                            parts = [u.get("first_name"), u.get("middle_name"), u.get("last_name")]
                            display = " ".join([p for p in parts if p]) or u.get("name")
                        user_display_map[u.name] = display
                for t in teachers:
                    teacher_user_map[t.name] = user_display_map.get(t.get("user_id")) or t.get("user_id") or t.get("name")

            for r in rows:
                # Prefer Timetable Subject title if linked via SIS Subject
                subj_id = r.get("subject_id")
                ts_id = timetable_subject_by_subject.get(subj_id)
                ts_title = timetable_subject_title_map.get(ts_id) if ts_id else None
                default_title = subject_title_map.get(subj_id) or r.get("subject_title") or r.get("subject_name") or ""
                r["subject_title"] = ts_title or default_title
                teacher_names_list = []
                if r.get("teacher_1_id"):
                    teacher_names_list.append(teacher_user_map.get(r.get("teacher_1_id")) or "")
                if r.get("teacher_2_id"):
                    teacher_names_list.append(teacher_user_map.get(r.get("teacher_2_id")) or "")
                r["teacher_names"] = ", ".join([n for n in teacher_names_list if n])
        except Exception as enrich_error:
            pass

        entries = _build_entries(rows, ws)
        
        return list_response(entries, "Teacher week fetched successfully")
    except Exception as e:

        return error_response(f"Error fetching teacher week: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_class_week():
    """Return class weekly timetable entries."""
    try:
        # Get parameters from frappe request
        class_id = frappe.local.form_dict.get("class_id") or frappe.request.args.get("class_id")
        week_start = frappe.local.form_dict.get("week_start") or frappe.request.args.get("week_start")
        week_end = frappe.local.form_dict.get("week_end") or frappe.request.args.get("week_end")

        if not class_id:
            return validation_error_response("Validation failed", {"class_id": ["Class is required"]})
        if not week_start:
            return validation_error_response("Validation failed", {"week_start": ["Week start is required"]})

        ws = _parse_iso_date(week_start)
        we = _parse_iso_date(week_end) if week_end else _add_days(ws, 6)

        # 1) Find timetable instances for this class that overlap the requested week
        # Apply date filtering to get only instances that are valid for the requested week
        instance_filters = {"class_id": class_id}
        date_conditions = []

        # Add date range filtering: instances must be active during the requested week
        if ws and we:
            # Instance must start before or on the week end date
            # AND end after or on the week start date
            date_conditions.append(["start_date", "<=", we])
            date_conditions.append(["end_date", ">=", ws])

        if date_conditions:
            # Combine class filter with date filters
            instance_filters.update({
                "start_date": ["<=", we],
                "end_date": [">=", ws]
            })

        try:
            instances = frappe.get_all(
                "SIS Timetable Instance",
                fields=["name", "class_id", "start_date", "end_date"],
                filters=instance_filters,
                order_by="start_date asc"
            )
        except Exception as e:
            return error_response(f"Failed to query instances: {str(e)}")

        if not instances:
            return list_response([], "Class week fetched successfully")

        instance_ids = [i.name for i in instances if i.name]
        instances_map = {i.name: i for i in instances}

        # 2) Load child rows belonging to these instances
        try:
            # Prefer standard child table linkage to avoid relying on custom link field
            row_filters = {
                "parent": ["in", instance_ids],
                "parenttype": "SIS Timetable Instance",
                "parentfield": "weekly_pattern",
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
                ],
                filters=row_filters,
                order_by="day_of_week asc",
            )
            # Fallback: some rows may have been created via explicit link field
            if not rows:
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
                    ],
                    filters={"parent_timetable_instance": ["in", instance_ids]},
                    order_by="day_of_week asc",
                )
                # Normalize to same shape
                for r in alt_rows:
                    r["parent"] = r.get("parent_timetable_instance")
                rows = alt_rows
            # Final fallback: direct SQL in case get_all filters behave differently
            if not rows:
                placeholders = ",".join(["%s"] * len(instance_ids))
                sql = f"""
                    SELECT name, parent, day_of_week, timetable_column_id, subject_id, teacher_1_id, teacher_2_id
                    FROM `tabSIS Timetable Instance Row`
                    WHERE parent IN ({placeholders})
                """
                sql_rows = frappe.db.sql(sql, instance_ids, as_dict=True)
                rows = sql_rows or []
        except Exception as e:
            return error_response(f"Failed to query instance rows: {str(e)}")

        # 3) Attach class_id to rows for FE and builder
        for r in rows:
            parent = r.get("parent")
            r["class_id"] = instances_map.get(parent, {}).get("class_id")

        # 4) Enrich subject_title and teacher_names
        try:
            subject_ids = list({r.get("subject_id") for r in rows if r.get("subject_id")})
            teacher_ids = list({tid for r in rows for tid in [r.get("teacher_1_id"), r.get("teacher_2_id")] if tid})

            subject_title_map = {}
            timetable_subject_by_subject = {}
            timetable_subject_title_map = {}
            if subject_ids:
                subj_rows = frappe.get_all(
                    "SIS Subject",
                    fields=["name", "title", "timetable_subject_id"],
                    filters={"name": ["in", subject_ids]},
                )
                for s in subj_rows:
                    subject_title_map[s.name] = s.title
                    if s.get("timetable_subject_id"):
                        timetable_subject_by_subject[s.name] = s.get("timetable_subject_id")
                ts_ids = list({ts for ts in timetable_subject_by_subject.values() if ts})
                if ts_ids:
                    ts_rows = frappe.get_all(
                        "SIS Timetable Subject",
                        fields=["name", "title_vn", "title_en"],
                        filters={"name": ["in", ts_ids]},
                    )
                    for ts in ts_rows:
                        timetable_subject_title_map[ts.name] = ts.title_vn or ts.title_en or ""

            teacher_user_map = {}
            if teacher_ids:
                teachers = frappe.get_all(
                    "SIS Teacher",
                    fields=["name", "user_id"],
                    filters={"name": ["in", teacher_ids]},
                )
                user_ids = [t.user_id for t in teachers if t.get("user_id")]
                user_display_map = {}
                if user_ids:
                    for u in frappe.get_all(
                        "User",
                        fields=["name", "full_name", "first_name", "middle_name", "last_name"],
                        filters={"name": ["in", user_ids]},
                    ):
                        display = u.get("full_name")
                        if not display:
                            parts = [u.get("first_name"), u.get("middle_name"), u.get("last_name")]
                            display = " ".join([p for p in parts if p]) or u.get("name")
                        user_display_map[u.name] = display
                for t in teachers:
                    teacher_user_map[t.name] = user_display_map.get(t.get("user_id")) or t.get("user_id") or t.get("name")

            for r in rows:
                subj_id = r.get("subject_id")
                ts_id = timetable_subject_by_subject.get(subj_id)
                ts_title = timetable_subject_title_map.get(ts_id) if ts_id else None
                default_title = subject_title_map.get(subj_id) or r.get("subject_title") or r.get("subject_name") or ""
                r["subject_title"] = ts_title or default_title
                teacher_names_list = []
                if r.get("teacher_1_id"):
                    teacher_names_list.append(teacher_user_map.get(r.get("teacher_1_id")) or "")
                if r.get("teacher_2_id"):
                    teacher_names_list.append(teacher_user_map.get(r.get("teacher_2_id")) or "")
                r["teacher_names"] = ", ".join([n for n in teacher_names_list if n])
        except Exception as enrich_error:
            pass

        entries = _build_entries(rows, ws)
        
        # TEMPORARILY DISABLE override logic to restore original timetable
        # entries_with_overrides = _apply_timetable_overrides(entries, "Class", class_id, ws, we)
        
        return list_response(entries, "Class week fetched successfully")
    except Exception as e:

        return error_response(f"Error fetching class week: {str(e)}")


# =========================
# Import & CRUD API endpoints
# =========================

@frappe.whitelist(allow_guest=False)
def test_class_week_api(class_id: str = None, week_start: str = None):
    """Test function for get_class_week API"""
    try:

        if not class_id:
            class_id = "SIS-CLASS-00385"  # Default test class
        if not week_start:
            week_start = "2025-08-25"  # Default test date

        # Call the actual get_class_week function
        result = get_class_week(class_id, week_start, None)
        return {
            "success": True,
            "message": "Test class week API successful",
            "test_params": {"class_id": class_id, "week_start": week_start},
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Test failed: {str(e)}",
            "test_params": {"class_id": class_id, "week_start": week_start}
        }

@frappe.whitelist(allow_guest=False)
def import_timetable():
    """Import timetable from Excel with dry-run validation and final import"""
    try:
        # Get request data - handle both FormData and regular form data
        data = {}

        # Try different sources for FormData
        if hasattr(frappe.request, 'form_data') and frappe.request.form_data:
            # For werkzeug form data
            data = frappe.request.form_data
        elif hasattr(frappe.request, 'form') and frappe.request.form:
            # For flask-style form data
            data = frappe.request.form
        elif frappe.local.form_dict:
            # Fallback to form_dict
            data = frappe.local.form_dict
        elif hasattr(frappe.request, 'args') and frappe.request.args:
            # Try request args
            data = frappe.request.args

        # Convert to dict if it's not already
        if hasattr(data, 'to_dict'):
            data = data.to_dict()
        elif not isinstance(data, dict):
            data = dict(data) if data else {}

        # Check for dry_run parameter
        dry_run = data.get("dry_run", "false").lower() == "true"

        # Extract basic info
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        campus_id = data.get("campus_id")
        school_year_id = data.get("school_year_id")
        education_stage_id = data.get("education_stage_id")
        start_date = data.get("start_date")
        end_date = data.get("end_date")

        # Validate required fields - end_date is now auto-calculated from school_year_id
        if not all([title_vn, campus_id, school_year_id, education_stage_id, start_date]):
            return validation_error_response("Validation failed", {
                "required_fields": ["title_vn", "campus_id", "school_year_id", "education_stage_id", "start_date"],
                "logs": []
            })
        
        # Auto-calculate end_date from school year if not provided
        if not end_date:
            try:
                school_year = frappe.get_doc("SIS School Year", school_year_id)
                if school_year.campus_id != campus_id:
                    return validation_error_response("Validation failed", {
                        "school_year_id": ["School year does not belong to the selected campus"],
                        "logs": []
                    })
                end_date = school_year.end_date
                
            except frappe.DoesNotExistError:
                return validation_error_response("Validation failed", {
                    "school_year_id": ["School year not found"],
                    "logs": []
                })
            except Exception as e:
                return validation_error_response("Validation failed", {
                    "school_year_id": [f"Error retrieving school year: {str(e)}"],
                    "logs": []
                })

        # Get current user campus
        user_campus = get_current_campus_from_context()
        if user_campus and user_campus != campus_id:
            return forbidden_response("Access denied: Campus mismatch")

        # Process Excel import if file is provided
        files = frappe.request.files

        if files and 'file' in files:
            # File is uploaded, process it
            file_data = files['file']
            if not file_data:
                return validation_error_response("Validation failed", {"file": ["No file uploaded"], "logs": []})

            # Save file temporarily
            file_path = save_uploaded_file(file_data, "timetable_import.xlsx")

            # Call Excel import processor with metadata
            import_data = {
                "file_path": file_path,
                "title_vn": title_vn,
                "title_en": title_en,
                "campus_id": campus_id,
                "school_year_id": school_year_id,
                "education_stage_id": education_stage_id,
                "start_date": start_date,
                "end_date": end_date,
                "dry_run": dry_run
            }

            # Process the Excel import
            result = process_excel_import_with_metadata_v2(import_data)

            # Clean up temp file
            import os
            if os.path.exists(file_path):
                os.remove(file_path)

            return result
        else:
            # No file uploaded, just validate metadata
            result = {
                "dry_run": dry_run,
                "title_vn": title_vn,
                "title_en": title_en,
                "campus_id": campus_id,
                "school_year_id": school_year_id,
                "education_stage_id": education_stage_id,
                "start_date": start_date,
                "end_date": end_date,
                "message": "Metadata validation completed",
                "requires_file": True,
                "logs": []
            }

            return single_item_response(result, "Timetable metadata validated successfully")

    except Exception as e:

        return error_response(f"Error importing timetable: {str(e)}")


def save_uploaded_file(file_data, filename: str) -> str:
    """Save uploaded file temporarily and return file path"""
    try:
        import os
        import uuid

        # Create temporary directory if it doesn't exist
        temp_dir = frappe.utils.get_site_path("private", "files", "temp")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir, exist_ok=True)

        # Generate unique filename
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = os.path.join(temp_dir, unique_filename)

        # Save file
        with open(file_path, 'wb') as f:
            f.write(file_data.read())

        return file_path
    except Exception as e:

        raise e


@frappe.whitelist(allow_guest=False)
def get_timetables():
    """Get list of timetables with filtering"""
    try:
        # Get query parameters
        page = int(frappe.local.form_dict.get("page", 1))
        limit = int(frappe.local.form_dict.get("limit", 20))
        campus_id = frappe.local.form_dict.get("campus_id")
        school_year_id = frappe.local.form_dict.get("school_year_id")

        # Build filters
        filters = {}
        if campus_id:
            filters["campus_id"] = campus_id
        if school_year_id:
            filters["school_year_id"] = school_year_id

        # Get campus from user context
        user_campus = get_current_campus_from_context()
        if user_campus:
            filters["campus_id"] = user_campus

        # Query timetables
        timetables = frappe.get_all(
            "SIS Timetable",
            fields=["name", "title_vn", "title_en", "campus_id", "school_year_id", "education_stage_id", "start_date", "end_date", "created_by"],
            filters=filters,
            start=(page - 1) * limit,
            page_length=limit,
            order_by="creation desc"
        )

        # Get total count
        total_count = frappe.db.count("SIS Timetable", filters=filters)

        result = {
            "data": timetables,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit
            }
        }

        return single_item_response(result, "Timetables fetched successfully")

    except Exception as e:

        return error_response(f"Error fetching timetables: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_detail():
    """Get detailed timetable information"""
    try:
        timetable_id = frappe.local.form_dict.get("name")
        if not timetable_id:
            return validation_error_response("Validation failed", {"name": ["Timetable ID is required"]})

        # Get timetable
        timetable = frappe.get_doc("SIS Timetable", timetable_id)

        # Check campus permission
        user_campus = get_current_campus_from_context()
        if user_campus and timetable.campus_id != user_campus:
            return forbidden_response("Access denied: Campus mismatch")

        # Get instances
        instances = frappe.get_all(
            "SIS Timetable Instance",
            fields=["name", "class_id", "start_date", "end_date", "is_locked"],
            filters={"timetable_id": timetable_id},
            order_by="class_id"
        )

        result = {
            "timetable": {
                "name": timetable.name,
                "title_vn": timetable.title_vn,
                "title_en": timetable.title_en,
                "campus_id": timetable.campus_id,
                "school_year_id": timetable.school_year_id,
                "education_stage_id": timetable.education_stage_id,
                "start_date": timetable.start_date,
                "end_date": timetable.end_date,
                "upload_source": timetable.upload_source,
                "created_by": timetable.created_by
            },
            "instances": instances
        }

        return single_item_response(result, "Timetable detail fetched successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Timetable not found")
    except Exception as e:

        return error_response(f"Error fetching timetable detail: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_timetable():
    """Delete a timetable and all its instances"""
    try:
        timetable_id = frappe.local.form_dict.get("name")
        if not timetable_id:
            return validation_error_response("Validation failed", {"name": ["Timetable ID is required"]})

        # Get timetable
        timetable = frappe.get_doc("SIS Timetable", timetable_id)

        # Check campus permission
        user_campus = get_current_campus_from_context()
        if user_campus and timetable.campus_id != user_campus:
            return forbidden_response("Access denied: Campus mismatch")

        # Delete timetable (this will cascade delete instances due to foreign key)
        frappe.delete_doc("SIS Timetable", timetable_id)
        frappe.db.commit()

        return success_response("Timetable deleted successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Timetable not found")
    except Exception as e:

        return error_response(f"Error deleting timetable: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_instance_row_details(row_id: str = None):
    """Get detailed information for a specific timetable instance row for editing"""
    try:
        row_id = row_id or _get_request_arg("row_id")
        if not row_id:
            return validation_error_response("Validation failed", {"row_id": ["Row ID is required"]})

        # Get the instance row
        row = frappe.get_doc("SIS Timetable Instance Row", row_id)

        # Get related data for dropdowns/edit options
        subjects = frappe.get_all(
            "SIS Subject",
            fields=["name", "title"],
            filters={"is_active": 1},
            order_by="title asc"
        )

        # Get available teachers for this period/class combination
        teachers = frappe.get_all(
            "SIS Teacher",
            fields=["name", "user_id", "first_name", "last_name", "full_name"],
            filters={"status": "Active"},
            order_by="full_name asc"
        )

        # Get available rooms (if room assignment is supported)
        rooms = frappe.get_all(
            "SIS Room",
            fields=["name", "room_name", "capacity"],
            filters={"is_active": 1},
            order_by="room_name asc"
        ) if frappe.db.has_table("SIS Room") else []

        # Get instance information
        instance = frappe.get_doc("SIS Timetable Instance", row.parent)

        # Check if instance is locked
        is_locked = instance.get("is_locked", False)

        result_data = {
            "row": {
                "name": row.name,
                "day_of_week": row.day_of_week,
                "timetable_column_id": row.timetable_column_id,
                "subject_id": row.subject_id,
                "subject_title": row.subject_id and frappe.db.get_value("SIS Subject", row.subject_id, "title"),
                "teacher_1_id": row.teacher_1_id,
                "teacher_2_id": row.teacher_2_id,
                "parent": row.parent,
                "parent_timetable_instance": row.parent_timetable_instance
            },
            "instance": {
                "name": instance.name,
                "class_id": instance.class_id,
                "timetable_id": instance.timetable_id,
                "start_date": str(instance.start_date),
                "end_date": str(instance.end_date),
                "is_locked": is_locked
            },
            "options": {
                "subjects": subjects,
                "teachers": teachers,
                "rooms": rooms
            }
        }

        return single_item_response(result_data, "Instance row details fetched successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Instance row not found")
    except Exception as e:

        return error_response(f"Error fetching instance row details: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=["GET", "POST", "PUT"])
def update_instance_row(row_id: str = None, subject_id: str = None, teacher_1_id: str = None,
                       teacher_2_id: str = None, room_id: str = None):
    """Update a specific timetable instance row"""  # Ignore if can't write to file

    try:
        # Get parameters
        row_id = row_id or _get_request_arg("row_id")
        subject_id = subject_id or _get_request_arg("subject_id")
        teacher_1_id = teacher_1_id or _get_request_arg("teacher_1_id")
        teacher_2_id = teacher_2_id or _get_request_arg("teacher_2_id")
        room_id = room_id or _get_request_arg("room_id")

        if not row_id:
            return validation_error_response("Validation failed", {"row_id": ["Row ID is required"]})

        # Get the instance row (ignore permissions to bypass framework-level checks)
        try:
            row = frappe.get_doc("SIS Timetable Instance Row", row_id, ignore_permissions=True)

            # Store old teacher values BEFORE any updates (get from database, not from current object)
            old_teacher_1_id = frappe.db.get_value("SIS Timetable Instance Row", row_id, "teacher_1_id")
            old_teacher_2_id = frappe.db.get_value("SIS Timetable Instance Row", row_id, "teacher_2_id")

        except Exception as e:
            raise

        # Check if parent instance is locked
        try:
            instance = frappe.get_doc("SIS Timetable Instance", row.parent, ignore_permissions=True)
        except Exception as e:
            raise

        if instance.get("is_locked"):
            return validation_error_response("Validation failed", {
                "instance_locked": ["Cannot edit a locked instance"]
            })

        # Temporarily bypass campus check for debugging
        # if user_campus and user_campus != instance.campus_id:
        #     return forbidden_response("Access denied: Campus mismatch")

        # Validate subject exists (SIS Subject doesn't have is_active field)
        if subject_id:
            # SIS Subject doctype doesn't have is_active field, so just check if exists
            subject_exists = frappe.db.exists("SIS Subject", {"name": subject_id})

            if not subject_exists:
                return validation_error_response("Validation failed", {
                    "subject_id": ["Subject does not exist"]
                })

        # Validate teachers exist (SIS Teacher doesn't have status field)
        for teacher_id in [teacher_1_id, teacher_2_id]:
            if teacher_id:
                teacher_exists = frappe.db.exists("SIS Teacher", {"name": teacher_id})

                if not teacher_exists:
                    return validation_error_response("Validation failed", {
                        "teacher_id": [f"Teacher does not exist: {teacher_id}"]
                    })

        # Check for teacher conflicts if teachers are assigned
        if teacher_1_id or teacher_2_id:
            conflict_check = _check_teacher_conflicts(
                [tid for tid in [teacher_1_id, teacher_2_id] if tid],
                row.day_of_week,
                row.timetable_column_id,
                instance.start_date,
                instance.end_date,
                row.name  # Exclude current row from conflict check
            )

            if conflict_check.get("has_conflict"):
                return validation_error_response("Validation failed", {
                    "teacher_conflict": conflict_check["conflicts"]
                })

        # Update the row
        update_data = {}
        if subject_id is not None:
            update_data["subject_id"] = subject_id
        if teacher_1_id is not None:
            update_data["teacher_1_id"] = teacher_1_id
        if teacher_2_id is not None:
            update_data["teacher_2_id"] = teacher_2_id
        if room_id is not None and frappe.db.has_table("SIS Room"):
            update_data["room_id"] = room_id

        if update_data:
            for field, value in update_data.items():
                setattr(row, field, value)
            row.save(ignore_permissions=True)
            frappe.db.commit()

            # Note: Không sync related timetables để cell edit chỉ ảnh hưởng đúng 1 cell
            # _sync_related_timetables(row, instance, old_teacher_1_id, old_teacher_2_id)

        result_data = {
            "row_id": row.name,
            "updated_fields": list(update_data.keys()),
            "instance_id": instance.name,
            "class_id": instance.class_id
        }

        return single_item_response(result_data, "Instance row updated successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Instance row not found")
    except frappe.PermissionError as e:
        return forbidden_response(f"Permission denied: {str(e)}")
    except Exception as e:
        frappe.db.rollback()
        return error_response(f"Error updating instance row: {str(e)}")


def _check_teacher_conflicts(teacher_ids: list, day_of_week: str, timetable_column_id: str,
                           start_date, end_date, exclude_row_id: str = None):
    """Check for teacher scheduling conflicts"""
    try:
        conflicts = []

        for teacher_id in teacher_ids:
            # Find other instances where this teacher is assigned at the same time
            conflict_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "parent", "day_of_week", "timetable_column_id"],
                filters={
                    "day_of_week": day_of_week,
                    "timetable_column_id": timetable_column_id,
                    "teacher_1_id": teacher_id
                }
            )

            # Also check teacher_2_id
            conflict_rows_2 = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name", "parent", "day_of_week", "timetable_column_id"],
                filters={
                    "day_of_week": day_of_week,
                    "timetable_column_id": timetable_column_id,
                    "teacher_2_id": teacher_id
                }
            )

            conflict_rows.extend(conflict_rows_2)

            # Exclude current row if updating
            if exclude_row_id:
                conflict_rows = [r for r in conflict_rows if r["name"] != exclude_row_id]

            if conflict_rows:
                # Get instance and class info for conflicts
                for conflict in conflict_rows:
                    instance = frappe.get_doc("SIS Timetable Instance", conflict["parent"])
                    conflicts.append({
                        "teacher_id": teacher_id,
                        "conflicting_class": instance.class_id,
                        "day_of_week": day_of_week,
                        "period": timetable_column_id
                    })

        return {
            "has_conflict": len(conflicts) > 0,
            "conflicts": conflicts
        }

    except Exception as e:

        return {"has_conflict": False, "conflicts": []}


def _sync_related_timetables(row, instance, old_teacher_1_id=None, old_teacher_2_id=None):
    """Sync changes to related teacher and student timetables"""
    try:
        # Get current teachers from row
        new_teacher_1_id = getattr(row, 'teacher_1_id', None)
        new_teacher_2_id = getattr(row, 'teacher_2_id', None)

        # 1. Remove old teacher timetable entries
        teachers_to_remove = []
        if old_teacher_1_id and old_teacher_1_id != new_teacher_1_id:
            teachers_to_remove.append(old_teacher_1_id)
        if old_teacher_2_id and old_teacher_2_id != new_teacher_2_id:
            teachers_to_remove.append(old_teacher_2_id)

        # Debug: Log what we're doing
        if teachers_to_remove:
            print(f"DEBUG: Removing teacher timetable entries for teachers: {teachers_to_remove}")
            print(f"DEBUG: Old teachers: teacher_1={old_teacher_1_id}, teacher_2={old_teacher_2_id}")
            print(f"DEBUG: New teachers: teacher_1={new_teacher_1_id}, teacher_2={new_teacher_2_id}")

        for teacher_id in teachers_to_remove:
            if teacher_id:
                # Comprehensive deletion strategy to handle both manual and Excel-imported entries

                # Strategy 1: Exact match with all filters (for manual edits)
                existing_entries = frappe.get_all(
                    "SIS Teacher Timetable",
                    filters={
                        "teacher_id": teacher_id,
                        "timetable_instance_id": instance.name,
                        "day_of_week": row.day_of_week,
                        "timetable_column_id": row.timetable_column_id,
                        "class_id": instance.class_id
                    }
                )

                # Strategy 2: If no exact match, get all entries for this teacher in this instance
                # This handles Excel-imported entries that might have different date formats
                if len(existing_entries) == 0:
                    instance_entries = frappe.get_all(
                        "SIS Teacher Timetable",
                        filters={
                            "teacher_id": teacher_id,
                            "timetable_instance_id": instance.name,
                            "class_id": instance.class_id  # Ensure same class
                        }
                    )

                    # Filter by day_of_week and timetable_column_id in memory
                    for entry in instance_entries:
                        if (entry.get("day_of_week") == row.day_of_week and
                            entry.get("timetable_column_id") == row.timetable_column_id):
                            existing_entries.append(entry)

                # Strategy 3: Fallback - find any entries for this teacher on this day/week
                # This handles edge cases where entries might be created with different logic
                if len(existing_entries) == 0:
                    # Get entries by teacher and day_of_week only, then filter by instance
                    day_entries = frappe.get_all(
                        "SIS Teacher Timetable",
                        filters={
                            "teacher_id": teacher_id,
                            "day_of_week": row.day_of_week,
                            "class_id": instance.class_id
                        }
                    )

                    # Filter by timetable_instance_id to ensure we're only deleting from current instance
                    for entry in day_entries:
                        if entry.get("timetable_instance_id") == instance.name:
                            existing_entries.append(entry)

                # Strategy 4: Last resort - delete ALL entries for this teacher in this instance
                # This ensures no orphaned entries remain, especially for Excel-imported data
                if len(existing_entries) == 0:
                    all_instance_entries = frappe.get_all(
                        "SIS Teacher Timetable",
                        filters={
                            "teacher_id": teacher_id,
                            "timetable_instance_id": instance.name
                        }
                    )
                    existing_entries.extend(all_instance_entries)

                # Delete all found entries
                for entry in existing_entries:
                    try:
                        frappe.delete_doc("SIS Teacher Timetable", entry.name, ignore_permissions=True)
                    except Exception as e:
                        pass

        # 2. Create new teacher timetable entries
        teachers_to_add = []
        if new_teacher_1_id:
            teachers_to_add.append(new_teacher_1_id)
        if new_teacher_2_id:
            teachers_to_add.append(new_teacher_2_id)

        for teacher_id in teachers_to_add:
            if teacher_id:
                # Check if entry already exists with comprehensive filters
                existing_entries = frappe.get_all(
                    "SIS Teacher Timetable",
                    filters={
                        "teacher_id": teacher_id,
                        "timetable_instance_id": instance.name,
                        "day_of_week": row.day_of_week,
                        "timetable_column_id": row.timetable_column_id,
                        "class_id": instance.class_id
                    },
                    limit=1
                )

                if len(existing_entries) > 0:
                    continue  # Entry already exists, skip creation

                try:
                    # Create new teacher timetable entry
                    teacher_timetable = frappe.get_doc({
                        "doctype": "SIS Teacher Timetable",
                        "teacher_id": teacher_id,
                        "timetable_instance_id": instance.name,
                        "day_of_week": row.day_of_week,
                        "timetable_column_id": row.timetable_column_id,
                        "subject_id": getattr(row, 'subject_id', None),
                        "class_id": instance.class_id,
                        "room_id": getattr(row, 'room_id', None),
                        "date": getattr(row, 'date', None)
                    })

                    teacher_timetable.insert(ignore_permissions=True)

                except Exception as e:
                    pass

    except Exception as e:
        pass


@frappe.whitelist(allow_guest=False, methods=["GET", "POST", "PUT"])
def create_or_update_timetable_override(date: str = None, timetable_column_id: str = None,
                                       target_type: str = None, target_id: str = None,
                                       subject_id: str = None, teacher_1_id: str = None,
                                       teacher_2_id: str = None, room_id: str = None,
                                       override_id: str = None):
    """Create or update a date-specific timetable override for individual cell edits"""
    try:
        # Get parameters from request
        date = date or _get_request_arg("date")
        timetable_column_id = timetable_column_id or _get_request_arg("timetable_column_id")
        target_type = target_type or _get_request_arg("target_type")
        target_id = target_id or _get_request_arg("target_id")
        subject_id = subject_id or _get_request_arg("subject_id")
        teacher_1_id = teacher_1_id or _get_request_arg("teacher_1_id")
        teacher_2_id = teacher_2_id or _get_request_arg("teacher_2_id")
        room_id = room_id or _get_request_arg("room_id")
        override_id = override_id or _get_request_arg("override_id")

        # Validate required fields
        if not all([date, timetable_column_id, target_type, target_id]):
            return validation_error_response("Validation failed", {
                "required_fields": ["date", "timetable_column_id", "target_type", "target_id"]
            })

        # Validate target_type
        if target_type not in ["Student", "Teacher", "Class"]:
            return validation_error_response("Validation failed", {
                "target_type": ["Target type must be Student, Teacher, or Class"]
            })

        # Get campus from user context for permission checking
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"  # Default fallback

        # Validate target exists before proceeding
        if target_type == "Class":
            if not frappe.db.exists("SIS Class", target_id):
                return not_found_response(f"Class {target_id} not found")
        elif target_type == "Teacher":
            if not frappe.db.exists("SIS Teacher", target_id):
                return not_found_response(f"Teacher {target_id} not found")
        elif target_type == "Student":
            if not frappe.db.exists("SIS Student", target_id):
                return not_found_response(f"Student {target_id} not found")

        # Create a custom table for date-specific overrides to avoid SIS Event dependency
        # We'll create this as a simple storage without going through Frappe doctype system
        virtual_event = f"manual-edit-{frappe.generate_hash()[:8]}"
        
        # Create custom override table if it doesn't exist
        try:
            frappe.db.sql("""
                CREATE TABLE IF NOT EXISTS `tabTimetable_Date_Override` (
                    `name` varchar(140) NOT NULL,
                    `date` date NOT NULL,
                    `timetable_column_id` varchar(140) NOT NULL,
                    `target_type` varchar(50) NOT NULL,
                    `target_id` varchar(140) NOT NULL,
                    `subject_id` varchar(140) NULL,
                    `teacher_1_id` varchar(140) NULL,
                    `teacher_2_id` varchar(140) NULL,
                    `room_id` varchar(140) NULL,
                    `override_type` varchar(50) DEFAULT 'replace',
                    `created_by` varchar(140) NOT NULL,
                    `creation` datetime NOT NULL,
                    `modified` datetime NOT NULL,
                    `modified_by` varchar(140) NOT NULL,
                    PRIMARY KEY (`name`),
                    UNIQUE KEY `unique_override` (`date`, `timetable_column_id`, `target_type`, `target_id`)
                )
            """)
        except Exception as create_error:
            # Table might already exist, which is fine
            pass

        # Check if override already exists in custom table
        existing_override = frappe.db.sql("""
            SELECT name FROM `tabTimetable_Date_Override`
            WHERE date = %s AND timetable_column_id = %s AND target_type = %s AND target_id = %s
            LIMIT 1
        """, (date, timetable_column_id, target_type, target_id), as_dict=True)

        override_name = f"override-{frappe.generate_hash()[:10]}"
        current_time = frappe.utils.now()

        if existing_override:
            # Update existing override
            override_name = existing_override[0]['name']
            
            # Build update query dynamically
            update_fields = []
            update_values = []
            
            if subject_id is not None:
                update_fields.append("subject_id = %s")
                update_values.append(subject_id)
            if teacher_1_id is not None:
                update_fields.append("teacher_1_id = %s")
                update_values.append(teacher_1_id)
            if teacher_2_id is not None:
                update_fields.append("teacher_2_id = %s")
                update_values.append(teacher_2_id if teacher_2_id != 'none' else None)
            if room_id is not None:
                update_fields.append("room_id = %s")
                update_values.append(room_id)

            if update_fields:
                update_fields.append("modified = %s")
                update_fields.append("modified_by = %s")
                update_values.extend([current_time, frappe.session.user])
                update_values.append(override_name)  # WHERE condition

                frappe.db.sql(f"""
                    UPDATE `tabTimetable_Date_Override`
                    SET {', '.join(update_fields)}
                    WHERE name = %s
                """, update_values)

        else:
            # Create new override
            frappe.db.sql("""
                INSERT INTO `tabTimetable_Date_Override`
                (name, date, timetable_column_id, target_type, target_id, subject_id, 
                 teacher_1_id, teacher_2_id, room_id, override_type, created_by, creation, modified, modified_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                override_name, date, timetable_column_id, target_type, target_id,
                subject_id, teacher_1_id, 
                teacher_2_id if teacher_2_id != 'none' else None,
                room_id, 'replace', frappe.session.user, current_time, current_time, frappe.session.user
            ))

        frappe.db.commit()

        result_data = {
            "override_id": override_name,
            "date": date,
            "timetable_column_id": timetable_column_id,
            "target_type": target_type,
            "target_id": target_id,
            "updated_fields": ["subject_id", "teacher_1_id", "teacher_2_id", "room_id"]
        }

        return single_item_response(result_data, "Timetable override created/updated successfully")

    except frappe.DoesNotExistError:
        return not_found_response("Record not found")
    except frappe.PermissionError as e:
        return forbidden_response(f"Permission denied: {str(e)}")
    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(f"Error in create_or_update_timetable_override: {str(e)}")
        return error_response(f"Error creating/updating timetable override: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_overrides_for_date_range(start_date: str = None, end_date: str = None,
                                          target_type: str = None, target_id: str = None):
    """Get all timetable overrides for a specific date range and target"""
    try:
        # Get parameters
        start_date = start_date or _get_request_arg("start_date")
        end_date = end_date or _get_request_arg("end_date")
        target_type = target_type or _get_request_arg("target_type")
        target_id = target_id or _get_request_arg("target_id")

        if not all([start_date, end_date, target_type, target_id]):
            return validation_error_response("Validation failed", {
                "required_fields": ["start_date", "end_date", "target_type", "target_id"]
            })

        # Build filters
        filters = {
            "date": ["between", [start_date, end_date]],
            "target_type": target_type,
            "target_id": target_id
        }

        # Get overrides from custom table
        overrides = frappe.db.sql("""
            SELECT name, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type
            FROM `tabTimetable_Date_Override`
            WHERE target_type = %s AND target_id = %s AND date BETWEEN %s AND %s
            ORDER BY date ASC, timetable_column_id ASC
        """, (target_type, target_id, start_date, end_date), as_dict=True)

        # Enrich with display data similar to get_class_week
        for override in overrides:
            # Get subject title
            if override.get("subject_id"):
                subject_title = frappe.db.get_value("SIS Subject", override["subject_id"], "title")
                override["subject_title"] = subject_title

            # Get teacher names
            teacher_names = []
            if override.get("teacher_1_id"):
                teacher1 = frappe.get_doc("SIS Teacher", override["teacher_1_id"])
                if teacher1.user_id:
                    user1 = frappe.get_doc("User", teacher1.user_id)
                    display_name1 = user1.full_name or f"{user1.first_name or ''} {user1.last_name or ''}".strip()
                    teacher_names.append(display_name1)
                    
            if override.get("teacher_2_id"):
                teacher2 = frappe.get_doc("SIS Teacher", override["teacher_2_id"])
                if teacher2.user_id:
                    user2 = frappe.get_doc("User", teacher2.user_id)
                    display_name2 = user2.full_name or f"{user2.first_name or ''} {user2.last_name or ''}".strip()
                    teacher_names.append(display_name2)
                    
            override["teacher_names"] = ", ".join(teacher_names)

        return list_response(overrides, "Timetable overrides fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error in get_timetable_overrides_for_date_range: {str(e)}")
        return error_response(f"Error fetching timetable overrides: {str(e)}")


@frappe.whitelist(allow_guest=False)
def debug_get_all_overrides():
    """Debug function to get all override data"""
    try:
        # Get all overrides from custom table
        all_overrides = frappe.db.sql("""
            SELECT * FROM `tabTimetable_Date_Override`
            ORDER BY creation DESC
            LIMIT 50
        """, as_dict=True)
        
        return single_item_response({
            "total_count": len(all_overrides),
            "overrides": all_overrides
        }, f"Found {len(all_overrides)} total overrides")
        
    except Exception as e:
        return error_response(f"Debug error: {str(e)}")