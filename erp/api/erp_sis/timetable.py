

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

def _apply_timetable_overrides(entries: list[dict], target_type: str, target_id, 
                              week_start: datetime, week_end: datetime) -> list[dict]:
    """Apply date-specific timetable overrides to entries"""
    try:
        # Convert datetime to date string for database query
        start_date_str = week_start.strftime("%Y-%m-%d")
        end_date_str = week_end.strftime("%Y-%m-%d")
        
        # Handle different target_id types: string for Class, set for Teacher
        if target_type == "Teacher":
            # For teacher, target_id is a set of resolved teacher IDs
            resolved_teacher_ids = list(target_id) if isinstance(target_id, set) else [target_id]
            primary_target_id = resolved_teacher_ids[0] if resolved_teacher_ids else str(target_id)
        else:
            # For class/student, target_id is a simple string
            resolved_teacher_ids = []
            primary_target_id = str(target_id)
        
        # Get all overrides for this target and date range from custom table
        # CROSS-TARGET SUPPORT: For teacher view, also get class overrides where this teacher is assigned
        overrides = []
        
        # Direct overrides for this target (only for Class/Student, not Teacher since teachers don't have direct overrides)
        if target_type != "Teacher":
            direct_overrides = frappe.db.sql("""
                SELECT name, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type
                FROM `tabTimetable_Date_Override`
                WHERE target_type = %s AND target_id = %s AND date BETWEEN %s AND %s
                ORDER BY date ASC, timetable_column_id ASC
            """, (target_type, primary_target_id, start_date_str, end_date_str), as_dict=True)
            overrides.extend(direct_overrides)
        
        # Cross-target support: If querying teacher timetable, also get class overrides where this teacher is assigned
        if target_type == "Teacher":
            # Build dynamic query for multiple teacher IDs
            teacher_conditions = []
            sql_params = [start_date_str, end_date_str]
            
            for teacher_id in resolved_teacher_ids:
                teacher_conditions.append("(teacher_1_id = %s OR teacher_2_id = %s)")
                sql_params.extend([teacher_id, teacher_id])
            
            teacher_where = " OR ".join(teacher_conditions)
            
            sql_query = f"""
                SELECT name, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type, target_id as source_class_id
                FROM `tabTimetable_Date_Override`
                WHERE target_type = 'Class' 
                AND date BETWEEN %s AND %s 
                AND ({teacher_where})
                ORDER BY date ASC, timetable_column_id ASC
            """
            
            cross_overrides = frappe.db.sql(sql_query, sql_params, as_dict=True)
            
            # Mark cross-target overrides 
            for override in cross_overrides:
                override["is_cross_target"] = True
                override["source_target_type"] = "Class"
                
            overrides.extend(cross_overrides)
        
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
                try:
                    subject = frappe.get_doc("SIS Subject", override["subject_id"])
                    subject_title = subject.title
                except:
                    subject_title = ""
                
            teacher_names = []
            if override.get("teacher_1_id"):
                try:
                    teacher1 = frappe.get_doc("SIS Teacher", override["teacher_1_id"])
                    if teacher1.user_id:
                        user1 = frappe.get_doc("User", teacher1.user_id)
                        display_name1 = user1.full_name or f"{user1.first_name or ''} {user1.last_name or ''}".strip()
                        teacher_names.append(display_name1)
                except:
                    pass  # Skip if teacher not found
                    
            if override.get("teacher_2_id"):
                try:
                    teacher2 = frappe.get_doc("SIS Teacher", override["teacher_2_id"])
                    if teacher2.user_id:
                        user2 = frappe.get_doc("User", teacher2.user_id)
                        display_name2 = user2.full_name or f"{user2.first_name or ''} {user2.last_name or ''}".strip()
                        teacher_names.append(display_name2)
                except:
                    pass  # Skip if teacher not found
                    
            # Determine class_id based on override type
            class_id_for_override = ""
            if override.get("is_cross_target"):
                # Cross-target override (class→teacher): use source class_id
                class_id_for_override = override.get("source_class_id", "")
            elif target_type == "Class":
                # Direct class override: use current target_id
                class_id_for_override = primary_target_id
                
            override_map[date][column_id] = {
                "name": f"override-{override['name']}",  # Mark as override entry
                "subject_title": subject_title,
                "teacher_names": ", ".join(teacher_names),
                "override_type": override.get("override_type", "replace"),
                "override_id": override["name"],
                "class_id": class_id_for_override,
                "is_cross_target": override.get("is_cross_target", False),
                "source_target_type": override.get("source_target_type", target_type),
                "source_class_id": override.get("source_class_id", "")
            }
            
        # Apply overrides to entries
        enhanced_entries = []
        matched_overrides = set()  # Track which overrides were matched to existing entries
        
        for entry in entries:
            entry_date = entry.get("date")
            entry_column = entry.get("timetable_column_id")
            
            # Check if there's an override for this date/column combination
            if (entry_date in override_map and 
                entry_column in override_map[entry_date]):
                
                override_data = override_map[entry_date][entry_column]
                matched_overrides.add(f"{entry_date}|{entry_column}")  # Track matched override
                
                if override_data["override_type"] == "replace":
                    # Replace entry with override data
                    enhanced_entry = {**entry}  # Copy original entry
                    enhanced_entry.update({
                        "name": override_data["name"],
                        "subject_title": override_data["subject_title"],
                        "teacher_names": override_data["teacher_names"],
                        "class_id": override_data.get("class_id", entry.get("class_id", "")),  # Use override class_id if available
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
                        "class_id": override_data.get("class_id", entry.get("class_id", "")),  # Use override class_id if available
                        "is_override": True,
                        "override_id": override_data["override_id"]
                    })
                    enhanced_entries.append(override_entry)
            else:
                # No override, keep original entry
                enhanced_entries.append(entry)
        
        # CRITICAL FIX: Create entries for unmatched overrides (teacher has no existing entry for that date/period)
        for date_str, date_overrides in override_map.items():
            for column_id, override_data in date_overrides.items():
                override_key = f"{date_str}|{column_id}"
                
                if override_key not in matched_overrides:
                    # This override didn't match any existing entry - create a new entry
                    try:
                        # Parse date to get day_of_week
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                        day_names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
                        day_of_week = day_names[date_obj.weekday()]
                        
                        # Get period info from timetable column
                        period_info = {}
                        try:
                            column = frappe.get_doc("SIS Timetable Column", column_id)
                            period_info = {
                                "period_priority": column.period_priority,
                                "period_name": column.period_name
                            }
                        except:
                            pass
                        
                        # Create new entry for the override
                        new_entry = {
                            "name": override_data["name"],
                            "date": date_str,
                            "day_of_week": day_of_week,
                            "timetable_column_id": column_id,
                            "period_priority": period_info.get("period_priority"),
                            "subject_title": override_data["subject_title"],
                            "teacher_names": override_data["teacher_names"],
                            "class_id": override_data.get("class_id", ""),  # Use class_id from override_map
                            "is_override": True,
                            "override_id": override_data["override_id"]
                        }
                        
                        enhanced_entries.append(new_entry)
                        
                    except Exception as create_error:
                        frappe.log_error(f"Error creating override entry: {str(create_error)}")
        
        return enhanced_entries
        
    except Exception as e:
        frappe.log_error(f"Error applying timetable overrides: {str(e)}")
        # Return original entries if override processing fails
        return entries


