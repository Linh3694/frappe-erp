# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
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
        
        return list_response(timetable_subjects, "Timetable subjects fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subjects: {str(e)}")
        return error_response(f"Error fetching timetable subjects: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_subject_by_id():
    """Get a specific timetable subject by ID"""
    try:
        # Debug: Print all request data
        print("=== DEBUG get_timetable_subject_by_id ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get subject_id from multiple sources (form data or JSON payload)
        subject_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        subject_id = frappe.form_dict.get('subject_id')
        print(f"Subject ID from form_dict: {subject_id}")

        # If not found, try from JSON payload
        if not subject_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                subject_id = json_data.get('subject_id')
                print(f"Subject ID from JSON payload: {subject_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final subject_id: {repr(subject_id)}")

        if not subject_id:
            return validation_error_response({"subject_id": ["Subject ID is required"]})
        
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
            return not_found_response("Timetable subject not found or access denied")
        
        subject_data = {
            "name": timetable_subject.name,
            "title_vn": timetable_subject.title_vn,
            "title_en": timetable_subject.title_en,
            "campus_id": timetable_subject.campus_id
        }
        return single_item_response(subject_data, "Timetable subject fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching timetable subject {subject_id}: {str(e)}")
        return error_response(f"Error fetching timetable subject: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_timetable_subject():
    """Create a new timetable subject - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_timetable_subject: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_timetable_subject: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_timetable_subject: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_timetable_subject: {data}")
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        
        # Input validation
        if not title_vn:
            frappe.throw(_("Title VN is required"))
        
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
            frappe.throw(_(f"Timetable subject with title '{title_vn}' already exists"))
        
        # Create new timetable subject
        timetable_subject_doc = frappe.get_doc({
            "doctype": "SIS Timetable Subject",
            "title_vn": title_vn,
            "title_en": title_en,
            "campus_id": campus_id
        })
        
        timetable_subject_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        subject_data = {
            "name": timetable_subject_doc.name,
            "title_vn": timetable_subject_doc.title_vn,
            "title_en": timetable_subject_doc.title_en,
            "campus_id": timetable_subject_doc.campus_id
        }
        return single_item_response(subject_data, "Timetable subject created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating timetable subject: {str(e)}")
        frappe.throw(_(f"Error creating timetable subject: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_timetable_subject():
    """Update an existing timetable subject"""
    try:
        # Debug: Print all request data
        print("=== DEBUG update_timetable_subject ===")
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

        subject_id = data.get('subject_id')
        print(f"Final subject_id: {repr(subject_id)}")

        if not subject_id:
            return {
                "success": False,
                "message": "Subject ID is required",
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
            timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_id)
            
            # Check campus permission
            if timetable_subject_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to modify this timetable subject")
                
        except frappe.DoesNotExistError:
            return not_found_response("Timetable subject not found")
        
        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')

        print(f"Updating with: title_vn={title_vn}, title_en={title_en}")

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
                return validation_error_response({"title_vn": [f"Timetable subject with title '{title_vn}' already exists"]})
            timetable_subject_doc.title_vn = title_vn
        
        if title_en and title_en != timetable_subject_doc.title_en:
            timetable_subject_doc.title_en = title_en
        
        timetable_subject_doc.save()
        frappe.db.commit()
        
        subject_data = {
            "name": timetable_subject_doc.name,
            "title_vn": timetable_subject_doc.title_vn,
            "title_en": timetable_subject_doc.title_en,
            "campus_id": timetable_subject_doc.campus_id
        }
        return single_item_response(subject_data, "Timetable subject updated successfully")
        
    except Exception as e:
        frappe.log_error(f"Error updating timetable subject {subject_id}: {str(e)}")
        return error_response(f"Error updating timetable subject: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_timetable_subject():
    """Delete a timetable subject"""
    try:
        # Debug: Print request data
        print("=== DEBUG delete_timetable_subject ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get subject_id from multiple sources (form data or JSON payload)
        subject_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        subject_id = frappe.form_dict.get('subject_id')
        print(f"Subject ID from form_dict: {subject_id}")

        # If not found, try from JSON payload
        if not subject_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                subject_id = json_data.get('subject_id')
                print(f"Subject ID from JSON payload: {subject_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final subject_id: {repr(subject_id)}")

        if not subject_id:
            return validation_error_response({"subject_id": ["Subject ID is required"]})
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            timetable_subject_doc = frappe.get_doc("SIS Timetable Subject", subject_id)
            
            # Check campus permission
            if timetable_subject_doc.campus_id != campus_id:
                return forbidden_response("Access denied: You don't have permission to delete this timetable subject")
                
        except frappe.DoesNotExistError:
            return not_found_response("Timetable subject not found")
        
        # Delete the document
        frappe.delete_doc("SIS Timetable Subject", subject_id)
        frappe.db.commit()
        
        return success_response(message="Timetable subject deleted successfully")
        
    except Exception as e:
        frappe.log_error(f"Error deleting timetable subject {subject_id}: {str(e)}")
        return error_response(f"Error deleting timetable subject: {str(e)}")
