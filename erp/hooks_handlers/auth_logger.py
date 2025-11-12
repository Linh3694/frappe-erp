"""
Authentication Logging Handler
Logs login, logout, and authentication failures
"""

import frappe
from erp.utils.centralized_logger import log_authentication, log_error


def on_user_login(login_manager=None, **kwargs):
    """Hook called on successful user login"""
    frappe.errprint(f"🔵 [on_user_login] Called with login_manager={login_manager}, kwargs={kwargs}")
    
    try:
        # Get user from session
        user = frappe.session.user
        frappe.errprint(f"🔵 [on_user_login] frappe.session.user = {user}")
        
        if not user or user == 'Guest':
            frappe.errprint(f"🔵 [on_user_login] User is Guest or empty, skipping log")
            return

        # Get user document
        user_doc = None
        try:
            user_doc = frappe.get_doc('User', user)
        except frappe.DoesNotExistError:
            frappe.errprint(f"🔵 [on_user_login] User doc not found for {user}")
        except Exception as e:
            frappe.errprint(f"🔵 [on_user_login] Error getting user doc: {str(e)}")

        # Get name (first_name + last_name)
        fullname = user
        if user_doc:
            first_name = user_doc.first_name or ""
            last_name = user_doc.last_name or ""
            fullname = f"{last_name} {first_name}".strip() or user

        # Get IP address
        try:
            ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
            if ip and ',' in ip:
                ip = ip.split(',')[0].strip()
        except Exception as e:
            frappe.errprint(f"🔵 [on_user_login] Error getting IP: {str(e)}")
            ip = 'unknown'
        
        frappe.errprint(f"🔵 [on_user_login] Logging: user={user}, fullname={fullname}, ip={ip}")
        
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
        frappe.errprint(f"✅ [on_user_login] Successfully logged login for {user}")
        
    except Exception as e:
        frappe.errprint(f"❌ [on_user_login] Error logging user login: {str(e)}")
        import traceback
        frappe.errprint(traceback.format_exc())


def on_user_logout(user=None, **kwargs):
    """Hook called on user logout"""
    frappe.errprint(f"🔵 [on_user_logout] Called with user={user}, kwargs={kwargs}")
    
    try:
        # Get user from parameter or session
        user = user or frappe.session.user
        frappe.errprint(f"🔵 [on_user_logout] Final user = {user}")
        
        if not user or user == 'Guest':
            frappe.errprint(f"🔵 [on_user_logout] User is Guest or empty, skipping log")
            return

        # Get user document
        user_doc = None
        try:
            user_doc = frappe.get_doc('User', user)
        except frappe.DoesNotExistError:
            frappe.errprint(f"🔵 [on_user_logout] User doc not found for {user}")
        except Exception as e:
            frappe.errprint(f"🔵 [on_user_logout] Error getting user doc: {str(e)}")

        # Get name (first_name + last_name)
        fullname = user
        if user_doc:
            first_name = user_doc.first_name or ""
            last_name = user_doc.last_name or ""
            fullname = f"{last_name} {first_name}".strip() or user

        # Get IP address
        try:
            ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
            if ip and ',' in ip:
                ip = ip.split(',')[0].strip()
        except Exception as e:
            frappe.errprint(f"🔵 [on_user_logout] Error getting IP: {str(e)}")
            ip = 'unknown'
        
        frappe.errprint(f"🔵 [on_user_logout] Logging: user={user}, fullname={fullname}, ip={ip}")
        
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
        frappe.errprint(f"✅ [on_user_logout] Successfully logged logout for {user}")
        
    except Exception as e:
        frappe.errprint(f"❌ [on_user_logout] Error logging user logout: {str(e)}")
        import traceback
        frappe.errprint(traceback.format_exc())


def log_failed_login(user: str, reason: str):
    """Log failed login attempts"""
    try:
        # Get IP address
        try:
            ip = frappe.get_request_header('X-Forwarded-For') or frappe.request.remote_addr or 'unknown'
            if ip and ',' in ip:
                ip = ip.split(',')[0].strip()
        except Exception as e:
            frappe.errprint(f"🔵 [log_failed_login] Error getting IP: {str(e)}")
            ip = 'unknown'
        
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
        frappe.errprint(f"❌ [log_failed_login] Error logging failed login: {str(e)}")

