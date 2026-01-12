# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, get_time
from datetime import datetime, time, timedelta
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


def format_time_for_html(time_value):
    """Format time value to HH:MM format for HTML time input"""
    if not time_value:
        return ""

    try:
        # Handle datetime.time object
        if hasattr(time_value, 'strftime'):
            return time_value.strftime("%H:%M")

        # Handle datetime.timedelta object (convert to time)
        if isinstance(time_value, timedelta):
            # Convert timedelta to time (assuming it's from midnight)
            total_seconds = int(time_value.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours:02d}:{minutes:02d}"

        # Handle string format
        if isinstance(time_value, str):
            # Try to parse string as time
            try:
                parsed_time = get_time(time_value)
                return parsed_time.strftime("%H:%M")
            except:
                return time_value

        # Fallback
        return str(time_value)

    except Exception:
        return ""


@frappe.whitelist(allow_guest=False)
def get_all_timetable_columns():
    """
    Get all timetable columns with basic information
    
    Query params:
        - education_stage: Filter theo cấp học
        - schedule_id: Filter theo schedule cụ thể
        - date: Lấy periods của schedule áp dụng cho ngày cụ thể (YYYY-MM-DD)
        - include_legacy: Bao gồm cả periods không có schedule (default: true)
    
    ⚡ Performance: Cached for 15 minutes (shared cache - master data)
    """
    try:
        from frappe.utils import getdate
        
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
        
        # Add education_stage filter if provided
        education_stage = frappe.local.form_dict.get("education_stage") or frappe.request.args.get("education_stage")
        schedule_id = frappe.local.form_dict.get("schedule_id") or frappe.request.args.get("schedule_id")
        # Support cả "date" và "date_filter" params cho backward compatibility
        date_filter = (
            frappe.local.form_dict.get("date") or 
            frappe.request.args.get("date") or 
            frappe.local.form_dict.get("date_filter") or 
            frappe.request.args.get("date_filter")
        )
        include_legacy = frappe.local.form_dict.get("include_legacy") or frappe.request.args.get("include_legacy")
        
        # Default include_legacy to true for backward compatibility
        if include_legacy is None or include_legacy == "" or include_legacy == "1" or include_legacy == "true":
            include_legacy = True
        else:
            include_legacy = False
        
        if education_stage:
            filters["education_stage_id"] = education_stage
        
        # ⚡ CACHE: Build cache key based on all params
        cache_key = f"schedules:{campus_id}:{education_stage or 'all'}:{schedule_id or 'none'}:{date_filter or 'none'}:{include_legacy}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for timetable_columns {cache_key}")
                return list_response(
                    data=cached_data,
                    message="Timetable columns fetched successfully (cached)"
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for timetable_columns {cache_key} - fetching from DB")
        
        timetables = []
        
        # Case 1: Filter by specific schedule_id
        if schedule_id:
            filters["schedule_id"] = schedule_id
            timetables = frappe.get_all(
                "SIS Timetable Column",
                fields=[
                    "name",
                    "schedule_id",
                    "education_stage_id",
                    "period_priority",
                    "period_type", 
                    "period_name",
                    "start_time",
                    "end_time",
                    "campus_id",
                    "creation",
                    "modified"
                ],
                filters=filters,
                order_by="education_stage_id asc, period_priority asc"
            )
        
        # Case 2: Filter by date - find schedule for that date
        elif date_filter:
            target_date = getdate(date_filter)
            
            # Find active schedule for this date
            schedule_filters = {
                "campus_id": campus_id,
                "is_active": 1,
                "start_date": ["<=", target_date],
                "end_date": [">=", target_date]
            }
            if education_stage:
                schedule_filters["education_stage_id"] = education_stage
            
            schedules = frappe.get_all(
                "SIS Schedule",
                filters=schedule_filters,
                fields=["name"],
                order_by="start_date desc"
            )
            
            if schedules:
                # Get periods from matching schedules
                schedule_ids = [s.name for s in schedules]
                timetables = frappe.get_all(
                    "SIS Timetable Column",
                    fields=[
                        "name",
                        "schedule_id",
                        "education_stage_id",
                        "period_priority",
                        "period_type", 
                        "period_name",
                        "start_time",
                        "end_time",
                        "campus_id",
                        "creation",
                        "modified"
                    ],
                    filters={
                        **filters,
                        "schedule_id": ["in", schedule_ids]
                    },
                    order_by="education_stage_id asc, period_priority asc"
                )
            
            # Include legacy periods if needed
            if include_legacy:
                legacy_filters = {**filters, "schedule_id": ["is", "not set"]}
                legacy_timetables = frappe.get_all(
                    "SIS Timetable Column",
                    fields=[
                        "name",
                        "schedule_id",
                        "education_stage_id",
                        "period_priority",
                        "period_type", 
                        "period_name",
                        "start_time",
                        "end_time",
                        "campus_id",
                        "creation",
                        "modified"
                    ],
                    filters=legacy_filters,
                    order_by="education_stage_id asc, period_priority asc"
                )
                
                # Merge: nếu có schedule periods thì dùng, không thì fallback to legacy
                if not timetables:
                    timetables = legacy_timetables
        
        # Case 3: No specific filter - get all (legacy behavior)
        else:
            timetables = frappe.get_all(
                "SIS Timetable Column",
                fields=[
                    "name",
                    "schedule_id",
                    "education_stage_id",
                    "period_priority",
                    "period_type", 
                    "period_name",
                    "start_time",
                    "end_time",
                    "campus_id",
                    "creation",
                    "modified"
                ],
                filters=filters,
                order_by="education_stage_id asc, period_priority asc"
            )

        # 🔄 DEDUPE: Loại bỏ periods trùng theo education_stage_id + period_priority
        # Ưu tiên schedule periods hơn legacy (có schedule_id)
        seen = set()
        deduped_timetables = []
        for timetable in timetables:
            key = (timetable.get("education_stage_id"), timetable.get("period_priority"))
            if key not in seen:
                seen.add(key)
                deduped_timetables.append(timetable)
        timetables = deduped_timetables
        
        frappe.logger().info(f"📊 Returning {len(timetables)} periods (after dedupe)")

        # Format time fields for HTML time input (HH:MM format)
        for timetable in timetables:
            timetable["start_time"] = format_time_for_html(timetable.get("start_time"))
            timetable["end_time"] = format_time_for_html(timetable.get("end_time"))

        # ⚡ CACHE: Store result in Redis (15 min = 900 sec)
        try:
            frappe.cache().set_value(cache_key, timetables, expires_in_sec=900)
            frappe.logger().info(f"✅ Cached timetable_columns for {cache_key}")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")

        return list_response(timetables, "Timetable columns fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable columns: {str(e)}")
        return error_response(f"Error fetching timetable columns: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_column_by_id():
    """Get a specific timetable column by ID"""
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
                r'/api/method/erp\.api\.erp_sis\.timetable\.get_timetable_column_by_id/([^/?]+)',
                r'/erp\.api\.erp_sis\.timetable\.get_timetable_column_by_id/([^/?]+)',
                r'get_timetable_column_by_id/([^/?]+)',
            ]

            for pattern in url_patterns:
                match = re.search(pattern, frappe.request.url or '')
                if match:
                    timetable_column_id = match.group(1)
                    frappe.logger().info(f"Get timetable column column - Found timetable_column_id '{timetable_column_id}' using pattern '{pattern}' from URL: {frappe.request.url}")
                    break

        if not timetable_column_id:
            return validation_error_response("Validation failed", {"timetable_column_id": ["Timetable Column ID is required"]})

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        filters = {
            "name": timetable_column_id,
            "campus_id": campus_id
        }

        timetable_column = frappe.get_doc("SIS Timetable Column", filters)

        if not timetable_column:
            return not_found_response("Timetable column not found or access denied")

        timetable_column_data = {
            "name": timetable_column.name,
            "schedule_id": timetable_column.schedule_id if hasattr(timetable_column, 'schedule_id') else None,
            "education_stage_id": timetable_column.education_stage_id,
            "period_priority": timetable_column.period_priority,
            "period_type": timetable_column.period_type,
            "period_name": timetable_column.period_name,
            "start_time": format_time_for_html(timetable_column.start_time),
            "end_time": format_time_for_html(timetable_column.end_time),
            "campus_id": timetable_column.campus_id
        }
        return single_item_response(timetable_column_data, "Timetable column fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching timetable column: {str(e)}")
        return error_response(f"Error fetching timetable column: {str(e)}")



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
        schedule_id = data.get("schedule_id")  # Optional - can be updated

        # Debug logging - current values
        frappe.logger().info(f"Update timetable column column - Current values: education_stage_id={timetable_column_doc.education_stage_id}, period_priority={timetable_column_doc.period_priority}, period_type={timetable_column_doc.period_type}, period_name={timetable_column_doc.period_name}, schedule_id={getattr(timetable_column_doc, 'schedule_id', None)}")
        current_start_time_raw = timetable_column_doc.start_time
        current_end_time_raw = timetable_column_doc.end_time
        frappe.logger().info(f"Update timetable column column - Current times raw: start_time={current_start_time_raw}, end_time={current_end_time_raw}")

        # Debug logging - new values
        frappe.logger().info(f"Update timetable column column - New values: education_stage_id={education_stage_id}, period_priority={period_priority}, period_type={period_type}, period_name={period_name}, start_time={start_time}, end_time={end_time}")

        # Track if any updates were made
        updates_made = []

        # Update schedule_id if provided (can be set or cleared)
        if "schedule_id" in data:
            current_schedule_id = getattr(timetable_column_doc, 'schedule_id', None)
            if schedule_id != current_schedule_id:
                # Verify schedule exists if not None
                if schedule_id:
                    schedule_exists = frappe.db.exists("SIS Schedule", {"name": schedule_id, "campus_id": campus_id})
                    if not schedule_exists:
                        return not_found_response("Selected schedule does not exist or access denied")
                
                frappe.logger().info(f"Update timetable column - Updating schedule_id: {current_schedule_id} -> {schedule_id}")
                timetable_column_doc.schedule_id = schedule_id
                updates_made.append(f"schedule_id: {schedule_id}")

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

        if period_priority is not None:
            # Convert period_priority to int if it's a string
            if isinstance(period_priority, str):
                try:
                    period_priority = int(period_priority)
                except (ValueError, TypeError):
                    return validation_error_response("Validation failed", {"period_priority": ["Period priority must be a number"]})
            elif not isinstance(period_priority, int):
                return validation_error_response("Validation failed", {"period_priority": ["Period priority must be a number"]})

            # Check if value has changed
            if period_priority != timetable_column_doc.period_priority:
                # Check for duplicate period_priority
                # ⚡ FIX: Chỉ check duplicate trong cùng schedule (nếu có) hoặc trong legacy (nếu không có schedule)
                final_education_stage_id = education_stage_id or timetable_column_doc.education_stage_id
                final_schedule_id = schedule_id if "schedule_id" in data else getattr(timetable_column_doc, 'schedule_id', None)
                
                duplicate_check_filters = {
                    "education_stage_id": final_education_stage_id,
                    "period_priority": period_priority,
                    "campus_id": campus_id,
                    "name": ["!=", timetable_column_id]
                }
                
                # Nếu có schedule_id, chỉ check trong cùng schedule
                # Nếu không, chỉ check trong legacy columns (không có schedule)
                if final_schedule_id:
                    duplicate_check_filters["schedule_id"] = final_schedule_id
                else:
                    duplicate_check_filters["schedule_id"] = ["is", "not set"]
                
                existing = frappe.db.exists("SIS Timetable Column", duplicate_check_filters)
                if existing:
                    return validation_error_response("Validation failed", {"period_priority": [f"Timetable column with priority '{period_priority}' already exists for this education stage/schedule"]})

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
            # ⚡ FIX: Cho phép period_name trùng nhau (như đã config ở create)
            # Không check duplicate, chỉ update
            frappe.logger().info(f"Update timetable column - Updating period_name: {timetable_column_doc.period_name} -> {period_name}")
            timetable_column_doc.period_name = period_name
            updates_made.append(f"period_name: {period_name}")

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
        
        # ⚡ CACHE: Clear schedules cache after update
        try:
            # Clear both specific education_stage cache and 'all' cache
            education_stage_for_cache = timetable_column_doc.education_stage_id
            cache_key_specific = f"schedules:{campus_id}:{education_stage_for_cache}"
            cache_key_all = f"schedules:{campus_id}:all"
            frappe.cache().delete_key(cache_key_specific)
            frappe.cache().delete_key(cache_key_all)
            frappe.logger().info(f"✅ Cleared schedules cache after update")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache clear failed: {cache_error}")
        
        # Format time fields for HTML time input (HH:MM format)
        start_time_formatted = format_time_for_html(timetable_column_doc.start_time)
        end_time_formatted = format_time_for_html(timetable_column_doc.end_time)

        timetable_data = {
            "name": timetable_column_doc.name,
            "schedule_id": getattr(timetable_column_doc, 'schedule_id', None),
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
        education_stage_for_cache = timetable_column_doc.education_stage_id
        frappe.delete_doc("SIS Timetable Column", timetable_column_id)
        frappe.db.commit()
        
        # ⚡ CACHE: Clear schedules cache after delete
        try:
            cache_key_specific = f"schedules:{campus_id}:{education_stage_for_cache}"
            cache_key_all = f"schedules:{campus_id}:all"
            frappe.cache().delete_key(cache_key_specific)
            frappe.cache().delete_key(cache_key_all)
            frappe.logger().info(f"✅ Cleared schedules cache after delete")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache clear failed: {cache_error}")

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

        # Get data from request - prioritize JSON over form_dict for API calls
        data = {}

        # Debug logging
        frappe.logger().info(f"Create timetable column - Raw request data: {frappe.request.data}")
        frappe.logger().info(f"Create timetable column - Form dict: {frappe.local.form_dict}")

        # First try to parse JSON data from request body (preferred for API calls)
        if frappe.request.data and frappe.request.data.strip():
            try:
                json_data = json.loads(frappe.request.data)
                if json_data and isinstance(json_data, dict):
                    data.update(json_data)
                    frappe.logger().info(f"Create timetable column - Using JSON data: {data}")
                else:
                    frappe.logger().info(f"Create timetable column - JSON data is empty or not dict")
            except (json.JSONDecodeError, TypeError) as e:
                frappe.logger().info(f"Create timetable column - JSON parsing failed ({e}), trying form_dict")
                pass

        # Fallback to form_dict if JSON parsing failed or no JSON data
        if not data and frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))
            frappe.logger().info(f"Create timetable column - Using form_dict data as fallback: {data}")

        frappe.logger().info(f"Create timetable column - Final data: {data}")
        frappe.logger().info(f"Create timetable column - Data keys: {list(data.keys()) if data else 'None'}")

        # Check if we have any data at all
        if not data:
            frappe.logger().error("Create timetable column - No data received from request")
            frappe.throw(_("No data received"))

        # Extract values from data
        education_stage_id = data.get("education_stage_id")
        period_priority = data.get("period_priority")
        period_type = data.get("period_type")
        period_name = data.get("period_name")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        schedule_id = data.get("schedule_id")  # Optional - link to SIS Schedule

        frappe.logger().info(f"Create timetable column - Raw extracted values: education_stage_id={repr(education_stage_id)}, period_priority={repr(period_priority)}, period_type={repr(period_type)}, period_name={repr(period_name)}, start_time={repr(start_time)}, end_time={repr(end_time)}, schedule_id={repr(schedule_id)}")

        # Debug logging for extracted values
        frappe.logger().info(f"Create timetable column - Extracted values: education_stage_id={education_stage_id}, period_priority={period_priority}, period_type={period_type}, period_name={period_name}, start_time={start_time}, end_time={end_time}")

        # Input validation - handle both None and empty values
        if (not education_stage_id or (isinstance(education_stage_id, str) and education_stage_id.strip() == "")) or \
           (period_priority is None) or \
           (not period_type or str(period_type).strip() == "") or \
           (not period_name or str(period_name).strip() == "") or \
           (not start_time or str(start_time).strip() == "") or \
           (not end_time or str(end_time).strip() == ""):
            frappe.logger().error(f"Create timetable column - Validation failed. Field values: education_stage_id='{education_stage_id}', period_priority='{period_priority}', period_type='{period_type}', period_name='{period_name}', start_time='{start_time}', end_time='{end_time}'")
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
        
        # Build duplicate check filters - include schedule_id if provided
        duplicate_check_filters = {
            "education_stage_id": education_stage_id,
            "campus_id": campus_id
        }
        # Nếu có schedule_id, chỉ check trùng trong cùng schedule
        # Nếu không có, check trong tất cả legacy columns (không có schedule)
        if schedule_id:
            duplicate_check_filters["schedule_id"] = schedule_id
        else:
            duplicate_check_filters["schedule_id"] = ["is", "not set"]
        
        # Check if period priority already exists for this education stage/schedule
        existing_priority = frappe.db.exists(
            "SIS Timetable Column",
            {
                **duplicate_check_filters,
                "period_priority": period_priority
            }
        )

        if existing_priority:
            frappe.throw(_(f"Period priority '{period_priority}' already exists for this education stage/schedule"))

        # Cho phép period_name trùng nhau (VD: "Tiết 1" có thể xuất hiện ở nhiều schedule khác nhau)
        
        # Create new timetable column
        timetable_column_doc = frappe.get_doc({
            "doctype": "SIS Timetable Column",
            "schedule_id": schedule_id if schedule_id else None,
            "education_stage_id": education_stage_id,
            "period_priority": period_priority,
            "period_type": period_type,
            "period_name": period_name,
            "start_time": start_time,
            "end_time": end_time,
            "campus_id": campus_id
        })
        
        try:
            timetable_column_doc.insert()
            frappe.db.commit()

            frappe.logger().info(f"Create timetable column - Record created successfully: {timetable_column_doc.name}")
            
            # ⚡ CACHE: Clear schedules cache after create (clear pattern-based keys)
            try:
                # Clear multiple cache patterns để đảm bảo fresh data
                cache_patterns = [
                    f"schedules:{campus_id}:{education_stage_id}:*",
                    f"schedules:{campus_id}:all:*",
                ]
                for pattern in cache_patterns:
                    frappe.cache().delete_keys(pattern)
                frappe.logger().info(f"✅ Cleared schedules cache after create")
            except Exception as cache_error:
                frappe.logger().warning(f"Cache clear failed: {cache_error}")

            # Return the created data - follow Education Stage pattern
            timetable_data = {
                "name": timetable_column_doc.name,
                "schedule_id": timetable_column_doc.schedule_id if hasattr(timetable_column_doc, 'schedule_id') else None,
                "education_stage_id": timetable_column_doc.education_stage_id,
                "period_priority": timetable_column_doc.period_priority,
                "period_type": timetable_column_doc.period_type,
                "period_name": timetable_column_doc.period_name,
                "start_time": start_time,  # Use original string value
                "end_time": end_time,      # Use original string value
                "campus_id": timetable_column_doc.campus_id
            }

            frappe.logger().info(f"Create timetable column - Returning data: {timetable_data}")
            return single_item_response(timetable_data, "Timetable column created successfully")

        except Exception as insert_error:
            frappe.logger().error(f"Create timetable column - Insert failed: {str(insert_error)}")
            frappe.throw(_(f"Failed to save timetable column: {str(insert_error)}"))
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable column: {str(e)}")
        frappe.throw(_(f"Error creating timetable column: {str(e)}"))
