# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import success_response, error_response


@frappe.whitelist(allow_guest=False)
def get_all_rooms():
    """Get all rooms with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using fallback: {campus_id}")
        
        # Get buildings for this campus to filter rooms
        building_filters = {"campus_id": campus_id}
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=["name"],
            filters=building_filters
        )
        
        building_ids = [b.name for b in buildings]
        
        if not building_ids:
            return success_response(
                data=[],
                message="No buildings found for this campus",
                meta={"total_count": 0}
            )
        
        # Get rooms that belong to buildings in this campus
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title",
                "capacity",
                "room_type",
                "building_id",
                "creation",
                "modified"
            ],
            filters={"building_id": ["in", building_ids]},
            order_by="title_vn asc"
        )
        
        return success_response(
            data=rooms,
            message="Rooms fetched successfully",
            meta={"total_count": len(rooms)}
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching rooms: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching rooms: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_room_by_id():
    """Get a specific room by ID"""
    try:
        # Get room_id from JSON payload or form_dict  
        room_id = None
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data and 'room_id' in json_data:
                    room_id = json_data['room_id']
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback to form_dict
        if not room_id:
            room_id = frappe.local.form_dict.get('room_id')
            
        if not room_id:
            return error_response("Room ID is required")
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
        
        # Get room and check if it belongs to a building in this campus
        room = frappe.get_doc("ERP Administrative Room", room_id)
        
        if not room:
            return error_response("Room not found")
        
        # Check if the room's building belongs to this campus
        building_exists = frappe.db.exists(
            "ERP Administrative Building",
            {
                "name": room.building_id,
                "campus_id": campus_id
            }
        )
        
        if not building_exists:
            return error_response("Room not found or access denied")
        
        return success_response(
            data={
                "name": room.name,
                "title_vn": room.title_vn,
                "title_en": room.title_en,
                "short_title": room.short_title,
                "capacity": room.capacity,
                "room_type": room.room_type,
                "building_id": room.building_id
            },
            message="Room fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching room: {str(e)}")
        return error_response(f"Error fetching room: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_room():
    """Create a new room - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_room: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_room: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_room: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_room: {data}")
        
        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        capacity = data.get("capacity")
        room_type = data.get("room_type")
        building_id = data.get("building_id")
        
        # Input validation
        if not title_vn or not short_title or not room_type or not building_id:
            return {
                "success": False,
                "data": {},
                "message": "Title VN, short title, room type, and building are required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using fallback: {campus_id}")
        
        # Get building details to extract campus_id
        building_doc = frappe.get_doc("ERP Administrative Building", building_id)
        building_campus_id = building_doc.campus_id

        # Verify building exists and belongs to same campus (if we have campus context)
        if campus_id and building_campus_id != campus_id:
            return {
                "success": False,
                "data": {},
                "message": "Selected building does not belong to your campus"
            }

        # Check if room title already exists in this building
        existing = frappe.db.exists(
            "ERP Administrative Room",
            {
                "title_vn": title_vn,
                "building_id": building_id
            }
        )

        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"Room with title '{title_vn}' already exists in this building"
            }

        # Create new room - use campus_id from the building
        room_doc = frappe.get_doc({
            "doctype": "ERP Administrative Room",
            "title_vn": title_vn,
            "title_en": title_en,
            "short_title": short_title,
            "capacity": capacity or 0,
            "room_type": room_type,
            "building_id": building_id,
            "campus_id": building_campus_id  # Use campus_id from building
        })
        
        room_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow StandardApiResponse pattern
        return success_response(
            data={
                "name": room_doc.name,
                "title_vn": room_doc.title_vn,
                "title_en": room_doc.title_en,
                "short_title": room_doc.short_title,
                "capacity": room_doc.capacity,
                "room_type": room_doc.room_type,
                "building_id": room_doc.building_id
            },
            message="Room created successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error creating room: {str(e)}")
        return error_response(f"Error creating room: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_room():
    """Update an existing room - SIMPLE VERSION with JSON payload support"""
    try:
        # Get data from request - follow Building pattern
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
        
        room_id = data.get('room_id')
        if not room_id:
            return error_response("Room ID is required")
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
        
        # Get existing document and verify access
        try:
            room_doc = frappe.get_doc("ERP Administrative Room", room_id)
            
            # Check if the room's building belongs to this campus
            building_exists = frappe.db.exists(
                "ERP Administrative Building",
                {
                    "name": room_doc.building_id,
                    "campus_id": campus_id
                }
            )
            
            if not building_exists:
                return error_response("Access denied: You don't have permission to modify this room")
                
        except frappe.DoesNotExistError:
            return error_response("Room not found")
        
        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        short_title = data.get('short_title')
        capacity = data.get('capacity')
        room_type = data.get('room_type')
        building_id = data.get('building_id')
        
        if title_vn and title_vn != room_doc.title_vn:
            # Check for duplicate room title in the same building
            existing = frappe.db.exists(
                "ERP Administrative Room",
                {
                    "title_vn": title_vn,
                    "building_id": room_doc.building_id,
                    "name": ["!=", room_id]
                }
            )
            if existing:
                return error_response(f"Room with title '{title_vn}' already exists in this building")
            room_doc.title_vn = title_vn
        
        if title_en and title_en != room_doc.title_en:
            room_doc.title_en = title_en
            
        if short_title and short_title != room_doc.short_title:
            room_doc.short_title = short_title
            
        if capacity is not None:
            room_doc.capacity = capacity
            
        if room_type and room_type != room_doc.room_type:
            room_doc.room_type = room_type
            
        if building_id and building_id != room_doc.building_id:
            # Get new building details to extract campus_id
            new_building_doc = frappe.get_doc("ERP Administrative Building", building_id)
            new_building_campus_id = new_building_doc.campus_id

            # Verify new building belongs to same campus (if we have campus context)
            if campus_id and new_building_campus_id != campus_id:
                return error_response("Selected building does not belong to your campus")

            room_doc.building_id = building_id
            room_doc.campus_id = new_building_campus_id  # Update campus_id when building changes
        
        room_doc.save()
        frappe.db.commit()
        
        return success_response(
            data={
                "name": room_doc.name,
                "title_vn": room_doc.title_vn,
                "title_en": room_doc.title_en,
                "short_title": room_doc.short_title,
                "capacity": room_doc.capacity,
                "room_type": room_doc.room_type,
                "building_id": room_doc.building_id
            },
            message="Room updated successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error updating room: {str(e)}")
        return error_response(f"Error updating room: {str(e)}")


@frappe.whitelist(allow_guest=False) 
def delete_room():
    """Delete a room"""
    try:
        # Get data from request - follow Building pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    room_id = data.get('room_id')
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                room_id = data.get('room_id')
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            room_id = data.get('room_id')
        
        if not room_id:
            return error_response("Room ID is required")
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                # Final fallback to known campus
                campus_id = "CAMPUS-00001"
        
        # Get existing document and verify access
        try:
            room_doc = frappe.get_doc("ERP Administrative Room", room_id)
            
            # Check if the room's building belongs to this campus
            building_exists = frappe.db.exists(
                "ERP Administrative Building",
                {
                    "name": room_doc.building_id,
                    "campus_id": campus_id
                }
            )
            
            if not building_exists:
                return error_response("Access denied: You don't have permission to delete this room")
                
        except frappe.DoesNotExistError:
            return error_response("Room not found")
        
        # Delete the document
        frappe.delete_doc("ERP Administrative Room", room_id)
        frappe.db.commit()
        
        return success_response(message="Room deleted successfully")
        
    except Exception as e:
        frappe.log_error(f"Error deleting room: {str(e)}")
        return error_response(f"Error deleting room: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_buildings_for_selection():
    """Get buildings for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        buildings = frappe.get_all(
            "ERP Administrative Building",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title"
            ],
            filters=filters,
            order_by="title_vn asc"
        )
        
        return success_response(
            data=buildings,
            message="Buildings fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching buildings for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching buildings: {str(e)}"
        }
