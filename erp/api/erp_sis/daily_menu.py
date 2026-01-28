# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, format_date
import json
import calendar
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_request_data():
    """Extract data from request (JSON body or form_dict)"""
    try:
        if frappe.request.data:
            json_data = json.loads(frappe.request.data)
            if json_data:
                return json_data
    except (json.JSONDecodeError, TypeError):
        pass
    
    return frappe.local.form_dict


def get_request_param(param_name):
    """Helper function to get parameter from request in order of priority"""
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


def normalize_education_stage(raw_education_stage):
    """Normalize education stage values to match DocType options"""
    if not raw_education_stage:
        return ""
    if "tiểu" in raw_education_stage.lower():
        return "Tiểu học"
    elif "trung" in raw_education_stage.lower():
        return "Trung học"
    else:
        return raw_education_stage


def process_breakfast_items(meal_data, menu_name):
    """Process breakfast items from meal data"""
    items = []
    breakfast_options = meal_data.get("breakfast_options", {})
    
    for option_key in ["option1", "option2", "external"]:
        option_data = breakfast_options.get(option_key)
        if option_data:
            items.append({
                "doctype": "SIS Daily Menu Item",
                "meal_type": "breakfast",
                "meal_type_reference": option_key,
                "menu_category_id": option_data.get("menu_category_id", ""),
                "display_name": option_data.get("display_name", ""),
                "display_name_en": option_data.get("display_name_en", ""),
                "education_stage": ""
            })
    
    return items


