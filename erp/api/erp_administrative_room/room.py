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
            order_by="room_name asc"
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
def get_room_by_id(room_id):
    """Get room details by ID"""
    try:
        if not room_id:
            return {
                "success": False,
                "message": "Room ID is required"
            }
        
        room = frappe.get_doc("ERP Administrative Room", room_id)
        
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
        
        try:
            # Query IT devices where room field equals this room
            it_devices = frappe.get_all(
                "ERP IT Inventory Device",
                filters={"room": room_id},
                fields=[
                    "name", "device_name", "device_type", "manufacturer", 
                    "serial_number", "status", "processor", "ram", "storage"
                ]
            )
            
            # Group devices by type
            for device in it_devices:
                device_type = device.device_type.lower() if device.device_type else "tools"
                
                device_info = {
                    "name": device.name,
                    "device_name": device.device_name,
                    "manufacturer": device.manufacturer,
                    "serial_number": device.serial_number,
                    "status": device.status,
                    "specs": {
                        "processor": device.processor,
                        "ram": device.ram,
                        "storage": device.storage
                    }
                }
                
                # Map device types to appropriate categories
                if device_type in ["laptop", "desktop"]:
                    devices["laptops"].append(device_info)
                elif device_type == "monitor":
                    devices["monitors"].append(device_info)
                elif device_type == "projector":
                    devices["projectors"].append(device_info)
                elif device_type == "printer":
                    devices["printers"].append(device_info)
                elif device_type == "phone":
                    devices["phones"].append(device_info)
                else:
                    devices["tools"].append(device_info)
                        
        except Exception as e:
            frappe.log_error(f"Error fetching devices for room {room_id}: {str(e)}")
        
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