def _build_entries(rows: list[dict], week_start: datetime) -> list[dict]:
    """
    Build timetable entries from instance rows.
    
    🎯 Date-specific override rows take precedence over pattern rows.
    - Date-specific rows (date != NULL) override pattern rows for specific dates
    - Pattern rows (date == NULL) fill remaining slots
    """
    return _build_entries_with_date_precedence(rows, week_start)


def _build_entries_legacy(rows: list[dict], week_start: datetime) -> list[dict]:
    """
    Legacy logic: All rows treated as patterns, date calculated from day_of_week.
    This is the SAFE default behavior.
    """
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
            "room_id": r.get("room_id"),
            "room_name": r.get("room_name"),
            "room_type": r.get("room_type"),
        })
    return result


def _build_entries_with_date_precedence(rows: list[dict], week_start: datetime) -> list[dict]:
    """
    🎯 NEW LOGIC: Date-specific override rows take precedence over pattern rows.
    
    Strategy:
    1. Separate rows into date-specific overrides vs patterns
    2. Build entries from patterns for all days
    3. Override with date-specific rows where they exist
    
    This ensures:
    - Date-range assignments work correctly
    - Pattern rows remain as templates
    - No data duplication
    """
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
    
    # Separate pattern rows vs date-specific override rows
    pattern_rows = []
    override_rows = []
    
    for r in rows:
        if r.get("date"):
            # Date-specific override
            override_rows.append(r)
        else:
            # Pattern row (date is NULL)
            pattern_rows.append(r)
    
    frappe.logger().info(f"📊 _build_entries: {len(pattern_rows)} pattern rows, {len(override_rows)} override rows")
    
    # Build override map: (date_str, column_id, day_of_week) → row
    # Include day_of_week to handle multiple subjects in same period
    override_map = {}
    for r in override_rows:
        date_str = r.get("date") if isinstance(r.get("date"), str) else r.get("date").strftime("%Y-%m-%d")
        key = (date_str, r.get("timetable_column_id"), r.get("day_of_week"))
        override_map[key] = r
    
    result: list[dict] = []
    
    # Build from pattern rows first
    for r in pattern_rows:
        idx = _day_of_week_to_index(r.get("day_of_week"))
        if idx < 0:
            continue
        
        d = _add_days(week_start, idx)
        date_str = d.strftime("%Y-%m-%d")
        key = (date_str, r.get("timetable_column_id"), r.get("day_of_week"))
        
        # Only use pattern if no override exists for this date/period/day
        if key not in override_map:
            col = columns_map.get(r.get("timetable_column_id")) or {}
            result.append({
                "name": r.get("name"),
                "date": date_str,
                "day_of_week": r.get("day_of_week"),
                "timetable_column_id": r.get("timetable_column_id"),
                "period_priority": col.get("period_priority"),
                "subject_title": r.get("subject_title") or r.get("subject_name") or r.get("subject") or "",
                "teacher_names": r.get("teacher_names") or r.get("teacher_display") or "",
                "class_id": r.get("class_id"),
                "room_id": r.get("room_id"),
                "room_name": r.get("room_name"),
                "room_type": r.get("room_type"),
                "is_pattern": True  # Mark as pattern for debugging
            })
    
    # Add date-specific overrides (these take precedence)
    week_end = _add_days(week_start, 6)
    for r in override_rows:
        row_date = r.get("date")
        if isinstance(row_date, str):
            from datetime import datetime
            row_date = datetime.strptime(row_date, "%Y-%m-%d")
        
        # Only include overrides within this week
        if week_start <= row_date <= week_end:
            col = columns_map.get(r.get("timetable_column_id")) or {}
            result.append({
                "name": r.get("name"),
                "date": row_date.strftime("%Y-%m-%d"),
                "day_of_week": r.get("day_of_week"),
                "timetable_column_id": r.get("timetable_column_id"),
                "period_priority": col.get("period_priority"),
                "subject_title": r.get("subject_title") or r.get("subject_name") or r.get("subject") or "",
                "teacher_names": r.get("teacher_names") or r.get("teacher_display") or "",
                "class_id": r.get("class_id"),
                "room_id": r.get("room_id"),
                "room_name": r.get("room_name"),
                "room_type": r.get("room_type"),
                "is_override": True  # Mark as override for debugging
            })
    
    frappe.logger().info(f"✅ _build_entries: Built {len(result)} entries ({len([e for e in result if e.get('is_pattern')])} from patterns, {len([e for e in result if e.get('is_override')])} overrides)")
    
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
        frappe.logger().info("🏫 TIMETABLE: get_teacher_week called")
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
                
                frappe.logger().info(f"🔍 TIMETABLE: Filtering by education_stage={education_stage} with column_filters={column_filters}")
                    
                valid_columns = frappe.get_all(
                    "SIS Timetable Column",
                    fields=["name"],
                    filters=column_filters
                )
                
                frappe.logger().info(f"🔍 TIMETABLE: Found {len(valid_columns)} valid columns for education_stage={education_stage}")
                
                if valid_columns:
                    valid_column_ids = [col.name for col in valid_columns]
                    filters["timetable_column_id"] = ["in", valid_column_ids]
                    frappe.logger().info(f"✅ TIMETABLE: Applied filter with {len(valid_column_ids)} column IDs")
                else:
                    # If no columns found for this education stage, return empty
                    frappe.logger().warning(f"⚠️ TIMETABLE: No timetable columns found for education_stage={education_stage}")
                    return list_response([], "No timetable columns found for this education stage")
                    
            except Exception as education_filter_error:
                # ❌ DO NOT silently ignore errors - log and return error response
                error_msg = f"Error filtering by education stage {education_stage}: {str(education_filter_error)}"
                frappe.logger().error(f"❌ TIMETABLE: {error_msg}")
                frappe.log_error(error_msg, "Timetable Education Stage Filter Error")
                return error_response(error_msg)

        # ✅ NEW APPROACH: Query from SIS Teacher Timetable materialized view instead of Instance Rows
        # This ensures we only return entries that have been properly created with teacher assignments
        
        frappe.logger().info(f"🔍 TIMETABLE: Querying Teacher Timetable for teachers: {resolved_teacher_ids}")
        
        # Build date filter for the week
        teacher_timetable_filters = {
            "date": ["between", [ws, week_end]] if week_end else [">=", ws]
        }
        
        # Add education_stage filter if already applied to 'filters'
        if "timetable_column_id" in filters:
            teacher_timetable_filters["timetable_column_id"] = filters["timetable_column_id"]
        
        frappe.logger().info(f"🔍 TIMETABLE: Teacher Timetable filters: {teacher_timetable_filters}")
        
        try:
            # Query Teacher Timetable directly - this is the materialized view
            rows = []
            for teacher_id in resolved_teacher_ids:
                teacher_filters = {**teacher_timetable_filters, "teacher_id": teacher_id}
                teacher_rows = frappe.get_all(
                    "SIS Teacher Timetable",
                    fields=[
                        "name",
                        "teacher_id", 
                        "class_id",
                        "day_of_week",
                        "timetable_column_id",
                        "subject_id",
                        "room_id",
                        "date",
                        "timetable_instance_id"
                    ],
                    filters=teacher_filters,
                    order_by="date asc, day_of_week asc"
                )
                rows.extend(teacher_rows)
                frappe.logger().info(f"  - Found {len(teacher_rows)} entries for teacher {teacher_id}")
            
            frappe.logger().info(f"✅ TIMETABLE: Total {len(rows)} entries from Teacher Timetable")
            
            # Map to structure expected by downstream code
            # Teacher Timetable already has teacher_id, treat as teacher_1_id for compatibility
            for row in rows:
                row["teacher_1_id"] = row.get("teacher_id")
                row["parent"] = row.get("timetable_instance_id")  # For compatibility with instance lookup
                
        except Exception as query_error:
            frappe.logger().error(f"❌ TIMETABLE: Query failed: {str(query_error)}")
            return error_response(f"Query failed: {str(query_error)}")

        # Teacher Timetable already has class_id, no need to fetch from instance
        # Just log for debugging
        frappe.logger().info(f"📝 TIMETABLE: Rows already have class_id from Teacher Timetable")
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

            # Enrich with room information for Teacher Timetable data
            frappe.logger().info(f"🏫 ROOM ENRICH: Starting room enrichment for {len(rows)} rows")
            for r in rows:
                frappe.logger().info(f"🏫 ROOM ENRICH: Processing class={r.get('class_id')}, subject={r.get('subject_title')}")
                try:
                    from erp.api.erp_administrative.room import get_room_for_class_subject
                    room_info = get_room_for_class_subject(r.get("class_id"), r.get("subject_title"))
                    frappe.logger().info(f"🏫 ROOM INFO: class={r.get('class_id')}, subject={r.get('subject_title')} -> room={room_info.get('room_name')}, type={room_info.get('room_type')}")
                    r["room_id"] = room_info.get("room_id")
                    r["room_name"] = room_info.get("room_name")
                    r["room_type"] = room_info.get("room_type")
                    frappe.logger().info(f"🏫 ROOM ENRICH: Added room info to row: {r.get('room_name')}")
                except Exception as room_error:
                    frappe.logger().warning(f"Failed to get room for class {r.get('class_id')}, subject {r.get('subject_title')}: {str(room_error)}")
                    import traceback
                    frappe.logger().error(f"Room error traceback: {traceback.format_exc()}")
                    r["room_id"] = None
                    r["room_name"] = "Lỗi tải phòng"
                    r["room_type"] = None
        except Exception as enrich_error:
            frappe.logger().error(f"Error in enrichment section: {str(enrich_error)}")
            import traceback
            frappe.logger().error(f"Enrichment error traceback: {traceback.format_exc()}")
            # Still try to add room info even if other enrichment failed
            try:
                from erp.api.erp_administrative.room import get_room_for_class_subject
                for r in rows:
                    if not r.get("room_id"):
                        try:
                            room_info = get_room_for_class_subject(r.get("class_id"), r.get("subject_title"))
                            r["room_id"] = room_info.get("room_id")
                            r["room_name"] = room_info.get("room_name")
                            r["room_type"] = room_info.get("room_type")
                        except Exception:
                            r["room_id"] = None
                            r["room_name"] = "Chưa có phòng"
                            r["room_type"] = None
            except Exception:
                pass

        entries = _build_entries(rows, ws)
        frappe.logger().info(f"📝 TIMETABLE: Built {len(entries)} entries from {len(rows)} rows")

        # Debug: Check room info in final entries
        if entries:
            sample_entry = entries[0]
            frappe.logger().info(f"🏫 FINAL ENTRIES: Sample entry has room info: room_name={sample_entry.get('room_name')}, room_type={sample_entry.get('room_type')}, room_id={sample_entry.get('room_id')}")
        
        # Apply timetable overrides for date-specific changes (PRIORITY 3)
        week_end = _add_days(ws, 6)
        entries_with_overrides = _apply_timetable_overrides(entries, "Teacher", resolved_teacher_ids, ws, week_end)
        
        frappe.logger().info(f"✅ TIMETABLE: Final response - {len(entries_with_overrides)} entries (after overrides)")
        
        # Detect duplicates by unique key
        if len(entries_with_overrides) > 0:
            unique_keys = set()
            duplicates = []
            for entry in entries_with_overrides:
                key = f"{entry.get('date')}_{entry.get('timetable_column_id')}_{entry.get('class_id')}"
                if key in unique_keys:
                    duplicates.append(entry)
                unique_keys.add(key)
            
            if duplicates:
                frappe.logger().warning(f"⚠️ TIMETABLE: Found {len(duplicates)} duplicate entries!")
                for dup in duplicates[:3]:  # Log first 3
                    frappe.logger().warning(f"  - Duplicate: {dup.get('date')} / {dup.get('class_id')} / {dup.get('subject_title')}")
        
        return list_response(entries_with_overrides, "Teacher week fetched successfully")
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
                    "date",  # ✅ ADD: Support date-specific override rows
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
                        "date",  # ✅ ADD: Support date-specific override rows
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
                    SELECT name, parent_timetable_instance, day_of_week, date, timetable_column_id, subject_id, teacher_1_id, teacher_2_id
                    FROM `tabSIS Timetable Instance Row`
                    WHERE parent_timetable_instance IN ({placeholders})
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

            # Enrich with room information
            for r in rows:
                try:
                    from erp.api.erp_administrative.room import get_room_for_class_subject
                    room_info = get_room_for_class_subject(r.get("class_id"), r.get("subject_title"))
                    r["room_id"] = room_info.get("room_id")
                    r["room_name"] = room_info.get("room_name")
                    r["room_type"] = room_info.get("room_type")
                except Exception as room_error:
                    frappe.logger().warning(f"Failed to get room for class {r.get('class_id')}, subject {r.get('subject_title')}: {str(room_error)}")
                    import traceback
                    frappe.logger().error(f"Room error traceback: {traceback.format_exc()}")
                    r["room_id"] = None
                    r["room_name"] = "Lỗi tải phòng"
                    r["room_type"] = None
        except Exception as enrich_error:
            frappe.logger().error(f"Error in enrichment section: {str(enrich_error)}")
            import traceback
            frappe.logger().error(f"Enrichment error traceback: {traceback.format_exc()}")
            # Still try to add room info even if other enrichment failed
            try:
                from erp.api.erp_administrative.room import get_room_for_class_subject
                for r in rows:
                    if not r.get("room_id"):
                        try:
                            room_info = get_room_for_class_subject(r.get("class_id"), r.get("subject_title"))
                            r["room_id"] = room_info.get("room_id")
                            r["room_name"] = room_info.get("room_name")
                            r["room_type"] = room_info.get("room_type")
                        except Exception:
                            r["room_id"] = None
                            r["room_name"] = "Chưa có phòng"
                            r["room_type"] = None
            except Exception:
                pass

        entries = _build_entries(rows, ws)
        
        # Apply timetable overrides for date-specific changes (PRIORITY 3)
        entries_with_overrides = _apply_timetable_overrides(entries, "Class", class_id, ws, we)
        
        return list_response(entries_with_overrides, "Class week fetched successfully")
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

        # Validate required fields - end_date can be provided by user or auto-calculated from school_year_id
        if not all([title_vn, campus_id, school_year_id, education_stage_id, start_date]):
            return validation_error_response("Validation failed", {
                "required_fields": ["title_vn", "campus_id", "school_year_id", "education_stage_id", "start_date"],
                "logs": []
            })
        
        # Auto-calculate end_date from school year if not provided (fallback for backward compatibility)
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

            # Enqueue background job for processing to avoid worker timeout
            job = frappe.enqueue(
                method='erp.api.erp_sis.timetable_excel_import.process_excel_import_background',
                queue='long',
                timeout=7200,  # 2 hour timeout - increased for handling 40+ classes
                is_async=True,
                **import_data
            )
            
            job_name = job.get_id() if hasattr(job, 'get_id') else str(job)
            
            return single_item_response({
                "status": "processing",
                "job_id": job_name,
                "message": "Timetable import đang được xử lý trong background",
                "logs": ["📤 Đã upload file thành công", f"⚙️ Background job started: {job_name}"]
            }, "Timetable import job created")
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


