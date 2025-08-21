# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_buildings():
    """Get all buildings with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        buildings = frappe.get_all(
            "ERP Administrative Building",
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
            "data": buildings,
            "total_count": len(buildings),
            "message": "Buildings fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching buildings: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching buildings: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_building_by_id(building_id):
    """Get a specific building by ID"""
    try:
        if not building_id:
            return {
                "success": False,
                "data": {},
                "message": "Building ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": building_id,
            "campus_id": campus_id
        }
        
        building = frappe.get_doc("ERP Administrative Building", filters)
        
        if not building:
            return {
                "success": False,
                "data": {},
                "message": "Building not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": building.name,
                "title_vn": building.title_vn,
                "title_en": building.title_en,
                "short_title": building.short_title,
                "campus_id": building.campus_id
            },
            "message": "Building fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching building {building_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching building: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_building():
    """Create a new building - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_building: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_building: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_building: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_building: {data}")
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        
        # Input validation
        if not title_vn or not short_title:
            frappe.throw(_("Title VN and short title are required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if building title already exists for this campus
        existing = frappe.db.exists(
            "ERP Administrative Building",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Building with title '{title_vn}' already exists"))
            
        # Check if short title already exists for this campus
        existing_code = frappe.db.exists(
            "ERP Administrative Building",
            {
                "short_title": short_title,
                "campus_id": campus_id
            }
        )
        
        if existing_code:
            return {
                "success": False,
                "data": {},
                "message": f"Building with short title '{short_title}' already exists"
            }
        
        # Create new building
        building_doc = frappe.get_doc({
            "doctype": "ERP Administrative Building",
            "title_vn": title_vn,
            "title_en": title_en,
            "short_title": short_title,
            "campus_id": campus_id
        })
        
        building_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Building created successfully"))
        return {
            "name": building_doc.name,
            "title_vn": building_doc.title_vn,
            "title_en": building_doc.title_en,
            "short_title": building_doc.short_title,
            "campus_id": building_doc.campus_id
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating building: {str(e)}")
        frappe.throw(_(f"Error creating building: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_building(building_id, title_vn=None, title_en=None, short_title=None):
    """Update an existing building"""
    try:
        if not building_id:
            return {
                "success": False,
                "data": {},
                "message": "Building ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)
            
            # Check campus permission
            if building_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this building"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Building not found"
            }
        
        # Update fields if provided
        if title_vn and title_vn != building_doc.title_vn:
            # Check for duplicate building title
            existing = frappe.db.exists(
                "ERP Administrative Building",
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "name": ["!=", building_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Building with title '{title_vn}' already exists"
                }
            building_doc.title_vn = title_vn
        
        if title_en and title_en != building_doc.title_en:
            building_doc.title_en = title_en
            
        if short_title and short_title != building_doc.short_title:
            # Check for duplicate short title
            existing_code = frappe.db.exists(
                "ERP Administrative Building",
                {
                    "short_title": short_title,
                    "campus_id": campus_id,
                    "name": ["!=", building_id]
                }
            )
            if existing_code:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Building with short title '{short_title}' already exists"
                }
            building_doc.short_title = short_title
        
        building_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": building_doc.name,
                "title_vn": building_doc.title_vn,
                "title_en": building_doc.title_en,
                "short_title": building_doc.short_title,
                "campus_id": building_doc.campus_id
            },
            "message": "Building updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating building {building_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating building: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_building(building_id):
    """Delete a building"""
    try:
        if not building_id:
            return {
                "success": False,
                "data": {},
                "message": "Building ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)
            
            # Check campus permission
            if building_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this building"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Building not found"
            }
        
        # Delete the document
        frappe.delete_doc("ERP Administrative Building", building_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Building deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting building {building_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting building: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def check_short_title_availability(short_title, building_id=None):
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
        
        # If updating existing building, exclude it from check
        if building_id:
            filters["name"] = ["!=", building_id]
        
        existing = frappe.db.exists("ERP Administrative Building", filters)
        
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
