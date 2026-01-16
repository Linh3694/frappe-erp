# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Module Usage Tracker for Parent Portal
Ghi nhận khi phụ huynh sử dụng các module trong app
"""

import frappe
from frappe.utils import today, now_datetime
from functools import wraps

# Mapping API endpoints → Module names
# Thứ tự quan trọng: keywords cụ thể hơn phải đặt trước
API_MODULE_MAPPING = {
    # Thực đơn - cụ thể trước
    'daily_menu': 'Thực đơn',
    'menu_registration': 'Đăng ký ăn',
    'buffet': 'Thực đơn',
    'menu': 'Thực đơn',
    'meal': 'Thực đơn',
    
    # Thông báo - cụ thể trước
    'notification_center': 'Thông báo',
    'notification': 'Thông báo',
    'announcement': 'Thông báo',
    'news': 'Thông báo',
    
    # Thời khóa biểu
    'timetable': 'Thời khóa biểu',
    'schedule': 'Thời khóa biểu',
    
    # Điểm danh
    'attendance': 'Điểm danh',
    
    # Xin phép
    'leave': 'Xin phép',
    'absence': 'Xin phép',
    
    # Bảng điểm
    'report_card': 'Bảng điểm',
    'grade': 'Bảng điểm',
    'score': 'Bảng điểm',
    'gradebook': 'Bảng điểm',
    'subject': 'Bảng điểm',
    
    # Lịch học
    'calendar': 'Lịch học',
    'event': 'Lịch học',
    
    # Xe bus
    'bus': 'Xe bus',
    'transport': 'Xe bus',
    
    # Liên lạc
    'contact_log': 'Liên lạc',
    'contact': 'Liên lạc',
    'message': 'Liên lạc',
    'chat': 'Liên lạc',
    
    # Đánh giá / Feedback
    'feedback': 'Đánh giá',
    'rating': 'Đánh giá',
    
    # Thông tin học sinh
    'student': 'Thông tin HS',
    'children': 'Thông tin HS',
    'interface': 'Thông tin HS',
    
    # Học phí / Tài chính
    'finance': 'Học phí',
    'fee': 'Học phí',
    'payment': 'Học phí',
    'tuition': 'Học phí',
    
    # Tái tuyển sinh / Scholarship
    're_enrollment': 'Tái tuyển sinh',
    'scholarship': 'Học bổng',
}


def detect_module_from_endpoint(endpoint):
    """
    Detect module name from API endpoint.
    
    Args:
        endpoint: API path like '/api/method/erp.api.parent_portal.timetable.get_student_timetable'
        
    Returns:
        str: Module name hoặc None nếu không detect được
    """
    if not endpoint:
        return None
    
    endpoint_lower = endpoint.lower()
    
    # Sắp xếp keywords theo độ dài giảm dần để match keyword dài (cụ thể) trước
    sorted_keywords = sorted(API_MODULE_MAPPING.keys(), key=len, reverse=True)
    
    for keyword in sorted_keywords:
        if keyword in endpoint_lower:
            return API_MODULE_MAPPING[keyword]
    
    return None


def record_module_usage(guardian_name, module_name):
    """
    Ghi nhận việc sử dụng module.
    Lưu vào Portal Guardian Activity với activity_type = module name.
    
    Args:
        guardian_name: CRM Guardian document name
        module_name: Tên module (e.g., "Thời khóa biểu")
    """
    try:
        if not guardian_name or not module_name:
            return False
        
        current_date = today()
        
        # Tìm record hiện có cho guardian + ngày + module
        existing = frappe.db.sql("""
            SELECT name FROM `tabPortal Guardian Activity`
            WHERE guardian = %s AND activity_date = %s AND activity_type = %s
            LIMIT 1
        """, (guardian_name, current_date, module_name))
        
        if existing:
            # Cập nhật record hiện có
            frappe.db.sql("""
                UPDATE `tabPortal Guardian Activity`
                SET activity_count = activity_count + 1,
                    last_activity_at = %s
                WHERE name = %s
            """, (now_datetime(), existing[0][0]))
            frappe.errprint(f"✅ [ModuleUsage] Updated existing: {existing[0][0]}")
        else:
            # Tạo record mới
            doc = frappe.new_doc("Portal Guardian Activity")
            doc.guardian = guardian_name
            doc.activity_date = current_date
            doc.activity_type = module_name
            doc.activity_count = 1
            doc.last_activity_at = now_datetime()
            doc.insert(ignore_permissions=True)
            frappe.errprint(f"✅ [ModuleUsage] Created new: {doc.name}")
        
        frappe.db.commit()
        return True
        
    except Exception as e:
        import traceback
        frappe.errprint(f"❌ [ModuleUsage] Error: {str(e)}")
        frappe.errprint(traceback.format_exc())
        frappe.log_error(f"Error recording module usage: {str(e)}", "Module Tracker")
        return False


def get_current_guardian_from_session():
    """
    Lấy guardian name từ session hiện tại.
    Dựa vào email format: {guardian_id}@parent.wellspring.edu.vn
    """
    try:
        user_email = frappe.session.user
        if not user_email or '@parent.wellspring.edu.vn' not in user_email:
            return None
        
        # Extract guardian_id from email
        guardian_id = user_email.split('@')[0]
        
        # Find guardian by guardian_id
        guardian_name = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
        return guardian_name
        
    except Exception:
        return None


def track_module_usage(func):
    """
    Decorator để tự động track module usage khi guardian gọi API.
    
    Usage:
        @frappe.whitelist()
        @track_module_usage
        def get_student_timetable():
            ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            # Chỉ track cho parent portal users
            guardian_name = get_current_guardian_from_session()
            if guardian_name:
                # Detect module từ function name hoặc request path
                endpoint = frappe.request.path if frappe.request else func.__name__
                module_name = detect_module_from_endpoint(endpoint)
                
                if module_name:
                    record_module_usage(guardian_name, module_name)
        except Exception as e:
            # Không làm ảnh hưởng đến API chính
            frappe.log_error(f"Module tracking error: {str(e)}", "Module Tracker")
        
        # Luôn chạy function gốc
        return func(*args, **kwargs)
    
    return wrapper


