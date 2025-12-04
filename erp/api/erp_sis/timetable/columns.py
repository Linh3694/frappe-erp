# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

"""
Timetable Column CRUD Operations

Handles creation, update, deletion of timetable columns (periods).
"""

import json
import frappe
from frappe import _
from frappe.utils.data import get_time
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
from .helpers import format_time_for_html


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
                    get_time(start_time)  # Validate time format
                    timetable_column_doc.start_time = start_time
                    updates_made.append(f"start_time: {start_time}")
                except Exception:
                    return validation_error_response("Validation failed", {"start_time": ["Invalid start time format"]})

        if end_time and end_time.strip():
            if end_time != current_end_time:
                try:
                    get_time(end_time)  # Validate time format
                    timetable_column_doc.end_time = end_time
                    updates_made.append(f"end_time: {end_time}")
                except Exception:
                    return validation_error_response("Validation failed", {"end_time": ["Invalid end time format"]})

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

