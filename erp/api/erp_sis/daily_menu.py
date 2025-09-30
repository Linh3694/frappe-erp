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
            
            # Convert flat items to meals structure
            meals_result = {}
            for item in daily_menu_doc.items:
                meal_type = item.meal_type
                if meal_type not in meals_result:
                    meals_result[meal_type] = {
                        "meal_type": meal_type,
                        "menu_type": "custom",
                        "meal_type_reference": item.meal_type_reference or "",
                        "name": f"{meal_type}_{menu.name}",
                        "items": []
                    }
                
                meals_result[meal_type]["items"].append({
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or "",
                    "education_stage": item.education_stage or ""
                })

            menu["meals"] = list(meals_result.values())

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

        # Get menu items directly (much simpler now)
        daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)
        
        # Convert flat items to meals structure for frontend compatibility
        meals_result = {}
        for item in daily_menu_doc.items:
            meal_type = item.meal_type
            if meal_type not in meals_result:
                meals_result[meal_type] = {
                    "meal_type": meal_type,
                    "menu_type": "custom",
                    "meal_type_reference": item.meal_type_reference or "",
                    "name": f"{meal_type}_{menu.name}",  # Generate consistent meal name for frontend
                    "items": []
                }
            
            meals_result[meal_type]["items"].append({
                "menu_category_id": item.menu_category_id,
                "display_name": item.display_name or "",
                "display_name_en": item.display_name_en or "",
                "education_stage": item.education_stage or ""
            })

        menu_data = {
            "name": menu.name,
            "menu_date": menu.menu_date,
            "meals": list(meals_result.values())
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
            for meal_data in meals:
                meal_type = meal_data.get("meal_type")
                meal_type_reference = meal_data.get("meal_type_reference", "")
                
                for item_data in meal_data.get("items", []):
                    # Only allow education_stage for dinner meals
                    education_stage = ""
                    if meal_type == "dinner":
                        raw_education_stage = item_data.get("education_stage", "")
                        # Normalize education stage values to match DocType options
                        if raw_education_stage:
                            if "tiểu" in raw_education_stage.lower():
                                education_stage = "Tiểu học"
                            elif "trung" in raw_education_stage.lower():
                                education_stage = "Trung học"
                            else:
                                education_stage = raw_education_stage
                    
                    all_items.append({
                        "doctype": "SIS Daily Menu Item",
                        "meal_type": meal_type,
                        "meal_type_reference": meal_type_reference,
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

        # Convert flat items back to meals structure for frontend compatibility
        meals_result = {}
        for item in daily_menu_doc.items:
            meal_type = item.meal_type
            if meal_type not in meals_result:
                meals_result[meal_type] = {
                    "meal_type": meal_type,
                    "menu_type": "custom",
                    "meal_type_reference": item.meal_type_reference or "",
                    "items": []
                }
            
            meals_result[meal_type]["items"].append({
                "menu_category_id": item.menu_category_id,
                "display_name": item.display_name or "",
                "display_name_en": item.display_name_en or "",
                "education_stage": item.education_stage or ""
            })

        daily_menu_data = {
            "name": daily_menu_doc.name,
            "menu_date": daily_menu_doc.menu_date,
            "meals": list(meals_result.values())
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
                for meal_data in meals:
                    meal_type = meal_data.get("meal_type")
                    meal_type_reference = meal_data.get("meal_type_reference", "")
                    
                    for item_data in meal_data.get("items", []):
                        # Only allow education_stage for dinner meals
                        education_stage = ""
                        if meal_type == "dinner":
                            raw_education_stage = item_data.get("education_stage", "")
                            # Normalize education stage values to match DocType options
                            if raw_education_stage:
                                if "tiểu" in raw_education_stage.lower():
                                    education_stage = "Tiểu học"
                                elif "trung" in raw_education_stage.lower():
                                    education_stage = "Trung học"
                                else:
                                    education_stage = raw_education_stage
                        
                        daily_menu_doc.append("items", {
                            "doctype": "SIS Daily Menu Item",
                            "meal_type": meal_type,
                            "meal_type_reference": meal_type_reference,
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

        # Convert flat items back to meals structure for frontend compatibility
        meals_result = {}
        for item in daily_menu_doc.items:
            meal_type = item.meal_type
            if meal_type not in meals_result:
                meals_result[meal_type] = {
                    "meal_type": meal_type,
                    "menu_type": "custom",
                    "meal_type_reference": item.meal_type_reference or "",
                    "items": []
                }
            
            meals_result[meal_type]["items"].append({
                "menu_category_id": item.menu_category_id,
                "display_name": item.display_name or "",
                "display_name_en": item.display_name_en or "",
                "education_stage": item.education_stage or ""
            })

        daily_menu_data = {
            "name": daily_menu_doc.name,
            "menu_date": daily_menu_doc.menu_date,
            "meals": list(meals_result.values())
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
            
            # Convert flat items to meals structure
            meals_result = {}
            for item in daily_menu_doc.items:
                meal_type = item.meal_type
                if meal_type not in meals_result:
                    meals_result[meal_type] = {
                        "meal_type": meal_type,
                        "menu_type": "custom",
                        "meal_type_reference": item.meal_type_reference or "",
                        "name": f"{meal_type}_{menu.name}",
                        "items": []
                    }
                
                meals_result[meal_type]["items"].append({
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or "",
                    "education_stage": item.education_stage or ""
                })

            menu["meals"] = list(meals_result.values())

        return list_response(daily_menus, "Daily menus for month fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus for month {month}: {str(e)}")
        return error_response(f"Error fetching daily menus for month: {str(e)}")

