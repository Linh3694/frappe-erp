# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, get_time
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


@frappe.whitelist(allow_guest=False)
def get_all_timetables():
    """Get all timetable columns with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        timetables = frappe.get_all(
            "SIS Timetable Column",
            fields=[
                "name",
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

        # Format time fields for HTML time input (HH:MM format)
        for timetable in timetables:
            if timetable.get("start_time"):
                try:
                    if hasattr(timetable["start_time"], "strftime"):
                        timetable["start_time"] = timetable["start_time"].strftime("%H:%M")
                    else:
                        # If it's already a string, try to parse and format
                        time_obj = get_time(str(timetable["start_time"]))
                        timetable["start_time"] = time_obj.strftime("%H:%M")
                except:
                    timetable["start_time"] = ""
            else:
                timetable["start_time"] = ""

            if timetable.get("end_time"):
                try:
                    if hasattr(timetable["end_time"], "strftime"):
                        timetable["end_time"] = timetable["end_time"].strftime("%H:%M")
                    else:
                        # If it's already a string, try to parse and format
                        time_obj = get_time(str(timetable["end_time"]))
                        timetable["end_time"] = time_obj.strftime("%H:%M")
                except:
                    timetable["end_time"] = ""
            else:
                timetable["end_time"] = ""

        return list_response(timetables, "Timetables fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetables: {str(e)}")
        return error_response(f"Error fetching timetables: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_by_id():
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

        timetable_id = data.get("timetable_id")
        if not timetable_id:
            return validation_error_response("Validation failed", {"timetable_id": ["Timetable ID is required"]})

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        filters = {
            "name": timetable_id,
            "campus_id": campus_id
        }

        timetable = frappe.get_doc("SIS Timetable Column", filters)

        if not timetable:
            return not_found_response("Timetable not found or access denied")

        timetable_data = {
            "name": timetable.name,
            "education_stage_id": timetable.education_stage_id,
            "period_priority": timetable.period_priority,
            "period_type": timetable.period_type,
            "period_name": timetable.period_name,
            "start_time": timetable.start_time.strftime("%H:%M") if timetable.start_time else "",
            "end_time": timetable.end_time.strftime("%H:%M") if timetable.end_time else "",
            "campus_id": timetable.campus_id
        }
        return single_item_response(timetable_data, "Timetable fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching timetable: {str(e)}")
        return error_response(f"Error fetching timetable: {str(e)}")



@frappe.whitelist(allow_guest=False)
def update_timetable():
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

        timetable_id = data.get("timetable_id")
        if not timetable_id:
            return validation_error_response("Validation failed", {"timetable_id": ["Timetable ID is required"]})

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            timetable_doc = frappe.get_doc("SIS Timetable Column", timetable_id)
            
            # Check campus permission
            if timetable_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to modify this timetable")
                
        except frappe.DoesNotExistError:
            return not_found_response("Timetable not found")
        
        # Extract values from data
        education_stage_id = data.get("education_stage_id")
        period_priority = data.get("period_priority")
        period_type = data.get("period_type")
        period_name = data.get("period_name")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        # Update fields if provided
        if education_stage_id and education_stage_id != timetable_doc.education_stage_id:
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

            timetable_doc.education_stage_id = education_stage_id

        if period_priority is not None and int(period_priority) != timetable_doc.period_priority:
            # Validate period_priority is integer
            try:
                period_priority = int(period_priority)
            except (ValueError, TypeError):
                return validation_error_response("Validation failed", {"period_priority": ["Period priority must be a number"]})

            # Check for duplicate period_priority
            final_education_stage_id = education_stage_id or timetable_doc.education_stage_id
            existing = frappe.db.exists(
                "SIS Timetable Column",
                {
                    "education_stage_id": final_education_stage_id,
                    "period_priority": period_priority,
                    "campus_id": campus_id,
                    "name": ["!=", timetable_id]
                }
            )
            if existing:
                return validation_error_response("Validation failed", {"period_priority": [f"Timetable with priority '{period_priority}' already exists for this education stage"]})

            timetable_doc.period_priority = period_priority

        if period_type and period_type != timetable_doc.period_type:
            if period_type not in ['study', 'non-study']:
                return validation_error_response("Validation failed", {"period_type": ["Period type must be 'study' or 'non-study'"]})
            timetable_doc.period_type = period_type

        if period_name and period_name != timetable_doc.period_name:
            timetable_doc.period_name = period_name

        if start_time and start_time != timetable_doc.start_time.strftime("%H:%M"):
            try:
                start_time_obj = get_time(start_time)
                timetable_doc.start_time = start_time
            except Exception:
                return validation_error_response("Validation failed", {"start_time": ["Invalid start time format"]})

        if end_time and end_time != timetable_doc.end_time.strftime("%H:%M"):
            try:
                end_time_obj = get_time(end_time)
                timetable_doc.end_time = end_time
            except Exception:
                return validation_error_response("Validation failed", {"end_time": ["Invalid end time format"]})
        
        # Validate time range after updates
        if timetable_doc.start_time >= timetable_doc.end_time:
            return validation_error_response("Validation failed", {"start_time": ["Start time must be before end time"]})
        
        timetable_doc.save()
        frappe.db.commit()
        
        # Format time fields for HTML time input (HH:MM format)
        start_time_formatted = ""
        end_time_formatted = ""

        try:
            if timetable_doc.start_time:
                start_time_formatted = timetable_doc.start_time.strftime("%H:%M")
        except:
            start_time_formatted = ""

        try:
            if timetable_doc.end_time:
                end_time_formatted = timetable_doc.end_time.strftime("%H:%M")
        except:
            end_time_formatted = ""

        timetable_data = {
            "name": timetable_doc.name,
            "education_stage_id": timetable_doc.education_stage_id,
            "period_priority": timetable_doc.period_priority,
            "period_type": timetable_doc.period_type,
            "period_name": timetable_doc.period_name,
            "start_time": start_time_formatted,
            "end_time": end_time_formatted,
            "campus_id": timetable_doc.campus_id
        }
        return single_item_response(timetable_data, "Timetable updated successfully")
        
    except Exception as e:
        frappe.log_error(f"Error updating timetable {timetable_id}: {str(e)}")
        return error_response(f"Error updating timetable: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_timetable():
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

        timetable_id = data.get("timetable_id")
        if not timetable_id:
            return validation_error_response("Validation failed", {"timetable_id": ["Timetable ID is required"]})

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get existing document
        try:
            timetable_doc = frappe.get_doc("SIS Timetable Column", timetable_id)

            # Check campus permission
            if timetable_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to delete this timetable")

        except frappe.DoesNotExistError:
            return not_found_response("Timetable not found")

        # Delete the document
        frappe.delete_doc("SIS Timetable Column", timetable_id)
        frappe.db.commit()

        return success_response(message="Timetable deleted successfully")

    except Exception as e:
        frappe.log_error(f"Error deleting timetable: {str(e)}")
        return error_response(f"Error deleting timetable: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_education_stages_for_timetable():
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
        frappe.log_error(f"Error fetching education stages for timetable: {str(e)}")
        return error_response(f"Error fetching education stages: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_timetable():
    """Create a new timetable column - SIMPLE VERSION"""
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
        timetable_doc = frappe.get_doc({
            "doctype": "SIS Timetable Column",
            "education_stage_id": education_stage_id,
            "period_priority": period_priority,
            "period_type": period_type,
            "period_name": period_name,
            "start_time": start_time,
            "end_time": end_time,
            "campus_id": campus_id
        })
        
        timetable_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Timetable column created successfully"))

        # Format time fields for HTML time input (HH:MM format)
        start_time_formatted = ""
        end_time_formatted = ""

        try:
            if timetable_doc.start_time:
                start_time_formatted = timetable_doc.start_time.strftime("%H:%M")
        except:
            start_time_formatted = ""

        try:
            if timetable_doc.end_time:
                end_time_formatted = timetable_doc.end_time.strftime("%H:%M")
        except:
            end_time_formatted = ""

        timetable_data = {
            "name": timetable_doc.name,
            "education_stage_id": timetable_doc.education_stage_id,
            "period_priority": timetable_doc.period_priority,
            "period_type": timetable_doc.period_type,
            "period_name": timetable_doc.period_name,
            "start_time": start_time_formatted,
            "end_time": end_time_formatted,
            "campus_id": timetable_doc.campus_id
        }
        return single_item_response(timetable_data, "Timetable created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable column: {str(e)}")
        frappe.throw(_(f"Error creating timetable column: {str(e)}"))
