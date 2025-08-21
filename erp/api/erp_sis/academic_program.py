# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_academic_programs():
    """Get all academic programs with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        academic_programs = frappe.get_all(
            "SIS Academic Program",
            fields=[
                "name",
                "title_vn",
                "title_en", 
                "short_title",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return {
            "success": True,
            "data": academic_programs,
            "total_count": len(academic_programs),
            "message": "Academic programs fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching academic programs: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching academic programs: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_academic_program_by_id(program_id):
    """Get a specific academic program by ID"""
    try:
        if not program_id:
            return {
                "success": False,
                "data": {},
                "message": "Program ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": program_id,
            "campus_id": campus_id
        }
        
        academic_program = frappe.get_doc("SIS Academic Program", filters)
        
        if not academic_program:
            return {
                "success": False,
                "data": {},
                "message": "Academic program not found or access denied"
            }
        
        return {
            "success": True,
                "data": {
                    "name": academic_program.name,
                    "title_vn": academic_program.title_vn,
                    "title_en": academic_program.title_en,
                    "short_title": academic_program.short_title,
                    "campus_id": academic_program.campus_id
                },
                "message": "Academic program fetched successfully"
            }
        
    except Exception as e:
        frappe.log_error(f"Error fetching academic program {program_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching academic program: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_academic_program(title_vn, title_en, short_title):
    """Create a new academic program - SIMPLE VERSION"""
    try:
        # Input validation
        if not title_vn or not short_title:
            return {
                "success": False,
                "data": {},
                "message": "Title VN and short title are required"
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
        
        # Check if program title already exists for this campus
        existing = frappe.db.exists(
            "SIS Academic Program",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"Academic program with title '{title_vn}' already exists"
            }
            
        # Check if short title already exists for this campus
        existing_code = frappe.db.exists(
            "SIS Academic Program",
            {
                "short_title": short_title,
                "campus_id": campus_id
            }
        )
        
        if existing_code:
            return {
                "success": False,
                "data": {},
                "message": f"Academic program with short title '{short_title}' already exists"
            }
        
        # Create new academic program - with detailed debugging
        frappe.logger().info(f"Creating SIS Academic Program with data: title_vn={title_vn}, title_en={title_en}, short_title={short_title}, campus_id={campus_id}")
        
        try:
            academic_program_doc = frappe.get_doc({
                "doctype": "SIS Academic Program",
                "title_vn": title_vn,
                "title_en": title_en or "",  # Provide default empty string
                "short_title": short_title,
                "campus_id": campus_id
            })
            
            frappe.logger().info(f"Academic program doc created: {academic_program_doc}")
            
            academic_program_doc.insert()
            frappe.logger().info("Academic program doc inserted successfully")
            
            frappe.db.commit()
            frappe.logger().info("Database committed successfully")
            
        except Exception as doc_error:
            frappe.logger().error(f"Error creating/inserting academic program doc: {str(doc_error)}")
            raise doc_error
        
        # Return the created data
        return {
            "success": True,
            "data": {
                "name": academic_program_doc.name,
                "title_vn": academic_program_doc.title_vn,
                "title_en": academic_program_doc.title_en,
                "short_title": academic_program_doc.short_title,
                "campus_id": academic_program_doc.campus_id
            },
            "message": "Academic program created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating academic program: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating academic program: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def update_academic_program(program_id, title_vn=None, title_en=None, short_title=None):
    """Update an existing academic program"""
    try:
        if not program_id:
            return {
                "success": False,
                "data": {},
                "message": "Program ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            academic_program_doc = frappe.get_doc("SIS Academic Program", program_id)
            
            # Check campus permission
            if academic_program_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this academic program"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Academic program not found"
            }
        
        # Update fields if provided
        if title_vn and title_vn != academic_program_doc.title_vn:
            # Check for duplicate program title
            existing = frappe.db.exists(
                "SIS Academic Program",
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "name": ["!=", program_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Academic program with title '{title_vn}' already exists"
                }
            academic_program_doc.title_vn = title_vn
        
        if title_en and title_en != academic_program_doc.title_en:
            academic_program_doc.title_en = title_en
            
        if short_title and short_title != academic_program_doc.short_title:
            # Check for duplicate short title
            existing_code = frappe.db.exists(
                "SIS Academic Program",
                {
                    "short_title": short_title,
                    "campus_id": campus_id,
                    "name": ["!=", program_id]
                }
            )
            if existing_code:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Academic program with short title '{short_title}' already exists"
                }
            academic_program_doc.short_title = short_title
        
        academic_program_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": academic_program_doc.name,
                "title_vn": academic_program_doc.title_vn,
                "title_en": academic_program_doc.title_en,
                "short_title": academic_program_doc.short_title,
                "campus_id": academic_program_doc.campus_id
            },
            "message": "Academic program updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating academic program {program_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating academic program: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_academic_program(program_id):
    """Delete an academic program"""
    try:
        if not program_id:
            return {
                "success": False,
                "data": {},
                "message": "Program ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            academic_program_doc = frappe.get_doc("SIS Academic Program", program_id)
            
            # Check campus permission
            if academic_program_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this academic program"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Academic program not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS Academic Program", program_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Academic program deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting academic program {program_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting academic program: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def check_short_title_availability(short_title, program_id=None):
    """Check if short title is available"""
    try:
        if not short_title:
            return {
                "success": False,
                "is_available": False,
                "short_title": short_title,
                "message": "Short title is required"
            }
        
        # Get campus from user context  
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {
            "short_title": short_title,
            "campus_id": campus_id
        }
        
        # If updating existing program, exclude it from check
        if program_id:
            filters["name"] = ["!=", program_id]
        
        existing = frappe.db.exists("SIS Academic Program", filters)
        
        is_available = not bool(existing)
        
        return {
            "success": True,
            "is_available": is_available,
            "short_title": short_title,
            "message": "Available" if is_available else "Short title already exists"
        }
        
    except Exception as e:
        frappe.log_error(f"Error checking short title availability: {str(e)}")
        return {
            "success": False,
            "is_available": False,
            "short_title": short_title,
            "message": f"Error checking availability: {str(e)}"
        }
