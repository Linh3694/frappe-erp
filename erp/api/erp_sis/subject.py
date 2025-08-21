# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_subjects():
    """Get all subjects with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        subjects = frappe.get_all(
            "SIS Subject",
            fields=[
                "name",
                "title",
                "education_stage",
                "timetable_subject_id",
                "actual_subject_id",
                "room_id",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title asc"
        )
        
        return {
            "success": True,
            "data": subjects,
            "total_count": len(subjects),
            "message": "Subjects fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching subjects: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_subject_by_id(subject_id):
    """Get a specific subject by ID"""
    try:
        if not subject_id:
            return {
                "success": False,
                "data": {},
                "message": "Subject ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": subject_id,
            "campus_id": campus_id
        }
        
        subject = frappe.get_doc("SIS Subject", filters)
        
        if not subject:
            return {
                "success": False,
                "data": {},
                "message": "Subject not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": subject.name,
                "title": subject.title,
                "education_stage": subject.education_stage,
                "timetable_subject_id": subject.timetable_subject_id,
                "actual_subject_id": subject.actual_subject_id,
                "room_id": subject.room_id,
                "campus_id": subject.campus_id
            },
            "message": "Subject fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_subject(title, education_stage, timetable_subject_id=None, actual_subject_id=None, room_id=None):
    """Create a new subject - SIMPLE VERSION"""
    try:
        # Input validation
        if not title or not education_stage:
            return {
                "success": False,
                "data": {},
                "message": "Title and education stage are required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if subject title already exists for this campus
        existing = frappe.db.exists(
            "SIS Subject",
            {
                "title": title,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"Subject with title '{title}' already exists"
            }
        
        # Verify education stage exists and belongs to same campus
        education_stage_exists = frappe.db.exists(
            "SIS Education Stage",
            {
                "name": education_stage,
                "campus_id": campus_id
            }
        )
        
        if not education_stage_exists:
            return {
                "success": False,
                "data": {},
                "message": "Selected education stage does not exist or access denied"
            }
        
        # Create new subject
        subject_doc = frappe.get_doc({
            "doctype": "SIS Subject",
            "title": title,
            "education_stage": education_stage,
            "timetable_subject_id": timetable_subject_id,
            "actual_subject_id": actual_subject_id,
            "room_id": room_id,
            "campus_id": campus_id
        })
        
        subject_doc.insert()
        frappe.db.commit()
        
        # Return the created data
        return {
            "success": True,
            "data": {
                "name": subject_doc.name,
                "title": subject_doc.title,
                "education_stage": subject_doc.education_stage,
                "timetable_subject_id": subject_doc.timetable_subject_id,
                "actual_subject_id": subject_doc.actual_subject_id,
                "room_id": subject_doc.room_id,
                "campus_id": subject_doc.campus_id
            },
            "message": "Subject created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating subject: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def update_subject(subject_id, title=None, education_stage=None, timetable_subject_id=None, actual_subject_id=None, room_id=None):
    """Update an existing subject"""
    try:
        if not subject_id:
            return {
                "success": False,
                "data": {},
                "message": "Subject ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            subject_doc = frappe.get_doc("SIS Subject", subject_id)
            
            # Check campus permission
            if subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Subject not found"
            }
        
        # Update fields if provided
        if title and title != subject_doc.title:
            # Check for duplicate subject title
            existing = frappe.db.exists(
                "SIS Subject",
                {
                    "title": title,
                    "campus_id": campus_id,
                    "name": ["!=", subject_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Subject with title '{title}' already exists"
                }
            subject_doc.title = title
        
        if education_stage and education_stage != subject_doc.education_stage:
            # Verify education stage exists and belongs to same campus
            education_stage_exists = frappe.db.exists(
                "SIS Education Stage",
                {
                    "name": education_stage,
                    "campus_id": campus_id
                }
            )
            
            if not education_stage_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected education stage does not exist or access denied"
                }
            subject_doc.education_stage = education_stage
            
        if timetable_subject_id is not None and timetable_subject_id != subject_doc.timetable_subject_id:
            subject_doc.timetable_subject_id = timetable_subject_id
            
        if actual_subject_id is not None and actual_subject_id != subject_doc.actual_subject_id:
            subject_doc.actual_subject_id = actual_subject_id
            
        if room_id is not None and room_id != subject_doc.room_id:
            subject_doc.room_id = room_id
        
        subject_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": subject_doc.name,
                "title": subject_doc.title,
                "education_stage": subject_doc.education_stage,
                "timetable_subject_id": subject_doc.timetable_subject_id,
                "actual_subject_id": subject_doc.actual_subject_id,
                "room_id": subject_doc.room_id,
                "campus_id": subject_doc.campus_id
            },
            "message": "Subject updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_subject(subject_id):
    """Delete a subject"""
    try:
        if not subject_id:
            return {
                "success": False,
                "data": {},
                "message": "Subject ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            subject_doc = frappe.get_doc("SIS Subject", subject_id)
            
            # Check campus permission
            if subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Subject not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Subject", subject_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Subject deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_education_stages_for_selection():
    """Get education stages for dropdown selection"""
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
        frappe.log_error(f"Error fetching education stages for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education stages: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_timetable_subjects_for_selection():
    """Get timetable subjects for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        timetable_subjects = frappe.get_all(
            "SIS Timetable Subject",
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
            "data": timetable_subjects,
            "message": "Timetable subjects fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subjects for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching timetable subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_actual_subjects_for_selection():
    """Get actual subjects for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get buildings for this campus to filter rooms
        building_filters = {"campus_id": campus_id}
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=["name"],
            filters=building_filters
        )
        
        building_ids = [b.name for b in buildings]
        
        if not building_ids:
            return {
                "success": True,
                "data": [],
                "message": "No buildings found for this campus"
            }
        
        actual_subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=[
                "name",
                "title_vn",
                "title_en"
            ],
            filters={"curriculum_id": ["!=", ""]},  # Ensure it has a curriculum
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": actual_subjects,
            "message": "Actual subjects fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subjects for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching actual subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_rooms_for_selection():
    """Get rooms for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get buildings for this campus to filter rooms
        building_filters = {"campus_id": campus_id}
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=["name"],
            filters=building_filters
        )
        
        building_ids = [b.name for b in buildings]
        
        if not building_ids:
            return {
                "success": True,
                "data": [],
                "message": "No buildings found for this campus"
            }
        
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title"
            ],
            filters={"building_id": ["in", building_ids]},
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": rooms,
            "message": "Rooms fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching rooms for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching rooms: {str(e)}"
        }