@frappe.whitelist(methods=["GET"])
def get_import_job_status():
    """
    Get the status/result of timetable import background job.
    Frontend should poll this endpoint after submitting import.
    """
    try:
        cache_key = f"timetable_import_result_{frappe.session.user}"
        result = frappe.cache().get_value(cache_key)
        
        if result:
            # Clear cache after retrieval
            frappe.cache().delete_value(cache_key)
            return single_item_response(result, "Import result retrieved")
        else:
            return single_item_response({
                "status": "processing",
                "message": "Import vẫn đang xử lý..."
            }, "Import in progress")
    
    except Exception as e:
        return error_response(f"Error retrieving import status: {str(e)}")


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
    """
    PRIORITY 3: Create or update a date-specific timetable override for individual cell edits.
    
    This handles direct changes on WeeklyGrid cells and only affects that specific date/period.
    Does NOT modify timetable instance rows - those are handled by Priority 2 (Subject Assignment sync).
    """
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
        
        
        # Convert "none" strings to None
        if teacher_1_id == "none" or teacher_1_id == "":
            teacher_1_id = None
        if teacher_2_id == "none" or teacher_2_id == "":
            teacher_2_id = None
        if subject_id == "none" or subject_id == "":
            subject_id = None
        if room_id == "none" or room_id == "":
            room_id = None

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
        
        if existing_override:
            # Update existing override
            override_name = existing_override[0].name
            frappe.db.sql("""
                UPDATE `tabTimetable_Date_Override`
                SET subject_id = %s, teacher_1_id = %s, teacher_2_id = %s, room_id = %s,
                    override_type = %s, modified = %s, modified_by = %s
                WHERE name = %s
            """, (subject_id, teacher_1_id, teacher_2_id, room_id, 'replace',
                  frappe.utils.now(), frappe.session.user, override_name))
            
            action = "updated"
        else:
            # Create new override
            override_name = f"OVERRIDE-{frappe.generate_hash()[:8]}"
            frappe.db.sql("""
                INSERT INTO `tabTimetable_Date_Override`
                (name, date, timetable_column_id, target_type, target_id, subject_id, teacher_1_id, teacher_2_id, room_id, override_type, created_by, creation, modified, modified_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (override_name, date, timetable_column_id, target_type, target_id, subject_id, teacher_1_id, teacher_2_id, room_id, 'replace',
                  frappe.session.user, frappe.utils.now(), frappe.utils.now(), frappe.session.user))
            
            action = "created"
        
        frappe.db.commit()
        
        # PRIORITY 3.5: Sync Teacher Timetable for date-specific override
        # Note: Teacher timetable sync is temporarily disabled due to validation issues
        # TODO: Fix Teacher Timetable validation or format compatibility
        
        # Get subject and teacher names for response
        subject_title = ""
        if subject_id:
            subject_title = frappe.db.get_value("SIS Subject", subject_id, "title") or ""
            
        teacher_names = []
        if teacher_1_id:
            try:
                teacher1 = frappe.get_doc("SIS Teacher", teacher_1_id)
                if teacher1.user_id:
                    user1 = frappe.get_doc("User", teacher1.user_id)
                    display_name1 = user1.full_name or f"{user1.first_name or ''} {user1.last_name or ''}".strip()
                    if display_name1:
                        teacher_names.append(display_name1)
            except:
                pass  # Skip if teacher not found
        if teacher_2_id:
            try:
                teacher2 = frappe.get_doc("SIS Teacher", teacher_2_id)
                if teacher2.user_id:
                    user2 = frappe.get_doc("User", teacher2.user_id)
                    display_name2 = user2.full_name or f"{user2.first_name or ''} {user2.last_name or ''}".strip()
                    if display_name2:
                        teacher_names.append(display_name2)
            except:
                pass  # Skip if teacher not found
        
        return single_item_response({
            "name": override_name,
            "date": date,
            "timetable_column_id": timetable_column_id,
            "target_type": target_type,
            "target_id": target_id,
            "subject_id": subject_id,
            "subject_title": subject_title,
            "teacher_1_id": teacher_1_id,
            "teacher_2_id": teacher_2_id,
            "teacher_names": ", ".join(teacher_names),
            "room_id": room_id,
            "override_type": "replace",
            "action": action
        }, f"Timetable override {action} successfully for {date}")

    except Exception as e:
        frappe.log_error(f"Error creating/updating timetable override: {str(e)}")
        return error_response(f"Error creating timetable override: {str(e)}")




@frappe.whitelist(allow_guest=False, methods=["DELETE"])
def delete_timetable_override(override_id: str = None):
    """Delete a specific timetable override"""
    try:
        override_id = override_id or _get_request_arg("override_id")
        
        if not override_id:
            return validation_error_response("Validation failed", {
                "override_id": ["Override ID is required"]
            })
            
        # Delete from custom table
        deleted_count = frappe.db.sql("""
            DELETE FROM `tabTimetable_Date_Override`
            WHERE name = %s AND created_by = %s
        """, (override_id, frappe.session.user))
        
        if deleted_count:
            frappe.db.commit()
            
            # TODO: Sync teacher timetable when deleting override
            
            return single_item_response({"deleted": True}, "Timetable override deleted successfully")
        else:
            return not_found_response("Timetable override not found or access denied")
            
    except Exception as e:
        frappe.log_error(f"Error deleting timetable override: {str(e)}")
        return error_response(f"Error deleting timetable override: {str(e)}")


def _sync_teacher_timetable_for_override(date: str, timetable_column_id: str, target_type: str, target_id: str,
                                        old_teacher_1_id: str = None, old_teacher_2_id: str = None,
                                        new_teacher_1_id: str = None, new_teacher_2_id: str = None,
                                        subject_id: str = None, room_id: str = None):
    """
    PRIORITY 3.5: Sync Teacher Timetable entries for date-specific cell overrides
    
    This ensures attendance/class log systems recognize the teacher change for specific date.
    """
    try:
        if target_type != "Class":
            # Only handle class-based overrides for now
            return
            
        class_id = target_id
        
        # Parse date to get day of week
        from datetime import datetime
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        day_of_week_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
        day_of_week = day_of_week_map.get(date_obj.weekday())
        
        if not day_of_week:
            return
            
        # 1. Find existing Teacher Timetable entries for this date/period/class
        existing_entries = frappe.get_all(
            "SIS Teacher Timetable",
            fields=["name", "teacher_id", "timetable_instance_id"],
            filters={
                "class_id": class_id,
                "day_of_week": day_of_week,
                "timetable_column_id": timetable_column_id,
                "date": date  # Specific date filter
            }
        )
        
        # 2. Remove existing entries (will be replaced with override teachers)
        old_teachers_removed = []
        for entry in existing_entries:
            old_teachers_removed.append(entry.teacher_id)
            try:
                frappe.delete_doc("SIS Teacher Timetable", entry.name, ignore_permissions=True)
            except Exception as delete_error:
                frappe.log_error(f"Error removing teacher timetable entry: {str(delete_error)}")
        
        # 3. Create new Teacher Timetable entries for override teachers
        new_teachers = []
        if new_teacher_1_id and new_teacher_1_id != "none":
            new_teachers.append(new_teacher_1_id)
        if new_teacher_2_id and new_teacher_2_id != "none":
            new_teachers.append(new_teacher_2_id)
            
        # Find timetable instance for this class/date
        timetable_instance_id = None
        try:
            instances = frappe.get_all(
                "SIS Timetable Instance",
                fields=["name"],
                filters={
                    "class_id": class_id,
                    "start_date": ["<=", date],
                    "end_date": [">=", date]
                },
                limit=1
            )
            if instances:
                timetable_instance_id = instances[0].name
        except:
            pass
            
        if not timetable_instance_id:
            return
            
        # Create new entries
        for teacher_id in new_teachers:
            if not teacher_id:
                continue
                
            try:
                teacher_timetable = frappe.get_doc({
                    "doctype": "SIS Teacher Timetable",
                    "teacher_id": teacher_id,
                    "timetable_instance_id": timetable_instance_id,
                    "class_id": class_id,
                    "day_of_week": day_of_week,
                    "timetable_column_id": timetable_column_id,
                    "subject_id": subject_id,
                    "room_id": room_id,
                    "date": date  # Specific date for override
                })
                
                teacher_timetable.insert(ignore_permissions=True)
                
            except Exception as create_error:
                frappe.log_error(f"Error creating teacher timetable entry: {str(create_error)}")
        
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error(f"Error syncing teacher timetable for override: {str(e)}")
        raise


def _get_request_arg(arg_name: str):
    """Helper to get argument from various request sources"""
    # Try JSON data first
    if frappe.request.data:
        try:
            data = json.loads(frappe.request.data)
            return data.get(arg_name)
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Try form data
    if hasattr(frappe.local, 'form_dict') and frappe.local.form_dict:
        return frappe.local.form_dict.get(arg_name)
        
    # Try query params
    if hasattr(frappe.request, 'args') and frappe.request.args:
        return frappe.request.args.get(arg_name)
        
    return None
