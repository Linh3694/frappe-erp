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
        # Get badge_id from multiple sources (form data or JSON payload)
        badge_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        badge_id = frappe.form_dict.get('badge_id')

        # If not found, try from JSON payload
        if not badge_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                badge_id = json_data.get('badge_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
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
        frappe.log_error(f"Error fetching badge {badge_id}: {str(e)}")
        return error_response(
            message="Error fetching badge",
            code="FETCH_BADGE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_badge():
    """Create a new badge"""
    try:
        # Get data from request - handle both FormData and JSON
        data = {}

        # Handle FormData (multipart/form-data) vs JSON data differently
        # Based on daily_menu.py pattern - prioritize form_dict for multipart data
        data = {}

        # For multipart/form-data, form_dict should contain the text fields
        content_type = frappe.request.headers.get('Content-Type', '')
        is_multipart = content_type.startswith('multipart/form-data')

        if is_multipart:
            frappe.logger().info("Processing multipart/form-data request")
            # In multipart requests, text fields go to form_dict
            data = dict(frappe.form_dict) if frappe.form_dict else {}
            if not data:
                data = dict(frappe.local.form_dict) if frappe.local.form_dict else {}
        else:
            frappe.logger().info("Processing JSON/application request")
            # For JSON requests, try to parse from request.data
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_badge: {data}")
                except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                    frappe.logger().error(f"Failed to parse JSON data: {str(e)}")
                    # Fallback to form_dict
                    data = dict(frappe.local.form_dict) if frappe.local.form_dict else {}

        frappe.logger().info(f"Final data for create_badge: {data}")
        frappe.logger().info(f"Content-Type: {content_type}")
        frappe.logger().info(f"Is multipart: {is_multipart}")
        frappe.logger().info(f"===================================")

        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        description_vn = data.get("description_vn")
        description_en = data.get("description_en")

        # Input validation
        if not title_vn:
            debug_info = {
                "debug_request_info": {
                    "content_type": frappe.request.headers.get('Content-Type', 'N/A'),
                    "form_dict": dict(frappe.form_dict) if frappe.form_dict else None,
                    "local_form_dict": dict(frappe.local.form_dict) if frappe.local.form_dict else None,
                    "request_files": list(frappe.request.files.keys()) if frappe.request.files else None,
                    "raw_data_length": len(frappe.request.data) if frappe.request.data else 0,
                    "parsed_title_vn": title_vn,
                    "parsed_title_en": title_en
                }
            }
            return validation_error_response(
                message="Title VN is required",
                errors={
                    "title_vn": ["Required"],
                    "debug_info": debug_info
                }
            )

        # Create new badge
        frappe.logger().info(f"Creating SIS Badge with data: title_vn={title_vn}, title_en={title_en}")

        try:
            frappe.logger().info("Creating badge document...")
            badge_doc = frappe.get_doc({
                "doctype": "SIS Badge",
                "title_vn": title_vn,
                "title_en": title_en or "",
                "description_vn": description_vn or "",
                "description_en": description_en or "",
                "is_active": 1
            })
            frappe.logger().info(f"Badge doc created successfully: {badge_doc.name}")

            frappe.logger().info("Inserting badge document...")
            badge_doc.insert()
            frappe.logger().info(f"Badge doc inserted successfully: {badge_doc.name}")

            # Handle image upload if provided
            image_url = None
            if frappe.request.files and 'image' in frappe.request.files:
                frappe.logger().info("Processing image upload...")
                try:
                    uploaded_file = frappe.request.files['image']
                    frappe.logger().info(f"Uploaded file: {uploaded_file.filename if uploaded_file else 'None'}")

                    if uploaded_file and uploaded_file.filename:
                        frappe.logger().info(f"Uploading file: {uploaded_file.filename}")

                        try:
                            # Read file content
                            file_content = uploaded_file.stream.read()
                            frappe.logger().info(f"Read file content, size: {len(file_content)} bytes")

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

                                # Update badge with image URL
                                frappe.logger().info("Updating badge with image URL...")
                                badge_doc.image = image_url
                                badge_doc.save()
                                frappe.logger().info("Badge updated with image URL")
                            else:
                                frappe.logger().error("save_file returned None")

                        except Exception as file_error:
                            frappe.logger().error(f"Error in file upload process: {str(file_error)}")
                            raise file_error
                    else:
                        frappe.logger().info("No valid image file provided")
                except Exception as img_error:
                    frappe.logger().error(f"Error uploading image: {str(img_error)}")
                    frappe.logger().error(f"Image error traceback: {frappe.get_traceback()}")
                    # Don't fail the whole operation if image upload fails

            frappe.logger().info("Committing transaction...")
            frappe.db.commit()
            frappe.logger().info("Database committed successfully")

        except Exception as doc_error:
            frappe.logger().error(f"Error creating/inserting badge doc: {str(doc_error)}")
            raise doc_error

        # Return the created data
        frappe.msgprint(_("Badge created successfully"))
        return single_item_response(
            data={
                "name": badge_doc.name,
                "title_vn": badge_doc.title_vn,
                "title_en": badge_doc.title_en,
                "description_vn": badge_doc.description_vn,
                "description_en": badge_doc.description_en,
                "image": badge_doc.image,
                "is_active": badge_doc.is_active
            },
            message="Badge created successfully"
        )

    except Exception as e:
        frappe.logger().error(f"=== CREATE BADGE ERROR ===")
        frappe.logger().error(f"Error creating badge: {str(e)}")
        frappe.logger().error(f"Error type: {type(e).__name__}")
        frappe.logger().error(f"Full traceback: {frappe.get_traceback()}")
        frappe.logger().error(f"=========================")

        return error_response(
            message=f"Error creating badge: {str(e)}",
            code="CREATE_BADGE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_badge():
    """Update an existing badge"""
    try:
        # Get data from request - handle both FormData and JSON
        data = {}

        # Handle FormData (multipart/form-data) vs JSON data differently
        # Based on daily_menu.py pattern - prioritize form_dict for multipart data
        data = {}

        # For multipart/form-data, form_dict should contain the text fields
        content_type = frappe.request.headers.get('Content-Type', '')
        is_multipart = content_type.startswith('multipart/form-data')

        if is_multipart:
            frappe.logger().info("Processing multipart/form-data request for update")
            # In multipart requests, text fields go to form_dict
            data = dict(frappe.form_dict) if frappe.form_dict else {}
            if not data:
                data = dict(frappe.local.form_dict) if frappe.local.form_dict else {}
        else:
            frappe.logger().info("Processing JSON/application request for update")
            # For JSON requests, try to parse from request.data
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                    data = json_data
                    frappe.logger().info(f"Received JSON data for update_badge: {data}")
                except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                    frappe.logger().error(f"Failed to parse JSON data: {str(e)}")
                    # Fallback to form_dict
                    data = dict(frappe.local.form_dict) if frappe.local.form_dict else {}

        frappe.logger().info(f"Final data for update_badge: {data}")
        frappe.logger().info(f"Content-Type: {content_type}")
        frappe.logger().info(f"Is multipart: {is_multipart}")
        frappe.logger().info(f"===================================")

        badge_id = data.get('badge_id')

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

        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        description_vn = data.get('description_vn')
        description_en = data.get('description_en')

        if title_vn and title_vn != badge_doc.title_vn:
            badge_doc.title_vn = title_vn

        if title_en is not None and title_en != badge_doc.title_en:
            badge_doc.title_en = title_en

        if description_vn is not None and description_vn != badge_doc.description_vn:
            badge_doc.description_vn = description_vn

        if description_en is not None and description_en != badge_doc.description_en:
            badge_doc.description_en = description_en

        # Handle image update if provided
        if frappe.request.files and 'image' in frappe.request.files:
            frappe.logger().info("Processing image update...")
            try:
                uploaded_file = frappe.request.files['image']
                frappe.logger().info(f"Update uploaded file: {uploaded_file.filename if uploaded_file else 'None'}")

                if uploaded_file and uploaded_file.filename:
                    frappe.logger().info(f"Uploading new image: {uploaded_file.filename}")

                    try:
                        # Read file content
                        file_content = uploaded_file.stream.read()
                        frappe.logger().info(f"Read file content, size: {len(file_content)} bytes")

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

                            # Update badge with new image URL
                            badge_doc.image = image_url
                        else:
                            frappe.logger().error("save_file returned None for update")

                    except Exception as file_error:
                        frappe.logger().error(f"Error in file update process: {str(file_error)}")
                        # Don't fail the whole operation if image upload fails
                else:
                    frappe.logger().info("No valid image file provided for update")
            except Exception as img_error:
                frappe.logger().error(f"Error updating image: {str(img_error)}")
                frappe.logger().error(f"Image update error traceback: {frappe.get_traceback()}")
                # Don't fail the whole operation if image upload fails

        badge_doc.save()
        frappe.db.commit()

        return single_item_response(
            data={
                "name": badge_doc.name,
                "title_vn": badge_doc.title_vn,
                "title_en": badge_doc.title_en,
                "description_vn": badge_doc.description_vn,
                "description_en": badge_doc.description_en,
                "image": badge_doc.image,
                "is_active": badge_doc.is_active
            },
            message="Badge updated successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error updating badge {badge_id}: {str(e)}")
        return error_response(
            message="Error updating badge",
            code="UPDATE_BADGE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_badge():
    """Delete a badge"""
    try:
        # Get badge_id from multiple sources (form data or JSON payload)
        badge_id = None

        # Try from form_dict first (for FormData/URLSearchParams)
        badge_id = frappe.form_dict.get('badge_id')

        # If not found, try from JSON payload
        if not badge_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                badge_id = json_data.get('badge_id')
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
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
        # Add business logic checks here if needed
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
        frappe.log_error(f"Error deleting badge {badge_id}: {str(e)}")
        return error_response(
            message="Lỗi không mong muốn khi xóa huy hiệu",
            code="DELETE_BADGE_ERROR"
        )
