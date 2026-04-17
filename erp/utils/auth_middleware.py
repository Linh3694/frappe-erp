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

        auth_header = (frappe.get_request_header("Authorization") or "").strip()
        token_header = (frappe.get_request_header("X-Frappe-Token") or "").strip()
        has_explicit_jwt = (
            auth_header.lower().startswith("bearer ") and len(auth_header) > 7
        ) or bool(token_header)

        # Khi SPA gui Bearer / X-Frappe-Token: uu tien JWT truoc cookie session.
        # Neu bo qua JWT vi da co cookie, get_issue (can_approve_reject) va approve_issue (_can_approve)
        # co the khac user -> hien nut Duyet nhung POST bi PermissionError.
        if has_explicit_jwt:
            user_email = authenticate_via_jwt()
            if user_email:
                frappe.set_user(user_email)
                try:
                    frappe.local.login_manager.user = user_email
                except Exception:
                    pass
                frappe.logger().info(f"🔑 Global JWT auth (token priority): Set user {user_email}")
                frappe.local.jwt_authenticated = True
                return
            # Token sai/hết hạn: không return — cho phép dùng cookie session bên dưới

        if frappe.session.user and frappe.session.user != 'Guest':
            return

        # Khong co header JWT: thu JWT nhu cu khi van Guest (tuong thich nguoc)
        user_email = authenticate_via_jwt()

        if user_email:
            frappe.set_user(user_email)
            try:
                frappe.local.login_manager.user = user_email
            except Exception:
                pass
            frappe.logger().info(f"🔑 Global JWT auth: Set user {user_email}")
            frappe.local.jwt_authenticated = True

    except Exception as e:
        # Don't break request processing on auth errors
        frappe.logger().error(f"Error in global JWT auth middleware: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
