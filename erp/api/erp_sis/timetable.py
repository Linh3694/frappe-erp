

# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from datetime import datetime, timedelta
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
)
from .timetable_excel_import import process_excel_import, process_excel_import_with_metadata_v2

def _noop():
    return None
@frappe.whitelist(allow_guest=False)
def update_timetable_column():
    """Update an existing timetable column"""
    try:
        # Debug: Log which function is being called
        frappe.logger().info("=== UPDATE_TIMETABLE_COLUMN FUNCTION CALLED ===")
        frappe.logger().info(f"Update timetable column column - Request method: {frappe.request.method}")
        frappe.logger().info(f"Update timetable column column - Request URL: {frappe.request.url}")

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

        # Debug logging
        frappe.logger().info(f"Update timetable column column - Raw data: {data}")
        frappe.logger().info(f"Update timetable column column - Form dict: {frappe.local.form_dict}")
        frappe.logger().info(f"Update timetable column column - Request data: {frappe.request.data}")
        frappe.logger().info(f"Update timetable column column - Request URL: {frappe.request.url}")
        frappe.logger().info(f"Update timetable column column - Request method: {frappe.request.method}")

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
                    frappe.logger().info(f"Update timetable column column - Found timetable_column_id '{timetable_column_id}' using pattern '{pattern}' from URL: {frappe.request.url}")
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
            frappe.logger().error(f"Update timetable column column - Missing timetable_column_id. Data keys: {list(data.keys()) if data else 'None'}, Form dict keys: {list(frappe.local.form_dict.keys()) if frappe.local.form_dict else 'None'}")
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

        # Debug logging - current values
        frappe.logger().info(f"Update timetable column column - Current values: education_stage_id={timetable_column_doc.education_stage_id}, period_priority={timetable_column_doc.period_priority}, period_type={timetable_column_doc.period_type}, period_name={timetable_column_doc.period_name}")
        current_start_time_raw = timetable_column_doc.start_time
        current_end_time_raw = timetable_column_doc.end_time
        frappe.logger().info(f"Update timetable column column - Current times raw: start_time={current_start_time_raw}, end_time={current_end_time_raw}")

        # Debug logging - new values
        frappe.logger().info(f"Update timetable column column - New values: education_stage_id={education_stage_id}, period_priority={period_priority}, period_type={period_type}, period_name={period_name}, start_time={start_time}, end_time={end_time}")

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

            frappe.logger().info(f"Update timetable column - Updating education_stage_id: {timetable_column_doc.education_stage_id} -> {education_stage_id}")
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

            frappe.logger().info(f"Update timetable column - Updating period_priority: {timetable_column_doc.period_priority} -> {period_priority}")
            timetable_column_doc.period_priority = period_priority
            updates_made.append(f"period_priority: {period_priority}")

        if period_type and period_type != timetable_column_doc.period_type:
            if period_type not in ['study', 'non-study']:
                return validation_error_response("Validation failed", {"period_type": ["Period type must be 'study' or 'non-study'"]})
            frappe.logger().info(f"Update timetable column - Updating period_type: {timetable_column_doc.period_type} -> {period_type}")
            timetable_column_doc.period_type = period_type
            updates_made.append(f"period_type: {period_type}")

        if period_name and period_name != timetable_column_doc.period_name:
            frappe.logger().info(f"Update timetable column - Updating period_name: {timetable_column_doc.period_name} -> {period_name}")
            timetable_column_doc.period_name = period_name
            updates_made.append(f"period_name: {period_name}")

        # Handle time updates with better validation
        current_start_time = format_time_for_html(timetable_column_doc.start_time)
        current_end_time = format_time_for_html(timetable_column_doc.end_time)

        frappe.logger().info(f"Update timetable column - Time comparison: start_time '{start_time}' vs current '{current_start_time}', end_time '{end_time}' vs current '{current_end_time}'")

        if start_time and start_time.strip():
            if start_time != current_start_time:
                frappe.logger().info(f"Update timetable column - Updating start_time: {current_start_time} -> {start_time}")
                try:
                    start_time_obj = get_time(start_time)
                    timetable_column_doc.start_time = start_time
                    updates_made.append(f"start_time: {start_time}")
                except Exception as e:
                    frappe.log_error(f"Error parsing start_time '{start_time}': {str(e)}")
                    return validation_error_response("Validation failed", {"start_time": ["Invalid start time format"]})
            else:
                frappe.logger().info(f"Update timetable column - start_time unchanged: {start_time}")

        if end_time and end_time.strip():
            if end_time != current_end_time:
                frappe.logger().info(f"Update timetable column - Updating end_time: {current_end_time} -> {end_time}")
                try:
                    end_time_obj = get_time(end_time)
                    timetable_column_doc.end_time = end_time
                    updates_made.append(f"end_time: {end_time}")
                except Exception as e:
                    frappe.log_error(f"Error parsing end_time '{end_time}': {str(e)}")
                    return validation_error_response("Validation failed", {"end_time": ["Invalid end time format"]})
            else:
                frappe.logger().info(f"Update timetable column - end_time unchanged: {end_time}")

        # Validate time range after updates
        if hasattr(timetable_column_doc, 'start_time') and hasattr(timetable_column_doc, 'end_time') and timetable_column_doc.start_time and timetable_column_doc.end_time:
            try:
                start_time_obj = get_time(str(timetable_column_doc.start_time))
                end_time_obj = get_time(str(timetable_column_doc.end_time))
                if start_time_obj >= end_time_obj:
                    return validation_error_response("Validation failed", {"start_time": ["Start time must be before end time"]})
            except Exception as e:
                frappe.log_error(f"Error validating time range: {str(e)}")
                return validation_error_response("Validation failed", {"start_time": ["Invalid time values"]})

        # Check if any updates were made
        frappe.logger().info(f"Update timetable column - Updates made: {updates_made}")

        if not updates_made:
            frappe.logger().warning(f"Update timetable column - No updates detected, returning current data")
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
        frappe.logger().info(f"Update timetable column - Saving document with updates: {updates_made}")
        timetable_column_doc.save()
        frappe.db.commit()
        frappe.logger().info(f"Update timetable column - Document saved and committed successfully")
        
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
        frappe.log_error(f"Error updating timetable column {timetable_column_id}: {str(e)}")
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
        frappe.log_error(f"Error deleting timetable column: {str(e)}")
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
        frappe.log_error(f"Error fetching education stages for timetable column: {str(e)}")
        return error_response(f"Error fetching education stages: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_timetable_column():
    """Create a new timetable column - SIMPLE VERSION"""
    try:
        # Debug: Log which function is being called
        frappe.logger().info("=== CREATE_TIMETABLE FUNCTION CALLED ===")
        frappe.logger().info(f"Create timetable column - Request method: {frappe.request.method}")
        frappe.logger().info(f"Create timetable column - Request URL: {frappe.request.url}")

        # Get data from request - handle both JSON and form data
        data = frappe.local.form_dict or {}

        # Debug logging
        frappe.logger().info(f"Create timetable column - Raw request data: {frappe.request.data}")
        frappe.logger().info(f"Create timetable column - Form dict: {frappe.local.form_dict}")
        frappe.logger().info(f"Create timetable column - Initial data: {data}")

        # If request has JSON data, try to parse it
        if frappe.request.data and frappe.request.data.strip():
            try:
                json_data = json.loads(frappe.request.data)
                if json_data and isinstance(json_data, dict):
                    data = json_data
                    frappe.logger().info(f"Create timetable column - Using JSON data: {data}")
                else:
                    frappe.logger().info(f"Create timetable column - JSON data is empty or not dict, using form_dict")
            except (json.JSONDecodeError, TypeError) as e:
                # If JSON parsing fails, use form_dict which contains URL-encoded data
                frappe.logger().info(f"Create timetable column - JSON parsing failed ({e}), using form_dict")
                pass

        frappe.logger().info(f"Create timetable column - Final data: {data}")

        # Extract values from data
        education_stage_id = data.get("education_stage_id")
        period_priority = data.get("period_priority")
        period_type = data.get("period_type")
        period_name = data.get("period_name")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        # Debug logging for extracted values
        frappe.logger().info(f"Create timetable column - Extracted values: education_stage_id={education_stage_id}, period_priority={period_priority}, period_type={period_type}, period_name={period_name}, start_time={start_time}, end_time={end_time}")

        # Input validation
        if not education_stage_id or not period_priority or not period_type or not period_name or not start_time or not end_time:
            frappe.logger().error(f"Create timetable column - Validation failed. Missing fields: education_stage_id={bool(education_stage_id)}, period_priority={bool(period_priority)}, period_type={bool(period_type)}, period_name={bool(period_name)}, start_time={bool(start_time)}, end_time={bool(end_time)}")
            frappe.throw(_("All fields are required"))
        
        # Get campus from user context
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            frappe.logger().error(f"Error getting campus context: {str(e)}")
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

        # Debug: Log time values before and after formatting
        frappe.logger().info(f"Create timetable column - Raw times from doc: start_time={timetable_column_doc.start_time}, end_time={timetable_column_doc.end_time}")
        frappe.logger().info(f"Create timetable column - Raw times types: start_time={type(timetable_column_doc.start_time)}, end_time={type(timetable_column_doc.end_time)}")

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

        frappe.logger().info(f"Create timetable column - Returning original times: start_time={start_time}, end_time={end_time}")
        return single_item_response(timetable_data, "Timetable column created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable column: {str(e)}")
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

        # Debug logging
        frappe.logger().info(f"=== GET TEACHER WEEK DEBUG ===")
        frappe.logger().info(f"Parameters: teacher_id={teacher_id}, week_start={week_start}, week_end={week_end}")
        frappe.logger().info(f"Request method: {frappe.request.method}")
        frappe.logger().info(f"Request args: {getattr(frappe.request, 'args', {})}")
        frappe.logger().info(f"Form dict: {frappe.local.form_dict}")

        if not teacher_id:
            return validation_error_response("Validation failed", {"teacher_id": ["Teacher is required"]})
        if not week_start:
            return validation_error_response("Validation failed", {"week_start": ["Week start is required"]})

        ws = _parse_iso_date(week_start)
        # Query timetable rows
        campus_id = get_current_campus_from_context() or "campus-1"
        filters = {
            "campus_id": campus_id,
        }

        # Debug: Try without class_id field first to test table
        frappe.logger().info("=== DEBUGGING TEACHER QUERY ===")

        # First try to get all records to test table existence
        try:
            all_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name"],
                limit=1
            )
            frappe.logger().info(f"Teacher query - Table exists, found {len(all_rows)} records")
        except Exception as table_error:
            frappe.logger().info(f"Teacher query - Table error: {str(table_error)}")
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
            frappe.logger().info(f"Teacher basic query successful, found {len(rows)} rows")

            # Step 2: Try adding more fields one by one
            available_fields = basic_fields[:]
            test_fields = ["timetable_column_id", "subject_name", "teacher_1_id", "teacher_2_id"]

            for field in test_fields:
                try:
                    test_rows = frappe.get_all(
                        "SIS Timetable Instance Row",
                        fields=available_fields + [field],
                        filters=filters,
                        limit=1
                    )
                    available_fields.append(field)
                    frappe.logger().info(f"Teacher field '{field}' is available")
                except Exception as field_error:
                    frappe.logger().info(f"Teacher field '{field}' not available: {str(field_error)}")

            # Step 3: Use all available fields
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=available_fields,
                filters=filters,
                order_by="day_of_week asc",
            )
            frappe.logger().info(f"Teacher final query successful with fields: {available_fields}")

        except Exception as query_error:
            frappe.logger().info(f"Teacher query error: {str(query_error)}")
            return error_response(f"Query failed: {str(query_error)}")
        # Filter in-memory for teacher (to avoid OR filter limitation in simple get_all)
        rows = [r for r in rows if r.get("teacher_1_id") == teacher_id or r.get("teacher_2_id") == teacher_id]

        entries = _build_entries(rows, ws)
        return list_response(entries, "Teacher week fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error get_teacher_week: {str(e)}")
        return error_response(f"Error fetching teacher week: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_class_week():
    """Return class weekly timetable entries."""
    try:
        # Get parameters from frappe request
        class_id = frappe.local.form_dict.get("class_id") or frappe.request.args.get("class_id")
        week_start = frappe.local.form_dict.get("week_start") or frappe.request.args.get("week_start")
        week_end = frappe.local.form_dict.get("week_end") or frappe.request.args.get("week_end")

        # Debug logging
        frappe.logger().info(f"=== GET CLASS WEEK DEBUG ===")
        frappe.logger().info(f"Parameters: class_id={class_id}, week_start={week_start}, week_end={week_end}")
        frappe.logger().info(f"Request method: {frappe.request.method}")
        frappe.logger().info(f"Request args: {getattr(frappe.request, 'args', {})}")
        frappe.logger().info(f"Form dict: {frappe.local.form_dict}")
        frappe.logger().info(f"Request data: {getattr(frappe.request, 'data', {})}")
        frappe.logger().info(f"Query string: {frappe.request.query_string}")

        if not class_id:
            frappe.logger().info("class_id is missing or empty")
            return validation_error_response("Validation failed", {"class_id": ["Class is required"]})
        if not week_start:
            frappe.logger().info("week_start is missing or empty")
            return validation_error_response("Validation failed", {"week_start": ["Week start is required"]})

        ws = _parse_iso_date(week_start)
        campus_id = get_current_campus_from_context() or "campus-1"
        filters = {
            "campus_id": campus_id,
            "class_id": class_id,
        }

        # Debug: Try without class_id filter first to see if table exists
        frappe.logger().info("=== DEBUGGING QUERY ===")
        frappe.logger().info(f"Filters: {filters}")

        # First try to get all records without class_id filter to test table existence
        try:
            all_rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=["name"],
                limit=1
            )
            frappe.logger().info(f"Table exists, found {len(all_rows)} records")
        except Exception as table_error:
            frappe.logger().info(f"Table error: {str(table_error)}")
            return error_response(f"Table not found: {str(table_error)}")

        # Try with minimal fields first to see what exists
        try:
            # Step 1: Try with only basic fields
            basic_fields = ["name", "day_of_week"]
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=basic_fields,
                filters={"campus_id": campus_id},
                limit=5  # Limit to see if basic query works
            )
            frappe.logger().info(f"Basic query successful, found {len(rows)} rows")
            frappe.logger().info(f"Sample row: {rows[0] if rows else 'No rows'}")

            # Step 2: Try adding more fields one by one
            available_fields = basic_fields[:]
            test_fields = ["timetable_column_id", "subject_name", "teacher_1_id", "teacher_2_id"]

            for field in test_fields:
                try:
                    test_rows = frappe.get_all(
                        "SIS Timetable Instance Row",
                        fields=available_fields + [field],
                        filters={"campus_id": campus_id},
                        limit=1
                    )
                    available_fields.append(field)
                    frappe.logger().info(f"Field '{field}' is available")
                except Exception as field_error:
                    frappe.logger().info(f"Field '{field}' not available: {str(field_error)}")

            # Step 3: Use all available fields
            rows = frappe.get_all(
                "SIS Timetable Instance Row",
                fields=available_fields,
                filters={"campus_id": campus_id},
                order_by="day_of_week asc",
            )
            frappe.logger().info(f"Final query successful with fields: {available_fields}")

        except Exception as query_error:
            frappe.logger().info(f"Query error: {str(query_error)}")
            return error_response(f"Query failed: {str(query_error)}")

        entries = _build_entries(rows, ws)
        return list_response(entries, "Class week fetched successfully")
    except Exception as e:
        frappe.log_error(f"Error get_class_week: {str(e)}")
        return error_response(f"Error fetching class week: {str(e)}")


