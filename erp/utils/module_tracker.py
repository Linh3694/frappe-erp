# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Module Usage Tracker for Parent Portal
Ghi nhận khi phụ huynh sử dụng các module trong app.

P0 (2026-08-05): debounce Redis + bỏ commit mỗi request — trước đây after_request
gọi SELECT/UPDATE/INSERT + commit theo từng API, bão hòa MariaDB lúc cao điểm.
"""

import frappe
from frappe.utils import today, now_datetime
from functools import wraps

# Chỉ ghi DB tối đa 1 lần / guardian+module trong cửa sổ này (giây)
_DEBOUNCE_SECONDS = 900  # 15 phút — đủ cho analytics module usage

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
    """Detect module name from API endpoint."""
    if not endpoint:
        return None

    endpoint_lower = endpoint.lower()
    sorted_keywords = sorted(API_MODULE_MAPPING.keys(), key=len, reverse=True)

    for keyword in sorted_keywords:
        if keyword in endpoint_lower:
            return API_MODULE_MAPPING[keyword]

    return None


def _debounce_cache_key(guardian_name, module_name, current_date):
    return f"module_usage|{current_date}|{guardian_name}|{module_name}"


def _should_skip_write(guardian_name, module_name, current_date):
    """True nếu vừa ghi gần đây — tránh storm SELECT/UPDATE lúc cao điểm."""
    try:
        return bool(
            frappe.cache().get_value(
                _debounce_cache_key(guardian_name, module_name, current_date)
            )
        )
    except Exception:
        return False


def _mark_written(guardian_name, module_name, current_date):
    try:
        frappe.cache().set_value(
            _debounce_cache_key(guardian_name, module_name, current_date),
            1,
            expires_in_sec=_DEBOUNCE_SECONDS,
        )
    except Exception:
        pass


def record_module_usage(guardian_name, module_name):
    """
    Ghi nhận việc sử dụng module vào Portal Guardian Activity.
    Debounce theo guardian+module+ngày; không spam errprint.
    """
    try:
        if not guardian_name or not module_name:
            return False

        current_date = today()
        if _should_skip_write(guardian_name, module_name, current_date):
            return True

        existing = frappe.db.sql(
            """
            SELECT name FROM `tabPortal Guardian Activity`
            WHERE guardian = %s AND activity_date = %s AND activity_type = %s
            LIMIT 1
            """,
            (guardian_name, current_date, module_name),
        )

        if existing:
            frappe.db.sql(
                """
                UPDATE `tabPortal Guardian Activity`
                SET activity_count = activity_count + 1,
                    last_activity_at = %s
                WHERE name = %s
                """,
                (now_datetime(), existing[0][0]),
            )
        else:
            doc = frappe.new_doc("Portal Guardian Activity")
            doc.guardian = guardian_name
            doc.activity_date = current_date
            doc.activity_type = module_name
            doc.activity_count = 1
            doc.last_activity_at = now_datetime()
            doc.insert(ignore_permissions=True, ignore_if_duplicate=True)

        # after_request nằm ngoài transaction request chính — cần commit riêng,
        # nhưng chỉ khi đã qua debounce (hiếm hơn ~15 phút/module).
        frappe.db.commit()
        _mark_written(guardian_name, module_name, current_date)
        return True

    except Exception as e:
        try:
            frappe.db.rollback()
        except Exception:
            pass
        frappe.log_error(f"Error recording module usage: {str(e)}", "Module Tracker")
        return False


def get_current_guardian_from_session():
    """
    Lấy guardian name từ session hiện tại.
    Cache ngắn theo user để tránh get_value lặp mỗi API.
    """
    try:
        user_email = frappe.session.user
        if not user_email or '@parent.wellspring.edu.vn' not in user_email:
            return None

        cache = frappe.cache()
        cache_key = f"portal_guardian_name|{user_email}"
        cached = cache.get_value(cache_key)
        if cached:
            return cached if cached != "__none__" else None

        guardian_id = user_email.split('@')[0]
        guardian_name = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
        cache.set_value(cache_key, guardian_name or "__none__", expires_in_sec=3600)
        return guardian_name

    except Exception:
        return None


def track_module_usage(func):
    """Decorator track module usage khi guardian gọi API."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            guardian_name = get_current_guardian_from_session()
            if guardian_name:
                endpoint = frappe.request.path if frappe.request else func.__name__
                module_name = detect_module_from_endpoint(endpoint)
                if module_name:
                    record_module_usage(guardian_name, module_name)
        except Exception as e:
            frappe.log_error(f"Module tracking error: {str(e)}", "Module Tracker")

        return func(*args, **kwargs)

    return wrapper


def track_request_module_usage():
    """
    Hook after_request — track Parent Portal APIs (đã debounce).
    """
    try:
        user_email = frappe.session.user if frappe.session else None
        if not user_email or '@parent.wellspring.edu.vn' not in user_email:
            return

        if not frappe.request:
            return

        request_path = frappe.request.path or ''
        if 'parent_portal' not in request_path and 'attendance' not in request_path:
            return

        module_name = detect_module_from_endpoint(request_path)
        if not module_name:
            return

        guardian_name = get_current_guardian_from_session()
        if not guardian_name:
            return

        record_module_usage(guardian_name, module_name)

    except Exception:
        # Không làm hỏng response chính
        pass


def get_module_usage_stats(days=30):
    """Lấy thống kê module usage trong X ngày gần đây."""
    try:
        from frappe.utils import add_days

        start_date = add_days(today(), -days)
        all_modules = list(set(API_MODULE_MAPPING.values()))

        stats = frappe.db.sql(
            """
            SELECT
                activity_type as module,
                SUM(activity_count) as total_count
            FROM `tabPortal Guardian Activity`
            WHERE activity_date >= %s
            AND activity_type IN %s
            GROUP BY activity_type
            ORDER BY total_count DESC
            """,
            (start_date, tuple(all_modules)),
            as_dict=True,
        )

        total_calls = sum(s.total_count or 0 for s in stats)
        stats_dict = {s.module: s.total_count or 0 for s in stats}

        formatted_data = []
        for module in all_modules:
            count = stats_dict.get(module, 0)
            percentage = round((count / total_calls * 100), 1) if total_calls > 0 else 0
            formatted_data.append({
                "module": module,
                "count": count,
                "percentage": percentage,
            })

        formatted_data.sort(key=lambda x: x['count'], reverse=True)

        return {
            "data": formatted_data,
            "total_calls": total_calls,
        }

    except Exception as e:
        frappe.log_error(f"Error getting module usage stats: {str(e)}", "Module Tracker")
        return {
            "data": [],
            "total_calls": 0,
        }
