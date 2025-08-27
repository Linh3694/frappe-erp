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
def get_academic_program_by_id():
    """Get a specific academic program by ID"""
    try:
        # Debug: Print all request data
        print("=== DEBUG get_academic_program_by_id ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get program_id from multiple sources (form data or JSON payload)
        program_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        program_id = frappe.form_dict.get('program_id')
        print(f"Program ID from form_dict: {program_id}")

        # If not found, try from JSON payload
        if not program_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                program_id = json_data.get('program_id')
                print(f"Program ID from JSON payload: {program_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final program_id: {repr(program_id)}")

        if not program_id:
            return {
                "success": False,
                "message": "Program ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None
                }
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
def create_academic_program():
    """Create a new academic program - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_academic_program: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_academic_program: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_academic_program: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_academic_program: {data}")
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        
        # Input validation
        if not title_vn or not short_title:
            frappe.throw(_("Title VN and short title are required"))
        
        # Get campus from user context - simplified
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            frappe.logger().error(f"Error getting campus context: {str(e)}")
            campus_id = None
        
        if not campus_id:
            # Get first available campus instead of hardcoded campus-1
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            if first_campus:
                campus_id = first_campus[0].name
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using first available: {campus_id}")
            else:
                # Create default campus if none exists
                default_campus = frappe.get_doc({
                    "doctype": "SIS Campus",
                    "title_vn": "Trường Mặc Định", 
                    "title_en": "Default Campus"
                })
                default_campus.insert()
                frappe.db.commit()
                campus_id = default_campus.name
                frappe.logger().info(f"Created default campus: {campus_id}")
        
        # Check if program title already exists for this campus
        existing = frappe.db.exists(
            "SIS Academic Program",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Academic program with title '{title_vn}' already exists"))
            
        # Check if short title already exists for this campus
        existing_code = frappe.db.exists(
            "SIS Academic Program",
            {
                "short_title": short_title,
                "campus_id": campus_id
            }
        )
        
        if existing_code:
            frappe.throw(_(f"Academic program with short title '{short_title}' already exists"))
        
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
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Academic program created successfully"))
        return {
            "name": academic_program_doc.name,
            "title_vn": academic_program_doc.title_vn,
            "title_en": academic_program_doc.title_en,
            "short_title": academic_program_doc.short_title,
            "campus_id": academic_program_doc.campus_id
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating academic program: {str(e)}")
        frappe.throw(_(f"Error creating academic program: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_academic_program():
    """Update an existing academic program"""
    try:
        # Debug: Print all request data
        print("=== DEBUG update_academic_program ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get data from multiple sources (form data or JSON payload)
        data = {}

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # If JSON payload exists, merge it (JSON takes precedence)
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                data.update(json_data)
                print(f"Merged JSON data: {json_data}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON data merge failed: {e}")

        program_id = data.get('program_id')
        print(f"Final program_id: {repr(program_id)}")

        if not program_id:
            return {
                "success": False,
                "message": "Program ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "final_data": data
                }
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
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        short_title = data.get('short_title')

        print(f"Updating with: title_vn={title_vn}, title_en={title_en}, short_title={short_title}")

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
def delete_academic_program():
    """Delete an academic program"""
    try:
        # Debug: Print request data
        print("=== DEBUG delete_academic_program ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get program_id from multiple sources (form data or JSON payload)
        program_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        program_id = frappe.form_dict.get('program_id')
        print(f"Program ID from form_dict: {program_id}")

        # If not found, try from JSON payload
        if not program_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                program_id = json_data.get('program_id')
                print(f"Program ID from JSON payload: {program_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final program_id: {repr(program_id)}")

        if not program_id:
            return {
                "success": False,
                "message": "Program ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None
                }
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
def check_short_title_availability():
    """Check if short title is available"""
    try:
        # Debug: Print request data
        print("=== DEBUG check_short_title_availability ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get parameters from multiple sources (form data or JSON payload)
        short_title = None
        program_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        short_title = frappe.form_dict.get('short_title')
        program_id = frappe.form_dict.get('program_id')
        print(f"Parameters from form_dict: short_title={short_title}, program_id={program_id}")

        # If not found, try from JSON payload
        if not short_title and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                short_title = json_data.get('short_title')
                program_id = json_data.get('program_id')
                print(f"Parameters from JSON payload: short_title={short_title}, program_id={program_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        if not short_title:
            return {
                "success": False,
                "is_available": False,
                "short_title": short_title,
                "message": "Short title is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None
                }
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