# =========================
# Import & CRUD API endpoints
# =========================

@frappe.whitelist(allow_guest=False)
def test_class_week_api(class_id: str = None, week_start: str = None):
    """Test function for get_class_week API"""
    try:
        frappe.logger().info(f"=== TEST CLASS WEEK API ===")
        frappe.logger().info(f"Received: class_id={class_id}, week_start={week_start}")
        frappe.logger().info(f"Request args: {getattr(frappe.request, 'args', {})}")

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
        frappe.logger().info(f"Test class week API error: {str(e)}")
        return {
            "success": False,
            "message": f"Test failed: {str(e)}",
            "test_params": {"class_id": class_id, "week_start": week_start}
        }

@frappe.whitelist(allow_guest=False)
def import_timetable():
    """Import timetable from Excel with dry-run validation and final import"""
    try:
        # Collect logs for response
        logs = []

        def log_timetable_message(message: str):
            """Log both to frappe logger and collect for response"""
            frappe.logger().info(message)
            logs.append(f"{frappe.utils.now()}: {message}")

        # Get request data - handle both FormData and regular form data
        data = {}

        # Try different sources for FormData
        if hasattr(frappe.request, 'form_data') and frappe.request.form_data:
            # For werkzeug form data
            data = frappe.request.form_data
            log_timetable_message("Using form_data")
        elif hasattr(frappe.request, 'form') and frappe.request.form:
            # For flask-style form data
            data = frappe.request.form
            log_timetable_message("Using form")
        elif frappe.local.form_dict:
            # Fallback to form_dict
            data = frappe.local.form_dict
            log_timetable_message("Using form_dict")
        elif hasattr(frappe.request, 'args') and frappe.request.args:
            # Try request args
            data = frappe.request.args
            log_timetable_message("Using args")

        # Convert to dict if it's not already
        if hasattr(data, 'to_dict'):
            data = data.to_dict()
            log_timetable_message("Converted to dict using to_dict()")
        elif not isinstance(data, dict):
            data = dict(data) if data else {}
            log_timetable_message("Converted to dict using dict()")

        log_timetable_message(f"Final data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
        log_timetable_message(f"Raw data: {data}")

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

        # Log basic info for debugging
        log_timetable_message(f"Import timetable request - title_vn: {title_vn}, campus_id: {campus_id}")
        log_timetable_message(f"Current user: {frappe.session.user}")
        log_timetable_message(f"User roles: {frappe.get_roles(frappe.session.user) if frappe.session.user else 'No user'}")
        if hasattr(frappe.request, 'files') and frappe.request.files:
            log_timetable_message(f"Files available: {list(frappe.request.files.keys())}")

        # Validate required fields
        if not all([title_vn, campus_id, school_year_id, education_stage_id, start_date, end_date]):
            log_timetable_message("Validation failed - missing required fields")
            return validation_error_response("Validation failed", {
                "required_fields": ["title_vn", "campus_id", "school_year_id", "education_stage_id", "start_date", "end_date"],
                "logs": logs
            })

        # Get current user campus
        user_campus = get_current_campus_from_context()
        log_timetable_message(f"User campus: {user_campus}, requested campus: {campus_id}")
        if user_campus and user_campus != campus_id:
            log_timetable_message("Access denied - campus mismatch")
            return forbidden_response("Access denied: Campus mismatch")

        # Process Excel import if file is provided
        files = frappe.request.files
        log_timetable_message(f"Files object: {type(files)}")
        log_timetable_message(f"Files keys: {list(files.keys()) if files else 'No files'}")

        if files and 'file' in files:
            # File is uploaded, process it
            file_data = files['file']
            if not file_data:
                log_timetable_message("No file uploaded")
                return validation_error_response("Validation failed", {"file": ["No file uploaded"], "logs": logs})

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
            log_timetable_message("Starting Excel import processing")
            result = process_excel_import_with_metadata_v2(import_data)

            # Add logs to result if it's a dict
            if isinstance(result, dict) and 'data' in result:
                if isinstance(result['data'], dict):
                    result['data']['logs'] = logs

            # Clean up temp file
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
                log_timetable_message("Cleaned up temporary file")

            return result
        else:
            # No file uploaded, just validate metadata
            log_timetable_message("No file uploaded - metadata validation only")
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
                "logs": logs
            }

            return single_item_response(result, "Timetable metadata validated successfully")

    except Exception as e:
        frappe.log_error(f"Error importing timetable: {str(e)}")
        # Try to add logs to error response if possible
        try:
            if 'logs' in locals():
                return error_response(f"Error importing timetable: {str(e)}", {"logs": logs})
        except:
            pass
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
        frappe.log_error(f"Error saving uploaded file: {str(e)}")
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
        frappe.log_error(f"Error fetching timetables: {str(e)}")
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
        frappe.log_error(f"Error fetching timetable detail: {str(e)}")
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
        frappe.log_error(f"Error deleting timetable: {str(e)}")
        return error_response(f"Error deleting timetable: {str(e)}")
