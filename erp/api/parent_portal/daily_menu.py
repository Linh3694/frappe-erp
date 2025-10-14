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


def get_request_param(param_name):
    """Helper function to get parameter from request in order of priority"""
    # 1. Try function parameter
    # 2. Try JSON payload (POST)
    # 3. Try form_dict (POST)
    # 4. Try query params (GET)

    # Try JSON payload
    if frappe.request.data:
        try:
            json_data = json.loads(frappe.request.data)
            if json_data and param_name in json_data:
                return json_data[param_name]
        except (json.JSONDecodeError, TypeError):
            pass

    # Try form_dict
    value = frappe.local.form_dict.get(param_name)
    if value:
        return value

    # Try query params
    value = frappe.local.request.args.get(param_name)
    if value:
        return value

    return None


def get_detailed_menu_items(items):
    """Convert flat items array to detailed meals structure for parent portal"""
    meals_result = {}

    # Initialize meal structures with full nested structure
    meals_result = {
        "breakfast": {
            "meal_type": "breakfast",
            "menu_type": "custom",
            "meal_type_reference": "",
            "name": f"breakfast_detailed",
            "breakfast_options": {
                "option1": {"menu_category_id": "", "menu_category_details": None},
                "option2": {"menu_category_id": "", "menu_category_details": None},
                "external": {"menu_category_id": "", "menu_category_details": None}
            }
        },
        "lunch": {
            "meal_type": "lunch",
            "menu_type": "custom",
            "meal_type_reference": "",
            "name": f"lunch_detailed",
            "set_a_config": {"enabled": False, "items": []},
            "set_au_config": {"enabled": False, "items": []},
            "eat_clean_config": {"enabled": False, "items": []},
            "buffet_config": {"enabled": False, "name_vn": "", "name_en": "", "items": []}
        },
        "dinner": {
            "meal_type": "dinner",
            "menu_type": "custom",
            "meal_type_reference": "",
            "name": f"dinner_detailed",
            "dinner_items": []  # Array supports multiple snacks and drinks
        }
    }

    for item in items:
        meal_type = item.meal_type

        # Skip if meal_type not in our fixed structure
        if meal_type not in meals_result:
            continue

        # Get menu category details if menu_category_id exists
        menu_category_details = None
        if item.menu_category_id:
            try:
                menu_category = frappe.get_doc("SIS Menu Category", item.menu_category_id)
                menu_category_details = {
                    "id": menu_category.name,
                    "name": menu_category.name,
                    "title_vn": menu_category.title_vn,
                    "title_en": menu_category.title_en,
                    "display_name": item.display_name or menu_category.title_vn,
                    "display_name_en": item.display_name_en or menu_category.title_en,
                    "image_url": menu_category.image_url,
                    "code": menu_category.code
                }
            except frappe.DoesNotExistError:
                # Fallback if menu category not found
                menu_category_details = {
                    "id": item.menu_category_id,
                    "name": item.menu_category_id,
                    "title_vn": item.display_name or "",
                    "title_en": item.display_name_en or "",
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or "",
                    "image_url": "",
                    "code": ""
                }

        # Handle breakfast options
        if meal_type == "breakfast":
            # Map item to appropriate breakfast option
            meal_type_reference = item.meal_type_reference or ""
            if meal_type_reference == "option1" or not meal_type_reference:
                if not meals_result[meal_type]["breakfast_options"]["option1"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option1"] = {
                        "menu_category_id": item.menu_category_id,
                        "menu_category_details": menu_category_details
                    }
            elif meal_type_reference == "option2":
                if not meals_result[meal_type]["breakfast_options"]["option2"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option2"] = {
                        "menu_category_id": item.menu_category_id,
                        "menu_category_details": menu_category_details
                    }
            elif meal_type_reference == "external":
                if not meals_result[meal_type]["breakfast_options"]["external"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["external"] = {
                        "menu_category_id": item.menu_category_id,
                        "menu_category_details": menu_category_details
                    }
            # Fallback: assign to first available option
            else:
                if not meals_result[meal_type]["breakfast_options"]["option1"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option1"] = {
                        "menu_category_id": item.menu_category_id,
                        "menu_category_details": menu_category_details
                    }
                elif not meals_result[meal_type]["breakfast_options"]["option2"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option2"] = {
                        "menu_category_id": item.menu_category_id,
                        "menu_category_details": menu_category_details
                    }
                elif not meals_result[meal_type]["breakfast_options"]["external"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["external"] = {
                        "menu_category_id": item.menu_category_id,
                        "menu_category_details": menu_category_details
                    }

        # Handle lunch configurations
        elif meal_type == "lunch":
            meal_type_reference = item.meal_type_reference or ""

            if meal_type_reference == "set_a":
                meals_result[meal_type]["set_a_config"]["enabled"] = True
                meals_result[meal_type]["set_a_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['set_a_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "menu_category_details": menu_category_details
                })
            elif meal_type_reference == "set_au":
                meals_result[meal_type]["set_au_config"]["enabled"] = True
                meals_result[meal_type]["set_au_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['set_au_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "menu_category_details": menu_category_details
                })
            elif meal_type_reference == "eat_clean":
                meals_result[meal_type]["eat_clean_config"]["enabled"] = True
                meals_result[meal_type]["eat_clean_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['eat_clean_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "menu_category_details": menu_category_details
                })
            elif meal_type_reference == "buffet":
                meals_result[meal_type]["buffet_config"]["enabled"] = True
                # Get buffet names from the first item or any item that has them
                if not meals_result[meal_type]["buffet_config"]["name_vn"] and item.buffet_name_vn:
                    meals_result[meal_type]["buffet_config"]["name_vn"] = item.buffet_name_vn
                if not meals_result[meal_type]["buffet_config"]["name_en"] and item.buffet_name_en:
                    meals_result[meal_type]["buffet_config"]["name_en"] = item.buffet_name_en
                meals_result[meal_type]["buffet_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['buffet_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "menu_category_details": menu_category_details
                })

        # Handle dinner - use dinner_items array to support multiple snacks/drinks
        elif meal_type == "dinner":
            meal_type_reference = item.meal_type_reference or ""

            # Add all dinner items to dinner_items array
            meals_result[meal_type]["dinner_items"].append({
                "id": f"item_{len(meals_result[meal_type]['dinner_items'])}",
                "option_type": meal_type_reference if meal_type_reference else "",
                "menu_category_id": item.menu_category_id,
                "menu_category_details": menu_category_details,
                "education_stage": item.education_stage or ""
            })

        # Handle legacy items array for backward compatibility
        else:
            if "items" not in meals_result[meal_type]:
                meals_result[meal_type]["items"] = []
            meals_result[meal_type]["items"].append({
                "menu_category_id": item.menu_category_id,
                "menu_category_details": menu_category_details,
                "education_stage": item.education_stage or ""
            })

    return list(meals_result.values())


