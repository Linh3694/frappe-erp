# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, get_time
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


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
        
        return {
            "success": True,
            "data": timetables,
            "total_count": len(timetables),
            "message": "Timetables fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetables: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching timetables: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_timetable_by_id(timetable_id):
    """Get a specific timetable column by ID"""
    try:
        if not timetable_id:
            return {
                "success": False,
                "data": {},
                "message": "Timetable ID is required"
            }
        
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
            return {
                "success": False,
                "data": {},
                "message": "Timetable not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": timetable.name,
                "education_stage_id": timetable.education_stage_id,
                "period_priority": timetable.period_priority,
                "period_type": timetable.period_type,
                "period_name": timetable.period_name,
                "start_time": str(timetable.start_time),
                "end_time": str(timetable.end_time),
                "campus_id": timetable.campus_id
            },
            "message": "Timetable fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable {timetable_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching timetable: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_timetable(education_stage_id, period_priority, period_type, period_name, start_time, end_time):
    """Create a new timetable column - SIMPLE VERSION"""
    try:
        # Input validation
        if not education_stage_id or not period_priority or not period_type or not period_name or not start_time or not end_time:
            return {
                "success": False,
                "data": {},
                "message": "All fields are required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Verify education stage exists and belongs to same campus
        education_stage_exists = frappe.db.exists(
            "SIS Education Stage",
            {
                "name": education_stage_id,
                "campus_id": campus_id
            }
        )
        
        if not education_stage_exists:
            return {
                "success": False,
                "data": {},
                "message": "Selected education stage does not exist or access denied"
            }
        
        # Validate period_priority is integer
        try:
            period_priority = int(period_priority)
        except (ValueError, TypeError):
            return {
                "success": False,
                "data": {},
                "message": "Period priority must be a number"
            }
        
        # Validate period_type
        if period_type not in ['study', 'non-study']:
            return {
                "success": False,
                "data": {},
                "message": "Period type must be 'study' or 'non-study'"
            }
        
        # Validate time format
        try:
            start_time_obj = get_time(start_time)
            end_time_obj = get_time(end_time)
            
            if start_time_obj >= end_time_obj:
                return {
                    "success": False,
                    "data": {},
                    "message": "Start time must be before end time"
                }
        except Exception:
            return {
                "success": False,
                "data": {},
                "message": "Invalid time format"
            }
        
        # Check if timetable with same education_stage_id and period_priority already exists
        existing = frappe.db.exists(
            "SIS Timetable Column",
            {
                "education_stage_id": education_stage_id,
                "period_priority": period_priority,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"Timetable with priority '{period_priority}' already exists for this education stage"
            }
        
        # Create new timetable
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
        
        # Return the created data
        return {
            "success": True,
            "data": {
                "name": timetable_doc.name,
                "education_stage_id": timetable_doc.education_stage_id,
                "period_priority": timetable_doc.period_priority,
                "period_type": timetable_doc.period_type,
                "period_name": timetable_doc.period_name,
                "start_time": str(timetable_doc.start_time),
                "end_time": str(timetable_doc.end_time),
                "campus_id": timetable_doc.campus_id
            },
            "message": "Timetable created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating timetable: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def update_timetable(timetable_id, education_stage_id=None, period_priority=None, period_type=None, period_name=None, start_time=None, end_time=None):
    """Update an existing timetable column"""
    try:
        if not timetable_id:
            return {
                "success": False,
                "data": {},
                "message": "Timetable ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            timetable_doc = frappe.get_doc("SIS Timetable Column", timetable_id)
            
            # Check campus permission
            if timetable_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this timetable"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Timetable not found"
            }
        
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
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected education stage does not exist or access denied"
                }
            
            timetable_doc.education_stage_id = education_stage_id
        
        if period_priority is not None and int(period_priority) != timetable_doc.period_priority:
            # Validate period_priority is integer
            try:
                period_priority = int(period_priority)
            except (ValueError, TypeError):
                return {
                    "success": False,
                    "data": {},
                    "message": "Period priority must be a number"
                }
            
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
                return {
                    "success": False,
                    "data": {},
                    "message": f"Timetable with priority '{period_priority}' already exists for this education stage"
                }
            
            timetable_doc.period_priority = period_priority
        
        if period_type and period_type != timetable_doc.period_type:
            if period_type not in ['study', 'non-study']:
                return {
                    "success": False,
                    "data": {},
                    "message": "Period type must be 'study' or 'non-study'"
                }
            timetable_doc.period_type = period_type
        
        if period_name and period_name != timetable_doc.period_name:
            timetable_doc.period_name = period_name
        
        if start_time and str(start_time) != str(timetable_doc.start_time):
            try:
                start_time_obj = get_time(start_time)
                timetable_doc.start_time = start_time
            except Exception:
                return {
                    "success": False,
                    "data": {},
                    "message": "Invalid start time format"
                }
        
        if end_time and str(end_time) != str(timetable_doc.end_time):
            try:
                end_time_obj = get_time(end_time)
                timetable_doc.end_time = end_time
            except Exception:
                return {
                    "success": False,
                    "data": {},
                    "message": "Invalid end time format"
                }
        
        # Validate time range after updates
        if timetable_doc.start_time >= timetable_doc.end_time:
            return {
                "success": False,
                "data": {},
                "message": "Start time must be before end time"
            }
        
        timetable_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": timetable_doc.name,
                "education_stage_id": timetable_doc.education_stage_id,
                "period_priority": timetable_doc.period_priority,
                "period_type": timetable_doc.period_type,
                "period_name": timetable_doc.period_name,
                "start_time": str(timetable_doc.start_time),
                "end_time": str(timetable_doc.end_time),
                "campus_id": timetable_doc.campus_id
            },
            "message": "Timetable updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating timetable {timetable_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating timetable: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_timetable(timetable_id):
    """Delete a timetable column"""
    try:
        if not timetable_id:
            return {
                "success": False,
                "data": {},
                "message": "Timetable ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            timetable_doc = frappe.get_doc("SIS Timetable Column", timetable_id)
            
            # Check campus permission
            if timetable_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this timetable"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Timetable not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Timetable Column", timetable_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Timetable deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting timetable {timetable_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting timetable: {str(e)}"
        }


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
        
        return {
            "success": True,
            "data": education_stages,
            "message": "Education stages fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages for timetable: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education stages: {str(e)}"
        }
