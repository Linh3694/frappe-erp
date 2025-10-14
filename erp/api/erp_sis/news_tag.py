# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
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
def get_news_tags():
    """Get all news tags for current campus"""
    try:
        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        frappe.logger().info(f"Current campus_id: {campus_id}")

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Check if SIS News Tag doctype exists
        if not frappe.db.exists("DocType", "SIS News Tag"):
            frappe.logger().error("SIS News Tag DocType does not exist")
            return error_response(
                message="SIS News Tag DocType not found",
                code="DOCTYPE_NOT_FOUND"
            )

        filters = {"campus_id": campus_id}
        frappe.logger().info(f"Using filters: {filters}")

        # Get news tags
        tags = frappe.get_all(
            "SIS News Tag",
            fields=[
                "name",
                "name_en",
                "name_vn",
                "color",
                "description",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="name_en asc"
        )

        frappe.logger().info(f"Successfully retrieved {len(tags)} news tags")

        return list_response(
            data=tags,
            message="News tags fetched successfully"
        )

    except Exception as e:
        frappe.logger().error(f"Error fetching news tags: {str(e)}")
        return error_response(
            message=f"Failed to fetch news tags: {str(e)}",
            code="FETCH_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def create_news_tag():
    """Create a new news tag"""
    try:
        data = frappe.local.form_dict

        # Get current user's campus information
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        # Override campus_id to ensure user can't create for other campuses
        data.campus_id = campus_id

        # Validate required fields
        if not data.get("name_en") or not data.get("name_vn"):
            return validation_error_response("Both English and Vietnamese names are required")

        # Create the tag
        tag = frappe.get_doc({
            "doctype": "SIS News Tag",
            "campus_id": campus_id,
            "name_en": data.get("name_en"),
            "name_vn": data.get("name_vn"),
            "color": data.get("color", "#3B82F6")
        })

        tag.insert()

        # Get the created tag data
        created_tag = frappe.get_doc("SIS News Tag", tag.name)

        return single_item_response(
            data={
                "name": created_tag.name,
                "name_en": created_tag.name_en,
                "name_vn": created_tag.name_vn,
                "color": created_tag.color,
                "campus_id": created_tag.campus_id,
                "created_at": created_tag.created_at,
                "created_by": created_tag.created_by,
                "updated_at": created_tag.updated_at,
                "updated_by": created_tag.updated_by
            },
            message="News tag created successfully"
        )

    except frappe.DuplicateEntryError:
        return validation_error_response("A tag with this name already exists")
    except Exception as e:
        frappe.logger().error(f"Error creating news tag: {str(e)}")
        return error_response(
            message=f"Failed to create news tag: {str(e)}",
            code="CREATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def update_news_tag():
    """Update an existing news tag"""
    try:
        data = frappe.local.form_dict
        tag_id = data.get("tag_id")

        if not tag_id:
            return validation_error_response("Tag ID is required")

        # Get the tag
        tag = frappe.get_doc("SIS News Tag", tag_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and tag.campus_id != campus_id:
            return forbidden_response("You don't have access to this tag")

        # Update fields
        if "name_en" in data:
            tag.name_en = data.name_en
        if "name_vn" in data:
            tag.name_vn = data.name_vn
        if "color" in data:
            tag.color = data.color
        if "description" in data:
            tag.description = data.description
        if "is_active" in data:
            tag.is_active = data.is_active

        tag.save()

        return single_item_response(
            data={
                "name": tag.name,
                "name_en": tag.name_en,
                "name_vn": tag.name_vn,
                "color": tag.color,
                "description": tag.description,
                "campus_id": tag.campus_id,
                "is_active": tag.is_active,
                "created_at": tag.created_at,
                "created_by": tag.created_by,
                "updated_at": tag.updated_at,
                "updated_by": tag.updated_by
            },
            message="News tag updated successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News tag not found")
    except frappe.DuplicateEntryError:
        return validation_error_response("A tag with this name already exists")
    except Exception as e:
        frappe.logger().error(f"Error updating news tag: {str(e)}")
        return error_response(
            message=f"Failed to update news tag: {str(e)}",
            code="UPDATE_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def delete_news_tag():
    """Delete a news tag"""
    try:
        data = frappe.local.form_dict
        tag_id = data.get("tag_id")

        if not tag_id:
            return validation_error_response("Tag ID is required")

        # Get the tag
        tag = frappe.get_doc("SIS News Tag", tag_id)

        # Check if user has access to this campus
        campus_id = get_current_campus_from_context()
        if campus_id and tag.campus_id != campus_id:
            return forbidden_response("You don't have access to this tag")

        # Check if tag is being used in articles
        articles_count = frappe.db.count("SIS News Article Tag", {"news_tag_id": tag_id})
        if articles_count > 0:
            return validation_error_response(f"Cannot delete tag. It is being used in {articles_count} article(s)")

        # Delete the tag
        tag.delete()

        return success_response(
            message="News tag deleted successfully"
        )

    except frappe.DoesNotExistError:
        return not_found_response("News tag not found")
    except Exception as e:
        frappe.logger().error(f"Error deleting news tag: {str(e)}")
        return error_response(
            message=f"Failed to delete news tag: {str(e)}",
            code="DELETE_ERROR"
        )
