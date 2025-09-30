# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, format_date
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
def get_all_daily_menus():
    """Get all daily menus with basic information"""
    try:
        # Get filter parameters
        month = frappe.local.form_dict.get('month')

        filters = {}
        if month:
            # Parse month (format: yyyy-MM)
            try:
                year, month_num = month.split('-')
                start_date = f"{year}-{month_num}-01"
                # Calculate end date of month
                import calendar
                last_day = calendar.monthrange(int(year), int(month_num))[1]
                end_date = f"{year}-{month_num}-{last_day:02d}"
                filters["menu_date"] = ["between", [start_date, end_date]]
            except:
                pass

        daily_menus = frappe.get_all(
            "SIS Daily Menu",
            fields=[
                "name",
                "menu_date",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="menu_date desc"
        )

        # Get meals for each daily menu
        for menu in daily_menus:
            meals = frappe.get_all(
                "SIS Daily Menu Meal",
                filters={
                    "parent": menu.name
                },
                fields=["meal_type", "meal_type_reference", "name"],
                order_by="idx"
            )

            # Get items for each meal
            for meal in meals:
                items = frappe.get_all(
                    "SIS Daily Menu Meal Item",
                    filters={
                        "parent": meal.name
                    },
                    fields=["menu_category_id", "display_name", "display_name_en", "education_stage"],
                    order_by="idx"
                )
                meal["items"] = items

            menu["meals"] = meals

        return list_response(daily_menus, "Daily menus fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus: {str(e)}")
        return error_response(f"Error fetching daily menus: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_daily_menu_by_id(daily_menu_id=None):
    """Get a specific daily menu by ID"""
    try:
        # Get daily_menu_id from parameter or from JSON payload
        if not daily_menu_id:
            # Try to get from JSON payload
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data)
                    if json_data and 'daily_menu_id' in json_data:
                        daily_menu_id = json_data['daily_menu_id']
                except (json.JSONDecodeError, TypeError):
                    pass

            # Fallback to form_dict
            if not daily_menu_id:
                daily_menu_id = frappe.local.form_dict.get('daily_menu_id')

        if not daily_menu_id:
            return validation_error_response("Daily Menu ID is required", {"daily_menu_id": ["Daily Menu ID is required"]})

        daily_menus = frappe.get_all(
            "SIS Daily Menu",
            filters={
                "name": daily_menu_id
            },
            fields=[
                "name", "menu_date",
                "creation", "modified"
            ]
        )

        if not daily_menus:
            return not_found_response("Daily Menu not found")

        menu = daily_menus[0]

        # Get meals with items
        meals = frappe.get_all(
            "SIS Daily Menu Meal",
            filters={
                "parent": menu.name
            },
            fields=["meal_type", "meal_type_reference", "name"],
            order_by="idx"
        )

        # Get items for each meal
        for meal in meals:
            items = frappe.get_all(
                "SIS Daily Menu Meal Item",
                filters={
                    "parent": meal.name
                },
                fields=["menu_category_id", "display_name", "display_name_en", "education_stage"],
                order_by="idx"
            )
            meal["items"] = items

        menu_data = {
            "name": menu.name,
            "menu_date": menu.menu_date,
            "meals": meals
        }
        return single_item_response(menu_data, "Daily Menu fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menu {daily_menu_id}: {str(e)}")
        return error_response(f"Error fetching daily menu: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_daily_menu():
    """Create a new daily menu"""
    try:
        # Get data from request
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_daily_menu: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_daily_menu: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_daily_menu: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_daily_menu: {data}")

        # Extract values from data
        menu_date = data.get("menu_date")
        meals = data.get("meals") or []

        # Input validation
        if not menu_date:
            return validation_error_response(
                "Validation failed",
                {"menu_date": ["Ngày thực đơn là bắt buộc"]}
            )

        # Check if menu date already exists
        existing = frappe.db.exists(
            "SIS Daily Menu",
            {
                "menu_date": menu_date
            }
        )

        if existing:
            return validation_error_response("Menu date already exists", {"menu_date": [f"Ngày {menu_date} đã có thực đơn"]})

        # Create new daily menu
        daily_menu_doc = frappe.get_doc({
            "doctype": "SIS Daily Menu",
            "menu_date": menu_date
        })

        # Add meals with items
        for meal_data in meals:
            meal_doc = daily_menu_doc.append("meals", {
                "meal_type": meal_data.get("meal_type"),
                "meal_type_reference": meal_data.get("meal_type_reference", "")
            })

            # Add items to meal
            for item_data in meal_data.get("items", []):
                meal_doc.append("items", {
                    "menu_category_id": item_data.get("menu_category_id"),
                    "display_name": item_data.get("display_name", ""),
                    "display_name_en": item_data.get("display_name_en", ""),
                    "education_stage": item_data.get("education_stage", "")
                })

        daily_menu_doc.insert()
        frappe.db.commit()

        # Return the created data
        meals_result = []
        for meal in daily_menu_doc.meals:
            items_result = []
            for item in meal.items:
                items_result.append({
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name,
                    "display_name_en": item.display_name_en,
                    "education_stage": item.education_stage
                })

            meals_result.append({
                "meal_type": meal.meal_type,
                "menu_type": "custom",  # Default to custom since we don't store menu_type in backend
                "meal_type_reference": meal.meal_type_reference,
                "items": items_result
            })

        daily_menu_data = {
            "name": daily_menu_doc.name,
            "menu_date": daily_menu_doc.menu_date,
            "meals": meals_result
        }
        return single_item_response(daily_menu_data, "Daily Menu created successfully")

    except Exception as e:
        frappe.log_error(f"Error creating daily menu: {str(e)}")
        return error_response(f"Error creating daily menu: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_daily_menu():
    """Update an existing daily menu"""
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

        daily_menu_id = data.get('daily_menu_id') or data.get('name')
        if not daily_menu_id:
            return validation_error_response("Daily Menu ID is required", {"daily_menu_id": ["Daily Menu ID is required"]})

        # Get existing document
        try:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", daily_menu_id)

        except frappe.DoesNotExistError:
            return not_found_response("Daily Menu not found")

        # Update menu_date if provided
        menu_date = data.get('menu_date')
        meals = data.get('meals')

        if menu_date and menu_date != daily_menu_doc.menu_date:
            daily_menu_doc.menu_date = menu_date

        # Update meals if provided
        if meals is not None:
            # Clear existing meals
            daily_menu_doc.meals = []

            # Add new meals
            for meal_data in meals:
                meal_doc = daily_menu_doc.append("meals", {
                    "meal_type": meal_data.get("meal_type"),
                    "meal_type_reference": meal_data.get("meal_type_reference", "")
                })

                # Add items to meal
                for item_data in meal_data.get("items", []):
                    meal_doc.append("items", {
                        "menu_category_id": item_data.get("menu_category_id"),
                        "display_name": item_data.get("display_name", ""),
                        "display_name_en": item_data.get("display_name_en", ""),
                        "education_stage": item_data.get("education_stage", "")
                    })

        daily_menu_doc.save()
        frappe.db.commit()

        # Get updated data for response
        meals_result = []
        for meal in daily_menu_doc.meals:
            items_result = []
            for item in meal.items:
                items_result.append({
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name,
                    "display_name_en": item.display_name_en,
                    "education_stage": item.education_stage
                })

            meals_result.append({
                "meal_type": meal.meal_type,
                "menu_type": "custom",  # Default to custom
                "meal_type_reference": meal.meal_type_reference,
                "items": items_result
            })

        daily_menu_data = {
            "name": daily_menu_doc.name,
            "menu_date": daily_menu_doc.menu_date,
            "meals": meals_result
        }
        return single_item_response(daily_menu_data, "Daily Menu updated successfully")

    except Exception as e:
        frappe.log_error(f"Error updating daily menu: {str(e)}")
        return error_response(f"Error updating daily menu: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_daily_menu():
    """Delete a daily menu"""
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

        daily_menu_id = data.get('daily_menu_id') or data.get('name')
        if not daily_menu_id:
            return validation_error_response("Daily Menu ID is required", {"daily_menu_id": ["Daily Menu ID is required"]})

        # Get existing document
        try:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", daily_menu_id)

        except frappe.DoesNotExistError:
            return not_found_response("Daily Menu not found")

        # Delete the document
        frappe.delete_doc("SIS Daily Menu", daily_menu_id)
        frappe.db.commit()

        return success_response(message="Daily Menu deleted successfully")

    except Exception as e:
        frappe.log_error(f"Error deleting daily menu: {str(e)}")
        return error_response(f"Error deleting daily menu: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_daily_menus_by_month(month=None):
    """Get daily menus for a specific month"""
    try:
        # Get month from parameter or from JSON payload
        if not month:
            # Try to get from JSON payload
            if frappe.request.data:
                try:
                    json_data = json.loads(frappe.request.data)
                    if json_data and 'month' in json_data:
                        month = json_data['month']
                except (json.JSONDecodeError, TypeError):
                    pass

            # Fallback to form_dict
            if not month:
                month = frappe.local.form_dict.get('month')

        if not month:
            return validation_error_response("Month is required", {"month": ["Month is required"]})

        # Parse month (format: yyyy-MM)
        try:
            year, month_num = month.split('-')
            start_date = f"{year}-{month_num}-01"
            # Calculate end date of month
            import calendar
            last_day = calendar.monthrange(int(year), int(month_num))[1]
            end_date = f"{year}-{month_num}-{last_day:02d}"
        except:
            return validation_error_response("Invalid month format", {"month": ["Month must be in yyyy-MM format"]})

        daily_menus = frappe.get_all(
            "SIS Daily Menu",
            fields=[
                "name",
                "menu_date",
                "creation",
                "modified"
            ],
            filters={
                "menu_date": ["between", [start_date, end_date]]
            },
            order_by="menu_date asc"
        )

        # Get meals for each daily menu
        for menu in daily_menus:
            meals = frappe.get_all(
                "SIS Daily Menu Meal",
                filters={
                    "parent": menu.name
                },
                fields=["meal_type", "meal_type_reference", "name"],
                order_by="idx"
            )

            # Get items for each meal
            for meal in meals:
                items = frappe.get_all(
                    "SIS Daily Menu Meal Item",
                    filters={
                        "parent": meal.name
                    },
                    fields=["menu_category_id", "display_name", "display_name_en", "education_stage"],
                    order_by="idx"
                )
                meal["items"] = items

            menu["meals"] = meals

        return list_response(daily_menus, "Daily menus for month fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus for month {month}: {str(e)}")
        return error_response(f"Error fetching daily menus for month: {str(e)}")