def process_lunch_items(meal_data):
    """Process lunch items from meal data"""
    items = []
    
    # Handle set_a_config
    if meal_data.get("set_a_config", {}).get("enabled"):
        config = meal_data["set_a_config"]
        for item_data in config.get("items", []):
            items.append({
                "doctype": "SIS Daily Menu Item",
                "meal_type": "lunch",
                "meal_type_reference": "set_a",
                "menu_category_id": item_data.get("menu_category_id", ""),
                "display_name": item_data.get("display_name", ""),
                "display_name_en": item_data.get("display_name_en", ""),
                "education_stage": ""
            })

    # Handle set_au_config
    if meal_data.get("set_au_config", {}).get("enabled"):
        config = meal_data["set_au_config"]
        for item_data in config.get("items", []):
            items.append({
                "doctype": "SIS Daily Menu Item",
                "meal_type": "lunch",
                "meal_type_reference": "set_au",
                "menu_category_id": item_data.get("menu_category_id", ""),
                "display_name": item_data.get("display_name", ""),
                "display_name_en": item_data.get("display_name_en", ""),
                "education_stage": ""
            })

    # Handle eat_clean_config
    if meal_data.get("eat_clean_config", {}).get("enabled"):
        config = meal_data["eat_clean_config"]
        for item_data in config.get("items", []):
            items.append({
                "doctype": "SIS Daily Menu Item",
                "meal_type": "lunch",
                "meal_type_reference": "eat_clean",
                "menu_category_id": item_data.get("menu_category_id", ""),
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
            items.append({
                "doctype": "SIS Daily Menu Item",
                "meal_type": "lunch",
                "meal_type_reference": "buffet",
                "menu_category_id": item_data.get("menu_category_id", ""),
                "display_name": item_data.get("display_name", ""),
                "display_name_en": item_data.get("display_name_en", ""),
                "education_stage": "",
                "buffet_name_vn": buffet_name_vn,
                "buffet_name_en": buffet_name_en
            })
    
    return items


def process_meal_items(meal_type, meal_data, meal_type_reference=""):
    """Process generic meal items (especially dinner)"""
    items = []
    
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

            items.append({
                "doctype": "SIS Daily Menu Item",
                "meal_type": meal_type,
                "meal_type_reference": item_meal_type_ref,
                "menu_category_id": item_data.get("menu_category_id", ""),
                "display_name": item_data.get("display_name", ""),
                "display_name_en": item_data.get("display_name_en", ""),
                "education_stage": education_stage
            })
    
    return items


def convert_items_to_meals_structure(items, menu_name):
    """Convert flat items array to new meals structure for frontend"""
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
            "dinner_items": []
        }
    }

    for item in items:
        meal_type = item.meal_type

        # Skip if meal_type not in our fixed structure
        if meal_type not in meals_result:
            continue

        # Handle breakfast options
        if meal_type == "breakfast":
            meal_type_reference = item.meal_type_reference or ""
            if meal_type_reference == "option1" or not meal_type_reference:
                if not meals_result[meal_type]["breakfast_options"]["option1"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option1"] = {
                        "menu_category_id": item.menu_category_id,
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
            elif meal_type_reference == "option2":
                if not meals_result[meal_type]["breakfast_options"]["option2"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option2"] = {
                        "menu_category_id": item.menu_category_id,
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
            elif meal_type_reference == "external":
                if not meals_result[meal_type]["breakfast_options"]["external"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["external"] = {
                        "menu_category_id": item.menu_category_id,
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
            # Fallback: assign to first available option
            else:
                if not meals_result[meal_type]["breakfast_options"]["option1"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option1"] = {
                        "menu_category_id": item.menu_category_id,
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
                elif not meals_result[meal_type]["breakfast_options"]["option2"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["option2"] = {
                        "menu_category_id": item.menu_category_id,
                        "display_name": item.display_name or "",
                        "display_name_en": item.display_name_en or ""
                    }
                elif not meals_result[meal_type]["breakfast_options"]["external"]["menu_category_id"]:
                    meals_result[meal_type]["breakfast_options"]["external"] = {
                        "menu_category_id": item.menu_category_id,
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
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })
            elif meal_type_reference == "set_au":
                meals_result[meal_type]["set_au_config"]["enabled"] = True
                meals_result[meal_type]["set_au_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['set_au_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })
            elif meal_type_reference == "eat_clean":
                meals_result[meal_type]["eat_clean_config"]["enabled"] = True
                meals_result[meal_type]["eat_clean_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['eat_clean_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })
            elif meal_type_reference == "buffet":
                meals_result[meal_type]["buffet_config"]["enabled"] = True
                if not meals_result[meal_type]["buffet_config"]["name_vn"] and item.buffet_name_vn:
                    meals_result[meal_type]["buffet_config"]["name_vn"] = item.buffet_name_vn
                if not meals_result[meal_type]["buffet_config"]["name_en"] and item.buffet_name_en:
                    meals_result[meal_type]["buffet_config"]["name_en"] = item.buffet_name_en
                meals_result[meal_type]["buffet_config"]["items"].append({
                    "id": f"item_{len(meals_result[meal_type]['buffet_config']['items'])}",
                    "menu_category_id": item.menu_category_id,
                    "display_name": item.display_name or "",
                    "display_name_en": item.display_name_en or ""
                })

        # Handle dinner
        elif meal_type == "dinner":
            meal_type_reference = item.meal_type_reference or ""
            meals_result[meal_type]["dinner_items"].append({
                "id": f"item_{len(meals_result[meal_type]['dinner_items'])}",
                "option_type": meal_type_reference if meal_type_reference else "",
                "menu_category_id": item.menu_category_id,
                "display_name": item.display_name or "",
                "display_name_en": item.display_name_en or "",
                "education_stage": item.education_stage or ""
            })

    return list(meals_result.values())


# ============================================================================
# API ENDPOINTS
# ============================================================================

@frappe.whitelist(allow_guest=False)
def get_all_daily_menus():
    """Get all daily menus with pagination support"""
    try:
        # Sử dụng get_request_param để lấy parameter từ cả query string và form_dict
        fetch_all = get_request_param('fetch_all') == '1'

        if fetch_all:
            daily_menus = frappe.get_all(
                "SIS Daily Menu",
                fields=["name", "menu_date", "creation", "modified"],
                order_by="menu_date desc"
            )
        else:
            page = int(get_request_param('page') or 1)
            page_size = int(get_request_param('page_size') or 20)
            start = (page - 1) * page_size

            daily_menus = frappe.get_all(
                "SIS Daily Menu",
                fields=["name", "menu_date", "creation", "modified"],
                limit_start=start,
                limit_page_length=page_size,
                order_by="menu_date desc"
            )

        for menu in daily_menus:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)
            menu["meals"] = convert_items_to_meals_structure(daily_menu_doc.items, menu.name)

        return list_response(daily_menus, "Daily menus fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus: {str(e)}")
        return error_response(f"Error fetching daily menus: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_daily_menu_by_id(daily_menu_id=None):
    """Get a specific daily menu by ID"""
    try:
        if not daily_menu_id:
            daily_menu_id = get_request_param('daily_menu_id')

        if not daily_menu_id:
            return validation_error_response("Daily Menu ID is required", {"daily_menu_id": ["Daily Menu ID is required"]})

        daily_menus = frappe.get_all(
            "SIS Daily Menu",
            filters={"name": daily_menu_id},
            fields=["name", "menu_date", "creation", "modified"]
        )

        if not daily_menus:
            return not_found_response("Daily Menu not found")

        menu = daily_menus[0]
        daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)

        menu_data = {
            "name": menu.name,
            "menu_date": menu.menu_date,
            "meals": convert_items_to_meals_structure(daily_menu_doc.items, menu.name)
        }
        return single_item_response(menu_data, "Daily Menu fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menu {daily_menu_id}: {str(e)}")
        return error_response(f"Error fetching daily menu: {str(e)}")


def build_daily_menu_items(meals):
    """Build all items from meals structure - used by both create and update"""
    all_items = []

    for meal_data in meals:
        meal_type = meal_data.get("meal_type")

        if meal_type == "breakfast" and "breakfast_options" in meal_data:
            all_items.extend(process_breakfast_items(meal_data, ""))

        elif meal_type == "lunch":
            all_items.extend(process_lunch_items(meal_data))

        elif meal_type == "dinner":
            all_items.extend(process_meal_items(meal_type, meal_data))

    return all_items


@frappe.whitelist(allow_guest=False)
def create_daily_menu():
    """Create a new daily menu"""
    try:
        data = get_request_data()
        menu_date = data.get("menu_date")
        meals = data.get("meals") or []

        if not menu_date:
            return validation_error_response(
                "Validation failed",
                {"menu_date": ["Ngày thực đơn là bắt buộc"]}
            )

        if frappe.db.exists("SIS Daily Menu", {"menu_date": menu_date}):
            return validation_error_response("Menu date already exists", {"menu_date": [f"Ngày {menu_date} đã có thực đơn"]})

        frappe.db.begin()
        try:
            all_items = build_daily_menu_items(meals)

            daily_menu_doc = frappe.get_doc({
                "doctype": "SIS Daily Menu",
                "menu_date": menu_date,
                "items": all_items
            })

            daily_menu_doc.insert()
            frappe.db.commit()
            
        except Exception as e:
            frappe.db.rollback()
            raise e

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
        data = get_request_data()
        daily_menu_id = data.get('daily_menu_id') or data.get('name')
        
        if not daily_menu_id:
            return validation_error_response("Daily Menu ID is required", {"daily_menu_id": ["Daily Menu ID is required"]})

        try:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", daily_menu_id)
        except frappe.DoesNotExistError:
            return not_found_response("Daily Menu not found")

        menu_date = data.get('menu_date')
        meals = data.get('meals')

        if menu_date and menu_date != daily_menu_doc.menu_date:
            daily_menu_doc.menu_date = menu_date

        if meals is not None:
            frappe.db.begin()
            try:
                daily_menu_doc.items = []
                all_items = build_daily_menu_items(meals)

                for item in all_items:
                    daily_menu_doc.append("items", item)

                daily_menu_doc.save()
                frappe.db.commit()
                
            except Exception as e:
                frappe.db.rollback()
                raise e

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
        data = get_request_data()
        daily_menu_id = data.get('daily_menu_id') or data.get('name')
        
        if not daily_menu_id:
            return validation_error_response("Daily Menu ID is required", {"daily_menu_id": ["Daily Menu ID is required"]})

        try:
            frappe.delete_doc("SIS Daily Menu", daily_menu_id)
            frappe.db.commit()
        except frappe.DoesNotExistError:
            return not_found_response("Daily Menu not found")

        return success_response(message="Daily Menu deleted successfully")

    except Exception as e:
        frappe.log_error(f"Error deleting daily menu: {str(e)}")
        return error_response(f"Error deleting daily menu: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_available_months():
    """Get all available months that have daily menus"""
    try:
        months_data = frappe.db.sql("""
            SELECT DISTINCT DATE_FORMAT(menu_date, '%Y-%m') as month_value,
                   DATE_FORMAT(menu_date, '%m/%Y') as month_label
            FROM `tabSIS Daily Menu`
            WHERE docstatus = 0
            ORDER BY month_value DESC
        """, as_dict=True)

        if not months_data:
            current_month = frappe.utils.nowdate()[:7]
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
        if not month:
            month = get_request_param('month')

        if not month:
            return validation_error_response("Month is required", {"month": ["Month is required"]})

        try:
            year, month_num = month.split('-')
            start_date = f"{year}-{month_num}-01"
            last_day = calendar.monthrange(int(year), int(month_num))[1]
            end_date = f"{year}-{month_num}-{last_day:02d}"
        except:
            return validation_error_response("Invalid month format", {"month": ["Month must be in yyyy-MM format"]})

        daily_menus = frappe.get_all(
            "SIS Daily Menu",
            fields=["name", "menu_date", "creation", "modified"],
            filters={"menu_date": ["between", [start_date, end_date]]},
            order_by="menu_date asc"
        )

        for menu in daily_menus:
            daily_menu_doc = frappe.get_doc("SIS Daily Menu", menu.name)
            menu["meals"] = convert_items_to_meals_structure(daily_menu_doc.items, menu.name)

        return list_response(daily_menus, "Daily menus for month fetched successfully")

    except Exception as e:
        frappe.log_error(f"Error fetching daily menus for month {month}: {str(e)}")
        return error_response(f"Error fetching daily menus for month: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_meal_tracking_by_date(date=None):
    """Get meal tracking data by date - attendance summary by education stage for homeroom teachers"""
    try:
        if not date:
            date = get_request_param('date')

        if not date:
            return validation_error_response("Date is required", {"date": ["Date is required"]})

        # Validate date format (YYYY-MM-DD)
        try:
            from datetime import datetime
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return validation_error_response("Invalid date format", {"date": ["Date must be in YYYY-MM-DD format"]})

        # Get current campus from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()

        # Lấy năm học hiện tại đang active (is_enable = 1)
        current_year = frappe.get_all(
            "SIS School Year",
            filters={"is_enable": 1},
            fields=["name"],
            order_by="creation desc",
            limit=1
        )
        
        if not current_year:
            return single_item_response({
                'education_stages': [],
                'date': date,
                'total_classes': 0,
                'total_students': 0
            }, "Không tìm thấy năm học đang active")
        
        school_year_id = current_year[0].name

        # Step 1: Get all classes with homeroom teachers for the current campus AND school year
        classes_with_homeroom = frappe.get_all(
            "SIS Class",
            fields=["name", "homeroom_teacher", "vice_homeroom_teacher", "campus_id", "education_grade"],
            filters={
                "campus_id": campus_id or "campus-1",
                "homeroom_teacher": ["!=", ""],  # Must have homeroom teacher
                "school_year_id": school_year_id,  # Chỉ lấy lớp của năm học hiện tại
            }
        )

        if not classes_with_homeroom:
            return single_item_response({
                'education_stages': [],
                'date': date,
                'total_classes': 0,
                'total_students': 0
            }, f"No homeroom classes found for date {date}")

        # Step 2: Get education grade details to map to education stages
        education_grade_ids = list(set([cls.education_grade for cls in classes_with_homeroom if cls.education_grade]))
        education_grades = frappe.get_all(
            "SIS Education Grade",
            fields=["name", "education_stage_id"],
            filters={"name": ["in", education_grade_ids]}
        ) if education_grade_ids else []

        # Get education stage IDs and map to their Vietnamese titles
        education_stage_ids = list(set([grade.education_stage_id for grade in education_grades if grade.education_stage_id]))
        education_stages = frappe.get_all(
            "SIS Education Stage",
            fields=["name", "title_vn"],
            filters={"name": ["in", education_stage_ids]}
        ) if education_stage_ids else []

        stage_id_to_title_map = {stage.name: stage.title_vn for stage in education_stages}
        grade_to_stage_map = {grade.name: stage_id_to_title_map.get(grade.education_stage_id, grade.education_stage_id or "Unknown") for grade in education_grades}

        # Step 3: Get attendance data for the specified date với timestamp
        # Count students marked as present or late in homeroom period
        # Late students still arrive before lunch and need a meal
        # Sử dụng SQL để lấy cả timestamp modified cho việc tính trước/sau 9h
        class_ids = [cls.name for cls in classes_with_homeroom]
        class_ids_str = ', '.join([f"'{c}'" for c in class_ids])
        
        attendance_data = frappe.db.sql(f"""
            SELECT 
                class_id, 
                student_id, 
                status, 
                period,
                student_name, 
                student_code,
                TIME(modified) as modified_time
            FROM `tabSIS Class Attendance`
            WHERE date = %(date)s
                AND class_id IN ({class_ids_str})
                AND period = 'homeroom'
                AND status IN ('present', 'Present', 'PRESENT', 'late', 'Late', 'LATE')
        """, {"date": date}, as_dict=True)
        
        # Step 3b: Check if date is a registration date (not just Wednesday anymore)
        # Tìm xem ngày này có nằm trong registration_dates của period nào không
        is_registration_date = frappe.db.exists(
            "SIS Menu Registration Period Date",
            {"date": date}
        )
        
        # Get menu registration data by education stage nếu là ngày đăng ký
        set_a_by_stage = {}
        set_au_by_stage = {}
        registration_stage_stats = {}  # Thống kê từ registration để hiển thị khi chưa có điểm danh
        
        if is_registration_date:
            # Lấy thông tin đăng ký suất ăn theo education_stage cho ngày này
            menu_registration_data = frappe.db.sql("""
                SELECT 
                    es.title_vn as education_stage,
                    ri.choice,
                    COUNT(DISTINCT ri.parent) as count
                FROM `tabSIS Menu Registration Item` ri
                INNER JOIN `tabSIS Menu Registration` r ON ri.parent = r.name
                INNER JOIN `tabSIS Class` c ON r.class_id = c.name
                INNER JOIN `tabSIS Education Grade` eg ON c.education_grade = eg.name
                INNER JOIN `tabSIS Education Stage` es ON eg.education_stage_id = es.name
                WHERE ri.date = %s
                GROUP BY es.title_vn, ri.choice
            """, (date,), as_dict=True)
            
            for item in menu_registration_data:
                stage = item.education_stage
                if item.choice == 'A':
                    set_a_by_stage[stage] = item.count
                elif item.choice == 'AU':
                    set_au_by_stage[stage] = item.count
                
                # Tạo stats cho stage từ registration data (dùng khi chưa có điểm danh)
                if stage not in registration_stage_stats:
                    registration_stage_stats[stage] = {
                        'education_stage': stage,
                        'total_students': 0,  # Chưa có điểm danh nên = 0
                        'classes_count': 0,
                        'set_a': 0,
                        'set_au': 0,
                        'present_before_9': 0,
                        'present_after_9': 0
                    }
            
            # Cập nhật set_a và set_au cho registration_stage_stats
            for stage_name in registration_stage_stats:
                registration_stage_stats[stage_name]['set_a'] = set_a_by_stage.get(stage_name, 0)
                registration_stage_stats[stage_name]['set_au'] = set_au_by_stage.get(stage_name, 0)

        # Step 4: Group attendance by class (với thông tin trước/sau 9h)
        from datetime import time as dt_time
        cutoff_time = dt_time(9, 0, 0)  # 9:00 AM
        
        class_present_students = {}
        class_before_9 = {}
        class_after_9 = {}
        
        for record in attendance_data:
            class_id = record.class_id
            if class_id not in class_present_students:
                class_present_students[class_id] = 0
                class_before_9[class_id] = 0
                class_after_9[class_id] = 0
            
            class_present_students[class_id] += 1
            
            # Phân loại theo timestamp modified
            if record.modified_time:
                # Convert timedelta to time if needed
                if hasattr(record.modified_time, 'total_seconds'):
                    # timedelta from SQL
                    total_seconds = record.modified_time.total_seconds()
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    seconds = int(total_seconds % 60)
                    record_time = dt_time(hours, minutes, seconds)
                else:
                    record_time = record.modified_time
                
                if record_time < cutoff_time:
                    class_before_9[class_id] += 1
                else:
                    class_after_9[class_id] += 1
            else:
                # Nếu không có timestamp, tính là sau 9h (an toàn cho bộ phận bếp)
                class_after_9[class_id] += 1

        # Step 5: Group by education stage
        education_stage_stats = {}

        for cls in classes_with_homeroom:
            present_count = class_present_students.get(cls.name, 0)

            # Skip classes with no present students
            if present_count == 0:
                continue

            # Get education stage from grade mapping
            education_stage = grade_to_stage_map.get(cls.education_grade, "Unknown")

            if education_stage not in education_stage_stats:
                education_stage_stats[education_stage] = {
                    'education_stage': education_stage,
                    'total_students': 0,
                    'classes_count': 0,
                    'set_a': 0,
                    'set_au': 0,
                    'present_before_9': 0,
                    'present_after_9': 0
                }

            education_stage_stats[education_stage]['total_students'] += present_count
            education_stage_stats[education_stage]['classes_count'] += 1
            education_stage_stats[education_stage]['present_before_9'] += class_before_9.get(cls.name, 0)
            education_stage_stats[education_stage]['present_after_9'] += class_after_9.get(cls.name, 0)
        
        # Step 5b: Add Set Á/Âu data if is a registration date
        if is_registration_date:
            for stage_name, stats in education_stage_stats.items():
                stats['set_a'] = set_a_by_stage.get(stage_name, 0)
                stats['set_au'] = set_au_by_stage.get(stage_name, 0)
            
            # Nếu chưa có điểm danh nhưng có registration data -> merge registration stats
            # Để admin có thể xem trước tổng hợp đăng ký Á/Âu cho ngày trong tương lai
            for stage_name, reg_stats in registration_stage_stats.items():
                if stage_name not in education_stage_stats:
                    education_stage_stats[stage_name] = reg_stats

        # Step 6: Convert to list format for response
        result = {
            'education_stages': list(education_stage_stats.values()),
            'date': date,
            'is_registration_date': is_registration_date,  # Đổi từ is_wednesday sang is_registration_date
            'total_classes': len(class_present_students),
            'total_students': sum([stage['total_students'] for stage in education_stage_stats.values()])
        }

        return single_item_response(result, f"Meal tracking data fetched successfully for date {date}")

    except Exception as e:
        frappe.log_error(f"Error fetching meal tracking data: {str(e)}")
        return error_response(f"Error fetching meal tracking data: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_meal_tracking_class_detail(date=None, education_stage=None):
    """
    Lấy chi tiết danh sách lớp theo education stage với phân biệt điểm danh trước/sau 9h.
    
    Field `creation` là timestamp hệ thống tự động ghi khi INSERT record,
    không thể sửa được - đây là evidence tin cậy để bộ phận bếp chốt số liệu.
    
    Args:
        date: Ngày cần xem (YYYY-MM-DD)
        education_stage: Tên education stage (title_vn từ SIS Education Stage)
    
    Returns:
        {
            "classes": [...],
            "summary": {...}
        }
    """
    try:
        if not date:
            date = get_request_param('date')
        if not education_stage:
            education_stage = get_request_param('education_stage')

        if not date:
            return validation_error_response("Date is required", {"date": ["Date is required"]})
        
        if not education_stage:
            return validation_error_response("Education stage is required", {"education_stage": ["Education stage is required"]})

        # Validate date format (YYYY-MM-DD)
        try:
            from datetime import datetime
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return validation_error_response("Invalid date format", {"date": ["Date must be in YYYY-MM-DD format"]})

        # Lấy campus từ context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()

        # Lấy năm học hiện tại đang active (is_enable = 1)
        current_year = frappe.get_all(
            "SIS School Year",
            filters={"is_enable": 1},
            fields=["name"],
            order_by="creation desc",
            limit=1
        )
        
        if not current_year:
            return error_response("Không tìm thấy năm học đang active")
        
        school_year_id = current_year[0].name

        # Tìm education_stage_id từ title_vn
        stage_info = frappe.get_all(
            "SIS Education Stage",
            filters={"title_vn": education_stage},
            fields=["name"],
            limit=1
        )
        
        if not stage_info:
            return not_found_response(f"Education stage '{education_stage}' not found")
        
        stage_id = stage_info[0].name

        # Query chi tiết từng lớp với phân biệt điểm danh trước/sau 9h
        # Sử dụng field `modified` (timestamp cập nhật cuối) để phân biệt
        # Lý do: Nếu GV sửa status từ absent -> present sau 9h, cần tính vào "sau 9h"
        # Thời gian 9h sáng là mốc chốt cho bộ phận bếp
        # Status: present và late đều tính là có mặt (muộn vẫn đến trước buổi trưa, vẫn cần suất ăn)
        # SIS Teacher chỉ có user_id link đến User, cần join thêm để lấy full_name
        # QUAN TRỌNG: Chỉ lấy lớp của năm học hiện tại (school_year_id)
        class_detail_data = frappe.db.sql("""
            SELECT 
                ca.class_id,
                c.title as class_title,
                u.full_name as homeroom_teacher_name,
                COUNT(CASE WHEN TIME(ca.modified) < '09:00:00' THEN 1 END) as present_before_9,
                COUNT(CASE WHEN TIME(ca.modified) >= '09:00:00' THEN 1 END) as present_after_9,
                COUNT(*) as total_present
            FROM `tabSIS Class Attendance` ca
            INNER JOIN `tabSIS Class` c ON ca.class_id = c.name
            LEFT JOIN `tabSIS Teacher` t ON c.homeroom_teacher = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE ca.date = %(date)s
                AND ca.period = 'homeroom'
                AND ca.status IN ('present', 'Present', 'PRESENT', 'late', 'Late', 'LATE')
                AND c.campus_id = %(campus_id)s
                AND c.school_year_id = %(school_year_id)s
                AND c.education_grade IN (
                    SELECT name FROM `tabSIS Education Grade` 
                    WHERE education_stage_id = %(stage_id)s
                )
            GROUP BY ca.class_id, c.title, u.full_name
            ORDER BY c.title
        """, {
            "date": date,
            "campus_id": campus_id or "campus-1",
            "school_year_id": school_year_id,
            "stage_id": stage_id
        }, as_dict=True)

        # Lấy thống kê đăng ký suất ăn (Set Á/Âu) cho mỗi lớp thuộc education_stage này
        meal_registration_stats = frappe.db.sql("""
            SELECT 
                r.class_id,
                c.title as class_title,
                u.full_name as homeroom_teacher_name,
                SUM(CASE WHEN ri.choice = 'A' THEN 1 ELSE 0 END) as set_a,
                SUM(CASE WHEN ri.choice = 'AU' THEN 1 ELSE 0 END) as set_au
            FROM `tabSIS Menu Registration` r
            INNER JOIN `tabSIS Menu Registration Item` ri ON ri.parent = r.name
            INNER JOIN `tabSIS Class` c ON r.class_id = c.name
            LEFT JOIN `tabSIS Teacher` t ON c.homeroom_teacher = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE ri.date = %(date)s
                AND c.campus_id = %(campus_id)s
                AND c.school_year_id = %(school_year_id)s
                AND c.education_grade IN (
                    SELECT name FROM `tabSIS Education Grade` 
                    WHERE education_stage_id = %(stage_id)s
                )
            GROUP BY r.class_id, c.title, u.full_name
        """, {
            "date": date,
            "campus_id": campus_id or "campus-1",
            "school_year_id": school_year_id,
            "stage_id": stage_id
        }, as_dict=True)
        
        # Tạo map class_id -> meal stats
        class_meal_stats = {stat.class_id: stat for stat in meal_registration_stats}
        
        # Gán thống kê suất ăn cho mỗi lớp có điểm danh
        for cls in class_detail_data:
            stats = class_meal_stats.get(cls.class_id, {})
            cls['set_a'] = stats.get('set_a', 0) or 0
            cls['set_au'] = stats.get('set_au', 0) or 0
        
        # Merge: Thêm các lớp có đăng ký Set Á/Âu nhưng chưa có điểm danh
        existing_class_ids = {cls.class_id for cls in class_detail_data}
        for stat in meal_registration_stats:
            if stat.class_id not in existing_class_ids:
                class_detail_data.append({
                    'class_id': stat.class_id,
                    'class_title': stat.class_title,
                    'homeroom_teacher_name': stat.homeroom_teacher_name,
                    'present_before_9': 0,
                    'present_after_9': 0,
                    'total_present': 0,
                    'set_a': stat.set_a or 0,
                    'set_au': stat.set_au or 0
                })
        
        # Sắp xếp lại theo tên lớp
        class_detail_data.sort(key=lambda x: x.get('class_title', ''))

        # Tính tổng summary
        total_before_9 = sum(cls.get('present_before_9', 0) or 0 for cls in class_detail_data)
        total_after_9 = sum(cls.get('present_after_9', 0) or 0 for cls in class_detail_data)
        total_set_a = sum(cls.get('set_a', 0) or 0 for cls in class_detail_data)
        total_set_au = sum(cls.get('set_au', 0) or 0 for cls in class_detail_data)

        result = {
            "classes": class_detail_data,
            "summary": {
                "total_classes": len(class_detail_data),
                "total_before_9": total_before_9,
                "total_after_9": total_after_9,
                "total_present": total_before_9 + total_after_9,
                "total_set_a": total_set_a,
                "total_set_au": total_set_au
            },
            "date": date,
            "education_stage": education_stage
        }

        return single_item_response(result, f"Class detail fetched successfully for {education_stage} on {date}")

    except Exception as e:
        frappe.log_error(f"Error fetching meal tracking class detail: {str(e)}")
        return error_response(f"Error fetching class detail: {str(e)}")

