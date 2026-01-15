# -*- coding: utf-8 -*-
# Copyright (c) 2026, Linh Nguyen and contributors
# For license information, please see license.txt

"""
Portal Error Handler
Decorator và utilities để catch và log errors từ Parent Portal APIs
"""

from __future__ import unicode_literals
import frappe
import functools
import json
import traceback


def classify_error(error):
    """
    Phân loại error thành các loại chuẩn
    
    Args:
        error: Exception object
        
    Returns:
        str: Error type (ValidationError, PermissionError, NotFoundError, ServerError, TimeoutError, UnknownError)
    """
    error_type = type(error).__name__
    error_str = str(error).lower()
    
    # Frappe specific errors
    if error_type in ['ValidationError', 'MandatoryError', 'InvalidStatusError']:
        return 'ValidationError'
    if error_type in ['PermissionError', 'AuthenticationError']:
        return 'PermissionError'
    if error_type == 'DoesNotExistError' or 'not found' in error_str or 'does not exist' in error_str:
        return 'NotFoundError'
    if error_type in ['TimeLimitExceeded', 'TimeoutError'] or 'timeout' in error_str:
        return 'TimeoutError'
    if error_type in ['ServerError', 'InternalError', 'DatabaseError']:
        return 'ServerError'
    
    # Generic Python errors
    if error_type in ['ValueError', 'TypeError', 'KeyError', 'AttributeError']:
        return 'ValidationError'
    if error_type in ['PermissionError', 'PermissionDenied']:
        return 'PermissionError'
    if error_type in ['FileNotFoundError', 'IndexError']:
        return 'NotFoundError'
    if error_type in ['ConnectionError', 'TimeoutError']:
        return 'TimeoutError'
    
    return 'UnknownError'


def get_current_guardian():
    """
    Lấy thông tin guardian hiện tại từ session
    
    Returns:
        dict: Guardian info hoặc None
    """
    try:
        user_email = frappe.session.user
        
        if not user_email or user_email == 'Guest':
            return None
        
        # Check if user is a parent portal user
        if '@parent.wellspring.edu.vn' not in user_email:
            return None
        
        # Extract guardian_id from email
        guardian_id = user_email.split('@')[0]
        
        # Get guardian from database
        guardian = frappe.db.get_value(
            "CRM Guardian",
            {"guardian_id": guardian_id},
            ["name", "guardian_id", "guardian_name"],
            as_dict=True
        )
        
        return guardian
        
    except Exception:
        return None


def log_portal_error(api_endpoint, error, request_params=None, guardian=None):
    """
    Lưu error vào database Portal API Error
    
    Args:
        api_endpoint: Tên API endpoint (module.function)
        error: Exception object
        request_params: Dict chứa request parameters
        guardian: Dict chứa guardian info
    """
    try:
        doc = frappe.new_doc("Portal API Error")
        doc.error_id = frappe.generate_hash(length=10)
        doc.api_endpoint = api_endpoint
        doc.error_type = classify_error(error)
        doc.error_message = str(error)[:500]  # Giới hạn độ dài
        doc.stack_trace = traceback.format_exc()
        doc.occurred_at = frappe.utils.now_datetime()
        
        # Request params
        if request_params:
            try:
                doc.request_params = json.dumps(request_params, default=str, ensure_ascii=False)
            except Exception:
                doc.request_params = json.dumps({"error": "Could not serialize params"})
        
        # Guardian info
        if guardian:
            doc.guardian = guardian.get('name')
            doc.guardian_name = guardian.get('guardian_name')
        
        # Request info từ headers
        try:
            doc.ip_address = frappe.get_request_header('X-Forwarded-For') or \
                           (frappe.request.remote_addr if hasattr(frappe, 'request') and frappe.request else 'unknown')
            if doc.ip_address and ',' in doc.ip_address:
                doc.ip_address = doc.ip_address.split(',')[0].strip()
        except Exception:
            doc.ip_address = 'unknown'
        
        try:
            doc.user_agent = frappe.get_request_header('User-Agent') or 'unknown'
        except Exception:
            doc.user_agent = 'unknown'
        
        # Device info từ custom headers
        try:
            device_info = {
                'platform': frappe.get_request_header('X-Platform'),
                'app_version': frappe.get_request_header('X-App-Version'),
                'device_id': frappe.get_request_header('X-Device-ID'),
                'device_model': frappe.get_request_header('X-Device-Model')
            }
            # Loại bỏ None values
            device_info = {k: v for k, v in device_info.items() if v}
            doc.device_info = json.dumps(device_info, ensure_ascii=False)
        except Exception:
            doc.device_info = json.dumps({})
        
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
    except Exception as log_error:
        # Nếu không log được vào database, log vào error log
        frappe.log_error(
            f"Failed to log portal error: {str(log_error)}\nOriginal error: {str(error)}", 
            "Portal Error Handler"
        )


def catch_portal_errors(func):
    """
    Decorator để catch và log errors từ Parent Portal APIs.
    
    Sử dụng:
        @frappe.whitelist()
        @catch_portal_errors
        def my_api_function(param1, param2):
            # ... code ...
    
    Decorator sẽ:
    1. Catch mọi exception xảy ra trong function
    2. Log chi tiết error vào Portal API Error doctype
    3. Re-raise exception để client nhận được error response
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Lấy thông tin guardian hiện tại
            guardian = get_current_guardian()
            
            # Tạo API endpoint name
            api_endpoint = f"{func.__module__}.{func.__name__}"
            
            # Log error vào database
            log_portal_error(
                api_endpoint=api_endpoint,
                error=e,
                request_params=kwargs,
                guardian=guardian
            )
            
            # Re-raise để client nhận được error response
            raise
    
    return wrapper


def catch_portal_errors_silent(func):
    """
    Giống catch_portal_errors nhưng không re-raise exception.
    Trả về response error thay vì raise.
    
    Useful cho các API không muốn crash khi có lỗi.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Lấy thông tin guardian hiện tại
            guardian = get_current_guardian()
            
            # Tạo API endpoint name
            api_endpoint = f"{func.__module__}.{func.__name__}"
            
            # Log error vào database
            log_portal_error(
                api_endpoint=api_endpoint,
                error=e,
                request_params=kwargs,
                guardian=guardian
            )
            
            # Trả về error response thay vì raise
            return {
                "success": False,
                "message": str(e),
                "error_type": classify_error(e)
            }
    
    return wrapper
