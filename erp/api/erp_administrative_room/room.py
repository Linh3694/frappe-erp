# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, nowdate
import json
from erp.utils.campus_utils import get_current_campus_from_context


@frappe.whitelist()
def get_all_rooms():
    """Get all rooms with basic information"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title",
                "room_type",
                "capacity",
                "building_id",
                "campus_id",
                "description",
                "creation",
                "modified"
            ],
            filters={"campus_id": campus_id},
            order_by="title_vn asc"
        )

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
            # Try to get from JSON payload first
            if frappe.request.data:
                try:
                    # Handle both bytes and string data
                    data_to_decode = frappe.request.data
                    if isinstance(data_to_decode, bytes):
                        data_to_decode = data_to_decode.decode('utf-8')
                    json_data = json.loads(data_to_decode)
                    if json_data and 'room_id' in json_data:
                        room_id = json_data['room_id']
                except (json.JSONDecodeError, TypeError, UnicodeDecodeError, AttributeError):
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
                "name", "title_vn", "title_en", "short_title",
                "room_type", "capacity", "building_id", "campus_id",
                "description", "creation", "modified"
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
                    "title_vn": room.title_vn,
                    "title_en": room.title_en,
                    "short_title": room.short_title,
                    "room_type": room.room_type,
                    "capacity": room.capacity,
                    "building_id": room.building_id,
                    "description": room.description,
                    "creation": room.creation,
                    "modified": room.modified
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
def add_room(room_name, room_type, capacity=None, is_homeroom=0, description=None, room_name_en=None, building_id=None):
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
            "title_vn": room_name,
            "title_en": room_name_en or "",
            "short_title": room_name,  # Use room_name as short_title
            "room_type": room_type,
            "capacity": int(capacity) if capacity else None,
            "building_id": building_id
        })

        room_doc.insert()

        return {
            "success": True,
            "data": {
                "room_id": room_doc.name,
                "title_vn": room_doc.title_vn
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
def update_room(room_id, room_name=None, room_type=None, capacity=None, is_homeroom=None, description=None, room_name_en=None, building_id=None):
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
            room_doc.title_vn = room_name
        if room_name_en is not None:
            room_doc.title_en = room_name_en
        if room_type is not None:
            room_doc.room_type = room_type
        if capacity is not None:
            room_doc.capacity = int(capacity) if capacity else None
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
                "title_vn": room_doc.title_vn
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
        room_name = room_doc.title_vn
        
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
                    "title_vn": room.title_vn,
                    "title_en": room.title_en,
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
            "title_vn": room.title_vn,
            "capacity": room.capacity,
            "utilization_percentage": 0,  # To be calculated based on timetable data
            "scheduled_periods": 0,       # To be calculated
            "available_periods": 10
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

        # Multi-source data merging - follow Education Stage pattern

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # Merge JSON payload (takes precedence)
        if frappe.request.data:
            try:
                # Handle both bytes and string data
                data_to_decode = frappe.request.data
                if isinstance(data_to_decode, bytes):
                    data_to_decode = data_to_decode.decode('utf-8')
                json_data = json.loads(data_to_decode)
                data.update(json_data)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError, AttributeError):
                pass

        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        short_title = data.get("short_title")
        capacity = data.get("capacity")
        room_type = data.get("room_type")
        building_id = data.get("building_id")

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Input validation
        if not title_vn or not room_type:
            frappe.throw(_("Title VN and room type are required"))

        # Create new room document directly
        room_doc = frappe.get_doc({
            "doctype": "ERP Administrative Room",
            "title_vn": title_vn,
            "title_en": title_en or "",
            "short_title": short_title or "",
            "room_type": room_type,
            "capacity": int(capacity) if capacity else None,
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
                        "building_id": building_id,
                        "campus_id": campus_id
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
        # Multi-source ID extraction - follow Education Stage pattern
        room_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        room_id = frappe.local.form_dict.get('room_id')

        # If not found, try from JSON payload
        if not room_id and frappe.request.data:
            try:
                # Handle both bytes and string data
                data_to_decode = frappe.request.data
                if isinstance(data_to_decode, bytes):
                    data_to_decode = data_to_decode.decode('utf-8')
                json_data = json.loads(data_to_decode)
                room_id = json_data.get('room_id')
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError, AttributeError):
                pass

        if not room_id:
            return {
                "success": False,
                "data": {
                    "room": {}
                },
                "message": "Room ID is required"
            }

        # Multi-source data merging
        data = {}

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # Merge JSON payload (takes precedence)
        if frappe.request.data:
            try:
                # Handle both bytes and string data
                data_to_decode = frappe.request.data
                if isinstance(data_to_decode, bytes):
                    data_to_decode = data_to_decode.decode('utf-8')
                json_data = json.loads(data_to_decode)
                data.update(json_data)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError, AttributeError):
                pass

        # Extract values from data
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        short_title = data.get('short_title')
        capacity = data.get('capacity')
        room_type = data.get('room_type')
        building_id = data.get('building_id')

        # Get campus from user context
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

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
        if title_vn and title_vn != room_doc.title_vn:
            room_doc.title_vn = title_vn

        if title_en is not None and title_en != room_doc.title_en:
            room_doc.title_en = title_en

        if short_title and short_title != room_doc.short_title:
            room_doc.short_title = short_title

        if capacity is not None and str(capacity) != str(room_doc.capacity):
            room_doc.capacity = int(capacity)

        if room_type and room_type != room_doc.room_type:
            room_doc.room_type = room_type

        if building_id and building_id != room_doc.building_id:
            room_doc.building_id = building_id

        if campus_id and campus_id != room_doc.campus_id:
            room_doc.campus_id = campus_id

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
                    "title_vn": title_vn,
                    "title_en": title_en,
                    "short_title": short_title,
                    "capacity": capacity,
                    "room_type": room_type,
                    "building_id": building_id,
                    "campus_id": campus_id
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
        # Multi-source ID extraction - follow Education Stage pattern
        room_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        room_id = frappe.local.form_dict.get('room_id')

        # If not found, try from JSON payload
        if not room_id and frappe.request.data:
            try:
                # Handle both bytes and string data
                data_to_decode = frappe.request.data
                if isinstance(data_to_decode, bytes):
                    data_to_decode = data_to_decode.decode('utf-8')
                json_data = json.loads(data_to_decode)
                room_id = json_data.get('room_id')
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError, AttributeError):
                pass

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