"""
Authentication Logging Handler
Logs login, logout, and authentication failures
"""

import frappe
from erp.utils.centralized_logger import log_authentication, log_error


def parse_vietnamese_name(fullname: str) -> str:
    """Parse Vietnamese name to Western format: FirstName LastName"""
    if not fullname or fullname == 'Guest':
        return fullname

    parts = fullname.strip().split()
    if len(parts) < 2:
        return fullname

    # Move the first name (last part) to the front
    first_name = parts[-1]  # "Linh"
    family_name = ' '.join(parts[:-1])  # "Nguyễn Văn"

    return f"{first_name} {family_name}"


def on_user_login(login_manager=None, **kwargs):
    """Hook called on successful user login"""
    try:
        # Try multiple ways to get the logged-in user
        user = None

        # Method 1: From login_manager
        if login_manager and hasattr(login_manager, 'user'):
            user = login_manager.user

        # Method 2: From kwargs (sometimes passed directly)
        if not user and kwargs.get('user'):
            user = kwargs['user']

        # Method 3: From session (fallback)
        if not user:
            user = frappe.session.user

        # Skip if still Guest or empty
        if not user or user == 'Guest':
            return

        user_doc = frappe.get_doc('User', user) if user else None

        # Get user's full name and parse it
        raw_fullname = user_doc.full_name if user_doc else user
        fullname = parse_vietnamese_name(raw_fullname)
        
        # Get IP address
        try:
            ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
            if ip and ',' in ip:
                ip = ip.split(',')[0].strip()
        except:
            ip = 'unknown'
        
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
        if not user or user == 'Guest':
            return

        user_doc = frappe.get_doc('User', user) if user else None

        # Get user's full name and parse it
        raw_fullname = user_doc.full_name if user_doc else user
        fullname = parse_vietnamese_name(raw_fullname)

        # Get IP address
        try:
            ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
            if ip and ',' in ip:
                ip = ip.split(',')[0].strip()
        except:
            ip = 'unknown'
        
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
        ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
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

