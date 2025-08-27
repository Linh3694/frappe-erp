# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate
import json


@frappe.whitelist()
def get_all_rooms():
    """Get all rooms with basic information"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Debug logging
        frappe.logger().info(f"Getting rooms for campus: {campus_id}")

        # Get total count first (without filters)
        total_rooms = frappe.get_all("ERP Administrative Room", fields=["name"])
        frappe.logger().info(f"Total rooms in database: {len(total_rooms)}")

        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=[
                "name",
                "room_name",
                "room_name_en",
                "room_type",
                "capacity",
                "periods_per_day",
                "is_homeroom",
                "building_id",
                "description",
                "created_at",
                "updated_at"
            ],
            filters={"campus_id": campus_id},
            order_by="room_name asc"
        )

        frappe.logger().info(f"Rooms found for campus {campus_id}: {len(rooms)}")

        # If no rooms found for the campus, try to get all rooms (for testing)
        if len(rooms) == 0:
            frappe.logger().info("No rooms found for campus, trying to get all rooms...")
            all_rooms = frappe.get_all(
                "ERP Administrative Room",
                fields=[
                    "name",
                    "room_name",
                    "room_name_en",
                    "room_type",
                    "capacity",
                    "periods_per_day",
                    "is_homeroom",
                    "building_id",
                    "description",
                    "created_at",
                    "updated_at"
                ],
                order_by="room_name asc"
            )
            frappe.logger().info(f"All rooms in database: {len(all_rooms)}")
            if len(all_rooms) > 0:
                rooms = all_rooms[:5]  # Return max 5 rooms for testing

        return {
            "success": True,
            "data": {
                "rooms": rooms
            },
            "message": "Rooms fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching rooms: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching rooms",
            "error": str(e)
        }


@frappe.whitelist()
def get_room_by_id(room_id=None):
    """Get room details by ID - SIMPLE VERSION with JSON payload support"""
    try:
        # Get room_id from parameter or from JSON payload
        if not room_id:
            # Try to get from JSON payload
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
            return {
                "success": False,
                "data": {},
                "message": "Room ID is required"
            }

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get room with campus filter
        rooms = frappe.get_all(
            "ERP Administrative Room",
            filters={
                "name": room_id,
                "campus_id": campus_id
            },
            fields=[
                "name", "room_name", "room_name_en", "short_title",
                "room_type", "capacity", "periods_per_day", "is_homeroom",
                "building_id", "description", "created_at", "updated_at"
            ]
        )

        if not rooms:
            return {
                "success": False,
                "data": {},
                "message": "Room not found"
            }

        room = rooms[0]
        
        return {
            "success": True,
            "data": {
                "room": {
                    "name": room.name,
                    "room_name": room.room_name,
                    "room_name_en": room.room_name_en,
                    "room_type": room.room_type,
                    "capacity": room.capacity,
                    "periods_per_day": room.periods_per_day,
                    "is_homeroom": room.is_homeroom,
                    "building_id": room.building_id,
                    "description": room.description,
                    "created_at": room.created_at,
                    "updated_at": room.updated_at
                }
            },
            "message": "Room details fetched successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Room not found"
        }
    except Exception as e:
        frappe.log_error(f"Error fetching room {room_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching room details",
            "error": str(e)
        }


@frappe.whitelist()
def add_room(room_name, room_type, capacity=None, periods_per_day=10, is_homeroom=0, description=None, room_name_en=None, building_id=None):
    """Add new room"""
    try:
        # Validate required fields
        if not room_name or not room_type:
            return {
                "success": False,
                "message": "Room name and room type are required"
            }
        
        # Create new room document
        room_doc = frappe.get_doc({
            "doctype": "ERP Administrative Room",
            "room_name": room_name,
            "room_name_en": room_name_en,
            "room_type": room_type,
            "capacity": int(capacity) if capacity else None,
            "periods_per_day": int(periods_per_day) or 10,
            "is_homeroom": int(is_homeroom) or 0,
            "building_id": building_id,
            "description": description
        })
        
        room_doc.insert()
        
        return {
            "success": True,
            "data": {
                "room_id": room_doc.name,
                "room_name": room_doc.room_name
            },
            "message": "Room added successfully"
        }
        
    except frappe.DuplicateEntryError:
        return {
            "success": False,
            "message": f"Room with name '{room_name}' already exists"
        }
    except Exception as e:
        frappe.log_error(f"Error adding room: {str(e)}")
        return {
            "success": False,
            "message": "Error adding room",
            "error": str(e)
        }


@frappe.whitelist()
def update_room(room_id, room_name=None, room_type=None, capacity=None, periods_per_day=None, is_homeroom=None, description=None, room_name_en=None, building_id=None):
    """Update room information"""
    try:
        if not room_id:
            return {
                "success": False,
                "message": "Room ID is required"
            }
        
        room_doc = frappe.get_doc("ERP Administrative Room", room_id)
        
        # Update fields if provided
        if room_name is not None:
            room_doc.room_name = room_name
        if room_name_en is not None:
            room_doc.room_name_en = room_name_en
        if room_type is not None:
            room_doc.room_type = room_type
        if capacity is not None:
            room_doc.capacity = int(capacity) if capacity else None
        if periods_per_day is not None:
            room_doc.periods_per_day = int(periods_per_day)
        if is_homeroom is not None:
            room_doc.is_homeroom = int(is_homeroom)
        if building_id is not None:
            room_doc.building_id = building_id
        if description is not None:
            room_doc.description = description
        
        room_doc.save()
        
        return {
            "success": True,
            "data": {
                "room_id": room_doc.name,
                "room_name": room_doc.room_name
            },
            "message": "Room updated successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Room not found"
        }
    except Exception as e:
        frappe.log_error(f"Error updating room {room_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error updating room",
            "error": str(e)
        }


@frappe.whitelist()
def delete_room(room_id):
    """Delete room"""
    try:
        if not room_id:
            return {
                "success": False,
                "message": "Room ID is required"
            }
        
        room_doc = frappe.get_doc("ERP Administrative Room", room_id)
        room_name = room_doc.room_name
        
        # Check if room has any device assignments before deleting
        # This will be implemented when device integration is ready
        
        room_doc.delete()
        
        return {
            "success": True,
            "message": f"Room '{room_name}' deleted successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Room not found"
        }
    except Exception as e:
        frappe.log_error(f"Error deleting room {room_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error deleting room",
            "error": str(e)
        }


@frappe.whitelist()
def get_devices_by_room(room_id):
    """Get all devices assigned to a room"""
    try:
        if not room_id:
            return {
                "success": False,
                "message": "Room ID is required"
            }
        
        # Check if room exists
        room = frappe.get_doc("ERP Administrative Room", room_id)
        
        # Initialize devices structure
        devices = {
            "laptops": [],
            "monitors": [],
            "projectors": [],
            "printers": [],
            "tools": [],
            "phones": []
        }
        
        # Note: IT Inventory module has been removed, so device tracking is disabled
        # This section would populate devices from IT inventory if the module existed
        
        has_devices = any(len(device_list) > 0 for device_list in devices.values())
        
        return {
            "success": True,
            "data": {
                "room": {
                    "name": room.name,
                    "room_name": room.room_name,
                    "room_name_en": room.room_name_en,
                    "room_type": room.room_type,
                    "capacity": room.capacity,
                    "building_id": room.building_id
                },
                "devices": devices,
                "has_devices": has_devices
            },
            "message": "Devices fetched successfully" if has_devices else "No devices found for this room"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Room not found"
        }
    except Exception as e:
        frappe.log_error(f"Error fetching devices for room {room_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching devices",
            "error": str(e)
        }


@frappe.whitelist()
def get_room_utilization(room_id):
    """Get room utilization statistics"""
    try:
        if not room_id:
            return {
                "success": False,
                "message": "Room ID is required"
            }
        
        room = frappe.get_doc("ERP Administrative Room", room_id)
        
        # This will be implemented when timetable integration is ready
        utilization_data = {
            "room_id": room.name,
            "room_name": room.room_name,
            "capacity": room.capacity,
            "periods_per_day": room.periods_per_day,
            "is_homeroom": room.is_homeroom,
            "utilization_percentage": 0,  # To be calculated based on timetable data
            "scheduled_periods": 0,       # To be calculated
            "available_periods": room.periods_per_day or 10
        }
        
        return {
            "success": True,
            "data": utilization_data,
            "message": "Room utilization data fetched successfully"
        }

    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "Room not found"
        }
    except Exception as e:
        frappe.log_error(f"Error fetching room utilization {room_id}: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching room utilization",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def create_room():
    """Create a new room - SIMPLE VERSION with JSON payload support"""
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

        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        capacity = data.get("capacity")
        room_type = data.get("room_type")
        building_id = data.get("building_id")

        # Input validation
        if not title_vn or not room_type:
            frappe.throw(_("Title VN and room type are required"))

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Create new room document directly
        room_doc = frappe.get_doc({
            "doctype": "ERP Administrative Room",
            "room_name": title_vn,
            "room_name_en": title_en or "",
            "short_title": short_title or "",
            "room_type": room_type,
            "capacity": int(capacity) if capacity else None,
            "periods_per_day": 10,
            "is_homeroom": 0,
            "building_id": building_id,
            "campus_id": campus_id,
            "description": f"{short_title} - Room created via frontend" if short_title else ""
        })

        room_doc.insert()
        frappe.db.commit()

        result = {
            "success": True,
            "room_id": room_doc.name,
            "message": "Room created successfully"
        }

        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "room": {
                        "name": result.get("room_id"),
                        "title_vn": title_vn,
                        "title_en": title_en,
                        "short_title": short_title,
                        "capacity": capacity,
                        "room_type": room_type,
                        "building_id": building_id
                    }
                },
                "message": "Room created successfully"
            }
        else:
            return result

    except Exception as e:
        frappe.log_error(f"Error creating room: {str(e)}")
        frappe.throw(_(f"Error creating room: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_room():
    """Update an existing room - SIMPLE VERSION with JSON payload support"""
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

        room_id = data.get('room_id')
        if not room_id:
            return {
                "success": False,
                "data": {
                    "room": {}
                },
                "message": "Room ID is required"
            }

        # Extract values from data
        room_name = data.get('room_name') or data.get('title_vn')
        room_name_en = data.get('room_name_en') or data.get('title_en')
        short_title = data.get('short_title')
        capacity = data.get('capacity')
        room_type = data.get('room_type')
        building_id = data.get('building_id')

        # Get existing room document
        try:
            room_doc = frappe.get_doc("ERP Administrative Room", room_id)

            # Check campus permission
            if room_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {
                        "room": {}
                    },
                    "message": "Access denied: You don't have permission to modify this room"
                }

        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {
                    "room": {}
                },
                "message": "Room not found"
            }

        # Update fields if provided
        if room_name and room_name != room_doc.room_name:
            room_doc.room_name = room_name

        if room_name_en is not None and room_name_en != room_doc.room_name_en:
            room_doc.room_name_en = room_name_en

        if short_title and short_title != room_doc.short_title:
            room_doc.short_title = short_title

        if capacity is not None and str(capacity) != str(room_doc.capacity):
            room_doc.capacity = int(capacity)

        if room_type and room_type != room_doc.room_type:
            room_doc.room_type = room_type

        if building_id and building_id != room_doc.building_id:
            room_doc.building_id = building_id

        room_doc.save()
        frappe.db.commit()

        result = {
            "success": True,
            "message": "Room updated successfully"
        }

        if result.get("success"):
            return {
                "success": True,
                "data": {
                    "room": {
                        "name": room_id,
                        "title_vn": room_name,
                        "title_en": room_name_en,
                        "short_title": short_title,
                        "capacity": capacity,
                        "room_type": room_type,
                        "building_id": building_id
                    }
                },
                "message": "Room updated successfully"
            }
        else:
            return result

    except Exception as e:
        frappe.log_error(f"Error updating room: {str(e)}")
        return {
            "success": False,
            "data": {
                "room": {}
            },
            "message": f"Error updating room: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_room():
    """Delete a room - SIMPLE VERSION with JSON payload support"""
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

        room_id = data.get('room_id')
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

        # Get existing document
        try:
            room_doc = frappe.get_doc("ERP Administrative Room", room_id)

            # Check campus permission
            if room_doc.campus_id != campus_id:
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

        result = {
            "success": True,
            "message": "Room deleted successfully"
        }

        if result.get("success"):
            return {
                "success": True,
                "data": {},
                "message": "Room deleted successfully"
            }
        else:
            return result

    except Exception as e:
        frappe.log_error(f"Error deleting room: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting room: {str(e)}"
        }


@frappe.whitelist()
def create_sample_rooms():
    """Create sample rooms for testing - TEMPORARY FUNCTION"""
    try:
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        sample_rooms = [
            {
                "room_name": "Phòng học A101",
                "room_name_en": "Classroom A101",
                "short_title": "A101",
                "room_type": "classroom",
                "capacity": 30,
                "periods_per_day": 10,
                "is_homeroom": 0,
                "campus_id": campus_id
            },
            {
                "room_name": "Phòng học A102",
                "room_name_en": "Classroom A102",
                "short_title": "A102",
                "room_type": "classroom",
                "capacity": 25,
                "periods_per_day": 10,
                "is_homeroom": 0,
                "campus_id": campus_id
            },
            {
                "room_name": "Phòng chức năng B001",
                "room_name_en": "Function Room B001",
                "short_title": "B001",
                "room_type": "function",
                "capacity": 50,
                "periods_per_day": 8,
                "is_homeroom": 0,
                "campus_id": campus_id
            }
        ]

        created_rooms = []
        for room_data in sample_rooms:
            try:
                room_doc = frappe.get_doc({
                    "doctype": "ERP Administrative Room",
                    **room_data
                })
                room_doc.insert()
                created_rooms.append({
                    "name": room_doc.name,
                    "room_name": room_data["room_name"]
                })
            except Exception as e:
                frappe.logger().error(f"Error creating room {room_data['room_name']}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "data": {
                "created_rooms": created_rooms,
                "count": len(created_rooms)
            },
            "message": f"Created {len(created_rooms)} sample rooms successfully"
        }

    except Exception as e:
        frappe.logger().error(f"Error creating sample rooms: {str(e)}")
        return {
            "success": False,
            "message": "Error creating sample rooms",
            "error": str(e)
        }