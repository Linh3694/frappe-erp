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
def get_all_meal_types():
    """Get all meal types with basic information"""
    try:
        meal_types = frappe.get_all(
            "SIS Meal Type",
            fields=[
                "name",
                "title_vn",
                "title_en",
                "creation",
                "modified"
            ],
            order_by="title_vn asc"
        )

        # Get menu categories for each meal type
        for meal_type in meal_types:
            menu_categories = frappe.get_all(
                "SIS Meal Type Menu Category",
                filters={
                    "parent": meal_type.name
                },
                fields=["menu_category_id", "display_name"]
            )
            meal_type["menu_categories"] = [item.menu_category_id for item in menu_categories]
            meal_type["menu_categories_with_display"] = menu_categories

        return list_response(meal_types, "Meal types fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching meal types: {str(e)}")
        return error_response(f"Error fetching meal types: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_meal_type_by_id(meal_type_id=None):
    """Get a specific meal type by ID with JSON payload support"""
    try:
        # Get meal_type_id from parameter or from JSON payload
        if not meal_type_id:
            # Try to get from JSON payload
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data)
                    if json_data and 'meal_type_id' in json_data:
                        meal_type_id = json_data['meal_type_id']
                except (json.JSONDecodeError, TypeError):
                    pass

            # Fallback to form_dict
            if not meal_type_id:
                meal_type_id = frappe.local.form_dict.get('meal_type_id')

        if not meal_type_id:
            return validation_error_response("Meal Type ID is required", {"meal_type_id": ["Meal Type ID is required"]})

        meal_types = frappe.get_all(
            "SIS Meal Type",
            filters={
                "name": meal_type_id
            },
            fields=[
                "name", "title_vn", "title_en",
                "creation", "modified"
            ]
        )

        if not meal_types:
            return not_found_response("Meal Type not found")

        meal_type = meal_types[0]

        # Get menu categories with display names
        menu_categories = frappe.get_all(
            "SIS Meal Type Menu Category",
            filters={
                "parent": meal_type.name
            },
            fields=["menu_category_id", "display_name"],
            order_by="idx"
        )

        meal_type_data = {
            "name": meal_type.name,
            "title_vn": meal_type.title_vn,
            "title_en": meal_type.title_en,
            "menu_categories": [item.menu_category_id for item in menu_categories],
            "menu_categories_with_display": menu_categories
        }
        return single_item_response(meal_type_data, "Meal Type fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching meal type {meal_type_id}: {str(e)}")
        return error_response(f"Error fetching meal type: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_meal_type():
    """Create a new meal type"""
    try:
        # Get data from request - follow pattern from menu_category
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_meal_type: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_meal_type: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_meal_type: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_meal_type: {data}")

        # Extract values from data
        title_vn = data.get("title_vn")
        title_en = data.get("title_en")
        menu_categories = data.get("menu_categories") or []

        # Input validation
        if not title_vn or not title_en:
            return validation_error_response(
                "Validation failed",
                {
                    "title_vn": ["Tên tiếng Việt là bắt buộc"] if not title_vn else [],
                    "title_en": ["Tên tiếng Anh là bắt buộc"] if not title_en else []
                }
            )

        # Check if meal type title already exists
        existing = frappe.db.exists(
            "SIS Meal Type",
            {
                "title_vn": title_vn
            }
        )

        if existing:
            return validation_error_response("Meal type title already exists", {"title_vn": [f"Loại bữa với tên '{title_vn}' đã tồn tại"]})

        # Create new meal type
        meal_type_doc = frappe.get_doc({
            "doctype": "SIS Meal Type",
            "title_vn": title_vn,
            "title_en": title_en
        })

        # Add menu categories with display names
        for menu_item in menu_categories:
            if isinstance(menu_item, str):
                # Old format - just menu category ID
                meal_type_doc.append("menu_categories", {
                    "menu_category_id": menu_item,
                    "display_name": ""
                })
            elif isinstance(menu_item, dict):
                # New format - menu category ID with display name
                meal_type_doc.append("menu_categories", {
                    "menu_category_id": menu_item.get("menu_category_id"),
                    "display_name": menu_item.get("display_name", "")
                })

        meal_type_doc.insert()
        frappe.db.commit()

        # Get menu categories for response
        menu_categories_result = frappe.get_all(
            "SIS Meal Type Menu Category",
            filters={
                "parent": meal_type_doc.name
            },
            fields=["menu_category_id", "display_name"],
            order_by="idx"
        )

        # Return the created data
        meal_type_data = {
            "name": meal_type_doc.name,
            "title_vn": meal_type_doc.title_vn,
            "title_en": meal_type_doc.title_en,
            "menu_categories": [item.menu_category_id for item in menu_categories_result],
            "menu_categories_with_display": menu_categories_result
        }
        return single_item_response(meal_type_data, "Meal Type created successfully")

    except Exception as e:
        frappe.log_error(f"Error creating meal type: {str(e)}")
        return error_response(f"Error creating meal type: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_meal_type():
    """Update an existing meal type with JSON payload support"""
    try:
        # Get data from request
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

        meal_type_id = data.get('meal_type_id')
        if not meal_type_id:
            return validation_error_response("Meal Type ID is required", {"meal_type_id": ["Meal Type ID is required"]})

        # Get existing document
        try:
            meal_type_doc = frappe.get_doc("SIS Meal Type", meal_type_id)

        except frappe.DoesNotExistError:
            return not_found_response("Meal Type not found")

        # Update fields if provided
        title_vn = data.get('title_vn')
        title_en = data.get('title_en')
        menu_categories = data.get('menu_categories')

        if title_vn and title_vn != meal_type_doc.title_vn:
            meal_type_doc.title_vn = title_vn

        if title_en and title_en != meal_type_doc.title_en:
            meal_type_doc.title_en = title_en

        # Update menu categories if provided
        if menu_categories is not None:
            # Clear existing menu categories
            meal_type_doc.menu_categories = []
            
            # Add new menu categories
            for menu_item in menu_categories:
                if isinstance(menu_item, str):
                    # Old format - just menu category ID
                    meal_type_doc.append("menu_categories", {
                        "menu_category_id": menu_item,
                        "display_name": ""
                    })
                elif isinstance(menu_item, dict):
                    # New format - menu category ID with display name
                    meal_type_doc.append("menu_categories", {
                        "menu_category_id": menu_item.get("menu_category_id"),
                        "display_name": menu_item.get("display_name", "")
                    })

        meal_type_doc.save()
        frappe.db.commit()

        # Get updated menu categories for response
        menu_categories_result = frappe.get_all(
            "SIS Meal Type Menu Category",
            filters={
                "parent": meal_type_doc.name
            },
            fields=["menu_category_id", "display_name"],
            order_by="idx"
        )

        meal_type_data = {
            "name": meal_type_doc.name,
            "title_vn": meal_type_doc.title_vn,
            "title_en": meal_type_doc.title_en,
            "menu_categories": [item.menu_category_id for item in menu_categories_result],
            "menu_categories_with_display": menu_categories_result
        }
        return single_item_response(meal_type_data, "Meal Type updated successfully")

    except Exception as e:
        frappe.log_error(f"Error updating meal type: {str(e)}")
        return error_response(f"Error updating meal type: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_meal_type():
    """Delete a meal type"""
    try:
        # Get data from request
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

        meal_type_id = data.get('meal_type_id')
        if not meal_type_id:
            return validation_error_response("Meal Type ID is required", {"meal_type_id": ["Meal Type ID is required"]})

        # Get existing document
        try:
            meal_type_doc = frappe.get_doc("SIS Meal Type", meal_type_id)

        except frappe.DoesNotExistError:
            return not_found_response("Meal Type not found")

        # Delete the document
        frappe.delete_doc("SIS Meal Type", meal_type_id)
        frappe.db.commit()

        return success_response(message="Meal Type deleted successfully")

    except Exception as e:
        frappe.log_error(f"Error deleting meal type: {str(e)}")
        return error_response(f"Error deleting meal type: {str(e)}")
