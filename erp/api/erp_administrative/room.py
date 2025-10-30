# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import success_response, error_response
try:
    import pandas as pd
except ImportError:
    pd = None


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


class RoomExcelImporter:
    """Handle Excel import for Rooms with validation and mapping"""

    def __init__(self, campus_id: str):
        self.campus_id = campus_id
        self.errors: list = []
        self.warnings: list = []
        self.building_mapping = {}

    def validate_excel_structure(self, df):
        """Validate Excel file structure for room import

        Required columns: title_vn, title_en, short_title, room_type, building_title
        Optional columns: capacity
        """
        if len(df) == 0:
            self.errors.append("Excel file is empty or has no data rows")
            return False

        # Normalize column names
        df = self.normalize_columns(df)

        required_cols = ['title_vn', 'title_en', 'short_title', 'room_type', 'building_title']
        cols_lower = [str(c).strip().lower() for c in df.columns]

        missing_cols = []
        for col in required_cols:
            if col not in cols_lower:
                missing_cols.append(col)

        if missing_cols:
            self.errors.append(f"Missing required columns: {', '.join(missing_cols)}")
            return False

        return True

    def normalize_columns(self, df):
        """Rename Vietnamese/variant headers to canonical English headers"""
        try:
            canonical_map = {
                'tên tiếng việt': 'title_vn',
                'tên vn': 'title_vn',
                'vietnamese name': 'title_vn',
                'tên tiếng anh': 'title_en',
                'tên en': 'title_en',
                'english name': 'title_en',
                'ký hiệu': 'short_title',
                'short title': 'short_title',
                'mã phòng': 'short_title',
                'loại phòng': 'room_type',
                'room type': 'room_type',
                'tòa nhà': 'building_title',
                'building': 'building_title',
                'tên tòa nhà': 'building_title',
                'sức chứa': 'capacity',
                'capacity': 'capacity',
                'số lượng': 'capacity'
            }
            rename_map = {}
            for col in df.columns:
                key = str(col).strip().lower()
                if key in canonical_map:
                    rename_map[col] = canonical_map[key]
            if rename_map:
                df = df.rename(columns=rename_map)
        except Exception:
            pass
        return df

    def normalize_room_type(self, room_type_str):
        """Convert Vietnamese room types to English codes"""
        if not room_type_str:
            return None

        room_type_lower = str(room_type_str).strip().lower()

        # Map Vietnamese names to English codes
        room_type_mapping = {
            'phòng lớp học': 'classroom_room',
            'phòng học': 'classroom_room',
            'lớp học': 'classroom_room',
            'phòng họp': 'meeting_room',
            'họp': 'meeting_room',
            'hội trường': 'auditorium',
            'auditorium': 'auditorium',
            'sân ngoài trời': 'outdoor',
            'sân': 'outdoor',
            'phòng làm việc': 'office',
            'văn phòng': 'office',
            'phòng chức năng': 'function_room',
            'chức năng': 'function_room'
        }

        # Direct English mapping
        direct_mapping = {
            'classroom_room': 'classroom_room',
            'meeting_room': 'meeting_room',
            'auditorium': 'auditorium',
            'outdoor': 'outdoor',
            'office': 'office',
            'function_room': 'function_room'
        }

        # Try Vietnamese mapping first, then direct English
        if room_type_lower in room_type_mapping:
            return room_type_mapping[room_type_lower]
        elif room_type_lower in direct_mapping:
            return direct_mapping[room_type_lower]

        return None

    def load_building_mapping(self):
        """Load building mapping for the campus"""
        try:
            buildings = frappe.get_all(
                "ERP Administrative Building",
                filters={"campus_id": self.campus_id},
                fields=["name", "title_vn", "title_en", "short_title"]
            )

            for building in buildings:
                # Map by title_vn, title_en, and short_title
                self.building_mapping[building.title_vn.lower()] = building.name
                self.building_mapping[building.title_en.lower()] = building.name
                self.building_mapping[building.short_title.lower()] = building.name

        except Exception as e:
            self.errors.append(f"Error loading building mapping: {str(e)}")

    def find_building_id(self, building_title):
        """Find building ID by title"""
        if not building_title:
            return None

        title_lower = str(building_title).strip().lower()
        return self.building_mapping.get(title_lower)

    def validate_room_data(self, row_data):
        """Validate individual room data"""
        errors = []

        # Required fields
        if not row_data.get('title_vn'):
            errors.append("title_vn is required")
        if not row_data.get('title_en'):
            errors.append("title_en is required")
        if not row_data.get('short_title'):
            errors.append("short_title is required")

        # Room type validation
        room_type = self.normalize_room_type(row_data.get('room_type'))
        if not room_type:
            errors.append(f"Invalid room_type: {row_data.get('room_type')}")
        else:
            row_data['room_type'] = room_type  # Update with normalized value

        # Building validation
        building_id = self.find_building_id(row_data.get('building_title'))
        if not building_id:
            errors.append(f"Building not found: {row_data.get('building_title')}")
        else:
            row_data['building_id'] = building_id

        # Capacity validation
        capacity = row_data.get('capacity')
        if capacity is not None:
            try:
                capacity = int(capacity)
                if capacity < 0:
                    errors.append("Capacity must be non-negative")
                row_data['capacity'] = capacity
            except (ValueError, TypeError):
                errors.append("Capacity must be a valid number")

        return errors

    def process_excel_import(self, file_path, dry_run=False):
        """Process Excel import for rooms"""
        if not pd:
            return {"success": False, "message": "pandas library not available"}

        try:
            # Load building mapping
            self.load_building_mapping()

            # Read Excel file
            df = pd.read_excel(file_path)

            if not self.validate_excel_structure(df):
                return {
                    "success": False,
                    "message": "Excel structure validation failed",
                    "errors": self.errors,
                    "warnings": self.warnings
                }

            # Normalize columns
            df = self.normalize_columns(df)

            # Process each row
            processed_rooms = []
            validation_errors = []

            for index, row in df.iterrows():
                row_data = {
                    'title_vn': row.get('title_vn'),
                    'title_en': row.get('title_en'),
                    'short_title': row.get('short_title'),
                    'room_type': row.get('room_type'),
                    'building_title': row.get('building_title'),
                    'capacity': row.get('capacity')
                }

                # Validate row data
                row_errors = self.validate_room_data(row_data)
                if row_errors:
                    validation_errors.append({
                        "row": index + 2,  # +2 because Excel is 1-indexed and has header
                        "data": row_data,
                        "errors": row_errors
                    })
                else:
                    processed_rooms.append(row_data)

            if validation_errors and dry_run:
                return {
                    "success": False,
                    "message": "Validation failed",
                    "validation_errors": validation_errors,
                    "total_rows": len(df),
                    "valid_rows": len(processed_rooms)
                }

            if not dry_run and processed_rooms:
                # Create rooms in database
                created_count = 0
                for room_data in processed_rooms:
                    try:
                        room_doc = frappe.get_doc({
                            "doctype": "ERP Administrative Room",
                            "title_vn": room_data['title_vn'],
                            "title_en": room_data['title_en'],
                            "short_title": room_data['short_title'],
                            "room_type": room_data['room_type'],
                            "building_id": room_data['building_id'],
                            "capacity": room_data.get('capacity', 0),
                            "campus_id": self.campus_id
                        })
                        room_doc.insert()
                        created_count += 1
                    except Exception as e:
                        self.errors.append(f"Error creating room {room_data.get('title_vn')}: {str(e)}")

                frappe.db.commit()

            return {
                "success": True,
                "message": f"Import completed successfully. Created {created_count} rooms." if not dry_run else "Dry run completed successfully",
                "total_rows": len(df),
                "created_count": created_count if not dry_run else 0,
                "errors": self.errors,
                "warnings": self.warnings
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Error processing Excel import: {str(e)}",
                "errors": self.errors
            }


