# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context
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
def get_all_buildings():
    """Get all buildings with basic information - SIMPLE VERSION"""
    try:
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
            order_by="title_vn asc"
        )
        
        return list_response(buildings, "Buildings fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching buildings: {str(e)}")
        return error_response(f"Error fetching buildings: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_building_by_id(building_id=None):
    """Get a specific building by ID - SIMPLE VERSION with JSON payload support"""
    try:
        # Get building_id from parameter or from JSON payload
        if not building_id:
            # Try to get from JSON payload
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data)
                    if json_data and 'building_id' in json_data:
                        building_id = json_data['building_id']
                except (json.JSONDecodeError, TypeError):
                    pass

            # Fallback to form_dict
            if not building_id:
                building_id = frappe.local.form_dict.get('building_id')

        if not building_id:
            return validation_error_response({"building_id": ["Building ID is required"]})
        
        buildings = frappe.get_all(
            "ERP Administrative Building",
            filters={
                "name": building_id
            },
            fields=[
                "name", "title_vn", "title_en", "short_title",
                "campus_id", "creation", "modified"
            ]
        )

        if not buildings:
            return not_found_response("Building not found")

        building = buildings[0]
        
        if not building:
            return not_found_response("Building not found or access denied")
        
        building_data = {
            "name": building.name,
            "title_vn": building.title_vn,
            "title_en": building.title_en,
            "short_title": building.short_title,
            "campus_id": building.campus_id
        }
        return single_item_response(building_data, "Building fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching building {building_id}: {str(e)}")
        return error_response(f"Error fetching building: {str(e)}")


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
            return validation_error_response({
                "title_vn": ["Title VN is required"] if not title_vn else [],
                "short_title": ["Short title is required"] if not short_title else []
            })
        
        # Check if building title already exists
        existing = frappe.db.exists(
            "ERP Administrative Building",
            {
                "title_vn": title_vn
            }
        )

        if existing:
            return validation_error_response({"title_vn": [f"Building with title '{title_vn}' already exists"]})

        # Check if short title already exists
        existing_code = frappe.db.exists(
            "ERP Administrative Building",
            {
                "short_title": short_title
            }
        )
        
        if existing_code:
            return validation_error_response({"short_title": [f"Building with short title '{short_title}' already exists"]})
        
        # Get campus from user context or fallback
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"

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
        
        # Return the created data - follow Frappe pattern like other services
        building_data = {
            "name": building_doc.name,
            "title_vn": building_doc.title_vn,
            "title_en": building_doc.title_en,
            "short_title": building_doc.short_title,
            "campus_id": building_doc.campus_id
        }
        return single_item_response(building_data, "Building created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating building: {str(e)}")
        return error_response(f"Error creating building: {str(e)}")


@frappe.whitelist(allow_guest=False) 
def delete_building():
    """Delete a building"""
    try:
        # Get data from request - follow update_building pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
        
        building_id = data.get('building_id')
        if not building_id:
            return validation_error_response({"building_id": ["Building ID is required"]})
        
        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)
                
        except frappe.DoesNotExistError:
            return not_found_response("Building not found")
        
        # Delete the document
        frappe.delete_doc("ERP Administrative Building", building_id)
        frappe.db.commit()
        
        return success_response(message="Building deleted successfully")
        
    except Exception as e:
        frappe.log_error(f"Error deleting building: {str(e)}")
        return error_response(f"Error deleting building: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_buildings_for_selection():
    """Get buildings for dropdown selection - SIMPLE VERSION"""
    try:
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title"
            ],
            order_by="title_vn asc"
        )

        return list_response(buildings, "Buildings fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching buildings for selection: {str(e)}")
        return error_response(f"Error fetching buildings for selection: {str(e)}")





@frappe.whitelist(allow_guest=False)
def check_short_title_availability(short_title, building_id=None):
    """Check if short title is available"""
    try:
        if not short_title:
            return validation_error_response({"short_title": ["Short title is required"]})
        
        filters = {
            "short_title": short_title
        }
        
        # If updating existing building, exclude it from check
        if building_id:
            filters["name"] = ["!=", building_id]
        
        existing = frappe.db.exists("ERP Administrative Building", filters)
        
        is_available = not bool(existing)
        
        return success_response({
            "is_available": is_available,
            "short_title": short_title,
            "message": "Available" if is_available else "Short title already exists"
        })
        
    except Exception as e:
        frappe.log_error(f"Error checking short title availability: {str(e)}")
        return error_response(f"Error checking short title availability: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_building():
    """Update an existing building - SIMPLE VERSION with JSON payload support"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

        building_id = data.get('building_id')
        if not building_id:
            return validation_error_response({"building_id": ["Building ID is required"]})

        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)

        except frappe.DoesNotExistError:
            return not_found_response("Building not found")

        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        short_title = data.get('short_title')

        if title_vn and title_vn != building_doc.title_vn:
            building_doc.title_vn = title_vn

        if title_en is not None and title_en != building_doc.title_en:
            building_doc.title_en = title_en

        if short_title and short_title != building_doc.short_title:
            building_doc.short_title = short_title

        building_doc.save()
        frappe.db.commit()

        building_data = {
            "name": building_doc.name,
            "title_vn": building_doc.title_vn,
            "title_en": building_doc.title_en,
            "short_title": building_doc.short_title,
            "campus_id": building_doc.campus_id
        }
        return single_item_response(building_data, "Building updated successfully")

    except Exception as e:
        frappe.log_error(f"Error updating building: {str(e)}")
        return error_response(f"Error updating building: {str(e)}")
