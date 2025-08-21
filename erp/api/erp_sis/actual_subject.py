# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_actual_subjects():
    """Get all actual subjects with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        actual_subjects = frappe.get_all(
            "SIS Actual Subject",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "curriculum_id",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": actual_subjects,
            "total_count": len(actual_subjects),
            "message": "Actual subjects fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subjects: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching actual subjects: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_actual_subject_by_id(subject_id):
    """Get a specific actual subject by ID"""
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
        
        actual_subject = frappe.get_doc("SIS Actual Subject", filters)
        
        if not actual_subject:
            return {
                "success": False,
                "data": {},
                "message": "Actual subject not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": actual_subject.name,
                "title_vn": actual_subject.title_vn,
                "title_en": actual_subject.title_en,
                "curriculum_id": actual_subject.curriculum_id,
                "campus_id": actual_subject.campus_id
            },
            "message": "Actual subject fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching actual subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching actual subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_actual_subject():
    """Create a new actual subject - SIMPLE VERSION"""
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
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        curriculum_id = data.get("curriculum_id")
        
        # Input validation
        if not title_vn or not curriculum_id:
            frappe.throw(_("Title VN and Curriculum are required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if actual subject title already exists for this campus
        existing = frappe.db.exists(
            "SIS Actual Subject",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Actual subject with title '{title_vn}' already exists"))
        
        # Verify curriculum exists and belongs to same campus
        curriculum_exists = frappe.db.exists(
            "SIS Curriculum",
            {
                "name": curriculum_id,
                "campus_id": campus_id
            }
        )
        
        if not curriculum_exists:
            return {
                "success": False,
                "data": {},
                "message": "Selected curriculum does not exist or access denied"
            }
        
        # Create new actual subject
        actual_subject_doc = frappe.get_doc({
            "doctype": "SIS Actual Subject",
            "title_vn": title_vn,
            "title_en": title_en,
            "curriculum_id": curriculum_id,
            "campus_id": campus_id
        })
        
        actual_subject_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Actual subject created successfully"))
        return {
            "name": actual_subject_doc.name,
            "title_vn": actual_subject_doc.title_vn,
            "title_en": actual_subject_doc.title_en,
            "curriculum_id": actual_subject_doc.curriculum_id,
            "campus_id": actual_subject_doc.campus_id
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating actual subject: {str(e)}")
        frappe.throw(_(f"Error creating actual subject: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_actual_subject(subject_id, title_vn=None, title_en=None, curriculum_id=None):
    """Update an existing actual subject"""
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
            actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject_id)
            
            # Check campus permission
            if actual_subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this actual subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Actual subject not found"
            }
        
        # Update fields if provided
        if title_vn and title_vn != actual_subject_doc.title_vn:
            # Check for duplicate actual subject title
            existing = frappe.db.exists(
                "SIS Actual Subject",
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
                    "message": f"Actual subject with title '{title_vn}' already exists"
                }
            actual_subject_doc.title_vn = title_vn
        
        if title_en and title_en != actual_subject_doc.title_en:
            actual_subject_doc.title_en = title_en
            
        if curriculum_id and curriculum_id != actual_subject_doc.curriculum_id:
            # Verify curriculum exists and belongs to same campus
            curriculum_exists = frappe.db.exists(
                "SIS Curriculum",
                {
                    "name": curriculum_id,
                    "campus_id": campus_id
                }
            )
            
            if not curriculum_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected curriculum does not exist or access denied"
                }
            actual_subject_doc.curriculum_id = curriculum_id
        
        actual_subject_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": actual_subject_doc.name,
                "title_vn": actual_subject_doc.title_vn,
                "title_en": actual_subject_doc.title_en,
                "curriculum_id": actual_subject_doc.curriculum_id,
                "campus_id": actual_subject_doc.campus_id
            },
            "message": "Actual subject updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating actual subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating actual subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_actual_subject(subject_id):
    """Delete an actual subject"""
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
            actual_subject_doc = frappe.get_doc("SIS Actual Subject", subject_id)
            
            # Check campus permission
            if actual_subject_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this actual subject"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Actual subject not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Actual Subject", subject_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Actual subject deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting actual subject {subject_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting actual subject: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_curriculums_for_selection():
    """Get curriculums for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        curriculums = frappe.get_all(
            "SIS Curriculum",
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
            "data": curriculums,
            "message": "Curriculums fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching curriculums for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching curriculums: {str(e)}"
        }
