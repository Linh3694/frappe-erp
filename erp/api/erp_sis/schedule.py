# Copyright (c) 2025, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, getdate
import json
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
def get_all_schedules():
    """
    Lấy danh sách tất cả Schedule
    
    Query params:
        - education_stage: Filter theo cấp học
        - school_year: Filter theo năm học
        - is_active: Filter theo trạng thái active (default: 1)
        - date: Lấy schedule áp dụng cho ngày cụ thể
    
    Returns:
        List of schedules với thông tin cơ bản
    """
    try:
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Xây dựng filters
        filters = {"campus_id": campus_id}
        
        # Lấy params từ request
        education_stage = frappe.local.form_dict.get("education_stage") or frappe.request.args.get("education_stage")
        school_year = frappe.local.form_dict.get("school_year") or frappe.request.args.get("school_year")
        is_active = frappe.local.form_dict.get("is_active") or frappe.request.args.get("is_active")
        date_filter = frappe.local.form_dict.get("date") or frappe.request.args.get("date")
        
        if education_stage:
            filters["education_stage_id"] = education_stage
        
        if school_year:
            filters["school_year_id"] = school_year
        
        # Mặc định chỉ lấy active schedules
        if is_active is None or is_active == "1" or is_active == True:
            filters["is_active"] = 1
        elif is_active == "0" or is_active == False:
            filters["is_active"] = 0
        # Nếu is_active = "all" thì không filter
        
        # Lấy schedules
        schedules = frappe.get_all(
            "SIS Schedule",
            filters=filters,
            fields=[
                "name",
                "schedule_name",
                "description",
                "education_stage_id",
                "campus_id",
                "school_year_id",
                "start_date",
                "end_date",
                "is_active",
                "creation",
                "modified"
            ],
            order_by="start_date asc, schedule_name asc"
        )
        
        # Nếu có date filter, chỉ lấy schedules có date range bao gồm ngày đó
        if date_filter:
            target_date = getdate(date_filter)
            schedules = [
                s for s in schedules 
                if getdate(s.start_date) <= target_date <= getdate(s.end_date)
            ]
        
        # Đếm số periods cho mỗi schedule
        for schedule in schedules:
            period_count = frappe.db.count(
                "SIS Timetable Column",
                {"schedule_id": schedule.name}
            )
            schedule["period_count"] = period_count
        
        return list_response(schedules, "Schedules fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching schedules: {str(e)}")
        return error_response(f"Error fetching schedules: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_schedule_by_id():
    """
    Lấy chi tiết một Schedule theo ID
    
    URL format: .../get_schedule_by_id/<schedule_id>
    
    Returns:
        Schedule detail với danh sách periods
    """
    try:
        # Lấy schedule_id từ request
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
        
        schedule_id = data.get("schedule_id")
        
        # Thử lấy từ URL path
        if not schedule_id:
            import re
            url_patterns = [
                r'get_schedule_by_id/([^/?]+)',
            ]
            for pattern in url_patterns:
                match = re.search(pattern, frappe.request.url or '')
                if match:
                    schedule_id = match.group(1)
                    break
        
        if not schedule_id:
            return validation_error_response("Validation failed", {"schedule_id": ["Schedule ID is required"]})
        
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Lấy schedule
        try:
            schedule = frappe.get_doc("SIS Schedule", schedule_id)
        except frappe.DoesNotExistError:
            return not_found_response("Schedule not found")
        
        # Kiểm tra campus permission
        if schedule.campus_id != campus_id:
            return forbidden_response("Access denied: You don't have permission to access this schedule")
        
        # Lấy danh sách periods thuộc schedule này
        periods = frappe.get_all(
            "SIS Timetable Column",
            filters={"schedule_id": schedule_id},
            fields=[
                "name",
                "period_name",
                "period_priority",
                "period_type",
                "start_time",
                "end_time"
            ],
            order_by="period_priority asc"
        )
        
        # Format time fields
        for period in periods:
            period["start_time"] = format_time_for_html(period.get("start_time"))
            period["end_time"] = format_time_for_html(period.get("end_time"))
        
        schedule_data = {
            "name": schedule.name,
            "schedule_name": schedule.schedule_name,
            "description": schedule.description,
            "education_stage_id": schedule.education_stage_id,
            "campus_id": schedule.campus_id,
            "school_year_id": schedule.school_year_id,
            "start_date": str(schedule.start_date) if schedule.start_date else None,
            "end_date": str(schedule.end_date) if schedule.end_date else None,
            "is_active": schedule.is_active,
            "periods": periods,
            "period_count": len(periods)
        }
        
        return single_item_response(schedule_data, "Schedule fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching schedule: {str(e)}")
        return error_response(f"Error fetching schedule: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_schedule():
    """
    Tạo mới một Schedule
    
    Request body:
        - schedule_name: Tên thời gian biểu (required)
        - education_stage_id: Cấp học (required)
        - school_year_id: Năm học (required)
        - start_date: Ngày bắt đầu (required)
        - end_date: Ngày kết thúc (required)
        - description: Mô tả (optional)
        - is_active: Trạng thái (default: 1)
    
    Returns:
        Created schedule data
    """
    try:
        # Lấy data từ request
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except (json.JSONDecodeError, TypeError):
                data = dict(frappe.local.form_dict)
        else:
            data = dict(frappe.local.form_dict)
        
        # Validate required fields
        required_fields = ["schedule_name", "education_stage_id", "school_year_id", "start_date", "end_date"]
        missing_fields = {}
        for field in required_fields:
            if not data.get(field):
                missing_fields[field] = [f"{field} is required"]
        
        if missing_fields:
            return validation_error_response("Validation failed", missing_fields)
        
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            # Fallback: lấy campus đầu tiên
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            if first_campus:
                campus_id = first_campus[0].name
            else:
                return error_response("No campus found")
        
        # Tạo schedule
        schedule_doc = frappe.get_doc({
            "doctype": "SIS Schedule",
            "schedule_name": data.get("schedule_name"),
            "description": data.get("description"),
            "education_stage_id": data.get("education_stage_id"),
            "campus_id": campus_id,
            "school_year_id": data.get("school_year_id"),
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "is_active": data.get("is_active", 1)
        })
        
        schedule_doc.insert()
        frappe.db.commit()
        
        frappe.logger().info(f"Created schedule: {schedule_doc.name}")
        
        schedule_data = {
            "name": schedule_doc.name,
            "schedule_name": schedule_doc.schedule_name,
            "description": schedule_doc.description,
            "education_stage_id": schedule_doc.education_stage_id,
            "campus_id": schedule_doc.campus_id,
            "school_year_id": schedule_doc.school_year_id,
            "start_date": str(schedule_doc.start_date) if schedule_doc.start_date else None,
            "end_date": str(schedule_doc.end_date) if schedule_doc.end_date else None,
            "is_active": schedule_doc.is_active
        }
        
        return single_item_response(schedule_data, "Schedule created successfully")
        
    except frappe.ValidationError as e:
        return validation_error_response(str(e), {})
    except Exception as e:
        frappe.log_error(f"Error creating schedule: {str(e)}")
        return error_response(f"Error creating schedule: {str(e)}")


@frappe.whitelist(allow_guest=False)
def update_schedule():
    """
    Cập nhật một Schedule
    
    URL format: .../update_schedule/<schedule_id>
    
    Request body: fields to update
    
    Returns:
        Updated schedule data
    """
    try:
        # Lấy data từ request
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except (json.JSONDecodeError, TypeError):
                data = dict(frappe.local.form_dict)
        else:
            data = dict(frappe.local.form_dict)
        
        schedule_id = data.get("schedule_id")
        
        # Thử lấy từ URL path
        if not schedule_id:
            import re
            url_patterns = [
                r'update_schedule/([^/?]+)',
            ]
            for pattern in url_patterns:
                match = re.search(pattern, frappe.request.url or '')
                if match:
                    schedule_id = match.group(1)
                    break
        
        if not schedule_id:
            return validation_error_response("Validation failed", {"schedule_id": ["Schedule ID is required"]})
        
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Lấy schedule
        try:
            schedule_doc = frappe.get_doc("SIS Schedule", schedule_id)
        except frappe.DoesNotExistError:
            return not_found_response("Schedule not found")
        
        # Kiểm tra campus permission
        if schedule_doc.campus_id != campus_id:
            return forbidden_response("Access denied: You don't have permission to modify this schedule")
        
        # Cập nhật các fields
        updatable_fields = ["schedule_name", "description", "education_stage_id", "school_year_id", "start_date", "end_date", "is_active"]
        for field in updatable_fields:
            if field in data and data[field] is not None:
                setattr(schedule_doc, field, data[field])
        
        schedule_doc.save()
        frappe.db.commit()
        
        frappe.logger().info(f"Updated schedule: {schedule_doc.name}")
        
        schedule_data = {
            "name": schedule_doc.name,
            "schedule_name": schedule_doc.schedule_name,
            "description": schedule_doc.description,
            "education_stage_id": schedule_doc.education_stage_id,
            "campus_id": schedule_doc.campus_id,
            "school_year_id": schedule_doc.school_year_id,
            "start_date": str(schedule_doc.start_date) if schedule_doc.start_date else None,
            "end_date": str(schedule_doc.end_date) if schedule_doc.end_date else None,
            "is_active": schedule_doc.is_active
        }
        
        return single_item_response(schedule_data, "Schedule updated successfully")
        
    except frappe.ValidationError as e:
        return validation_error_response(str(e), {})
    except Exception as e:
        frappe.log_error(f"Error updating schedule: {str(e)}")
        return error_response(f"Error updating schedule: {str(e)}")


@frappe.whitelist(allow_guest=False)
def delete_schedule():
    """
    Xóa một Schedule
    
    URL format: .../delete_schedule/<schedule_id>
    
    Lưu ý: Không thể xóa schedule nếu có periods đang sử dụng
    
    Returns:
        Success message
    """
    try:
        # Lấy data từ request
        data = {}
        if frappe.request.data:
            try:
                data = json.loads(frappe.request.data)
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict
        
        schedule_id = data.get("schedule_id")
        
        # Thử lấy từ URL path
        if not schedule_id:
            import re
            url_patterns = [
                r'delete_schedule/([^/?]+)',
            ]
            for pattern in url_patterns:
                match = re.search(pattern, frappe.request.url or '')
                if match:
                    schedule_id = match.group(1)
                    break
        
        if not schedule_id:
            return validation_error_response("Validation failed", {"schedule_id": ["Schedule ID is required"]})
        
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Lấy schedule
        try:
            schedule_doc = frappe.get_doc("SIS Schedule", schedule_id)
        except frappe.DoesNotExistError:
            return not_found_response("Schedule not found")
        
        # Kiểm tra campus permission
        if schedule_doc.campus_id != campus_id:
            return forbidden_response("Access denied: You don't have permission to delete this schedule")
        
        # Xóa schedule (on_trash sẽ kiểm tra periods)
        frappe.delete_doc("SIS Schedule", schedule_id)
        frappe.db.commit()
        
        frappe.logger().info(f"Deleted schedule: {schedule_id}")
        
        return success_response(message="Schedule deleted successfully")
        
    except frappe.ValidationError as e:
        return validation_error_response(str(e), {})
    except Exception as e:
        frappe.log_error(f"Error deleting schedule: {str(e)}")
        return error_response(f"Error deleting schedule: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_periods_by_schedule():
    """
    Lấy danh sách periods thuộc một Schedule
    
    Query params:
        - schedule_id: Schedule ID (required)
    
    Returns:
        List of periods
    """
    try:
        schedule_id = frappe.local.form_dict.get("schedule_id") or frappe.request.args.get("schedule_id")
        
        if not schedule_id:
            return validation_error_response("Validation failed", {"schedule_id": ["Schedule ID is required"]})
        
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Kiểm tra schedule tồn tại và thuộc campus
        schedule = frappe.get_all(
            "SIS Schedule",
            filters={"name": schedule_id, "campus_id": campus_id},
            fields=["name"],
            limit=1
        )
        
        if not schedule:
            return not_found_response("Schedule not found or access denied")
        
        # Lấy periods
        periods = frappe.get_all(
            "SIS Timetable Column",
            filters={"schedule_id": schedule_id},
            fields=[
                "name",
                "period_name",
                "period_priority",
                "period_type",
                "start_time",
                "end_time",
                "education_stage_id"
            ],
            order_by="period_priority asc"
        )
        
        # Format time fields
        for period in periods:
            period["start_time"] = format_time_for_html(period.get("start_time"))
            period["end_time"] = format_time_for_html(period.get("end_time"))
        
        return list_response(periods, "Periods fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching periods: {str(e)}")
        return error_response(f"Error fetching periods: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_schedule_by_date():
    """
    Lấy schedule áp dụng cho một ngày cụ thể
    
    Query params:
        - date: Ngày cần tìm (required, format: YYYY-MM-DD)
        - education_stage: Cấp học (required)
    
    Returns:
        Schedule và danh sách periods áp dụng cho ngày đó
    """
    try:
        date_str = frappe.local.form_dict.get("date") or frappe.request.args.get("date")
        education_stage = frappe.local.form_dict.get("education_stage") or frappe.request.args.get("education_stage")
        
        if not date_str:
            date_str = nowdate()
        
        # Lấy campus từ context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        target_date = getdate(date_str)
        
        # Tìm schedule active có date range bao gồm ngày target
        filters = {
            "campus_id": campus_id,
            "is_active": 1,
            "start_date": ["<=", target_date],
            "end_date": [">=", target_date]
        }
        
        if education_stage:
            filters["education_stage_id"] = education_stage
        
        schedules = frappe.get_all(
            "SIS Schedule",
            filters=filters,
            fields=[
                "name",
                "schedule_name",
                "education_stage_id",
                "start_date",
                "end_date"
            ],
            order_by="start_date desc",
            limit=1
        )
        
        if not schedules:
            # Fallback: trả về periods không có schedule (legacy data)
            legacy_filters = {"campus_id": campus_id, "schedule_id": ["is", "not set"]}
            if education_stage:
                legacy_filters["education_stage_id"] = education_stage
            
            periods = frappe.get_all(
                "SIS Timetable Column",
                filters=legacy_filters,
                fields=[
                    "name",
                    "period_name",
                    "period_priority",
                    "period_type",
                    "start_time",
                    "end_time",
                    "education_stage_id"
                ],
                order_by="period_priority asc"
            )
            
            # Format time fields
            for period in periods:
                period["start_time"] = format_time_for_html(period.get("start_time"))
                period["end_time"] = format_time_for_html(period.get("end_time"))
            
            return single_item_response({
                "schedule": None,
                "periods": periods,
                "is_legacy": True
            }, "Using legacy periods (no schedule defined)")
        
        schedule = schedules[0]
        
        # Lấy periods của schedule
        periods = frappe.get_all(
            "SIS Timetable Column",
            filters={"schedule_id": schedule.name},
            fields=[
                "name",
                "period_name",
                "period_priority",
                "period_type",
                "start_time",
                "end_time",
                "education_stage_id"
            ],
            order_by="period_priority asc"
        )
        
        # Format time fields
        for period in periods:
            period["start_time"] = format_time_for_html(period.get("start_time"))
            period["end_time"] = format_time_for_html(period.get("end_time"))
        
        return single_item_response({
            "schedule": schedule,
            "periods": periods,
            "is_legacy": False
        }, "Schedule and periods fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching schedule by date: {str(e)}")
        return error_response(f"Error fetching schedule by date: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_education_stages_for_schedule():
    """
    Lấy danh sách education stages để hiển thị trong dropdown
    
    Returns:
        List of education stages
    """
    try:
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        education_stages = frappe.get_all(
            "SIS Education Stage",
            filters={"campus_id": campus_id},
            fields=["name", "title_vn", "title_en"],
            order_by="title_vn asc"
        )
        
        return list_response(education_stages, "Education stages fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching education stages: {str(e)}")
        return error_response(f"Error fetching education stages: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_school_years_for_schedule():
    """
    Lấy danh sách school years để hiển thị trong dropdown
    
    Returns:
        List of school years
    """
    try:
        school_years = frappe.get_all(
            "SIS School Year",
            fields=["name", "title", "is_enable", "start_date", "end_date"],
            order_by="start_date desc"
        )
        
        return list_response(school_years, "School years fetched successfully")
        
    except Exception as e:
        frappe.log_error(f"Error fetching school years: {str(e)}")
        return error_response(f"Error fetching school years: {str(e)}")


def format_time_for_html(time_value):
    """Format time value to HH:MM format for HTML time input"""
    if not time_value:
        return ""
    
    try:
        from datetime import timedelta
        
        # Handle datetime.time object
        if hasattr(time_value, 'strftime'):
            return time_value.strftime("%H:%M")
        
        # Handle datetime.timedelta object
        if isinstance(time_value, timedelta):
            total_seconds = int(time_value.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours:02d}:{minutes:02d}"
        
        # Handle string format
        if isinstance(time_value, str):
            from frappe.utils import get_time
            try:
                parsed_time = get_time(time_value)
                return parsed_time.strftime("%H:%M")
            except:
                return time_value
        
        return str(time_value)
    except Exception:
        return ""
