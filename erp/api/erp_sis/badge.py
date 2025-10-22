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
        # Get data from request - follow pattern
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_badge: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_badge: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_badge: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_badge: {data}")

        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        description_vn = data.get("description_vn")
        description_en = data.get("description_en")

        # Input validation
        if not title_vn:
            return validation_error_response(
                message="Title VN is required",
                errors={
                    "title_vn": ["Required"]
                }
            )

        # Create new badge
        frappe.logger().info(f"Creating SIS Badge with data: title_vn={title_vn}, title_en={title_en}")

        try:
            badge_doc = frappe.get_doc({
                "doctype": "SIS Badge",
                "title_vn": title_vn,
                "title_en": title_en or "",
                "description_vn": description_vn or "",
                "description_en": description_en or "",
                "is_active": 1
            })

            frappe.logger().info(f"Badge doc created: {badge_doc}")

            badge_doc.insert()
            frappe.logger().info("Badge doc inserted successfully")

            # Handle image upload if provided
            image_file = data.get("image")
            if image_file:
                # Image handling will be done through the standard Frappe attachment system
                # The image field in the DocType will handle this automatically
                pass

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
        frappe.log_error(f"Error creating badge: {str(e)}")
        return error_response(
            message="Error creating badge",
            code="CREATE_BADGE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_badge():
    """Update an existing badge"""
    try:
        # Get data from multiple sources (form data or JSON payload)
        data = {}

        # Start with form_dict data
        if frappe.local.form_dict:
            data.update(dict(frappe.local.form_dict))

        # If JSON payload exists, merge it (JSON takes precedence)
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                data.update(json_data)
            except (json.JSONDecodeError, TypeError, AttributeError, UnicodeDecodeError) as e:
                pass

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
        image_file = data.get("image")
        if image_file:
            # Image handling will be done through the standard Frappe attachment system
            pass

        badge_doc.save()
        frappe.db.commit()

        return single_item_response(
            data={
                "name": badge_doc.name,
                "badge_id": badge_doc.badge_id,
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
