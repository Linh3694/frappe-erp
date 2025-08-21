# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_timetable_subjects():
    """Get all timetable subjects with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        timetable_subjects = frappe.get_all(
            "SIS Timetable Subject",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": timetable_subjects,
            "total_count": len(timetable_subjects),
            "message": "Timetable subjects fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subjects: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching timetable subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_timetable_subject_by_id(subject_id):
    """Get a specific timetable subject by ID"""
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
        
        timetable_subject = frappe.get_doc("SIS Timetable Subject", filters)
        
        if not timetable_subject:
            return {
                "success": False,
                "data": {},
                "message": "Timetable subject not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": timetable_subject.name,
                "title_vn": timetable_subject.title_vn,
                "title_en": timetable_subject.title_en,
                "campus_id": timetable_subject.campus_id
            },
            "message": "Timetable subject fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching timetable subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_timetable_subject(title_vn, title_en):
    """Create a new timetable subject - SIMPLE VERSION"""
    try:
        # Input validation
        if not title_vn:
            return {
                "success": False,
                "data": {},
                "message": "Title VN is required"
            }
        
        # Get campus from user context - simplified
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            frappe.logger().error(f"Error getting campus context: {str(e)}")
            campus_id = None
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if timetable subject title already exists for this campus
        existing = frappe.db.exists(
            "SIS Timetable Subject",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"Timetable subject with title '{title_vn}' already exists"
            }
        
        # Create new timetable subject
        timetable_subject_doc = frappe.get_doc({
            "doctype": "SIS Timetable Subject",
            "title_vn": title_vn,
            "title_en": title_en,
            "campus_id": campus_id
        })
        
        timetable_subject_doc.insert()
        frappe.db.commit()
        
        # Return the created data
        return {
            "success": True,
            "data": {
                "name": timetable_subject_doc.name,
                "title_vn": timetable_subject_doc.title_vn,
                "title_en": timetable_subject_doc.title_en,
                "campus_id": timetable_subject_doc.campus_id
            },
            "message": "Timetable subject created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable subject: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating timetable subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def update_timetable_subject(subject_id, title_vn=None, title_en=None):
    """Update an existing timetable subject"""
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
            timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_id)
            
            # Check campus permission
            if timetable_subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this timetable subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Timetable subject not found"
            }
        
        # Update fields if provided
        if title_vn and title_vn != timetable_subject_doc.title_vn:
            # Check for duplicate timetable subject title
            existing = frappe.db.exists(
                "SIS Timetable Subject",
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "name": ["!=", subject_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Timetable subject with title '{title_vn}' already exists"
                }
            timetable_subject_doc.title_vn = title_vn
        
        if title_en and title_en != timetable_subject_doc.title_en:
            timetable_subject_doc.title_en = title_en
        
        timetable_subject_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": timetable_subject_doc.name,
                "title_vn": timetable_subject_doc.title_vn,
                "title_en": timetable_subject_doc.title_en,
                "campus_id": timetable_subject_doc.campus_id
            },
            "message": "Timetable subject updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating timetable subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating timetable subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_timetable_subject(subject_id):
    """Delete a timetable subject"""
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
            timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_id)
            
            # Check campus permission
            if timetable_subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this timetable subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Timetable subject not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Timetable Subject", subject_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Timetable subject deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting timetable subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting timetable subject: {str(e)}"
        }
