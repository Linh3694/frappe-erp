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


def convert_items_to_meals_structure(items, menu_name):
    """Convert flat items array to new meals structure for frontend"""
    meals_result = {}

    # Initialize meal structures with full nested structure
    meals_result = {
        "breakfast": {
            "meal_type": "breakfast",
            "menu_type": "custom",
            "meal_type_reference": "",
            "name": f"breakfast_{menu_name}",
            "breakfast_options": {
                "option1": {"menu_category_id": "", "display_name": "", "display_name_en": ""},
                "option2": {"menu_category_id": "", "display_name": "", "display_name_en": ""},
                "external": {"menu_category_id": "", "display_name": "", "display_name_en": ""}
            }
        },
        "lunch": {
            "meal_type": "lunch",
            "menu_type": "custom",
            "meal_type_reference": "",
            "name": f"lunch_{menu_name}",
            "set_a_config": {"enabled": False, "items": []},
            "set_au_config": {"enabled": False, "items": []},
            "eat_clean_config": {"enabled": False, "items": []},
            "buffet_config": {"enabled": False, "name_vn": "", "name_en": "", "items": []}
        },
        "dinner": {
            "meal_type": "dinner",
            "menu_type": "custom",
            "meal_type_reference": "",
            "name": f"dinner_{menu_name}",
            "dinner_items": []  # Array supports multiple snacks and drinks
        }
    }

    for item in items:
        meal_type = item.meal_type

        # Skip if meal_type not in our fixed structure
        if meal_type not in meals_result:
            continue

        # Helper function to convert empty menu_category_id to __none__
        def convert_menu_category_id(menu_category_id):
            return menu_category_id if menu_category_id else "__none__"

        # Handle breakfast options
        if meal_type == "breakfast":
            # Map item to appropriate breakfast option
            meal_type_reference = item.meal_type_reference or ""
            if meal_type_reference == "option1" or not meal_type_reference:
                if not meals_result[meal_type]["breakfast_options"]["option1"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option1"] = {
                        "menu_category_id": convert_menu_category_id(item.menu_category_id),
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
            elif meal_type_reference == "option2":
                if not meals_result[meal_type]["breakfast_options"]["option2"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option2"] = {
                        "menu_category_id": convert_menu_category_id(item.menu_category_id),
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
            elif meal_type_reference == "external":
                if not meals_result[meal_type]["breakfast_options"]["external"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["external"] = {
                        "menu_category_id": convert_menu_category_id(item.menu_category_id),
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
            # Fallback: assign to first available option
            else:
                if not meals_result[meal_type]["breakfast_options"]["option1"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option1"] = {
                        "menu_category_id": convert_menu_category_id(item.menu_category_id),
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
                elif not meals_result[meal_type]["breakfast_options"]["option2"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option2"] = {
                        "menu_category_id": convert_menu_category_id(item.menu_category_id),
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
                elif not meals_result[meal_type]["breakfast_options"]["external"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["external"] = {
                        "menu_category_id": convert_menu_category_id(item.menu_category_id),
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }

        # Handle lunch configurations
        elif meal_type == "lunch":
            meal_type_reference = item.meal_type_reference or ""

            if meal_type_reference == "set_a":
                meals_result[meal_type]["set_a_config"]["enabled"] = True
                meals_result[meal_type]["set_a_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['set_a_config']['items'])}",
                    "menu_category_id": convert_menu_category_id(item.menu_category_id),
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })
            elif meal_type_reference == "set_au":
                meals_result[meal_type]["set_au_config"]["enabled"] = True
                meals_result[meal_type]["set_au_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['set_au_config']['items'])}",
                    "menu_category_id": convert_menu_category_id(item.menu_category_id),
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })
            elif meal_type_reference == "eat_clean":
                meals_result[meal_type]["eat_clean_config"]["enabled"] = True
                meals_result[meal_type]["eat_clean_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['eat_clean_config']['items'])}",
                    "menu_category_id": convert_menu_category_id(item.menu_category_id),
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
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
                    "menu_category_id": convert_menu_category_id(item.menu_category_id),
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })

        # Handle dinner - use dinner_items array to support multiple snacks/drinks
        elif meal_type == "dinner":
            meal_type_reference = item.meal_type_reference or ""
            
            # Add all dinner items to dinner_items array
            meals_result[meal_type]["dinner_items"].append({
                "id": f"item_{len(meals_result[meal_type]['dinner_items'])}",
                "option_type": meal_type_reference if meal_type_reference else "",
                "menu_category_id": convert_menu_category_id(item.menu_category_id),
                "display_name": item.display_name or "",
                "display_name_en": item.display_name_en or "",
                "education_stage": item.education_stage or ""
            })

        # Handle legacy items array for backward compatibility
        else:
            if "items" not in meals_result[meal_type]:
                meals_result[meal_type]["items"] = []
            meals_result[meal_type]["items"].append({
                "menu_category_id": item.menu_category_id,
                "display_name": item.display_name or "",
                "display_name_en": item.display_name_en or "",
                "education_stage": item.education_stage or ""
            })

    return list(meals_result.values())


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


@frappe.whitelist(allow_guest=False)
def get_all_daily_menus():
    """Get all daily menus with pagination support"""
    try:
        # Check if fetch_all is requested
        fetch_all = frappe.local.form_dict.get('fetch_all') == '1'

        if fetch_all:
            # Return all records without pagination
            daily_menus = frappe.get_all(
                "SIS Daily Menu",
                fields=[
                    "name",
                    "menu_date",
                    "creation",
                    "modified"
                ],
                order_by="menu_date desc"
            )
        else:
            # Use pagination (existing logic)
            page = int(frappe.local.form_dict.get('page', 1))
            page_size = int(frappe.local.form_dict.get('page_size', 20))
            start = (page - 1) * page_size

            daily_menus = frappe.get_all(
                "SIS Daily Menu",
                fields=[
                    "name",
                    "menu_date",
                    "creation",
                    "modified"
                ],
                limit_start=start,
                limit_page_length=page_size,
                order_by="menu_date desc"
            )

        # Get items for each daily menu and convert to meals structure
        for menu in daily_menus:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)

            # Convert flat items to new meals structure
            menu["meals"] = convert_items_to_meals_structure(daily_menu_doc.items, menu.name)

        return list_response(daily_menus, "Daily menus fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus: {str(e)}")
        return error_response(f"Error fetching daily menus: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_daily_menu_by_id(daily_menu_id=None):
    """Get a specific daily menu by ID"""
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

        # Convert flat items to new meals structure for frontend compatibility
        menu_data = {
            "name": menu.name,
            "menu_date": menu.menu_date,
            "meals": convert_items_to_meals_structure(daily_menu_doc.items, menu.name)
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
                    pass
                else:
                    data = frappe.local.form_dict
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict

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

        # Create new daily menu with simplified structure
        frappe.db.begin()
        try:
            # Prepare all items with meal information
            all_items = []

            # Normalize education stage values to match DocType options
            def normalize_education_stage(raw_education_stage):
                if not raw_education_stage:
                    return ""
                if "tiểu" in raw_education_stage.lower():
                    return "Tiểu học"
                elif "trung" in raw_education_stage.lower():
                    return "Trung học"
                else:
                    return raw_education_stage

            for meal_data in meals:
                meal_type = meal_data.get("meal_type")
                meal_type_reference = meal_data.get("meal_type_reference", "")

                # Handle new breakfast_options structure
                if meal_type == "breakfast" and "breakfast_options" in meal_data:
                    breakfast_options = meal_data["breakfast_options"]
                    for option_key in ["option1", "option2", "external"]:
                        option_data = breakfast_options.get(option_key)
                        if option_data:
                            menu_category_id = option_data.get("menu_category_id", "")
                            # This maintains the fixed 3-option structure
                            all_items.append({
                                "doctype": "SIS Daily Menu Item",
                                "meal_type": meal_type,
                                "meal_type_reference": option_key,  # Use option_key as reference
                                "menu_category_id": menu_category_id,
                                "display_name": option_data.get("display_name", ""),
                                "display_name_en": option_data.get("display_name_en", ""),
                                "education_stage": ""
                            })

                # Handle lunch set configurations
                elif meal_type == "lunch":
                    # Handle set_a_config
                    if meal_data.get("set_a_config", {}).get("enabled"):
                        config = meal_data["set_a_config"]
                        for item_data in config.get("items", []):
                            menu_category_id = item_data.get("menu_category_id", "")
                            # Always create item for lunch set configs, even if menu_category_id is empty
                            # This maintains the fixed structure
                            all_items.append({
                                "doctype": "SIS Daily Menu Item",
                                "meal_type": meal_type,
                                "meal_type_reference": "set_a",
                                "menu_category_id": menu_category_id,
                                "display_name": item_data.get("display_name", ""),
                                "display_name_en": item_data.get("display_name_en", ""),
                                "education_stage": ""
                            })

                    # Handle set_au_config
                    if meal_data.get("set_au_config", {}).get("enabled"):
                        config = meal_data["set_au_config"]
                        for item_data in config.get("items", []):
                            menu_category_id = item_data.get("menu_category_id", "")
                            # Always create item for lunch set configs, even if menu_category_id is empty
                            all_items.append({
                                "doctype": "SIS Daily Menu Item",
                                "meal_type": meal_type,
                                "meal_type_reference": "set_au",
                                "menu_category_id": menu_category_id,
                                "display_name": item_data.get("display_name", ""),
                                "display_name_en": item_data.get("display_name_en", ""),
                                "education_stage": ""
                            })

                    # Handle eat_clean_config
                    if meal_data.get("eat_clean_config", {}).get("enabled"):
                        config = meal_data["eat_clean_config"]
                        for item_data in config.get("items", []):
                            menu_category_id = item_data.get("menu_category_id", "")
                            # Always create item for lunch set configs, even if menu_category_id is empty
                            all_items.append({
                                "doctype": "SIS Daily Menu Item",
                                "meal_type": meal_type,
                                "meal_type_reference": "eat_clean",
                                "menu_category_id": menu_category_id,
                                "display_name": item_data.get("display_name", ""),
                                "display_name_en": item_data.get("display_name_en", ""),
                                "education_stage": ""
                            })

                    # Handle buffet_config
                    if meal_data.get("buffet_config", {}).get("enabled"):
                        buffet_config = meal_data["buffet_config"]
                        buffet_name_vn = buffet_config.get("name_vn", "")
                        buffet_name_en = buffet_config.get("name_en", "")
                        for item_data in buffet_config.get("items", []):
                            menu_category_id = item_data.get("menu_category_id", "")
                            # Always create item for buffet config, even if menu_category_id is empty
                            all_items.append({
                                "doctype": "SIS Daily Menu Item",
                                "meal_type": meal_type,
                                "meal_type_reference": "buffet",
                                "menu_category_id": menu_category_id,
                                "display_name": item_data.get("display_name", ""),
                                "display_name_en": item_data.get("display_name_en", ""),
                                "education_stage": "",
                                "buffet_name_vn": buffet_name_vn,
                                "buffet_name_en": buffet_name_en
                            })

                # Handle items array (for dinner and other meal types with items array)
                # This now properly handles dinner items instead of the broken elif block
                if meal_data.get("items"):
                    for item_data in meal_data.get("items", []):
                        # Only allow education_stage for dinner meals
                        education_stage = ""
                        if meal_type == "dinner":
                            education_stage = normalize_education_stage(item_data.get("education_stage", ""))
                        
                        # For dinner items, use option_type as meal_type_reference if available
                        item_meal_type_ref = meal_type_reference
                        if meal_type == "dinner" and "option_type" in item_data:
                            item_meal_type_ref = item_data.get("option_type", "")

                        all_items.append({
                            "doctype": "SIS Daily Menu Item",
                            "meal_type": meal_type,
                            "meal_type_reference": item_meal_type_ref,
                            "menu_category_id": item_data.get("menu_category_id"),
                            "display_name": item_data.get("display_name", ""),
                            "display_name_en": item_data.get("display_name_en", ""),
                            "education_stage": education_stage
                        })

            # Create daily menu document with all items
            daily_menu_doc = frappe.get_doc({
                "doctype": "SIS Daily Menu",
                "menu_date": menu_date,
                "items": all_items
            })

            # Insert document - much simpler now
            daily_menu_doc.insert()
            frappe.db.commit()
            
        except Exception as e:
            frappe.db.rollback()
            raise e

        # Convert flat items back to new meals structure for frontend compatibility
        daily_menu_data = {
            "name": daily_menu_doc.name,
            "menu_date": daily_menu_doc.menu_date,
            "meals": convert_items_to_meals_structure(daily_menu_doc.items, daily_menu_doc.name)
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

        # Update items with optimized transaction
        if meals is not None:
            frappe.db.begin()
            try:
                # Clear existing items
                daily_menu_doc.items = []

                # Prepare all items with meal information
                # Normalize education stage values to match DocType options
                def normalize_education_stage(raw_education_stage):
                    if not raw_education_stage:
                        return ""
                    if "tiểu" in raw_education_stage.lower():
                        return "Tiểu học"
                    elif "trung" in raw_education_stage.lower():
                        return "Trung học"
                    else:
                        return raw_education_stage

                for meal_data in meals:
                    meal_type = meal_data.get("meal_type")
                    meal_type_reference = meal_data.get("meal_type_reference", "")

                    # Handle new breakfast_options structure
                    if meal_type == "breakfast" and "breakfast_options" in meal_data:
                        breakfast_options = meal_data["breakfast_options"]
                        for option_key in ["option1", "option2", "external"]:
                            option_data = breakfast_options.get(option_key)
                            if option_data:
                                menu_category_id = option_data.get("menu_category_id", "")
                                # Always create item for breakfast options, even if menu_category_id is empty
                                # This maintains the fixed 3-option structure
                                daily_menu_doc.append("items", {
                                    "doctype": "SIS Daily Menu Item",
                                    "meal_type": meal_type,
                                    "meal_type_reference": option_key,  # Use option_key as reference
                                    "menu_category_id": menu_category_id,
                                    "display_name": option_data.get("display_name", ""),
                                    "display_name_en": option_data.get("display_name_en", ""),
                                    "education_stage": ""
                                })

                    # Handle lunch set configurations
                    elif meal_type == "lunch":
                        # Handle set_a_config
                        if meal_data.get("set_a_config", {}).get("enabled"):
                            config = meal_data["set_a_config"]
                            for item_data in config.get("items", []):
                                menu_category_id = item_data.get("menu_category_id")
                                if menu_category_id:
                                    daily_menu_doc.append("items", {
                                        "doctype": "SIS Daily Menu Item",
                                        "meal_type": meal_type,
                                        "meal_type_reference": "set_a",
                                        "menu_category_id": menu_category_id,
                                        "display_name": item_data.get("display_name", ""),
                                        "display_name_en": item_data.get("display_name_en", ""),
                                        "education_stage": ""
                                    })

                        # Handle set_au_config
                        if meal_data.get("set_au_config", {}).get("enabled"):
                            config = meal_data["set_au_config"]
                            for item_data in config.get("items", []):
                                daily_menu_doc.append("items", {
                                    "doctype": "SIS Daily Menu Item",
                                    "meal_type": meal_type,
                                    "meal_type_reference": "set_au",
                                    "menu_category_id": item_data.get("menu_category_id"),
                                    "display_name": item_data.get("display_name", ""),
                                    "display_name_en": item_data.get("display_name_en", ""),
                                    "education_stage": ""
                                })

                        # Handle eat_clean_config
                        if meal_data.get("eat_clean_config", {}).get("enabled"):
                            config = meal_data["eat_clean_config"]
                            for item_data in config.get("items", []):
                                daily_menu_doc.append("items", {
                                    "doctype": "SIS Daily Menu Item",
                                    "meal_type": meal_type,
                                    "meal_type_reference": "eat_clean",
                                    "menu_category_id": item_data.get("menu_category_id"),
                                    "display_name": item_data.get("display_name", ""),
                                    "display_name_en": item_data.get("display_name_en", ""),
                                    "education_stage": ""
                                })

                        # Handle buffet_config
                        if meal_data.get("buffet_config") and meal_data["buffet_config"].get("items"):
                            buffet_config = meal_data["buffet_config"]
                            buffet_name_vn = buffet_config.get("name_vn", "")
                            buffet_name_en = buffet_config.get("name_en", "")
                            for item_data in buffet_config.get("items", []):
                                daily_menu_doc.append("items", {
                                    "doctype": "SIS Daily Menu Item",
                                    "meal_type": meal_type,
                                    "meal_type_reference": "buffet",
                                    "menu_category_id": item_data.get("menu_category_id"),
                                    "display_name": item_data.get("display_name", ""),
                                    "display_name_en": item_data.get("display_name_en", ""),
                                    "education_stage": "",
                                    "buffet_name_vn": buffet_name_vn,
                                    "buffet_name_en": buffet_name_en
                                })

                    # Handle items array (for dinner and other meal types with items array)
                    # This now properly handles dinner items instead of the broken elif block
                    if meal_data.get("items"):
                        for item_data in meal_data.get("items", []):
                            # Only allow education_stage for dinner meals
                            education_stage = ""
                            if meal_type == "dinner":
                                education_stage = normalize_education_stage(item_data.get("education_stage", ""))
                            
                            # For dinner items, use option_type as meal_type_reference if available
                            item_meal_type_ref = meal_type_reference
                            if meal_type == "dinner" and "option_type" in item_data:
                                item_meal_type_ref = item_data.get("option_type", "")

                            daily_menu_doc.append("items", {
                                "doctype": "SIS Daily Menu Item",
                                "meal_type": meal_type,
                                "meal_type_reference": item_meal_type_ref,
                                "menu_category_id": item_data.get("menu_category_id"),
                                "display_name": item_data.get("display_name", ""),
                                "display_name_en": item_data.get("display_name_en", ""),
                                "education_stage": education_stage
                            })

                # Save all changes in one transaction
                daily_menu_doc.save()
                frappe.db.commit()
                
            except Exception as e:
                frappe.db.rollback()
                raise e

        # Convert flat items back to new meals structure for frontend compatibility
        daily_menu_data = {
            "name": daily_menu_doc.name,
            "menu_date": daily_menu_doc.menu_date,
            "meals": convert_items_to_meals_structure(daily_menu_doc.items, daily_menu_doc.name)
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
def get_available_months():
    """Get all available months that have daily menus"""
    try:
        # Get distinct months from menu_date
        months_data = frappe.db.sql("""
            SELECT DISTINCT DATE_FORMAT(menu_date, '%Y-%m') as month_value,
                   DATE_FORMAT(menu_date, '%m/%Y') as month_label
            FROM `tabSIS Daily Menu`
            WHERE docstatus = 0
            ORDER BY month_value DESC
        """, as_dict=True)

        # If no data, return current month
        if not months_data:
            current_month = frappe.utils.nowdate()[:7]  # yyyy-MM format
            current_date = frappe.utils.getdate(frappe.utils.nowdate())
            month_label = current_date.strftime('%m/%Y')
            months_data = [{"month_value": current_month, "month_label": month_label}]

        return list_response(months_data, "Available months fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching available months: {str(e)}")
        return error_response(f"Error fetching available months: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_daily_menus_by_month(month=None):
    """Get daily menus for a specific month"""
    try:
        # Get month from parameter or from request
        if not month:
            month = get_request_param('month')

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

        # Get items for each daily menu and convert to meals structure
        for menu in daily_menus:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)

            # Convert flat items to new meals structure
            menu["meals"] = convert_items_to_meals_structure(daily_menu_doc.items, menu.name)

        return list_response(daily_menus, "Daily menus for month fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus for month {month}: {str(e)}")
        return error_response(f"Error fetching daily menus for month: {str(e)}")

