# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from .jwt_auth import authenticate_via_jwt


def jwt_auth_middleware():
    """
    Global JWT authentication middleware
    
    This runs before every request and automatically authenticates
    users via JWT token if present in headers.
    
    Applies to ALL API endpoints - no need to modify individual APIs.
    """
    try:
        # Skip if:
        # 1. User is already authenticated (not Guest)
        # 2. Request is to login endpoint 
        # 3. Request is to public endpoints
        
        if frappe.session.user and frappe.session.user != 'Guest':
            # User already authenticated via session
            return
            
        # Skip for certain endpoints that don't need auth
        request_path = frappe.request.path if frappe.request else ''
        
        skip_paths = [
            '/api/method/login',
            '/api/method/logout',
            '/api/method/frappe.auth.get_logged_user',
            '/api/method/frappe.core.doctype.user.user.sign_up',
            '/assets/',
            '/files/',
        ]
        
        if any(request_path.startswith(path) for path in skip_paths):
            return
        
        # Try JWT authentication
        user_email = authenticate_via_jwt()
        
        if user_email:
            # Set user in current session
            frappe.set_user(user_email)
            frappe.logger().info(f"🔑 Global JWT auth: Set user {user_email}")
            
            # Mark session as authenticated via JWT
            frappe.local.jwt_authenticated = True
        else:
            # No JWT or invalid JWT - continue as Guest
            # This allows public endpoints to work normally
            pass
            
    except Exception as e:
        # Don't break request processing on auth errors
        frappe.logger().error(f"Error in global JWT auth middleware: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
