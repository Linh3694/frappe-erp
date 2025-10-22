# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.api_response import (
    success_response, error_response, list_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


@frappe.whitelist(allow_guest=False)
def get_all_badges():
    """Get all badges - NO CAMPUS FILTERING"""
    try:
        badges = frappe.get_all(
            "SIS Badge",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "description_vn",
                "description_en",
                "image",
                "is_active",
                "creation",
                "modified"
            ],
            order_by="title_vn asc"
        )

        return list_response(
            data=badges,
            message="Badges fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching badges: {str(e)}")
        return error_response(
            message="Error fetching badges",
            code="FETCH_BADGES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_badge_by_id():
    """Get a specific badge by ID"""
    try:
        # Get badge_id from multiple sources
        badge_id = None

        # Try from form_dict first
        badge_id = frappe.form_dict.get('badge_id')

        # If not found, try from JSON payload
        if not badge_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                badge_id = json_data.get('badge_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass

        if not badge_id:
            return error_response(
                message="Badge ID is required",
                code="MISSING_BADGE_ID"
            )

        badge = frappe.get_doc("SIS Badge", badge_id)

        return single_item_response(
            data={
                "name": badge.name,
                "title_vn": badge.title_vn,
                "title_en": badge.title_en,
                "description_vn": badge.description_vn,
                "description_en": badge.description_en,
                "image": badge.image,
                "is_active": badge.is_active
            },
            message="Badge fetched successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response(
            message="Badge not found",
            code="BADGE_NOT_FOUND"
        )
    except Exception as e:
        frappe.log_error(f"Error fetching badge: {str(e)}")
        return error_response(
            message="Error fetching badge",
            code="FETCH_BADGE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_badge():
    """Create a new badge"""
    logs = []  # Collect logs to return in response
    
    try:
        # IMPORTANT: Check for files first to detect multipart form data
        files = frappe.request.files
        has_files = files and 'image' in files
        
        logs.append(f"Request method: {frappe.request.method}")
        logs.append(f"Request content type: {frappe.request.content_type}")
        logs.append(f"Has files: {has_files}")
        logs.append(f"Request files keys: {list(files.keys()) if files else 'None'}")

        # Get data from request - handle multipart form data properly
        data = {}
        
        # Check if request is multipart (either has files OR content-type is multipart)
        is_multipart = (frappe.request.content_type and 'multipart/form-data' in frappe.request.content_type)
        
        logs.append(f"Is multipart: {is_multipart}")
        
        # Try multiple methods to get form data when request is multipart
        if is_multipart:
            # Method 1: Try frappe.request.form (Werkzeug's ImmutableMultiDict) - MOST IMPORTANT
            if hasattr(frappe.request, 'form') and frappe.request.form:
                frappe.logger().info(f"Using frappe.request.form, keys: {list(frappe.request.form.keys())}")
                logs.append(f"Using frappe.request.form, keys: {list(frappe.request.form.keys())}")
                for key in frappe.request.form.keys():
                    data[key] = frappe.request.form.get(key)
                    frappe.logger().info(f"request.form[{key}] = {data[key]}")
                    logs.append(f"request.form[{key}] = {data[key]}")
            
            # Method 2: If request.form is empty, try form_dict
            if not data:
                frappe.logger().info("request.form is empty, trying form_dict")
                logs.append("request.form is empty, trying form_dict")
                data = dict(frappe.local.form_dict)
                frappe.logger().info(f"form_dict keys: {list(data.keys())}")
                logs.append(f"form_dict keys: {list(data.keys())}")
            
            # Method 3: Last resort - try werkzeug parser
            if not data or not data.get('title_vn'):
                frappe.logger().info("form_dict is empty, trying werkzeug parser")
                logs.append("form_dict is empty, trying werkzeug parser")
                try:
                    from werkzeug.formparser import parse_form_data
                    stream, form, files_parsed = parse_form_data(frappe.request.environ, silent=False)
                    
                    # Convert form data to dict
                    for key in form.keys():
                        data[key] = form.get(key)
                        frappe.logger().info(f"werkzeug form[{key}] = {data[key]}")
                        logs.append(f"werkzeug form[{key}] = {data[key]}")
                        
                    frappe.logger().info(f"Parsed multipart form data using werkzeug: {list(data.keys())}")
                    logs.append(f"Parsed multipart form data using werkzeug: {list(data.keys())}")
                    
                except Exception as e:
                    frappe.logger().error(f"Failed to parse multipart form data: {str(e)}")
                    logs.append(f"Failed to parse multipart form data: {str(e)}")
                    import traceback
                    frappe.logger().error(traceback.format_exc())
        else:
            # No files, use standard parsing
            data = dict(frappe.local.form_dict)
            frappe.logger().info(f"Using standard form_dict: {list(data.keys())}")
            logs.append(f"Using standard form_dict: {list(data.keys())}")
            
            # If form_dict is empty, try JSON body
            if not data or not data.get('title_vn'):
                try:
                    if frappe.request.data:
                        data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                        frappe.logger().info(f"Parsed JSON data: {list(data.keys())}")
                        logs.append(f"Parsed JSON data: {list(data.keys())}")
                except Exception as e:
                    frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")
                    logs.append(f"Failed to parse JSON from request: {str(e)}")
        
        # Log final parsed data for debugging
        frappe.logger().info(f"Final parsed data keys: {list(data.keys())}")
        logs.append(f"Final parsed data keys: {list(data.keys())}")
        for key, value in data.items():
            if key != 'cmd':  # Skip cmd to reduce noise
                log_value = value[:100] if isinstance(value, str) and len(value) > 100 else value
                frappe.logger().info(f"Form data {key}: {log_value} (type: {type(value).__name__})")
                logs.append(f"Form data {key}: {log_value} (type: {type(value).__name__})")

        # Extract values from data
        title_vn = str(data.get("title_vn", "")).strip()
        title_en = str(data.get("title_en", "")).strip()
        description_vn = str(data.get("description_vn", "")).strip()
        description_en = str(data.get("description_en", "")).strip()

        frappe.logger().info(f"Final data before validation: title_vn='{title_vn}', title_en='{title_en}'")
        logs.append(f"Final data before validation: title_vn='{title_vn}', title_en='{title_en}'")

        # Input validation
        if not title_vn:
            return validation_error_response(
                message="Title VN is required",
                errors={
                    "title_vn": ["Required"],
                    "logs": logs
                }
            )

        # Create new badge
        frappe.logger().info(f"Creating SIS Badge with data: title_vn={title_vn}, title_en={title_en}")
        logs.append(f"Creating SIS Badge with data: title_vn={title_vn}, title_en={title_en}")

        badge_doc = frappe.get_doc({
            "doctype": "SIS Badge",
            "title_vn": title_vn,
            "title_en": title_en,
            "description_vn": description_vn,
            "description_en": description_en,
            "is_active": 1
        })
        
        frappe.logger().info(f"Badge doc created, inserting...")
        logs.append(f"Badge doc created, inserting...")
        
        badge_doc.insert()
        
        frappe.logger().info(f"Badge doc inserted successfully: {badge_doc.name}")
        logs.append(f"Badge doc inserted successfully: {badge_doc.name}")

        # Handle image upload if provided
        image_url = None
        if has_files:
            frappe.logger().info("Processing image upload...")
            logs.append("Processing image upload...")
            try:
                uploaded_file = frappe.request.files['image']
                frappe.logger().info(f"Uploaded file: {uploaded_file.filename if uploaded_file else 'None'}")
                logs.append(f"Uploaded file: {uploaded_file.filename if uploaded_file else 'None'}")

                if uploaded_file and uploaded_file.filename:
                    frappe.logger().info(f"Uploading file: {uploaded_file.filename}")
                    logs.append(f"Uploading file: {uploaded_file.filename}")

                    # Read file content
                    file_content = uploaded_file.stream.read()
                    frappe.logger().info(f"Read file content, size: {len(file_content)} bytes")
                    logs.append(f"Read file content, size: {len(file_content)} bytes")

                    # Use frappe's file manager to save the file
                    from frappe.utils.file_manager import save_file

                    file_doc = save_file(
                        fname=uploaded_file.filename,
                        content=file_content,
                        dt="SIS Badge",
                        dn=badge_doc.name,
                        is_private=0
                    )

                    if file_doc:
                        image_url = file_doc.file_url
                        frappe.logger().info(f"Image uploaded successfully: {image_url}")
                        logs.append(f"Image uploaded successfully: {image_url}")

                        # Update badge with image URL
                        badge_doc.image = image_url
                        badge_doc.save()
                        frappe.logger().info("Badge updated with image URL")
                        logs.append("Badge updated with image URL")
                    else:
                        frappe.logger().error("save_file returned None")
                        logs.append("save_file returned None")
                else:
                    frappe.logger().info("No valid image file provided")
                    logs.append("No valid image file provided")
            except Exception as img_error:
                frappe.logger().error(f"Error uploading image: {str(img_error)}")
                logs.append(f"Error uploading image: {str(img_error)}")
                # Don't fail the whole operation if image upload fails

        frappe.db.commit()
        frappe.logger().info("Database committed successfully")
        logs.append("Database committed successfully")

        # Return the created data
        return single_item_response(
            data={
                "name": badge_doc.name,
                "title_vn": badge_doc.title_vn,
                "title_en": badge_doc.title_en,
                "description_vn": badge_doc.description_vn,
                "description_en": badge_doc.description_en,
                "image": badge_doc.image,
                "is_active": badge_doc.is_active,
                "logs": logs
            },
            message="Badge created successfully"
        )

    except Exception as e:
        frappe.logger().error(f"=== CREATE BADGE ERROR ===")
        frappe.logger().error(f"Error creating badge: {str(e)}")
        frappe.logger().error(f"Error type: {type(e).__name__}")
        frappe.logger().error(f"Full traceback: {frappe.get_traceback()}")
        frappe.logger().error(f"=========================")
        
        logs.append(f"=== CREATE BADGE ERROR ===")
        logs.append(f"Error: {str(e)}")
        logs.append(f"Error type: {type(e).__name__}")

        return error_response(
            message=f"Error creating badge: {str(e)}",
            code="CREATE_BADGE_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False)
def update_badge():
    """Update an existing badge"""
    logs = []  # Collect logs to return in response
    
    try:
        # IMPORTANT: Check for files first to detect multipart form data
        files = frappe.request.files
        has_files = files and 'image' in files
        
        logs.append(f"Request method: {frappe.request.method}")
        logs.append(f"Request content type: {frappe.request.content_type}")
        logs.append(f"Has files: {has_files}")
        logs.append(f"Request files keys: {list(files.keys()) if files else 'None'}")

        # Get data from request - handle multipart form data properly
        data = {}
        
        # Check if request is multipart (either has files OR content-type is multipart)
        is_multipart = (frappe.request.content_type and 'multipart/form-data' in frappe.request.content_type)
        
        logs.append(f"Is multipart: {is_multipart}")
        
        # Try multiple methods to get form data when request is multipart
        if is_multipart:
            # Method 1: Try frappe.request.form (Werkzeug's ImmutableMultiDict) - MOST IMPORTANT
            if hasattr(frappe.request, 'form') and frappe.request.form:
                frappe.logger().info(f"Using frappe.request.form for update, keys: {list(frappe.request.form.keys())}")
                logs.append(f"Using frappe.request.form, keys: {list(frappe.request.form.keys())}")
                for key in frappe.request.form.keys():
                    data[key] = frappe.request.form.get(key)
                    frappe.logger().info(f"request.form[{key}] = {data[key]}")
                    logs.append(f"request.form[{key}] = {data[key]}")
            
            # Method 2: If request.form is empty, try form_dict
            if not data:
                frappe.logger().info("request.form is empty, trying form_dict")
                logs.append("request.form is empty, trying form_dict")
                data = dict(frappe.local.form_dict)
                frappe.logger().info(f"form_dict keys: {list(data.keys())}")
                logs.append(f"form_dict keys: {list(data.keys())}")
            
            # Method 3: Last resort - try werkzeug parser
            if not data or not data.get('badge_id'):
                frappe.logger().info("form_dict is empty, trying werkzeug parser")
                logs.append("form_dict is empty, trying werkzeug parser")
                try:
                    from werkzeug.formparser import parse_form_data
                    stream, form, files_parsed = parse_form_data(frappe.request.environ, silent=False)
                    
                    # Convert form data to dict
                    for key in form.keys():
                        data[key] = form.get(key)
                        frappe.logger().info(f"werkzeug form[{key}] = {data[key]}")
                        logs.append(f"werkzeug form[{key}] = {data[key]}")
                        
                    frappe.logger().info(f"Parsed multipart form data using werkzeug: {list(data.keys())}")
                    logs.append(f"Parsed multipart form data using werkzeug: {list(data.keys())}")
                    
                except Exception as e:
                    frappe.logger().error(f"Failed to parse multipart form data: {str(e)}")
                    logs.append(f"Failed to parse multipart form data: {str(e)}")
                    import traceback
                    frappe.logger().error(traceback.format_exc())
        else:
            # No files, use standard parsing
            data = dict(frappe.local.form_dict)
            frappe.logger().info(f"Using standard form_dict: {list(data.keys())}")
            logs.append(f"Using standard form_dict: {list(data.keys())}")
            
            # If form_dict is empty, try JSON body
            if not data or not data.get('badge_id'):
                try:
                    if frappe.request.data:
                        data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                        frappe.logger().info(f"Parsed JSON data: {list(data.keys())}")
                        logs.append(f"Parsed JSON data: {list(data.keys())}")
                except Exception as e:
                    frappe.logger().error(f"Failed to parse JSON from request: {str(e)}")
                    logs.append(f"Failed to parse JSON from request: {str(e)}")
        
        # Log final parsed data for debugging
        frappe.logger().info(f"Final parsed data keys: {list(data.keys())}")
        logs.append(f"Final parsed data keys: {list(data.keys())}")
        for key, value in data.items():
            if key != 'cmd':  # Skip cmd to reduce noise
                log_value = value[:100] if isinstance(value, str) and len(value) > 100 else value
                frappe.logger().info(f"Form data {key}: {log_value} (type: {type(value).__name__})")
                logs.append(f"Form data {key}: {log_value} (type: {type(value).__name__})")

        badge_id = data.get('badge_id')

        if not badge_id:
            return error_response(
                message="Badge ID is required",
                code="MISSING_BADGE_ID",
                logs=logs
            )

        # Get existing document
        try:
            badge_doc = frappe.get_doc("SIS Badge", badge_id)
            logs.append(f"Found badge: {badge_id}")
        except frappe.DoesNotExistError:
            return error_response(
                message="Badge not found",
                code="BADGE_NOT_FOUND",
                logs=logs
            )

        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        description_vn = data.get('description_vn')
        description_en = data.get('description_en')

        if title_vn and title_vn != badge_doc.title_vn:
            badge_doc.title_vn = title_vn
            logs.append(f"Updated title_vn to: {title_vn}")

        if title_en is not None and title_en != badge_doc.title_en:
            badge_doc.title_en = title_en
            logs.append(f"Updated title_en to: {title_en}")

        if description_vn is not None and description_vn != badge_doc.description_vn:
            badge_doc.description_vn = description_vn
            logs.append(f"Updated description_vn")

        if description_en is not None and description_en != badge_doc.description_en:
            badge_doc.description_en = description_en
            logs.append(f"Updated description_en")

        # Handle image update if provided
        if has_files:
            frappe.logger().info("Processing image update...")
            logs.append("Processing image update...")
            try:
                uploaded_file = frappe.request.files['image']
                frappe.logger().info(f"Update uploaded file: {uploaded_file.filename if uploaded_file else 'None'}")
                logs.append(f"Update uploaded file: {uploaded_file.filename if uploaded_file else 'None'}")

                if uploaded_file and uploaded_file.filename:
                    frappe.logger().info(f"Uploading new image: {uploaded_file.filename}")
                    logs.append(f"Uploading new image: {uploaded_file.filename}")

                    # Read file content
                    file_content = uploaded_file.stream.read()
                    frappe.logger().info(f"Read file content, size: {len(file_content)} bytes")
                    logs.append(f"Read file content, size: {len(file_content)} bytes")

                    # Use frappe's file manager to save the file
                    from frappe.utils.file_manager import save_file

                    file_doc = save_file(
                        fname=uploaded_file.filename,
                        content=file_content,
                        dt="SIS Badge",
                        dn=badge_doc.name,
                        is_private=0
                    )

                    if file_doc:
                        image_url = file_doc.file_url
                        frappe.logger().info(f"Image updated successfully: {image_url}")
                        logs.append(f"Image updated successfully: {image_url}")

                        # Update badge with new image URL
                        badge_doc.image = image_url
                    else:
                        frappe.logger().error("save_file returned None for update")
                        logs.append("save_file returned None for update")
                else:
                    frappe.logger().info("No valid image file provided for update")
                    logs.append("No valid image file provided for update")
            except Exception as img_error:
                frappe.logger().error(f"Error updating image: {str(img_error)}")
                logs.append(f"Error updating image: {str(img_error)}")
                # Don't fail the whole operation if image upload fails

        badge_doc.save()
        frappe.db.commit()
        
        logs.append("Badge updated and committed successfully")

        return single_item_response(
            data={
                "name": badge_doc.name,
                "title_vn": badge_doc.title_vn,
                "title_en": badge_doc.title_en,
                "description_vn": badge_doc.description_vn,
                "description_en": badge_doc.description_en,
                "image": badge_doc.image,
                "is_active": badge_doc.is_active,
                "logs": logs
            },
            message="Badge updated successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error updating badge: {str(e)}")
        logs.append(f"Error updating badge: {str(e)}")
        return error_response(
            message="Error updating badge",
            code="UPDATE_BADGE_ERROR",
            logs=logs
        )


@frappe.whitelist(allow_guest=False)
def delete_badge():
    """Delete a badge"""
    try:
        # Get badge_id from multiple sources
        badge_id = None

        # Try from form_dict first
        badge_id = frappe.form_dict.get('badge_id')

        # If not found, try from JSON payload
        if not badge_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                badge_id = json_data.get('badge_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError):
                pass

        if not badge_id:
            return error_response(
                message="Badge ID is required",
                code="MISSING_BADGE_ID"
            )

        # Get existing document
        try:
            badge_doc = frappe.get_doc("SIS Badge", badge_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Badge not found",
                code="BADGE_NOT_FOUND"
            )

        # Check for linked documents before deletion
        linked_docs = []
        # Example: Check if badge is referenced in other doctypes
        # This can be extended based on actual business requirements

        if linked_docs:
            return error_response(
                message=f"Không thể xóa huy hiệu vì đang được liên kết với {', '.join(linked_docs)}. Vui lòng xóa hoặc chuyển các mục liên kết sang huy hiệu khác trước.",
                code="BADGE_LINKED"
            )

        # Delete the document
        frappe.delete_doc("SIS Badge", badge_id)
        frappe.db.commit()

        return success_response(
            message="Badge deleted successfully"
        )

    except frappe.LinkExistsError as e:
        return error_response(
            message=f"Không thể xóa huy hiệu vì đang được sử dụng bởi các module khác. Chi tiết: {str(e)}",
            code="BADGE_LINKED"
        )
    except Exception as e:
        frappe.log_error(f"Error deleting badge: {str(e)}")
        return error_response(
            message="Lỗi không mong muốn khi xóa huy hiệu",
            code="DELETE_BADGE_ERROR"
        )
