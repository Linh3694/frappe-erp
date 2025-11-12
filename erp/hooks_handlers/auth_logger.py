"""
Authentication Logging Handler
Logs login, logout, and authentication failures
"""

import frappe
from frappe.utils import get_request_header
from erp.utils.centralized_logger import log_authentication, log_error


def on_user_login(login_manager=None, **kwargs):
    """Hook called on successful user login"""
    try:
        user = login_manager.user if login_manager else frappe.session.user
        user_doc = frappe.get_doc('User', user) if user and user != 'Guest' else None
        
        # Get user's full name
        fullname = user_doc.full_name if user_doc else user
        
        # Get IP address
        ip = get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        
        log_authentication(
            user=user,
            action='login',
            ip=ip,
            status='success',
            details={
                'fullname': fullname,
                'user_type': user_doc.user_type if user_doc else None,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error logging user login: {str(e)}")


def on_user_logout(user=None, **kwargs):
    """Hook called on user logout"""
    try:
        user = user or frappe.session.user
        user_doc = frappe.get_doc('User', user) if user else None
        
        # Get user's full name
        fullname = user_doc.full_name if user_doc else user
        
        # Get IP address
        ip = get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        
        log_authentication(
            user=user,
            action='logout',
            ip=ip,
            status='success',
            details={
                'fullname': fullname,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error logging user logout: {str(e)}")


def log_failed_login(user: str, reason: str):
    """Log failed login attempts"""
    try:
        ip = get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()
        
        log_authentication(
            user=user,
            action='login_failed',
            ip=ip,
            status='failed',
            details={
                'reason': reason,
                'timestamp': frappe.utils.now()
            }
        )
    except Exception as e:
        frappe.errprint(f"Error logging failed login: {str(e)}")

