# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json


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
            return {
                "success": False,
                "data": {},
                "message": "Building ID is required"
            }
        
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
            return {
                "success": False,
                "data": {},
                "message": "Building not found"
            }

        building = buildings[0]
        
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
            return {
                "success": False,
                "data": {},
                "message": "Title VN and short title are required"
            }
        
        # Check if building title already exists
        existing = frappe.db.exists(
            "ERP Administrative Building",
            {
                "title_vn": title_vn
            }
        )

        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"Building with title '{title_vn}' already exists"
            }

        # Check if short title already exists
        existing_code = frappe.db.exists(
            "ERP Administrative Building",
            {
                "short_title": short_title
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
            "campus_id": "campus-1"  # Default campus
        })
        
        building_doc.insert()
        frappe.db.commit()
        
        # Return the created data - follow Frappe pattern like other services  
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
        return {
            "success": False,
            "data": {},
            "message": f"Error creating building: {str(e)}"
        }


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
        
        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)
                
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
        
        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)
                
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

        # Debug logging
        frappe.logger().info(f"Found {len(buildings)} buildings for selection")
        if len(buildings) == 0:
            frappe.logger().warning("No buildings found in database - creating sample buildings")

            # Create sample buildings if none exist
            sample_buildings = [
                {
                    "title_vn": "Tòa nhà A",
                    "title_en": "Building A",
                    "short_title": "TOA_A",
                    "campus_id": "campus-1"
                },
                {
                    "title_vn": "Tòa nhà B",
                    "title_en": "Building B",
                    "short_title": "TOA_B",
                    "campus_id": "campus-1"
                },
                {
                    "title_vn": "Tòa nhà C",
                    "title_en": "Building C",
                    "short_title": "TOA_C",
                    "campus_id": "campus-1"
                }
            ]

            for building_data in sample_buildings:
                try:
                    building_doc = frappe.get_doc({
                        "doctype": "ERP Administrative Building",
                        **building_data
                    })
                    building_doc.insert()
                    frappe.logger().info(f"Created sample building: {building_data['title_vn']}")
                except Exception as e:
                    frappe.logger().error(f"Error creating sample building {building_data['title_vn']}: {str(e)}")

            frappe.db.commit()

            # Re-fetch buildings after creating samples
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

            frappe.logger().info(f"After creating samples, found {len(buildings)} buildings")

        return {
            "success": True,
            "data": buildings,
            "message": "Buildings fetched successfully"
        }

    except Exception as e:
        frappe.log_error(f"Error fetching buildings for selection: {str(e)}")
        return {
            "success": False,
            "message": "Error fetching buildings for selection",
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def create_sample_buildings():
    """Create sample buildings for testing"""
    try:
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        sample_buildings = [
            {
                "title_vn": "Tòa nhà A",
                "title_en": "Building A",
                "short_title": "TOA_A",
                "campus_id": campus_id
            },
            {
                "title_vn": "Tòa nhà B",
                "title_en": "Building B",
                "short_title": "TOA_B",
                "campus_id": campus_id
            },
            {
                "title_vn": "Tòa nhà C",
                "title_en": "Building C",
                "short_title": "TOA_C",
                "campus_id": campus_id
            },
            {
                "title_vn": "Tòa nhà D",
                "title_en": "Building D",
                "short_title": "TOA_D",
                "campus_id": campus_id
            },
            {
                "title_vn": "Tòa nhà E",
                "title_en": "Building E",
                "short_title": "TOA_E",
                "campus_id": campus_id
            }
        ]

        created_buildings = []
        for building_data in sample_buildings:
            try:
                building_doc = frappe.get_doc({
                    "doctype": "ERP Administrative Building",
                    **building_data
                })
                building_doc.insert()
                created_buildings.append({
                    "name": building_doc.name,
                    "title_vn": building_data["title_vn"]
                })
            except frappe.DuplicateEntryError:
                # Building already exists, skip
                continue
            except Exception as e:
                frappe.log_error(f"Error creating building {building_data['title_vn']}: {str(e)}")

        frappe.db.commit()

        return {
            "success": True,
            "data": {
                "created_buildings": created_buildings,
                "count": len(created_buildings)
            },
            "message": f"Tạo thành công {len(created_buildings)} tòa nhà mẫu"
        }

    except Exception as e:
        frappe.log_error(f"Error creating sample buildings: {str(e)}")
        return {
            "success": False,
            "message": "Lỗi khi tạo tòa nhà mẫu",
            "error": str(e)
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
        
        filters = {
            "short_title": short_title
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
            return {
                "success": False,
                "data": {},
                "message": "Building ID is required"
            }

        # Get existing document
        try:
            building_doc = frappe.get_doc("ERP Administrative Building", building_id)

        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Building not found"
            }

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

        return {
            "success": True,
            "data": {
                "building": {
                    "name": building_doc.name,
                    "title_vn": building_doc.title_vn,
                    "title_en": building_doc.title_en,
                    "short_title": building_doc.short_title,
                    "campus_id": building_doc.campus_id
                }
            },
            "message": "Building updated successfully"
        }

    except Exception as e:
        frappe.log_error(f"Error updating building: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating building: {str(e)}"
        }