def save_uploaded_file(file_data, filename):
    """Save uploaded file temporarily"""
    import os
    import uuid

    # Create temp directory if it doesn't exist
    temp_dir = "/tmp/frappe_uploads"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # Generate unique filename
    unique_filename = f"{uuid.uuid4()}_{filename}"
    file_path = os.path.join(temp_dir, unique_filename)

    # Save file
    with open(file_path, 'wb') as f:
        if hasattr(file_data, 'read'):
            f.write(file_data.read())
        else:
            f.write(file_data)

    return file_path


@frappe.whitelist(allow_guest=False)
def import_rooms():
    """Import rooms from Excel file"""
    try:
        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback: try to get first available campus from database
            try:
                first_campus = frappe.db.get_value("SIS Campus", {}, "name", order_by="creation asc")
                campus_id = first_campus or "CAMPUS-00001"
            except Exception:
                campus_id = "CAMPUS-00001"

        # Check for dry_run parameter
        dry_run = frappe.local.form_dict.get("dry_run", "false").lower() == "true"

        # Process Excel import if file is provided
        files = frappe.request.files

        if files and 'file' in files:
            file_data = files['file']
            if not file_data:
                return validation_error_response({"file": ["No file uploaded"]})

            # Save file temporarily
            file_path = save_uploaded_file(file_data, "rooms_import.xlsx")

            # Process Excel import
            importer = RoomExcelImporter(campus_id)
            result = importer.process_excel_import(file_path, dry_run)

            # Clean up temp file
            try:
                import os
                os.remove(file_path)
            except Exception:
                pass

            if result["success"]:
                return success_response(result, result["message"])
            else:
                return validation_error_response(result["message"], {
                    "errors": result.get("errors", []),
                    "validation_errors": result.get("validation_errors", []),
                    "warnings": result.get("warnings", [])
                })
        else:
            return validation_error_response({"file": ["No file uploaded"]})

    except Exception as e:
        frappe.log_error(f"Error importing rooms: {str(e)}")
        return error_response(f"Error importing rooms: {str(e)}")


@frappe.whitelist(methods=["GET"])
def get_import_job_status():
    """Get the status/result of room import background job"""
    try:
        cache_key = f"room_import_result_{frappe.session.user}"
        cached_result = frappe.cache().get_value(cache_key)

        if cached_result:
            frappe.cache().delete_value(cache_key)
            return success_response(cached_result, "Import job completed")
        else:
            return success_response({"status": "processing"}, "Import job is still processing")

    except Exception as e:
        frappe.log_error(f"Error getting import job status: {str(e)}")
        return error_response(f"Error getting import job status: {str(e)}")


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
