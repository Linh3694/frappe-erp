# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_rooms():
    """Get all rooms with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles  
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
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
                "total_count": 0,
                "message": "No buildings found for this campus"
            }
        
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
        
        return {
            "success": True,
            "data": rooms,
            "total_count": len(rooms),
            "message": "Rooms fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching rooms: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching rooms: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_room_by_id(room_id):
    """Get a specific room by ID"""
    try:
        if not room_id:
            return {
                "success": False,
                "data": {},
                "message": "Room ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get room and check if it belongs to a building in this campus
        room = frappe.get_doc("ERP Administrative Room", room_id)
        
        if not room:
            return {
                "success": False,
                "data": {},
                "message": "Room not found"
            }
        
        # Check if the room's building belongs to this campus
        building_exists = frappe.db.exists(
            "ERP Administrative Building",
            {
                "name": room.building_id,
                "campus_id": campus_id
            }
        )
        
        if not building_exists:
            return {
                "success": False,
                "data": {},
                "message": "Room not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": room.name,
                "title_vn": room.title_vn,
                "title_en": room.title_en,
                "short_title": room.short_title,
                "capacity": room.capacity,
                "room_type": room.room_type,
                "building_id": room.building_id
            },
            "message": "Room fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching room {room_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching room: {str(e)}"
        }


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
            frappe.throw(_("Title VN, short title, room type, and building are required"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Verify building exists and belongs to same campus
        building_exists = frappe.db.exists(
            "ERP Administrative Building",
            {
                "name": building_id,
                "campus_id": campus_id
            }
        )
        
        if not building_exists:
            frappe.throw(_("Selected building does not exist or access denied"))
        
        # Check if room title already exists in this building
        existing = frappe.db.exists(
            "ERP Administrative Room",
            {
                "title_vn": title_vn,
                "building_id": building_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Room with title '{title_vn}' already exists in this building"))
        
        # Create new room
        room_doc = frappe.get_doc({
            "doctype": "ERP Administrative Room",
            "title_vn": title_vn,
            "title_en": title_en,
            "short_title": short_title,
            "capacity": capacity or 0,
            "room_type": room_type,
            "building_id": building_id
        })
        
        room_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Education Stage pattern
        frappe.msgprint(_("Room created successfully"))
        return {
            "name": room_doc.name,
            "title_vn": room_doc.title_vn,
            "title_en": room_doc.title_en,
            "short_title": room_doc.short_title,
            "capacity": room_doc.capacity,
            "room_type": room_doc.room_type,
            "building_id": room_doc.building_id,
            "campus_id": room_doc.campus_id
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating room: {str(e)}")
        frappe.throw(_(f"Error creating room: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_room(room_id, title_vn=None, title_en=None, short_title=None, capacity=None, room_type=None, building_id=None):
    """Update an existing room"""
    try:
        if not room_id:
            return {
                "success": False,
                "data": {},
                "message": "Room ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
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
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this room"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Room not found"
            }
        
        # Update fields if provided
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
                return {
                    "success": False,
                    "data": {},
                    "message": f"Room with title '{title_vn}' already exists in this building"
                }
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
            # Verify new building exists and belongs to same campus
            building_exists = frappe.db.exists(
                "ERP Administrative Building",
                {
                    "name": building_id,
                    "campus_id": campus_id
                }
            )
            
            if not building_exists:
                return {
                    "success": False,
                    "data": {},
                    "message": "Selected building does not exist or access denied"
                }
            room_doc.building_id = building_id
        
        room_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": room_doc.name,
                "title_vn": room_doc.title_vn,
                "title_en": room_doc.title_en,
                "short_title": room_doc.short_title,
                "capacity": room_doc.capacity,
                "room_type": room_doc.room_type,
                "building_id": room_doc.building_id
            },
            "message": "Room updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating room {room_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating room: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_room(room_id):
    """Delete a room"""
    try:
        if not room_id:
            return {
                "success": False,
                "data": {},
                "message": "Room ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
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
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this room"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Room not found"
            }
        
        # Delete the document
        frappe.delete_doc("ERP Administrative Room", room_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Room deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting room {room_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting room: {str(e)}"
        }


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
        
        return {
            "success": True,
            "data": buildings,
            "message": "Buildings fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching buildings for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching buildings: {str(e)}"
        }
