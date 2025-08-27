# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_education_stages():
    """Get all education stages with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        education_stages = frappe.get_all(
            "SIS Education Stage",
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
            "data": education_stages,
            "total_count": len(education_stages),
            "message": "Education stages fetched successfully"
        }
        
    except Exception as e:
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching education stages: {str(e)}",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def get_education_stage_by_id():
    """Get education stage details by ID"""
    try:
        # Try to get stage_id from different sources based on request method
        stage_id = None

        print("=== DEBUG get_education_stage_by_id ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Request args: {dict(frappe.request.args) if hasattr(frappe.request, 'args') else 'No args'}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")
        print(f"Request query_string: {frappe.request.query_string if hasattr(frappe.request, 'query_string') else 'No query_string'}")

        if frappe.request.method == 'GET':
            # For GET requests, stage_id comes from query parameters
            stage_id = frappe.form_dict.get('stage_id')
            print(f"GET - stage_id from form_dict: {stage_id}")

            # If not found in form_dict, try request.args (alternative for query params)
            if not stage_id and hasattr(frappe.request, 'args'):
                stage_id = frappe.request.args.get('stage_id')
                print(f"GET - stage_id from request.args: {stage_id}")

            # Also try direct query string parsing
            if not stage_id and hasattr(frappe.request, 'query_string'):
                from urllib.parse import parse_qs
                query_params = parse_qs(frappe.request.query_string.decode('utf-8'))
                stage_id = query_params.get('stage_id', [None])[0]
                print(f"GET - stage_id from query_string: {stage_id}")
        else:
            # For POST/PUT requests, try multiple approaches
            import json

            # Approach 1: Try frappe.request.data as JSON string
            if frappe.request.data and isinstance(frappe.request.data, str):
                try:
                    json_data = json.loads(frappe.request.data)
                    stage_id = json_data.get('stage_id')
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

            # Approach 2: If not found, try frappe.request.json
            if not stage_id and hasattr(frappe.request, 'json') and frappe.request.json:
                try:
                    stage_id = frappe.request.json.get('stage_id')
                except (TypeError, AttributeError):
                    pass

            # Approach 3: Try form data as fallback
            if not stage_id:
                stage_id = frappe.form_dict.get('stage_id')

        print(f"Final stage_id: {stage_id}")

        # Always return debug info for troubleshooting
        if not stage_id:
            return {
                "success": False,
                "message": "Stage ID is required",
                "debug": {
                    "request_method": frappe.request.method,
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "request_data_type": type(frappe.request.data).__name__,
                    "has_json_attr": hasattr(frappe.request, 'json'),
                    "json_content": frappe.request.json if hasattr(frappe.request, 'json') and frappe.request.json else None,
                    "stage_id_value": repr(stage_id),
                    "stage_id_type": type(stage_id).__name__
                }
            }

        # If stage_id is found, also include debug info
        print(f"=== SUCCESS DEBUG ===")
        print(f"Found stage_id: {stage_id}")
        print(f"Form dict: {dict(frappe.form_dict)}")

        stage = frappe.get_doc("SIS Education Stage", stage_id)

        if not stage:
            return {
                "success": False,
                "message": "Education stage not found"
            }

        stage_data = stage.as_dict()

        return {
            "success": True,
            "data": {
                "education_stage": stage_data
            },
            "message": "Education stage fetched successfully"
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education stage not found"
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Error fetching education stage",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def create_education_stage():
    """Create a new education stage - SIMPLE VERSION"""
    try:
        # Get data from form_dict (FormData will be available here)
        data = frappe.local.form_dict
        
        # Validate required fields
        required_fields = ["title_vn", "title_en", "short_title"]
        for field in required_fields:
            if not data.get(field):
                frappe.throw(_(f"Field '{field}' is required"))
        
        # Get campus from user roles or form data
        campus_id = data.get("campus_id")
        if not campus_id:
            campus_id = get_current_campus_from_context()
            if not campus_id:
                # Fallback to default if no campus found
                campus_id = "campus-1"
        
        # Check if short_title already exists for this campus
        existing_stage = frappe.db.exists("SIS Education Stage", {
            "short_title": data.get("short_title"),
            "campus_id": campus_id
        })
        
        if existing_stage:
            frappe.throw(_("Ký hiệu đã tồn tại cho trường học này"))
        
        # Create new education stage
        stage_doc = frappe.get_doc({
            "doctype": "SIS Education Stage",
            "title_vn": data.get("title_vn"),
            "title_en": data.get("title_en"),
            "short_title": data.get("short_title"),
            "campus_id": campus_id
        })
        
        stage_doc.insert(ignore_permissions=True)

        return {
            "success": True,
            "data": stage_doc.as_dict(),
            "message": "Education stage created successfully"
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error creating education stage: {str(e)}",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def update_education_stage():
    """Update an existing education stage"""
    try:
        # Debug: Print all available request data
        print("=== DEBUG update_education_stage ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Request args: {dict(frappe.request.args) if hasattr(frappe.request, 'args') else 'No args'}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")
        print(f"Request data type: {type(frappe.request.data)}")

        # Get stage_id from multiple sources (form data or JSON)
        stage_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        stage_id = frappe.form_dict.get('stage_id')
        print(f"Stage ID from form_dict: {stage_id}")

        # If not found, try from JSON payload
        if not stage_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                stage_id = json_data.get('stage_id')
                print(f"Stage ID from JSON payload: {stage_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final extracted stage_id: {stage_id}")

        if not stage_id:
            return {
                "success": False,
                "message": "Stage ID is required",
                "debug": {
                    "request_method": frappe.request.method,
                    "content_type": frappe.request.headers.get('Content-Type'),
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "stage_id_value": repr(stage_id),
                    "stage_id_type": type(stage_id).__name__
                }
            }

        # Get data from request (support both form data and JSON)
        data = {}

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # If JSON payload exists, merge it (JSON takes precedence)
        if frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                data.update(json_data)
                print(f"Merged JSON data: {json_data}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON data merge failed: {e}")

        print(f"Final data to update: {data}")

        # Get existing stage
        stage_doc = frappe.get_doc("SIS Education Stage", stage_id)
        
        if not stage_doc:
            return {
                "success": False,
                "message": "Education stage not found"
            }
        
        # Check if short_title already exists for this campus (excluding current stage)
        if data.get("short_title") and data.get("short_title") != stage_doc.short_title:
            existing_stage = frappe.db.exists("SIS Education Stage", {
                "short_title": data.get("short_title"),
                "campus_id": stage_doc.campus_id,
                "name": ["!=", stage_id]
            })
            
            if existing_stage:
                return {
                    "success": False,
                    "message": "Ký hiệu đã tồn tại cho trường học này"
                }
        
        # Update fields
        updatable_fields = ["title_vn", "title_en", "short_title"]
        for field in updatable_fields:
            if field in data:
                setattr(stage_doc, field, data.get(field))
        
        stage_doc.save(ignore_permissions=True)
        
        return {
            "success": True,
            "data": {
                "education_stage": stage_doc.as_dict()
            },
            "message": "Education stage updated successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education stage not found"
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Error updating education stage",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def delete_education_stage():
    """Delete an education stage"""
    try:
        # Debug: Print request data
        print("=== DEBUG delete_education_stage ===")
        print(f"Request method: {frappe.request.method}")
        print(f"Content-Type: {frappe.request.headers.get('Content-Type', 'Not set')}")
        print(f"Form dict: {dict(frappe.form_dict)}")
        print(f"Request data: {frappe.request.data}")

        # Get stage_id from multiple sources (form data or JSON)
        stage_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        stage_id = frappe.form_dict.get('stage_id')
        print(f"Stage ID from form_dict: {stage_id}")

        # If not found, try from JSON payload
        if not stage_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                stage_id = json_data.get('stage_id')
                print(f"Stage ID from JSON payload: {stage_id}")
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                print(f"JSON parsing failed: {e}")

        print(f"Final extracted stage_id: {stage_id}")

        if not stage_id:
            return {
                "success": False,
                "message": "Stage ID is required",
                "debug": {
                    "form_dict": dict(frappe.form_dict),
                    "request_data": str(frappe.request.data)[:500] if frappe.request.data else None,
                    "stage_id_value": repr(stage_id)
                }
            }

        # Check if stage exists
        stage_doc = frappe.get_doc("SIS Education Stage", stage_id)
        
        if not stage_doc:
            return {
                "success": False,
                "message": "Education stage not found"
            }
        
        # TODO: Add validation to check if stage is being used by other documents
        # before deleting
        
        # Delete the stage
        frappe.delete_doc("SIS Education Stage", stage_id, ignore_permissions=True)
        
        return {
            "success": True,
            "message": "Education stage deleted successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Education stage not found"
        }
    except Exception as e:
        return {
            "success": False,
            "message": "Error deleting education stage",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def check_short_title_availability():
    """Check if a short title is available for the current campus"""
    try:
        # Get parameters from form data
        short_title = frappe.form_dict.get('short_title')
        stage_id = frappe.form_dict.get('stage_id')

        if not short_title:
            return {
                "success": False,
                "message": "Short title is required"
            }
        
        # Get current user's campus from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            return {
                "success": False,
                "message": "User campus not found in roles"
            }
        
        filters = {
            "short_title": short_title,
            "campus_id": campus_id
        }
        
        # Exclude current stage if updating
        if stage_id:
            filters["name"] = ["!=", stage_id]
        
        existing_stage = frappe.db.exists("SIS Education Stage", filters)
        
        return {
            "success": True,
            "data": {
                "is_available": not bool(existing_stage),
                "short_title": short_title
            },
            "message": "Short title availability checked"
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": "Error checking short title availability",
            "error": str(e)
        }
