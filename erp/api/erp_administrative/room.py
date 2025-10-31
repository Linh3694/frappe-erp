# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
from frappe.exceptions import LinkExistsError
import json
from typing import Dict, Any
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import success_response, error_response, validation_error_response, not_found_response
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

    except LinkExistsError as e:
        # Handle case where room is linked to classes
        error_msg = "Không thể xóa phòng vì nó đang được sử dụng bởi các lớp học. Vui lòng gỡ bỏ liên kết trước khi xóa."
        return error_response(error_msg)

    except Exception as e:
        # Truncate error message to avoid CharacterLengthExceededError when logging
        error_str = str(e)
        if len(error_str) > 200:
            error_str = error_str[:200] + "..."

        frappe.log_error(f"Error deleting room: {error_str}")
        return error_response("Có lỗi xảy ra khi xóa phòng. Vui lòng thử lại sau.")


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
        # Check if dataframe is empty after reading
        if df is None or df.empty:
            self.errors.append("File Excel không thể đọc được hoặc file trống. Vui lòng kiểm tra: 1) File có đúng định dạng .xlsx hoặc .xls không? 2) File có bị hỏng không? 3) Bạn đã điền dữ liệu vào file mẫu chưa?")
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

        # Check if there's at least one data row (skip empty rows)
        data_rows = 0
        for idx, row in df.iterrows():
            # Check if at least one required field has data
            has_data = any(str(row.get(col, '')).strip() for col in required_cols)
            if has_data:
                data_rows += 1

        if data_rows == 0:
            self.errors.append("No valid data rows found. Please ensure data starts from row 2 and required columns are filled")
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
                'toà nhà': 'building_title',
                'building': 'building_title',
                'tên tòa nhà': 'building_title',
                'tên toà nhà': 'building_title',
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
            errors.append("Tên tiếng Việt là bắt buộc")
        if not row_data.get('short_title'):
            errors.append("Ký hiệu phòng là bắt buộc")

        # Room type validation
        room_type = self.normalize_room_type(row_data.get('room_type'))
        if not room_type:
            errors.append(f"Invalid room_type: {row_data.get('room_type')}")
        else:
            row_data['room_type'] = room_type  # Update with normalized value

        # Building validation (optional)
        building_id = self.find_building_id(row_data.get('building_title'))
        if building_id:
            row_data['building_id'] = building_id
        else:
            # Building not found, log warning but don't fail validation
            if row_data.get('building_title'):
                self.warnings.append(f"Toà nhà '{row_data.get('building_title')}' không tìm thấy trong hệ thống. Phòng sẽ được tạo mà không gán tòa nhà.")
            row_data['building_id'] = None

        # Capacity validation (optional)
        capacity = row_data.get('capacity')
        if capacity is not None and str(capacity).strip():
            try:
                # Handle NaN values from pandas
                if str(capacity).lower() == 'nan' or (hasattr(capacity, 'isnan') and capacity.isnan()):
                    # Keep as None for empty capacity
                    row_data['capacity'] = None
                else:
                    capacity = int(float(capacity))
                    if capacity < 0:
                        errors.append("Sức chứa phải là số không âm")
                    row_data['capacity'] = capacity
            except (ValueError, TypeError):
                errors.append("Sức chứa phải là số hợp lệ")
        else:
            # Keep as None for empty capacity
            row_data['capacity'] = None

        return errors

    def process_excel_import(self, file_path, dry_run=False):
        """Process Excel import for rooms"""
        if not pd:
            return {"success": False, "message": "pandas library not available"}

        try:
            # Debug: Check if file exists and readable
            import os
            debug_info = []
            debug_info.append(f"Excel file path: {file_path}")
            debug_info.append(f"File exists: {os.path.exists(file_path)}")

            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                debug_info.append(f"File size: {file_size} bytes")

                if file_size == 0:
                    return {
                        "success": False,
                        "message": "Excel file is empty (0 bytes)",
                        "errors": ["Uploaded file is empty"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }
            else:
                return {
                    "success": False,
                    "message": "Excel file not found",
                    "errors": ["File was not uploaded successfully"],
                    "debug_info": debug_info,
                    "warnings": self.warnings
                }

            # Load building mapping
            self.load_building_mapping()

            # Basic file validation before pandas
            debug_info.append("Basic file validation...")
            try:
                with open(file_path, 'rb') as f:
                    file_header = f.read(512)  # Read first 512 bytes

                file_size = len(file_header)
                debug_info.append(f"File header size: {file_size} bytes")

                if file_size < 4:
                    return {
                        "success": False,
                        "message": "File quá nhỏ, có thể không phải file Excel hợp lệ.",
                        "errors": ["File size too small"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                # Check for Excel signatures
                header_hex = file_header[:8].hex()
                debug_info.append(f"File header (hex): {header_hex}")

                # Check for common Excel signatures
                if header_hex.startswith('504b0304'):  # PK\x03\x04 - ZIP/XLSX
                    debug_info.append("Detected ZIP/XLSX file signature")
                elif header_hex.startswith('d0cf11e0a1b11ae1'):  # XLS signature
                    debug_info.append("Detected XLS file signature")
                else:
                    debug_info.append("Warning: File does not have standard Excel signature")

            except Exception as file_error:
                debug_info.append(f"Error reading file header: {str(file_error)}")
                return {
                    "success": False,
                    "message": f"Không thể đọc header của file: {str(file_error)}",
                    "errors": [f"File header read error: {str(file_error)}"],
                    "debug_info": debug_info,
                    "warnings": self.warnings
                }

            # Read Excel file (skip first row if it's sample data)
            debug_info.append("Attempting to read Excel file with pandas...")
            try:
                # First check if pandas is available
                if not pd:
                    return {
                        "success": False,
                        "message": "Pandas library not available on server",
                        "errors": ["Server configuration error: pandas library missing"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                # Try reading Excel file with multiple approaches
                df = None
                excel_error = None

                # Approach 1: Standard read_excel with openpyxl
                try:
                    df = pd.read_excel(file_path, header=0, engine='openpyxl')
                    debug_info.append("Successfully read with pandas + openpyxl engine")
                except Exception as e1:
                    debug_info.append(f"Pandas + openpyxl failed: {str(e1)}")
                    excel_error = e1

                    # Approach 2: Try direct openpyxl if available
                    try:
                        import openpyxl
                        wb = openpyxl.load_workbook(file_path, data_only=True)
                        sheet = wb.active

                        # Convert to pandas DataFrame manually
                        data = []
                        headers = []
                        for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
                            if row_idx == 0:  # First row is headers
                                headers = [str(cell) if cell is not None else '' for cell in row]
                            else:
                                data.append([cell for cell in row])

                        if headers and data:
                            df = pd.DataFrame(data, columns=headers)
                            debug_info.append("Successfully read with direct openpyxl")
                        else:
                            raise Exception("No headers or data found")

                    except ImportError:
                        debug_info.append("openpyxl not available for direct reading")
                    except Exception as e2:
                        debug_info.append(f"Direct openpyxl failed: {str(e2)}")

                        # Approach 3: Try xlrd engine for .xls files
                        try:
                            df = pd.read_excel(file_path, header=0, engine='xlrd')
                            debug_info.append("Successfully read with pandas + xlrd engine")
                        except Exception as e3:
                            debug_info.append(f"Pandas + xlrd also failed: {str(e3)}")

                            # Approach 4: Try without specifying engine
                            try:
                                df = pd.read_excel(file_path, header=0)
                                debug_info.append("Successfully read without specifying engine")
                            except Exception as e4:
                                debug_info.append(f"All pandas approaches failed. Last error: {str(e4)}")
                                excel_error = e4

                if df is None:
                    error_msg = f"Không thể đọc file Excel bằng bất kỳ phương pháp nào. Lỗi cuối cùng: {str(excel_error) if excel_error else 'Unknown error'}. Vui lòng kiểm tra: 1) File có đúng định dạng Excel (.xlsx hoặc .xls) không? 2) File có bị hỏng hoặc có mật khẩu không? 3) File có được lưu từ Excel thật sự không?"
                    return {
                        "success": False,
                        "message": error_msg,
                        "errors": [error_msg],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                debug_info.append(f"Excel file read successfully. Shape: {df.shape}")
                debug_info.append(f"Columns: {list(df.columns)}")

                # Check if dataframe has any data
                if df.empty:
                    debug_info.append(f"DataFrame is empty. Shape: {df.shape}")
                    return {
                        "success": False,
                        "message": "File Excel được đọc thành công nhưng không có dữ liệu. Vui lòng kiểm tra: 1) Bạn đã điền dữ liệu vào file mẫu chưa? 2) Dữ liệu có bắt đầu từ dòng 2 trở đi không? 3) File có bị xóa nhầm dữ liệu không?",
                        "errors": ["File Excel trống hoặc không có dữ liệu hợp lệ"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                # Check if there are any non-empty rows (skip header row)
                data_rows = 0
                for idx, row in df.iterrows():
                    # Check if row has any meaningful data
                    has_data = any(str(val).strip() for val in row.values if pd.notna(val))
                    if has_data:
                        data_rows += 1

                debug_info.append(f"Found {data_rows} rows with data (excluding header)")

                if data_rows == 0:
                    # Show sample of what was read
                    sample_rows = []
                    for idx, row in df.head(5).iterrows():
                        sample_rows.append(f"Row {idx + 1}: {dict(row)}")

                    debug_info.extend([
                        "Sample rows from file:",
                        *sample_rows
                    ])

                    return {
                        "success": False,
                        "message": f"File Excel có {len(df)} dòng nhưng không có dữ liệu hợp lệ. Vui lòng kiểm tra: 1) Dữ liệu có bắt đầu từ dòng 2 không? 2) Các cột có đúng tên không? 3) Ô dữ liệu có bị trống không?",
                        "errors": [f"Không tìm thấy dữ liệu hợp lệ trong {len(df)} dòng của file"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                debug_info.append(f"First 3 rows: {df.head(3).to_dict('records') if len(df) >= 3 else 'Less than 3 rows'}")

            except Exception as excel_error:
                debug_info.append(f"Unexpected error reading Excel file: {str(excel_error)}")
                error_msg = f"Lỗi không mong muốn khi đọc file Excel: {str(excel_error)}. Vui lòng thử lại hoặc liên hệ hỗ trợ kỹ thuật."
                return {
                    "success": False,
                    "message": error_msg,
                    "errors": [error_msg],
                    "debug_info": debug_info,
                    "warnings": self.warnings
                }

            if not self.validate_excel_structure(df):
                return {
                    "success": False,
                    "message": "Excel structure validation failed",
                    "errors": self.errors,
                    "warnings": self.warnings,
                    "debug_info": debug_info
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
                    "valid_rows": len(processed_rooms),
                    "debug_info": debug_info
                }

            if not dry_run and processed_rooms:
                # Create rooms in database
                created_count = 0
                for room_data in processed_rooms:
                    try:
                        room_data_dict = {
                            "doctype": "ERP Administrative Room",
                            "title_vn": room_data['title_vn'],
                            "title_en": room_data.get('title_en') or room_data['title_vn'],  # Fallback to title_vn if empty
                            "short_title": room_data['short_title'],
                            "room_type": room_data['room_type'],
                            "campus_id": self.campus_id
                        }

                        # Only add building_id if it exists
                        if room_data.get('building_id'):
                            room_data_dict["building_id"] = room_data['building_id']

                        # Only add capacity if it has a value
                        if room_data.get('capacity') is not None:
                            room_data_dict["capacity"] = room_data['capacity']

                        room_doc = frappe.get_doc(room_data_dict)
                        room_doc.insert()
                        created_count += 1
                    except Exception as e:
                        self.errors.append(f"Error creating room {room_data.get('title_vn')}: {str(e)}")

                frappe.db.commit()

            result = {
                "success": True,
                "message": f"Import completed successfully. Created {created_count} rooms." if not dry_run else "Dry run completed successfully",
                "total_rows": len(df),
                "created_count": created_count if not dry_run else 0,
                "valid_rows": len(processed_rooms),
                "errors": self.errors,
                "warnings": self.warnings,
                "debug_info": debug_info
            }

            # Add validation errors if any
            if validation_errors:
                result["validation_errors"] = validation_errors
                result["invalid_rows"] = len(validation_errors)

            return result

        except Exception as e:
            debug_info.append(f"Exception occurred: {str(e)}")
            return {
                "success": False,
                "message": f"Error processing Excel import: {str(e)}",
                "errors": self.errors,
                "debug_info": debug_info
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

    # Debug: Check file_data type and size
    file_size = len(file_data) if not hasattr(file_data, 'read') else "unknown (stream)"
    frappe.logger().info(f"Saving file: {filename}, size: {file_size}, type: {type(file_data)}")

    # Save file
    try:
        with open(file_path, 'wb') as f:
            if hasattr(file_data, 'read'):
                content = file_data.read()
                f.write(content)
                actual_size = len(content)
            else:
                f.write(file_data)
                actual_size = len(file_data)

        # Verify file was saved
        if os.path.exists(file_path):
            saved_size = os.path.getsize(file_path)
            frappe.logger().info(f"File saved successfully: {file_path}, saved size: {saved_size}")
            if saved_size == 0:
                frappe.logger().error("File was saved but is empty!")
        else:
            frappe.logger().error(f"File was not saved: {file_path}")

    except Exception as save_error:
        frappe.logger().error(f"Error saving file: {str(save_error)}")
        raise save_error

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
                return validation_error_response("No file uploaded", {"file": ["No file uploaded"]})

            # Debug file information before saving
            frappe.logger().info(f"File data type: {type(file_data)}")
            frappe.logger().info(f"File data attributes: {dir(file_data) if hasattr(file_data, '__dict__') else 'No __dict__'}")

            if hasattr(file_data, 'filename'):
                frappe.logger().info(f"Original filename: {file_data.filename}")
            if hasattr(file_data, 'content_type'):
                frappe.logger().info(f"Content type: {file_data.content_type}")

            # Save file temporarily
            file_path = save_uploaded_file(file_data, "rooms_import.xlsx")

            # Process Excel import
            importer = RoomExcelImporter(campus_id)
            result = importer.process_excel_import(file_path, dry_run)

            # Add file save info to debug_info if available
            if 'debug_info' not in result:
                result['debug_info'] = []
            result['debug_info'].insert(0, f"File saved to: {file_path}")

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


class BuildingExcelImporter:
    """Handle Excel import for Buildings with validation and mapping"""

    def __init__(self, campus_id: str):
        self.campus_id = campus_id
        self.errors: list = []
        self.warnings: list = []

    def validate_excel_structure(self, df):
        """Validate Excel file structure for building import

        Required columns: title_vn, title_en, short_title
        Optional columns: description
        """
        # Check if dataframe is empty after reading
        if df is None or df.empty:
            self.errors.append("File Excel không thể đọc được hoặc file trống. Vui lòng kiểm tra: 1) File có đúng định dạng .xlsx hoặc .xls không? 2) File có bị hỏng không? 3) Bạn đã điền dữ liệu vào file mẫu chưa?")
            return False

        # Normalize column names
        df = self.normalize_columns(df)

        required_cols = ['title_vn', 'title_en', 'short_title']
        cols_lower = [str(c).strip().lower() for c in df.columns]

        missing_cols = []
        for col in required_cols:
            if col not in cols_lower:
                missing_cols.append(col)

        if missing_cols:
            self.errors.append(f"Missing required columns: {', '.join(missing_cols)}")
            return False

        # Check if there's at least one data row (skip empty rows)
        data_rows = 0
        for idx, row in df.iterrows():
            # Check if at least one required field has data
            has_data = any(str(row.get(col, '')).strip() for col in required_cols)
            if has_data:
                data_rows += 1

        if data_rows == 0:
            self.errors.append("No valid data rows found. Please ensure data starts from row 2 and required columns are filled")
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
                'mã tòa nhà': 'short_title',
                'mô tả': 'description',
                'description': 'description'
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

    def process_excel_import(self, file_path, dry_run=False):
        """Process Excel import for buildings"""
        if not pd:
            return {"success": False, "message": "pandas library not available"}

        try:
            # Debug: Check if file exists and readable
            import os
            debug_info = []
            debug_info.append(f"Excel file path: {file_path}")
            debug_info.append(f"File exists: {os.path.exists(file_path)}")

            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                debug_info.append(f"File size: {file_size} bytes")

                if file_size == 0:
                    return {
                        "success": False,
                        "message": "Excel file is empty (0 bytes)",
                        "errors": ["Uploaded file is empty"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }
            else:
                return {
                    "success": False,
                    "message": "Excel file not found",
                    "errors": ["File was not uploaded successfully"],
                    "debug_info": debug_info,
                    "warnings": self.warnings
                }

            # Basic file validation before pandas
            debug_info.append("Basic file validation...")
            try:
                with open(file_path, 'rb') as f:
                    file_header = f.read(512)  # Read first 512 bytes

                file_size = len(file_header)
                debug_info.append(f"File header size: {file_size} bytes")

                if file_size < 4:
                    return {
                        "success": False,
                        "message": "File quá nhỏ, có thể không phải file Excel hợp lệ.",
                        "errors": ["File size too small"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                # Check for Excel signatures
                header_hex = file_header[:8].hex()
                debug_info.append(f"File header (hex): {header_hex}")

                # Check for common Excel signatures
                if header_hex.startswith('504b0304'):  # PK\x03\x04 - ZIP/XLSX
                    debug_info.append("Detected ZIP/XLSX file signature")
                elif header_hex.startswith('d0cf11e0a1b11ae1'):  # XLS signature
                    debug_info.append("Detected XLS file signature")
                else:
                    debug_info.append("Warning: File does not have standard Excel signature")

            except Exception as file_error:
                debug_info.append(f"Error reading file header: {str(file_error)}")
                return {
                    "success": False,
                    "message": f"Không thể đọc header của file: {str(file_error)}",
                    "errors": [f"File header read error: {str(file_error)}"],
                    "debug_info": debug_info,
                    "warnings": self.warnings
                }

            # Read Excel file (skip first row if it's sample data)
            debug_info.append("Attempting to read Excel file with pandas...")
            try:
                # First check if pandas is available
                if not pd:
                    return {
                        "success": False,
                        "message": "Pandas library not available on server",
                        "errors": ["Server configuration error: pandas library missing"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                # Try reading Excel file with multiple approaches
                df = None
                excel_error = None

                # Approach 1: Standard read_excel with openpyxl
                try:
                    df = pd.read_excel(file_path, header=0, engine='openpyxl')
                    debug_info.append("Successfully read with pandas + openpyxl engine")
                except Exception as e1:
                    debug_info.append(f"Pandas + openpyxl failed: {str(e1)}")
                    excel_error = e1

                    # Approach 2: Try direct openpyxl if available
                    try:
                        import openpyxl
                        wb = openpyxl.load_workbook(file_path, data_only=True)
                        sheet = wb.active

                        # Convert to pandas DataFrame manually
                        data = []
                        headers = []
                        for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
                            if row_idx == 0:  # First row is headers
                                headers = [str(cell) if cell is not None else '' for cell in row]
                            else:
                                data.append([cell for cell in row])

                        if headers and data:
                            df = pd.DataFrame(data, columns=headers)
                            debug_info.append("Successfully read with direct openpyxl")
                        else:
                            raise Exception("No headers or data found")

                    except ImportError:
                        debug_info.append("openpyxl not available for direct reading")
                    except Exception as e2:
                        debug_info.append(f"Direct openpyxl failed: {str(e2)}")

                        # Approach 3: Try xlrd engine for .xls files
                        try:
                            df = pd.read_excel(file_path, header=0, engine='xlrd')
                            debug_info.append("Successfully read with pandas + xlrd engine")
                        except Exception as e3:
                            debug_info.append(f"Pandas + xlrd also failed: {str(e3)}")

                            # Approach 4: Try without specifying engine
                            try:
                                df = pd.read_excel(file_path, header=0)
                                debug_info.append("Successfully read without specifying engine")
                            except Exception as e4:
                                debug_info.append(f"All pandas approaches failed. Last error: {str(e4)}")
                                excel_error = e4

                if df is None:
                    error_msg = f"Không thể đọc file Excel bằng bất kỳ phương pháp nào. Lỗi cuối cùng: {str(excel_error) if excel_error else 'Unknown error'}. Vui lòng kiểm tra: 1) File có đúng định dạng Excel (.xlsx hoặc .xls) không? 2) File có bị hỏng hoặc có mật khẩu không? 3) File có được lưu từ Excel thật sự không?"
                    return {
                        "success": False,
                        "message": error_msg,
                        "errors": [error_msg],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                debug_info.append(f"Excel file read successfully. Shape: {df.shape}")
                debug_info.append(f"Columns: {list(df.columns)}")

                # Check if dataframe has any data
                if df.empty:
                    debug_info.append(f"DataFrame is empty. Shape: {df.shape}")
                    return {
                        "success": False,
                        "message": "File Excel được đọc thành công nhưng không có dữ liệu. Vui lòng kiểm tra: 1) Bạn đã điền dữ liệu vào file mẫu chưa? 2) Dữ liệu có bắt đầu từ dòng 2 trở đi không? 3) File có bị xóa nhầm dữ liệu không?",
                        "errors": ["File Excel trống hoặc không có dữ liệu hợp lệ"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                # Check if there are any non-empty rows (skip header row)
                data_rows = 0
                for idx, row in df.iterrows():
                    # Check if row has any meaningful data
                    has_data = any(str(val).strip() for val in row.values if pd.notna(val))
                    if has_data:
                        data_rows += 1

                debug_info.append(f"Found {data_rows} rows with data (excluding header)")

                if data_rows == 0:
                    # Show sample of what was read
                    sample_rows = []
                    for idx, row in df.head(5).iterrows():
                        sample_rows.append(f"Row {idx + 1}: {dict(row)}")

                    debug_info.extend([
                        "Sample rows from file:",
                        *sample_rows
                    ])

                    return {
                        "success": False,
                        "message": f"File Excel có {len(df)} dòng nhưng không có dữ liệu hợp lệ. Vui lòng kiểm tra: 1) Dữ liệu có bắt đầu từ dòng 2 không? 2) Các cột có đúng tên không? 3) Ô dữ liệu có bị trống không?",
                        "errors": [f"Không tìm thấy dữ liệu hợp lệ trong {len(df)} dòng của file"],
                        "debug_info": debug_info,
                        "warnings": self.warnings
                    }

                debug_info.append(f"First 3 rows: {df.head(3).to_dict('records') if len(df) >= 3 else 'Less than 3 rows'}")

            except Exception as excel_error:
                debug_info.append(f"Unexpected error reading Excel file: {str(excel_error)}")
                error_msg = f"Lỗi không mong muốn khi đọc file Excel: {str(excel_error)}. Vui lòng thử lại hoặc liên hệ hỗ trợ kỹ thuật."
                return {
                    "success": False,
                    "message": error_msg,
                    "errors": [error_msg],
                    "debug_info": debug_info,
                    "warnings": self.warnings
                }

            if not self.validate_excel_structure(df):
                return {
                    "success": False,
                    "message": "Excel structure validation failed",
                    "errors": self.errors,
                    "warnings": self.warnings,
                    "debug_info": debug_info
                }

            # Normalize columns
            df = self.normalize_columns(df)

            # Process each row
            processed_buildings = []
            validation_errors = []

            for index, row in df.iterrows():
                row_data = {
                    'title_vn': row.get('title_vn'),
                    'title_en': row.get('title_en'),
                    'short_title': row.get('short_title'),
                    'description': row.get('description')
                }

                # Validate row data
                row_errors = self.validate_building_data(row_data)
                if row_errors:
                    validation_errors.append({
                        "row": index + 2,  # +2 because Excel is 1-indexed and has header
                        "data": row_data,
                        "errors": row_errors
                    })
                else:
                    processed_buildings.append(row_data)

            if validation_errors and dry_run:
                return {
                    "success": False,
                    "message": "Validation failed",
                    "validation_errors": validation_errors,
                    "total_rows": len(df),
                    "valid_rows": len(processed_buildings),
                    "debug_info": debug_info
                }

            if not dry_run and processed_buildings:
                # Create buildings in database
                created_count = 0
                for building_data in processed_buildings:
                    try:
                        building_doc = frappe.get_doc({
                            "doctype": "ERP Administrative Building",
                            "title_vn": building_data['title_vn'],
                            "title_en": building_data['title_en'],
                            "short_title": building_data['short_title'],
                            "description": building_data.get('description', ''),
                            "campus_id": self.campus_id
                        })
                        building_doc.insert()
                        created_count += 1
                    except Exception as e:
                        self.errors.append(f"Error creating building {building_data.get('title_vn')}: {str(e)}")

                frappe.db.commit()

            return {
                "success": True,
                "message": f"Import completed successfully. Created {created_count} buildings." if not dry_run else "Dry run completed successfully",
                "total_rows": len(df),
                "created_count": created_count if not dry_run else 0,
                "errors": self.errors,
                "warnings": self.warnings,
                "debug_info": debug_info
            }

        except Exception as e:
            debug_info.append(f"Exception occurred: {str(e)}")
            return {
                "success": False,
                "message": f"Error processing Excel import: {str(e)}",
                "errors": self.errors,
                "debug_info": debug_info
            }

    def validate_building_data(self, row_data):
        """Validate building row data"""
        errors = []

        # Required fields validation
        if not row_data.get('title_vn') or str(row_data['title_vn']).strip() == '':
            errors.append("Tên tiếng Việt không được để trống")

        if not row_data.get('title_en') or str(row_data['title_en']).strip() == '':
            errors.append("Tên tiếng Anh không được để trống")

        if not row_data.get('short_title') or str(row_data['short_title']).strip() == '':
            errors.append("Ký hiệu tòa nhà không được để trống")

        # Check for duplicates in the same import
        if hasattr(self, '_temp_buildings'):
            for existing in self._temp_buildings:
                if (existing['title_vn'] == row_data['title_vn'] or
                    existing['title_en'] == row_data['title_en'] or
                    existing['short_title'] == row_data['short_title']):
                    errors.append("Tòa nhà đã tồn tại trong file import này")
                    break

        # Check against existing buildings in database
        if row_data.get('title_vn'):
            existing = frappe.db.exists("ERP Administrative Building", {
                "title_vn": row_data['title_vn'],
                "campus_id": self.campus_id
            })
            if existing:
                errors.append(f"Tòa nhà với tên '{row_data['title_vn']}' đã tồn tại")

        if row_data.get('short_title'):
            existing = frappe.db.exists("ERP Administrative Building", {
                "short_title": row_data['short_title'],
                "campus_id": self.campus_id
            })
            if existing:
                errors.append(f"Tòa nhà với ký hiệu '{row_data['short_title']}' đã tồn tại")

        return errors


@frappe.whitelist(allow_guest=False)
def import_buildings():
    """Import buildings from Excel file"""
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
                return validation_error_response("No file uploaded", {"file": ["No file uploaded"]})

            # Debug file information before saving
            frappe.logger().info(f"File data type: {type(file_data)}")
            frappe.logger().info(f"File data attributes: {dir(file_data) if hasattr(file_data, '__dict__') else 'No __dict__'}")

            if hasattr(file_data, 'filename'):
                frappe.logger().info(f"Original filename: {file_data.filename}")
            if hasattr(file_data, 'content_type'):
                frappe.logger().info(f"Content type: {file_data.content_type}")

            # Save file temporarily
            file_path = save_uploaded_file(file_data, "buildings_import.xlsx")

            # Process Excel import
            importer = BuildingExcelImporter(campus_id)
            result = importer.process_excel_import(file_path, dry_run)

            # Add file save info to debug_info if available
            if 'debug_info' not in result:
                result['debug_info'] = []
            result['debug_info'].insert(0, f"File saved to: {file_path}")

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
        frappe.log_error(f"Error importing buildings: {str(e)}")
        return error_response(f"Error importing buildings: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_timetable_subjects_for_room_class(education_grade: str = None):
    """Get timetable subjects filtered by education grade for room class assignment"""
    try:
        # Handle both GET and POST requests
        if not education_grade:
            form = frappe.local.form_dict or {}
            education_grade = form.get("education_grade")
            if not education_grade and frappe.request and frappe.request.args:
                education_grade = frappe.request.args.get('education_grade')
            # Also check in request body for POST requests
            if not education_grade and frappe.request and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body or '{}')
                    education_grade = data.get('education_grade')
                except Exception:
                    pass

        if not education_grade:
            return validation_error_response("education_grade is required", {"education_grade": ["education_grade is required"]})

        # Get education stage from education grade
        education_grade_doc = frappe.get_all(
            "SIS Education Grade",
            fields=["education_stage_id"],
            filters={"name": education_grade},
            limit=1
        )

        if not education_grade_doc or not education_grade_doc[0].get("education_stage_id"):
            return validation_error_response("Education grade not found or has no education stage", {"education_grade": ["Invalid education grade"]})

        education_stage_id = education_grade_doc[0]["education_stage_id"]

        # Get timetable subjects filtered by education stage
        subjects = frappe.get_all(
            "SIS Timetable Subject",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "education_stage_id"
            ],
            filters={"education_stage_id": education_stage_id},
            order_by="title_vn asc"
        )

        # Enhance with additional info
        enhanced_subjects = []
        for subject in subjects:
            enhanced_subject = {
                "name": subject.name,
                "subject_name": subject.title_vn or subject.title_en,
                "subject_code": subject.name,  # Use name as code for now
                "education_grade": education_grade,
                "education_stage_id": subject.education_stage_id
            }

            # Get education stage title if education_stage_id exists
            if subject.education_stage_id:
                stage_info = frappe.get_all(
                    "SIS Education Stage",
                    fields=["title_vn"],
                    filters={"name": subject.education_stage_id},
                    limit=1
                )
                if stage_info:
                    enhanced_subject["education_stage_title"] = stage_info[0].get("title_vn")

            enhanced_subjects.append(enhanced_subject)

        return success_response(
            data=enhanced_subjects,
            message="Timetable subjects retrieved successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error getting timetable subjects: {str(e)}")
        return error_response(f"Error getting timetable subjects: {str(e)}")


@frappe.whitelist(allow_guest=False)
def available_rooms_for_class_selection(class_type: str):
    """Get available rooms for class selection based on class type"""
    try:
        if not class_type:
            return validation_error_response("class_type is required", {"class_type": ["class_type is required"]})

        # Get all rooms
        rooms = frappe.get_all(
            "ERP Administrative Room",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "short_title",
                "room_type",
                "building_id",
                "capacity"
            ],
            filters={"campus_id": frappe.local.session.get("campus_id")},
            order_by="title_vn asc"
        )

        enhanced_rooms = []

        for room in rooms:
            # Get building info
            building_title = None
            if room.building_id:
                building_info = frappe.get_all(
                    "ERP Administrative Building",
                    fields=["title_vn"],
                    filters={"name": room.building_id},
                    limit=1
                )
                if building_info:
                    building_title = building_info[0].get("title_vn")

            enhanced_room = {
                "name": room.name,
                "title": room.title_vn,
                "short_title": room.short_title,
                "room_type": room.room_type,
                "building_title": building_title,
                "capacity": room.capacity,
                "suggested_usage": None,
                "suggested_usage_display": None,
                "available": True,
                "reason": None
            }

            # Apply filtering logic based on class_type
            if class_type == "regular":
                # Only classroom rooms available and check if already has homeroom
                if room.room_type != "classroom_room":
                    enhanced_room["available"] = False
                    enhanced_room["reason"] = "Chỉ phòng học mới có thể làm lớp chủ nhiệm"
                else:
                    # Check if room already has a homeroom class
                    room_doc = frappe.get_doc("ERP Administrative Room", room.name)
                    has_homeroom = False
                    if hasattr(room_doc, 'room_classes'):
                        for room_class in room_doc.room_classes:
                            if room_class.usage_type == "homeroom":
                                has_homeroom = True
                                break

                    if has_homeroom:
                        enhanced_room["available"] = False
                        enhanced_room["reason"] = "Phòng này đã có lớp chủ nhiệm"
                    else:
                        enhanced_room["suggested_usage"] = "homeroom"
                        enhanced_room["suggested_usage_display"] = "Lớp chủ nhiệm"

            else:  # mixed or club classes
                # All rooms available, will be functional
                enhanced_room["suggested_usage"] = "functional"
                enhanced_room["suggested_usage_display"] = "Lớp chức năng"

            enhanced_rooms.append(enhanced_room)

        # Filter to only available rooms for regular classes, show all for others
        if class_type == "regular":
            result_rooms = [room for room in enhanced_rooms if room["available"]]
        else:
            result_rooms = enhanced_rooms

        return success_response(
            data=result_rooms,
            message="Available rooms retrieved successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error getting available rooms: {str(e)}")
        return error_response(f"Error getting available rooms: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_room_classes(room_id: str = None):
    """Get all classes assigned to a room"""
    frappe.logger().info("get_room_classes function called")
    try:
        frappe.logger().info(f"Initial room_id parameter: {room_id}")
        frappe.logger().info(f"frappe.local.form_dict: {frappe.local.form_dict}")
        frappe.logger().info(f"frappe.request: {frappe.request}")
        if frappe.request and hasattr(frappe.request, 'data'):
            frappe.logger().info(f"frappe.request.data: {frappe.request.data}")

        if not room_id:
            form = frappe.local.form_dict or {}
            room_id = form.get("room_id") or form.get("name")
            frappe.logger().info(f"room_id from form: {room_id}")
            if not room_id and frappe.request and frappe.request.args:
                room_id = frappe.request.args.get('room_id') or frappe.request.args.get('name')
                frappe.logger().info(f"room_id from args: {room_id}")
            # Also check in request body for POST requests
            if not room_id and frappe.request and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body or '{}')
                    room_id = data.get('room_id')
                except Exception:
                    pass
        if not room_id:
            return validation_error_response("Room ID is required", {"room_id": ["Room ID is required"]})

        frappe.logger().info(f"get_room_classes processing room_id: {room_id}")

        # Check if room exists
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response("Room not found")

        # Get room classes from child table (new method)
        enhanced_classes = []
        child_table_has_data = False

        try:
            # Use frappe.get_all to safely fetch child table records
            room_classes_data = frappe.get_all(
                "ERP Administrative Room Class",
                fields=["name", "class_id", "usage_type", "subject_id", "class_title", "school_year_id", "education_grade", "academic_program", "homeroom_teacher"],
                filters={"parent": room_id, "parenttype": "ERP Administrative Room"},
                order_by="creation asc"
            )
            
            if room_classes_data:
                child_table_has_data = True
                frappe.logger().info(f"Found {len(room_classes_data)} classes in child table")
                
                for room_class in room_classes_data:
                    frappe.logger().info(f"Processing room class: {room_class.class_id}, usage: {room_class.usage_type}")
                    try:
                        class_doc = frappe.get_doc("SIS Class", room_class.class_id)
                        frappe.logger().info(f"Got class doc: {class_doc.name}")
                    except Exception as e:
                        frappe.logger().error(f"Failed to get class doc {room_class.class_id}: {str(e)}")
                        continue

                    # Get education grade title
                    education_grade_title = None
                    if class_doc.education_grade:
                        grade_info = frappe.get_all(
                            "SIS Education Grade",
                            fields=["title_vn"],
                            filters={"name": class_doc.education_grade},
                            limit=1
                        )
                        if grade_info:
                            education_grade_title = grade_info[0].get("title_vn")

                    # Get academic program title
                    academic_program_title = None
                    if class_doc.academic_program:
                        program_info = frappe.get_all(
                            "SIS Academic Program",
                            fields=["title_vn"],
                            filters={"name": class_doc.academic_program},
                            limit=1
                        )
                        if program_info:
                            academic_program_title = program_info[0].get("title_vn")

                    enhanced_class = {
                        "name": class_doc.name,
                        "title": class_doc.title,
                        "short_title": class_doc.short_title,
                        "class_type": class_doc.class_type,
                        "school_year_id": class_doc.school_year_id,
                        "campus_id": class_doc.campus_id,
                        "education_grade": education_grade_title or class_doc.education_grade,
                        "academic_program": academic_program_title or class_doc.academic_program,
                        "homeroom_teacher": class_doc.homeroom_teacher,
                        "creation": class_doc.creation,
                        "modified": class_doc.modified,
                        "usage_type": room_class.usage_type,
                        "usage_type_display": "Lớp chủ nhiệm" if room_class.usage_type == "homeroom" else "Lớp chức năng",
                        "subject_id": room_class.subject_id,
                        "subject_name": None,
                        "subject_code": None
                    }

                    # Get subject info if subject_id exists
                    if room_class.subject_id:
                        try:
                            subject_doc = frappe.get_doc("SIS Timetable Subject", room_class.subject_id)
                            enhanced_class["subject_name"] = subject_doc.title_vn or subject_doc.title_en
                            enhanced_class["subject_code"] = subject_doc.name
                        except Exception as e:
                            frappe.logger().warning(f"Failed to get subject {room_class.subject_id}: {str(e)}")

                    # Add teacher info
                    if class_doc.homeroom_teacher:
                        teacher_info = frappe.get_all(
                            "SIS Teacher",
                            fields=["user_id"],
                            filters={"name": class_doc.homeroom_teacher},
                            limit=1
                        )
                        if teacher_info and teacher_info[0].get("user_id"):
                            user_info = frappe.get_all(
                                "User",
                                fields=["full_name"],
                                filters={"name": teacher_info[0]["user_id"]},
                                limit=1
                            )
                            if user_info:
                                enhanced_class["homeroom_teacher_name"] = user_info[0].get("full_name")

                    enhanced_classes.append(enhanced_class)

        except Exception as e:
            frappe.logger().warning(f"Error fetching from child table: {str(e)}")
            child_table_has_data = False

        # If child table has no data or failed, fallback to legacy method
        if not child_table_has_data:
            frappe.logger().info(f"Falling back to legacy method for room {room_id}")
            # Fallback to legacy method (classes with room field)
            classes = frappe.get_all(
                "SIS Class",
                fields=[
                    "name",
                    "title",
                    "short_title",
                    "class_type",
                    "school_year_id",
                    "campus_id",
                    "education_grade",
                    "academic_program",
                    "homeroom_teacher",
                    "creation",
                    "modified"
                ],
                filters={"room": room_id},
                order_by="title asc"
            )

            frappe.logger().info(f"Found {len(classes)} classes via legacy method")
            for class_data in classes:
                # Skip if already added from child table (to avoid duplicates)
                if any(ec["name"] == class_data["name"] for ec in enhanced_classes):
                    continue

                # Get education grade title
                education_grade_title = None
                if class_data.get("education_grade"):
                    grade_info = frappe.get_all(
                        "SIS Education Grade",
                        fields=["title_vn"],
                        filters={"name": class_data["education_grade"]},
                        limit=1
                    )
                    if grade_info:
                        education_grade_title = grade_info[0].get("title_vn")

                # Get academic program title
                academic_program_title = None
                if class_data.get("academic_program"):
                    program_info = frappe.get_all(
                        "SIS Academic Program",
                        fields=["title_vn"],
                        filters={"name": class_data["academic_program"]},
                        limit=1
                    )
                    if program_info:
                        academic_program_title = program_info[0].get("title_vn")

                enhanced_class = class_data.copy()
                enhanced_class["education_grade"] = education_grade_title or class_data.get("education_grade")
                enhanced_class["academic_program"] = academic_program_title or class_data.get("academic_program")

                # Determine usage type based on class_type
                if class_data.get("class_type") == "regular":
                    enhanced_class["usage_type"] = "homeroom"
                    enhanced_class["usage_type_display"] = "Lớp chủ nhiệm"
                else:
                    enhanced_class["usage_type"] = "functional"
                    enhanced_class["usage_type_display"] = "Lớp chức năng"

                # Add teacher info
                if class_data.get("homeroom_teacher"):
                    teacher_info = frappe.get_all(
                        "SIS Teacher",
                        fields=["user_id"],
                        filters={"name": class_data["homeroom_teacher"]},
                        limit=1
                    )
                    if teacher_info and teacher_info[0].get("user_id"):
                        user_info = frappe.get_all(
                            "User",
                            fields=["full_name"],
                            filters={"name": teacher_info[0]["user_id"]},
                            limit=1
                        )
                        if user_info:
                            enhanced_class["homeroom_teacher_name"] = user_info[0].get("full_name")

                enhanced_classes.append(enhanced_class)

        # Add debug info to response
        debug_info = {
            "room_id": room_id,
            "child_table_has_data": child_table_has_data,
            "total_classes_found": len(enhanced_classes),
            "classes": [{"name": c["name"], "usage_type": c["usage_type"]} for c in enhanced_classes]
        }

        frappe.logger().info(f"Returning {len(enhanced_classes)} classes for room {room_id}")

        return success_response(
            data=enhanced_classes,
            message="Room classes fetched successfully",
            debug_info=debug_info
        )

    except Exception as e:
        frappe.log_error(f"Error fetching room classes: {str(e)}")
        return error_response(f"Error fetching room classes: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def add_room_class():
    """Add a class to a room"""
    frappe.logger().info("add_room_class called")
    try:
        data = {}
        if frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
            except Exception:
                data = frappe.local.form_dict or {}
        else:
            data = frappe.local.form_dict or {}

        required = ["room_id", "class_id"]
        for field in required:
            if not data.get(field):
                return validation_error_response({field: [f"{field} is required"]})

        room_id = data.get("room_id")
        class_id = data.get("class_id")
        usage_type = data.get("usage_type")
        subject_id = data.get("subject_id")  # Optional for functional classes

        # Validate room exists
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response("Room not found")

        # Validate class exists
        if not frappe.db.exists("SIS Class", class_id):
            return not_found_response("Class not found")

        # Get class info
        class_info = frappe.get_doc("SIS Class", class_id)

        # Auto-determine usage_type if not provided
        if not usage_type:
            usage_type = "homeroom" if class_info.class_type == "regular" else "functional"
            frappe.logger().info(f"Auto-determined usage_type for class {class_id}: {usage_type} (class_type: {class_info.class_type})")

        # Validate usage_type
        if usage_type not in ["homeroom", "functional"]:
            return validation_error_response("Invalid usage type", {"usage_type": ["Usage type must be 'homeroom' or 'functional'"]})

        # Get room document
        room_doc = frappe.get_doc("ERP Administrative Room", room_id)

        # Check if class is already assigned to this room
        existing_assignment = None
        if hasattr(room_doc, 'room_classes'):
            for room_class in room_doc.room_classes:
                if room_class.class_id == class_id:
                    existing_assignment = room_class
                    break

        if existing_assignment:
            return validation_error_response(
                "Lớp đã được gán cho phòng này",
                {"class_id": ["Lớp này đã được gán cho phòng này rồi."]}
            )

        # Business logic: sync with SIS Class room field for homeroom
        if usage_type == "homeroom":
            # For homeroom usage, only allow if class_type is "regular"
            if class_info.class_type != "regular":
                return validation_error_response(
                    "Không thể đặt lớp này làm lớp chủ nhiệm",
                    {"usage_type": ["Chỉ lớp có loại 'regular' mới có thể làm lớp chủ nhiệm"]}
                )

            # Check if room already has a homeroom class (both in child table and legacy room field)
            # Check child table
            if hasattr(room_doc, 'room_classes'):
                for room_class in room_doc.room_classes:
                    if room_class.usage_type == "homeroom":
                        return validation_error_response(
                            "Phòng đã có lớp chủ nhiệm",
                            {"room_id": ["Phòng này đã có lớp chủ nhiệm. Một phòng chỉ có thể có 1 lớp chủ nhiệm."]}
                        )

            # Check legacy room field for backward compatibility
            existing_homeroom = frappe.get_all(
                "SIS Class",
                fields=["name", "title"],
                filters={"room": room_id, "class_type": "regular"},
                limit=1
            )

            if existing_homeroom:
                return validation_error_response(
                    "Phòng đã có lớp chủ nhiệm",
                    {"room_id": [f"Phòng này đã có lớp chủ nhiệm: {existing_homeroom[0].title}. Một phòng chỉ có thể có 1 lớp chủ nhiệm."]}
                )

            # Check if class is already homeroom for another room (legacy check)
            if class_info.room and class_info.room != room_id:
                return validation_error_response(
                    "Lớp đã là chủ nhiệm cho phòng khác",
                    {"class_id": ["Lớp này đã là lớp chủ nhiệm cho phòng khác. Không thể gán làm chủ nhiệm cho phòng này."]}
                )

            # Update class.room to this room (legacy compatibility)
            frappe.db.set_value("SIS Class", class_id, "room", room_id)
            frappe.logger().info(f"Updated SIS Class {class_id} room to {room_id} for homeroom usage")

        else:  # functional usage
            # For functional usage, require subject_id
            if not subject_id:
                return validation_error_response(
                    "Môn học là bắt buộc",
                    {"subject_id": ["Phải chọn môn học cho lớp chức năng"]}
                )

            # Validate subject exists
            if not frappe.db.exists("SIS Timetable Subject", subject_id):
                return validation_error_response("Môn học không tồn tại", {"subject_id": ["Môn học không tồn tại"]})

            # TODO: Add validation for subject compatibility with class education grade
            # Currently skipping validation as relationship needs to be clarified

            # For functional usage, check if class is already a homeroom somewhere (legacy check)
            if class_info.room and class_info.room != room_id and class_info.class_type == "regular":
                return validation_error_response(
                    "Lớp đã là chủ nhiệm",
                    {"class_id": ["Lớp này đang là lớp chủ nhiệm cho phòng khác. Không thể thêm làm phòng chức năng."]}
                )

            # For functional usage, we don't update class.room field to avoid conflicts with homeroom assignments

        # Add to Room Classes child table
        try:
            frappe.logger().info(f"Attempting to add class {class_id} to room {room_id}")

            # Get the room document
            room_doc = frappe.get_doc("ERP Administrative Room", room_id)
            frappe.logger().info(f"Got room doc: {room_doc.name}")

            # Append new room class to the child table
            room_class_data = {
                "class_id": class_id,
                "usage_type": usage_type,
                "class_title": class_info.title,
                "school_year_id": class_info.school_year_id,
                "education_grade": class_info.education_grade,
                "academic_program": class_info.academic_program,
                "homeroom_teacher": class_info.homeroom_teacher,
                "subject_id": subject_id if usage_type == "functional" else None
            }

            frappe.logger().info(f"Appending room class data: {room_class_data}")
            room_doc.append("room_classes", room_class_data)

            frappe.logger().info(f"Saving room doc...")
            room_doc.save(ignore_permissions=True)
            frappe.logger().info(f"Room doc saved successfully")

            frappe.db.commit()  # Ensure the transaction is committed
            frappe.logger().info(f"Added class {class_id} to room {room_id} with usage {usage_type}")

        except Exception as e:
            frappe.logger().error(f"Failed to add to child table: {str(e)}")
            frappe.logger().error(f"Exception type: {type(e).__name__}")
            import traceback
            frappe.logger().error(f"Traceback: {traceback.format_exc()}")
            return error_response(f"Không thể thêm lớp vào phòng: {str(e)}")

        frappe.db.commit()

        return success_response(
            data={
                "room_id": room_id,
                "class_id": class_id,
                "usage_type": usage_type,
                "subject_id": subject_id,
                "class_title": class_info.title,
                "class_type": class_info.class_type
            },
            message="Class added to room successfully"
        )
        frappe.logger().info(f"add_room_class completed successfully for class {class_id}")

    except Exception as e:
        frappe.log_error(f"Error adding room class: {str(e)}")
        return error_response(f"Error adding room class: {str(e)}")


def sync_class_room_assignment(doc, method):
    """Sync room assignment when SIS Class.room field is updated"""
    try:
        # Only process if room field was changed
        if not doc.has_value_changed('room'):
            return

        old_room = doc.get_doc_before_save().get('room') if doc.get_doc_before_save() else None
        new_room = doc.room

        # Remove from old room if exists
        if old_room:
            try:
                old_room_doc = frappe.get_doc("ERP Administrative Room", old_room)
                if hasattr(old_room_doc, 'room_classes'):
                    # Find and remove this class from old room
                    for i, room_class in enumerate(old_room_doc.room_classes):
                        if room_class.class_id == doc.name and room_class.usage_type == "homeroom":
                            old_room_doc.room_classes.pop(i)
                            old_room_doc.save()
                            frappe.logger().info(f"Removed class {doc.name} from old room {old_room}")
                            break
            except Exception as e:
                frappe.logger().warning(f"Could not remove class {doc.name} from old room {old_room}: {str(e)}")

        # Add to new room if exists
        if new_room:
            try:
                new_room_doc = frappe.get_doc("ERP Administrative Room", new_room)

                # Check if already exists
                existing = False
                if hasattr(new_room_doc, 'room_classes'):
                    for room_class in new_room_doc.room_classes:
                        if room_class.class_id == doc.name:
                            existing = True
                            break

                if not existing:
                    # Determine usage type
                    usage_type = "homeroom" if doc.class_type == "regular" else "functional"

                    # Add to child table
                    new_room_doc.append("room_classes", {
                        "class_id": doc.name,
                        "usage_type": usage_type,
                        "class_title": doc.title,
                        "school_year_id": doc.school_year_id,
                        "education_grade": doc.education_grade,
                        "academic_program": doc.academic_program,
                        "homeroom_teacher": doc.homeroom_teacher
                    })
                    new_room_doc.save()
                    frappe.logger().info(f"Added class {doc.name} to new room {new_room} with usage {usage_type}")

            except Exception as e:
                frappe.logger().warning(f"Could not add class {doc.name} to new room {new_room}: {str(e)}")

    except Exception as e:
        frappe.logger().error(f"Error syncing class room assignment: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def remove_room_class():
    """Remove a class from a room"""
    try:
        data = {}
        if frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
            except Exception:
                data = frappe.local.form_dict or {}
        else:
            data = frappe.local.form_dict or {}

        required = ["room_id", "class_id"]
        for field in required:
            if not data.get(field):
                return validation_error_response({field: [f"{field} is required"]})

        room_id = data.get("room_id")
        class_id = data.get("class_id")

        # Validate room exists
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response("Room not found")

        # Validate class exists
        if not frappe.db.exists("SIS Class", class_id):
            return not_found_response("Class not found")

        # Get class info
        class_info = frappe.get_doc("SIS Class", class_id)

        # Get room document
        room_doc = frappe.get_doc("ERP Administrative Room", room_id)

        # Remove from Room Classes child table
        removed = False
        if hasattr(room_doc, 'room_classes'):
            for i, room_class in enumerate(room_doc.room_classes):
                if room_class.class_id == class_id:
                    # Remove the child record
                    frappe.delete_doc("ERP Administrative Room Class", room_class.name)
                    removed = True
                    frappe.logger().info(f"Removed class {class_id} from room {room_id} child table")
                    break

        # Fallback: If this room is set as the class's room (legacy), remove it
        if class_info.room == room_id:
            frappe.db.set_value("SIS Class", class_id, "room", None)
            frappe.logger().info(f"Removed room {room_id} from SIS Class {class_id} (legacy)")

        if not removed:
            return validation_error_response(
                "Lớp không được gán cho phòng này",
                {"class_id": ["Lớp này không được gán cho phòng này."]}
            )

        frappe.db.commit()

        return success_response(
            data={
                "room_id": room_id,
                "class_id": class_id,
                "class_title": class_info.title
            },
            message="Class removed from room successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error removing room class: {str(e)}")
        return error_response(f"Error removing room class: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_available_classes_for_room(room_id: str = None, school_year_id: str = None):
    """Get classes that can be assigned to a room (not already assigned to other rooms)"""
    try:
        if not room_id:
            form = frappe.local.form_dict or {}
            room_id = form.get("room_id")
            if not room_id and frappe.request and frappe.request.args:
                room_id = frappe.request.args.get('room_id')
            # Also check in request body for POST requests
            if not room_id and frappe.request and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body or '{}')
                    room_id = data.get('room_id')
                except Exception:
                    pass
        if not room_id:
            return validation_error_response("Room ID is required", {"room_id": ["Room ID is required"]})

        # Get current campus
        campus_id = get_current_campus_from_context()

        filters = {"campus_id": campus_id or "campus-1"}

        if school_year_id:
            filters["school_year_id"] = school_year_id

        # Get all classes for this campus/year
        classes = frappe.get_all(
            "SIS Class",
            fields=[
                "name",
                "title",
                "short_title",
                "class_type",
                "room",
                "education_grade"
            ],
            filters=filters,
            order_by="title asc"
        )


        # Check if room already has a homeroom class (both child table and legacy)
        room_has_homeroom = False

        try:
            # Check child table first
            room_doc = frappe.get_doc("ERP Administrative Room", room_id)
            if hasattr(room_doc, 'room_classes'):
                for room_class in room_doc.room_classes:
                    if room_class.usage_type == "homeroom":
                        room_has_homeroom = True
                        break
        except Exception:
            pass

        # Fallback to legacy check
        if not room_has_homeroom:
            existing_homeroom = frappe.get_all(
                "SIS Class",
                fields=["name", "title"],
                filters={"room": room_id, "class_type": "regular"},
                limit=1
            )
            room_has_homeroom = len(existing_homeroom) > 0

        # Filter classes that are available
        available_classes = []
        for class_data in classes:
            is_current_room_class = class_data.get("room") == room_id
            has_room = bool(class_data.get("room"))
            is_regular_class = class_data.get("class_type") == "regular"

            # Logic for available classes:
            # 1. Classes without any room assigned
            # 2. Classes assigned to current room (for editing)
            # 3. For homeroom usage: only regular classes that are not homeroom for other rooms
            # 4. For functional usage: all classes except those that are homeroom for other rooms

            can_be_homeroom = False
            can_be_functional = False

            if not has_room:
                # Class has no room - can be both homeroom and functional
                can_be_homeroom = is_regular_class
                can_be_functional = True
            elif is_current_room_class:
                # Class is assigned to current room - can edit usage type
                can_be_homeroom = is_regular_class
                can_be_functional = True
            else:
                # Class is assigned to another room
                # Can only be functional, and only if it's not a regular class (not homeroom elsewhere)
                can_be_homeroom = False
                can_be_functional = not is_regular_class

            # Apply the room-has-homeroom rule: if room already has homeroom, don't suggest homeroom for other classes
            if room_has_homeroom and not is_current_room_class:
                can_be_homeroom = False

            if can_be_homeroom or can_be_functional:
                available_class = class_data.copy()


                # Determine suggested usage based on availability and room state
                if can_be_homeroom and not room_has_homeroom:
                    available_class["suggested_usage"] = "homeroom"
                    available_class["suggested_usage_display"] = "Lớp chủ nhiệm"
                elif can_be_functional:
                    available_class["suggested_usage"] = "functional"
                    available_class["suggested_usage_display"] = "Lớp chức năng"
                else:
                    # Fallback - should not happen with current logic
                    available_class["suggested_usage"] = "functional"
                    available_class["suggested_usage_display"] = "Lớp chức năng"

                available_classes.append(available_class)

        return success_response(
            data=available_classes,
            message="Available classes fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching available classes: {str(e)}")
        return error_response(f"Error fetching available classes: {str(e)}")


def get_room_for_class_subject(class_id: str, subject_title: str = None) -> Dict[str, Any]:
    """Get room information for a class and subject combination.

    Args:
        class_id: SIS Class ID
        subject_title: Subject title to match (optional)

    Returns:
        Dict with room_id, room_name, room_type ('functional' or 'homeroom')
    """
    try:
        # Get all room assignments for this class
        # Use SQL raw query to avoid Frappe auto-resolving Link fields to non-existent columns
        room_assignments_query = """
            SELECT 
                name,
                parent,
                usage_type,
                subject_id
            FROM `tabERP Administrative Room Class`
            WHERE class_id = %s
        """
        room_assignments = frappe.db.sql(room_assignments_query, (class_id,), as_dict=True)

        frappe.logger().info(f"🏫 ROOM DEBUG: Found {len(room_assignments)} room assignments for class {class_id}")
        
        if room_assignments:
            frappe.logger().info(f"🏫 ROOM DEBUG: Room assignments: {[(a.get('parent'), a.get('usage_type'), a.get('subject_id')) for a in room_assignments]}")

        # Priority 1: Try to find functional room matching subject if subject is provided
        if subject_title:
            for assignment in room_assignments:
                if assignment.get("usage_type") == "functional" and assignment.get("subject_id"):
                    # Get subject title from subject_id
                    try:
                        subject_doc = frappe.get_doc("SIS Timetable Subject", assignment["subject_id"])
                        subject_name = subject_doc.title_vn or subject_doc.title_en or ""
                        frappe.logger().info(f"🏫 ROOM DEBUG: Checking subject '{subject_name}' against '{subject_title}'")

                        if subject_name and subject_title.lower() in subject_name.lower():
                            # Get room details
                            room_doc = frappe.get_doc("ERP Administrative Room", assignment["parent"])
                            frappe.logger().info(f"🏫 ROOM DEBUG: Found matching functional room {assignment['parent']} for subject '{subject_title}'")
                            return {
                                "room_id": assignment["parent"],
                                "room_name": room_doc.title_vn or room_doc.title_en or room_doc.name,
                                "room_type": "functional"
                            }
                    except Exception as subj_error:
                        frappe.logger().warning(f"Error getting subject {assignment.get('subject_id')}: {str(subj_error)}")

        # Priority 2: Try to find homeroom room (preferred for any subject)
        homeroom_room = None
        for assignment in room_assignments:
            if assignment.get("usage_type") == "homeroom" and assignment.get("parent"):
                homeroom_room = assignment
                break
        
        if homeroom_room:
            try:
                room_doc = frappe.get_doc("ERP Administrative Room", homeroom_room["parent"])
                frappe.logger().info(f"🏫 ROOM DEBUG: Found homeroom room {homeroom_room['parent']} for class {class_id}")
                return {
                    "room_id": homeroom_room["parent"],
                    "room_name": room_doc.title_vn or room_doc.title_en or room_doc.name,
                    "room_type": "homeroom"
                }
            except Exception as room_error:
                frappe.logger().warning(f"Error getting homeroom room {homeroom_room.get('parent')}: {str(room_error)}")

        # Priority 3: Try to find any room assignment (fallback to any functional room)
        for assignment in room_assignments:
            if assignment.get("parent"):
                try:
                    room_doc = frappe.get_doc("ERP Administrative Room", assignment["parent"])
                    room_type = assignment.get("usage_type") or "homeroom"
                    frappe.logger().info(f"🏫 ROOM DEBUG: Found room {assignment['parent']} ({room_type}) for class {class_id}")
                    return {
                        "room_id": assignment["parent"],
                        "room_name": room_doc.title_vn or room_doc.title_en or room_doc.name,
                        "room_type": room_type
                    }
                except Exception as room_error:
                    frappe.logger().warning(f"Error getting room {assignment.get('parent')}: {str(room_error)}")
                    continue

        # Final fallback: get homeroom from class directly
        class_doc = frappe.get_doc("SIS Class", class_id)
        if class_doc.room:
            room_doc = frappe.get_doc("ERP Administrative Room", class_doc.room)
            frappe.logger().info(f"🏫 ROOM DEBUG: Using homeroom {class_doc.room} from class {class_id}")
            return {
                "room_id": class_doc.room,
                "room_name": room_doc.title_vn or room_doc.title_en or room_doc.name,
                "room_type": "homeroom"
            }

        # No room found
        frappe.logger().info(f"🏫 ROOM DEBUG: No room found for class {class_id}")
        return {
            "room_id": None,
            "room_name": "Chưa có phòng",
            "room_type": None
        }

    except Exception as e:
        frappe.logger().error(f"Error getting room for class {class_id}, subject {subject_title}: {str(e)}")
        return {
            "room_id": None,
            "room_name": "Lỗi tải phòng",
            "room_type": None
        }