def track_request_module_usage():
    """
    Hook function được gọi sau mỗi request.
    Tự động track module usage cho Parent Portal APIs.
    """
    try:
        # Chỉ track cho parent portal users
        user_email = frappe.session.user if frappe.session else None
        if not user_email or '@parent.wellspring.edu.vn' not in user_email:
            return
        
        # Lấy request path
        if not frappe.request:
            return
        
        request_path = frappe.request.path or ''
        
        # Chỉ track parent_portal APIs (và một số attendance APIs)
        if 'parent_portal' not in request_path and 'attendance' not in request_path:
            return
        
        # Detect module từ endpoint
        module_name = detect_module_from_endpoint(request_path)
        
        # Debug log
        frappe.errprint(f"🔵 [ModuleTracker] Path: {request_path}, Module: {module_name}")
        
        if not module_name:
            frappe.errprint(f"⚠️ [ModuleTracker] No module detected for: {request_path}")
            return
        
        # Lấy guardian từ session
        guardian_name = get_current_guardian_from_session()
        if not guardian_name:
            frappe.errprint(f"⚠️ [ModuleTracker] No guardian found for user: {user_email}")
            return
        
        # Record module usage
        frappe.errprint(f"🔵 [ModuleTracker] Recording: {guardian_name} -> {module_name}")
        result = record_module_usage(guardian_name, module_name)
        frappe.errprint(f"✅ [ModuleTracker] Recorded: {result}")
        
    except Exception as e:
        # Log lỗi để debug
        import traceback
        frappe.errprint(f"❌ [ModuleTracker] Error: {str(e)}")
        frappe.errprint(traceback.format_exc())


def get_module_usage_stats(days=30):
    """
    Lấy thống kê module usage trong X ngày gần đây.
    
    Args:
        days: Số ngày lấy thống kê
        
    Returns:
        list: [{"module": "Thời khóa biểu", "count": 100, "percentage": 25.5}, ...]
    """
    try:
        from frappe.utils import add_days
        
        start_date = add_days(today(), -days)
        
        # Lấy tất cả modules được định nghĩa
        all_modules = list(set(API_MODULE_MAPPING.values()))
        
        # Query usage stats - chỉ lấy các activity_type là module name
        stats = frappe.db.sql("""
            SELECT 
                activity_type as module,
                SUM(activity_count) as total_count
            FROM `tabPortal Guardian Activity`
            WHERE activity_date >= %s
            AND activity_type IN %s
            GROUP BY activity_type
            ORDER BY total_count DESC
        """, (start_date, tuple(all_modules)), as_dict=True)
        
        # Calculate total
        total_calls = sum(s.total_count or 0 for s in stats)
        
        # Create lookup dict
        stats_dict = {s.module: s.total_count or 0 for s in stats}
        
        # Format with all modules (including those with 0 count)
        formatted_data = []
        for module in all_modules:
            count = stats_dict.get(module, 0)
            percentage = round((count / total_calls * 100), 1) if total_calls > 0 else 0
            formatted_data.append({
                "module": module,
                "count": count,
                "percentage": percentage
            })
        
        # Sort by count descending
        formatted_data.sort(key=lambda x: x['count'], reverse=True)
        
        return {
            "data": formatted_data,
            "total_calls": total_calls
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting module usage stats: {str(e)}", "Module Tracker")
        return {
            "data": [],
            "total_calls": 0
        }