@frappe.whitelist(allow_guest=True, methods=['GET'])
def get_daily_menu_by_id(daily_menu_id=None):
    """Get a specific daily menu by ID with detailed item information for parent portal"""
    try:
        # Get daily_menu_id from parameter or from request
        if not daily_menu_id:
            daily_menu_id = get_request_param('daily_menu_id')

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

        # Get menu items directly
        daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)

        # Convert flat items to detailed meals structure for parent portal
        menu_data = {
            "name": menu.name,
            "menu_date": menu.menu_date,
            "meals": get_detailed_menu_items(daily_menu_doc.items)
        }
        return single_item_response(menu_data, "Daily Menu fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menu {daily_menu_id}: {str(e)}")
        return error_response(f"Error fetching daily menu: {str(e)}")


@frappe.whitelist(allow_guest=True, methods=['GET'])
def get_daily_menu_by_date(date=None):
    """Get daily menu by date for parent portal"""
    try:
        # Get date from parameter or from request
        if not date:
            date = get_request_param('date')

        if not date:
            return validation_error_response("Date is required", {"date": ["Date is required"]})

        # Find daily menu by date
        daily_menus = frappe.get_all(
            "SIS Daily Menu",
            filters={
                "menu_date": date
            },
            fields=[
                "name", "menu_date",
                "creation", "modified"
            ]
        )

        if not daily_menus:
            return not_found_response("Daily Menu not found for this date")

        menu = daily_menus[0]

        # Get menu items directly
        daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)

        # Convert flat items to detailed meals structure for parent portal
        menu_data = {
            "name": menu.name,
            "menu_date": menu.menu_date,
            "meals": get_detailed_menu_items(daily_menu_doc.items)
        }
        return single_item_response(menu_data, "Daily Menu fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menu for date {date}: {str(e)}")
        return error_response(f"Error fetching daily menu: {str(e)}")
