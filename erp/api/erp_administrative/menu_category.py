# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
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
def get_all_menu_categories():
    """Get all menu categories with basic information - SIMPLE VERSION"""
    try:
        menu_categories = frappe.get_all(
            "SIS Menu Category",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "code",
                "image_url",
                "creation",
                "modified"
            ],
            order_by="title_vn asc"
        )

        # Ensure image_url is always a string (never null)
        for category in menu_categories:
            if category.get('image_url') is None:
                category['image_url'] = ""
            elif not isinstance(category.get('image_url'), str):
                category['image_url'] = str(category.get('image_url', ""))

        return list_response(menu_categories, "Menu categories fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching menu categories: {str(e)}")
        return error_response(f"Error fetching menu categories: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_menu_category_by_id(menu_category_id=None):
    """Get a specific menu category by ID - SIMPLE VERSION with JSON payload support"""
    try:
        # Get menu_category_id from parameter or from JSON payload
        if not menu_category_id:
            # Try to get from JSON payload
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data)
                    if json_data and 'menu_category_id' in json_data:
                        menu_category_id = json_data['menu_category_id']
                except (json.JSONDecodeError, TypeError):
                    pass

            # Fallback to form_dict
            if not menu_category_id:
                menu_category_id = frappe.local.form_dict.get('menu_category_id')

        if not menu_category_id:
            return validation_error_response("Menu Category ID is required", {"menu_category_id": ["Menu Category ID is required"]})

        menu_categories = frappe.get_all(
            "SIS Menu Category",
            filters={
                "name": menu_category_id
            },
            fields=[
                "name", "title_vn", "title_en", "code", "image_url",
                "creation", "modified"
            ]
        )

        if not menu_categories:
            return not_found_response("Menu Category not found")

        menu_category = menu_categories[0]

        if not menu_category:
            return not_found_response("Menu Category not found or access denied")

        menu_category_data = {
            "name": menu_category.name,
            "title_vn": menu_category.title_vn,
            "title_en": menu_category.title_en,
            "code": menu_category.code,
            "image_url": menu_category.image_url or ""
        }
        return single_item_response(menu_category_data, "Menu Category fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching menu category {menu_category_id}: {str(e)}")
        return error_response(f"Error fetching menu category: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_menu_category():
    """Create a new menu category - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_menu_category: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_menu_category: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_menu_category: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_menu_category: {data}")

        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        code = data.get("code")
        image_url = data.get("image_url") or None

        # Input validation
        if not title_vn or not title_en or not code:
            return validation_error_response(
                "Validation failed",
                {
                    "title_vn": ["Title VN is required"] if not title_vn else [],
                    "title_en": ["Title EN is required"] if not title_en else [],
                    "code": ["Code is required"] if not code else []
                }
            )

        # Check if menu category title already exists
        existing = frappe.db.exists(
            "SIS Menu Category",
            {
                "title_vn": title_vn
            }
        )

        if existing:
            return validation_error_response("Menu category title already exists", {"title_vn": [f"Menu Category with title '{title_vn}' already exists"]})

        # Check if code already exists
        existing_code = frappe.db.exists(
            "SIS Menu Category",
            {
                "code": code
            }
        )

        if existing_code:
            return validation_error_response("Menu category code already exists", {"code": [f"Menu Category with code '{code}' already exists"]})

        # Create new menu category
        menu_category_doc = frappe.get_doc({
            "doctype": "SIS Menu Category",
            "title_vn": title_vn,
            "title_en": title_en,
            "code": code,
            "image_url": image_url
        })

        menu_category_doc.insert()
        frappe.db.commit()

        # Return the created data - follow Frappe pattern like other services
        menu_category_data = {
            "name": menu_category_doc.name,
            "title_vn": menu_category_doc.title_vn,
            "title_en": menu_category_doc.title_en,
            "code": menu_category_doc.code,
            "image_url": menu_category_doc.image_url or ""
        }
        return single_item_response(menu_category_data, "Menu Category created successfully")

    except Exception as e:
        frappe.log_error(f"Error creating menu category: {str(e)}")
        return error_response(f"Error creating menu category: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_menu_category():
    """Delete a menu category"""
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

        menu_category_id = data.get('menu_category_id')
        if not menu_category_id:
            return validation_error_response("Menu Category ID is required", {"menu_category_id": ["Menu Category ID is required"]})

        # Get existing document
        try:
            menu_category_doc = frappe.get_doc("SIS Menu Category", menu_category_id)

        except frappe.DoesNotExistError:
            return not_found_response("Menu Category not found")

        # Delete the document
        frappe.delete_doc("SIS Menu Category", menu_category_id)
        frappe.db.commit()

        return success_response(message="Menu Category deleted successfully")

    except Exception as e:
        frappe.log_error(f"Error deleting menu category: {str(e)}")
        return error_response(f"Error deleting menu category: {str(e)}")


@frappe.whitelist(allow_guest=False)
def check_code_availability(code, menu_category_id=None):
    """Check if code is available"""
    try:
        if not code:
            return validation_error_response("Code is required", {"code": ["Code is required"]})

        filters = {
            "code": code
        }

        # If updating existing menu category, exclude it from check
        if menu_category_id:
            filters["name"] = ["!=", menu_category_id]

        existing = frappe.db.exists("SIS Menu Category", filters)

        is_available = not bool(existing)

        return success_response({
            "is_available": is_available,
            "code": code,
            "message": "Available" if is_available else "Code already exists"
        })

    except Exception as e:
        frappe.log_error(f"Error checking code availability: {str(e)}")
        return error_response(f"Error checking code availability: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_menu_category():
    """Update an existing menu category - SIMPLE VERSION with JSON payload support"""
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

        menu_category_id = data.get('menu_category_id')
        if not menu_category_id:
            return validation_error_response("Menu Category ID is required", {"menu_category_id": ["Menu Category ID is required"]})

        # Get existing document
        try:
            menu_category_doc = frappe.get_doc("SIS Menu Category", menu_category_id)

        except frappe.DoesNotExistError:
            return not_found_response("Menu Category not found")

        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        code = data.get('code')
        image_url = data.get('image_url') or None

        if title_vn and title_vn != menu_category_doc.title_vn:
            menu_category_doc.title_vn = title_vn

        if title_en is not None and title_en != menu_category_doc.title_en:
            menu_category_doc.title_en = title_en

        if code and code != menu_category_doc.code:
            menu_category_doc.code = code

        if image_url is not None and image_url != menu_category_doc.image_url:
            menu_category_doc.image_url = image_url

        menu_category_doc.save()
        frappe.db.commit()

        menu_category_data = {
            "name": menu_category_doc.name,
            "title_vn": menu_category_doc.title_vn,
            "title_en": menu_category_doc.title_en,
            "code": menu_category_doc.code,
            "image_url": menu_category_doc.image_url or ""
        }
        return single_item_response(menu_category_data, "Menu Category updated successfully")

    except Exception as e:
        frappe.log_error(f"Error updating menu category: {str(e)}")
        return error_response(f"Error updating menu category: {str(e)}")


@frappe.whitelist(allow_guest=False)
def upload_menu_category_image():
    """Upload image for menu category - similar to sis_photo pattern"""
    try:
        # IMPORTANT: Check for files first to avoid encoding issues when parsing request data
        files = frappe.request.files
        has_files = files and 'file' in files

        # Get data from request - avoid parsing request.data when files are present
        menu_category_id = None

        if has_files:
            # When files are present, access individual form fields to avoid encoding issues
            # Don't try to parse frappe.request.data as it contains binary data
            try:
                menu_category_id = frappe.local.form_dict.get('menu_category_id')
                frappe.logger().info(f"Got menu_category_id from form_dict with files: {menu_category_id}")
            except UnicodeDecodeError as e:
                frappe.logger().error(f"Unicode decode error when accessing form_dict with files: {str(e)}")
                return error_response("Error processing form data with file upload")
        else:
            # No files, safe to parse request data
            data = {}
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data)
                    if json_data:
                        data = json_data
                except (json.JSONDecodeError, TypeError):
                    data = frappe.local.form_dict
            else:
                data = frappe.local.form_dict
            menu_category_id = data.get('menu_category_id')

        if not menu_category_id:
            return validation_error_response("Menu Category ID is required", {"menu_category_id": ["Menu Category ID is required"]})

        # Get existing menu category document
        try:
            menu_category_doc = frappe.get_doc("SIS Menu Category", menu_category_id)
        except frappe.DoesNotExistError:
            return not_found_response("Menu Category not found")

        # Get file from request.files (proper way to handle file uploads)
        files = frappe.request.files
        if not files or 'file' not in files:
            return validation_error_response("No file uploaded", {"file": ["No file uploaded"]})

        uploaded_file = files['file']
        file_name = uploaded_file.filename or "image.jpg"

        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/bmp', 'image/webp']
        if uploaded_file.content_type not in allowed_types:
            return validation_error_response("Invalid file type", {"file": ["Only image files (JPEG, PNG, GIF, BMP, WebP) are allowed"]})

        # Read file content as bytes
        try:
            file_content = uploaded_file.read()
            frappe.logger().info(f"Successfully read file content, size: {len(file_content)} bytes")
        except Exception as read_error:
            frappe.logger().error(f"Error reading file content: {str(read_error)}")
            return validation_error_response("Failed to read file", {"file": ["Error reading uploaded file"]})

        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(file_content) > max_size:
            return validation_error_response("File too large", {"file": ["File size must be less than 10MB"]})

        # Save file directly to avoid encoding issues
        import os

        # Generate new filename based on menu category code
        original_extension = os.path.splitext(file_name)[1] if file_name else '.jpg'
        if not original_extension:
            # Fallback to determine extension from content type if available
            if uploaded_file and hasattr(uploaded_file, 'content_type'):
                if 'jpeg' in uploaded_file.content_type or 'jpg' in uploaded_file.content_type:
                    original_extension = '.jpg'
                elif 'png' in uploaded_file.content_type:
                    original_extension = '.png'
                elif 'gif' in uploaded_file.content_type:
                    original_extension = '.gif'
                elif 'bmp' in uploaded_file.content_type:
                    original_extension = '.bmp'
                elif 'webp' in uploaded_file.content_type:
                    original_extension = '.webp'
                else:
                    original_extension = '.jpg'

        # Create new filename using menu category code
        new_file_name = f"{menu_category_doc.code}{original_extension}"
        
        frappe.logger().info(f"Original filename: {file_name}, New filename: {new_file_name}")

        # Create Menu Categories directory if it doesn't exist
        upload_dir = frappe.get_site_path("public", "files", "Menu_Categories")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir, exist_ok=True)

        # Save file directly to file system
        file_path = os.path.join(upload_dir, new_file_name)
        try:
            with open(file_path, 'wb') as f:
                f.write(file_content)
            frappe.logger().info(f"Successfully saved file to: {file_path}")
        except Exception as write_error:
            frappe.logger().error(f"Error writing file to disk: {str(write_error)}")
            return validation_error_response("Failed to save file", {"file": ["Error saving file to disk"]})

        # Create file URL
        file_url = f"/files/Menu_Categories/{new_file_name}"
        
        frappe.logger().info(f"File saved to: {file_path}, URL: {file_url}")

        # Update menu category with image URL (directly use file_url, no Frappe File document needed)
        menu_category_doc.image_url = file_url
        menu_category_doc.save()
        frappe.db.commit()

        response_data = {
            "name": menu_category_doc.name,
            "title_vn": menu_category_doc.title_vn,
            "title_en": menu_category_doc.title_en,
            "code": menu_category_doc.code,
            "image_url": menu_category_doc.image_url or "",
            "file_url": file_url
        }

        return single_item_response(response_data, "Image uploaded successfully")

    except Exception as e:
        frappe.log_error(f"Error uploading menu category image: {str(e)}")
        return error_response(f"Error uploading image: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_menu_category_with_image():
    """Create a new menu category with image upload - for AddMenuCategory form"""
    try:
        # IMPORTANT: Access form_dict AFTER processing files to avoid UTF-8 encoding issues
        # The issue occurs when Frappe tries to parse multipart data containing binary files

        # Get text fields from form_dict with error handling for encoding issues
        try:
            title_vn = frappe.local.form_dict.get("title_vn")
            title_en = frappe.local.form_dict.get("title_en")
            code = frappe.local.form_dict.get("code")
        except UnicodeDecodeError as e:
            frappe.logger().error(f"UTF-8 decode error when accessing form_dict: {str(e)}")
            # Try to parse multipart data manually as fallback
            try:
                from werkzeug.formparser import parse_form_data
                stream, form, files_parsed = parse_form_data(frappe.request.environ, silent=True)
                title_vn = form.get("title_vn")
                title_en = form.get("title_en")
                code = form.get("code")
                frappe.logger().info("Successfully parsed form data using werkzeug fallback")
            except Exception as fallback_error:
                frappe.logger().error(f"Fallback parsing also failed: {str(fallback_error)}")
                return error_response("Error processing form data with file upload")

        # Input validation
        if not title_vn or not title_en or not code:
            return validation_error_response(
                "Validation failed",
                {
                    "title_vn": ["Title VN is required"] if not title_vn else [],
                    "title_en": ["Title EN is required"] if not title_en else [],
                    "code": ["Code is required"] if not code else []
                }
            )

        # Check if menu category title already exists
        existing = frappe.db.exists(
            "SIS Menu Category",
            {
                "title_vn": title_vn
            }
        )

        if existing:
            return validation_error_response(
                "Menu category title already exists",
                {
                    "title_vn": ["Menu category with this Vietnamese title already exists"]
                }
            )

        # Check if code already exists
        existing_code = frappe.db.exists(
            "SIS Menu Category",
            {
                "code": code
            }
        )

        if existing_code:
            return validation_error_response(
                "Menu category code already exists",
                {
                    "code": ["Menu category with this code already exists"]
                }
            )

        # Create menu category document first
        menu_category_doc = frappe.get_doc({
            "doctype": "SIS Menu Category",
            "title_vn": title_vn,
            "title_en": title_en,
            "code": code,
            "image_url": None  # Will be updated after image upload
        })

        menu_category_doc.insert()
        frappe.db.commit()

        frappe.logger().info(f"Created menu category: {menu_category_doc.name} with code: {code}")

        # Handle image upload if file is provided
        image_url = ""
        files = frappe.request.files
        if files and 'file' in files:
            try:
                uploaded_file = files['file']
                file_name = uploaded_file.filename or "image.jpg"

                # Validate file type
                allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/bmp', 'image/webp']
                if uploaded_file.content_type not in allowed_types:
                    # Delete the created menu category if image validation fails
                    frappe.delete_doc("SIS Menu Category", menu_category_doc.name)
                    frappe.db.commit()
                    return validation_error_response("Invalid file type", {"file": ["Only image files (JPEG, PNG, GIF, BMP, WebP) are allowed"]})

                # Read file content as bytes
                try:
                    file_content = uploaded_file.read()
                    frappe.logger().info(f"Successfully read file content, size: {len(file_content)} bytes")
                except Exception as read_error:
                    frappe.logger().error(f"Error reading file content: {str(read_error)}")
                    # Delete the created menu category if file read fails
                    frappe.delete_doc("SIS Menu Category", menu_category_doc.name)
                    frappe.db.commit()
                    return validation_error_response("Failed to read file", {"file": ["Error reading uploaded file"]})

                # Validate file size (max 10MB)
                max_size = 10 * 1024 * 1024
                if len(file_content) > max_size:
                    # Delete the created menu category if image validation fails
                    frappe.delete_doc("SIS Menu Category", menu_category_doc.name)
                    frappe.db.commit()
                    return validation_error_response("File too large", {"file": ["File size must be less than 10MB"]})

                # Save file directly to avoid encoding issues
                import os

                # Generate new filename based on menu category code
                original_extension = os.path.splitext(file_name)[1] if file_name else '.jpg'
                if not original_extension:
                    # Fallback to determine extension from content type if available
                    if uploaded_file and hasattr(uploaded_file, 'content_type'):
                        if 'jpeg' in uploaded_file.content_type or 'jpg' in uploaded_file.content_type:
                            original_extension = '.jpg'
                        elif 'png' in uploaded_file.content_type:
                            original_extension = '.png'
                        elif 'gif' in uploaded_file.content_type:
                            original_extension = '.gif'
                        elif 'bmp' in uploaded_file.content_type:
                            original_extension = '.bmp'
                        elif 'webp' in uploaded_file.content_type:
                            original_extension = '.webp'
                        else:
                            original_extension = '.jpg'

                # Create new filename using menu category code
                new_file_name = f"{menu_category_doc.code}{original_extension}"
                
                frappe.logger().info(f"Uploading image with filename: {new_file_name}")

                # Create Menu Categories directory if it doesn't exist
                upload_dir = frappe.get_site_path("public", "files", "Menu_Categories")
                if not os.path.exists(upload_dir):
                    os.makedirs(upload_dir, exist_ok=True)

                # Save file directly to file system
                file_path = os.path.join(upload_dir, new_file_name)
                try:
                    with open(file_path, 'wb') as f:
                        f.write(file_content)
                    frappe.logger().info(f"Successfully saved file to: {file_path}")
                except Exception as write_error:
                    frappe.logger().error(f"Error writing file to disk: {str(write_error)}")
                    # Delete the created menu category if file save fails
                    frappe.delete_doc("SIS Menu Category", menu_category_doc.name)
                    frappe.db.commit()
                    return validation_error_response("Failed to save file", {"file": ["Error saving file to disk"]})

                # Create file URL
                file_url = f"/files/Menu_Categories/{new_file_name}"
                
                frappe.logger().info(f"File saved to: {file_path}, URL: {file_url}")

                menu_category_doc.image_url = file_url
                menu_category_doc.save()
                frappe.db.commit()
                image_url = file_url

                frappe.logger().info(f"Image uploaded successfully: {image_url}")

            except Exception as image_error:
                # If image upload fails, still return success for menu category creation
                # but log the image error
                frappe.log_error(f"Error uploading image during menu category creation: {str(image_error)}")
                frappe.logger().warning(f"Image upload failed but menu category created: {str(image_error)}")

        # Prepare response data
        response_data = {
            "name": menu_category_doc.name,
            "title_vn": menu_category_doc.title_vn,
            "title_en": menu_category_doc.title_en,
            "code": menu_category_doc.code,
            "image_url": image_url or "",
            "creation": str(menu_category_doc.creation),
            "modified": str(menu_category_doc.modified)
        }

        return single_item_response(response_data, "Menu category created successfully")

    except Exception as e:
        frappe.log_error(f"Error creating menu category with image: {str(e)}")
        return error_response(f"Error creating menu category: {str(e)}")
