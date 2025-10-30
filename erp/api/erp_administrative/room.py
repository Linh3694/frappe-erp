# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import success_response, error_response, validation_error_response
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
def get_room_classes(room_id: str = None):
    """Get all classes assigned to a room"""
    try:
        if not room_id:
            form = frappe.local.form_dict or {}
            room_id = form.get("room_id") or form.get("name")
            if not room_id and frappe.request and frappe.request.args:
                room_id = frappe.request.args.get('room_id') or frappe.request.args.get('name')
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

        # Check if room exists
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response("Room not found")

        # Get room classes from child table
        # Note: This assumes we add a child table "Room Classes" to ERP Administrative Room
        # For now, we'll get classes that have this room assigned
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

        # Enhance with usage type based on class_type
        enhanced_classes = []
        for class_data in classes:
            enhanced_class = class_data.copy()

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

        return success_response(
            data=enhanced_classes,
            message="Room classes fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching room classes: {str(e)}")
        return error_response(f"Error fetching room classes: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def add_room_class():
    """Add a class to a room"""
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

        required = ["room_id", "class_id", "usage_type"]
        for field in required:
            if not data.get(field):
                return validation_error_response({field: [f"{field} is required"]})

        room_id = data.get("room_id")
        class_id = data.get("class_id")
        usage_type = data.get("usage_type")

        # Validate room exists
        if not frappe.db.exists("ERP Administrative Room", room_id):
            return not_found_response("Room not found")

        # Validate class exists
        if not frappe.db.exists("SIS Class", class_id):
            return not_found_response("Class not found")

        # Validate usage_type
        if usage_type not in ["homeroom", "functional"]:
            return validation_error_response("Invalid usage type", {"usage_type": ["Usage type must be 'homeroom' or 'functional'"]})

        # Get class info
        class_info = frappe.get_doc("SIS Class", class_id)

        # Business logic: sync with SIS Class room field
        if usage_type == "homeroom":
            # For homeroom usage, only allow if class_type is "regular"
            if class_info.class_type == "regular":
                # Update class.room to this room
                frappe.db.set_value("SIS Class", class_id, "room", room_id)
                frappe.logger().info(f"Updated SIS Class {class_id} room to {room_id} for homeroom usage")
            else:
                return validation_error_response({
                    "usage_type": ["Không thể đặt lớp này làm lớp chủ nhiệm vì loại lớp không phải là 'regular'"]
                })
        else:
            # For functional usage, check if class already has a homeroom room
            if class_info.room and class_info.room != room_id:
                return validation_error_response({
                    "class_id": ["Lớp này đã có phòng chủ nhiệm. Không thể thêm làm phòng chức năng."]
                })
            # For functional usage, we don't update class.room field to avoid conflicts

        # TODO: Add to Room Classes child table when implemented
        # For now, we rely on the SIS Class room field logic above

        frappe.db.commit()

        return success_response(
            data={
                "room_id": room_id,
                "class_id": class_id,
                "usage_type": usage_type,
                "class_title": class_info.title,
                "class_type": class_info.class_type
            },
            message="Class added to room successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error adding room class: {str(e)}")
        return error_response(f"Error adding room class: {str(e)}")


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

        # If this room is set as the class's room, remove it
        if class_info.room == room_id:
            frappe.db.set_value("SIS Class", class_id, "room", None)
            frappe.logger().info(f"Removed room {room_id} from SIS Class {class_id}")

        # TODO: Remove from Room Classes child table when implemented

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
                "room"
            ],
            filters=filters,
            order_by="title asc"
        )

        # Filter classes that are available (don't have a room or have this room)
        available_classes = []
        for class_data in classes:
            if not class_data.get("room") or class_data.get("room") == room_id:
                available_class = class_data.copy()

                # Add display info
                if class_data.get("class_type") == "regular":
                    available_class["suggested_usage"] = "homeroom"
                    available_class["suggested_usage_display"] = "Lớp chủ nhiệm"
                else:
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
