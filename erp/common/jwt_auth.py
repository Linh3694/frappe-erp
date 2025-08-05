"""
JWT Authentication Handler for Frappe
Handles JWT token authentication for API requests
"""

import frappe
from frappe import _
import jwt
from datetime import datetime


def validate_jwt_auth():
    """
    JWT Authentication Hook for Frappe
    Called during request authentication to validate JWT tokens
    """
    try:
        # Skip if user is already authenticated or if it's a guest-allowed endpoint
        if frappe.session.user and frappe.session.user not in ("", "Guest"):
            return
        
        # Get Authorization header
        authorization_header = frappe.get_request_header("Authorization", "").strip()
        
        if not authorization_header:
            return
        
        # Check if it's Bearer token
        if not authorization_header.startswith("Bearer "):
            return
        
        # Extract token
        token = authorization_header.replace("Bearer ", "").strip()
        if not token:
            return
        
        # Verify JWT token
        user_email = verify_jwt_token(token)
        if not user_email:
            return
        
        # Check if user exists and is active
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"), frappe.AuthenticationError)
        
        user_doc = frappe.get_doc("User", user_email)
        if not user_doc.enabled:
            frappe.throw(_("User is disabled"), frappe.AuthenticationError)
        
        # Set user session
        frappe.set_user(user_email)
        frappe.local.login_manager.user = user_email
        
        # Update last activity
        update_user_activity(user_email)
        
    except frappe.AuthenticationError:
        raise
    except Exception as e:
        frappe.log_error(f"JWT Auth Error: {str(e)}", "JWT Authentication")
        # Don't raise error, let other auth methods handle it


def verify_jwt_token(token):
    """Verify JWT token and return user email"""
    try:
        # Get JWT secret from site config
        secret = (
            frappe.conf.get("jwt_secret") or 
            frappe.get_site_config().get("jwt_secret") or 
            "default_jwt_secret_change_in_production"
        )
        
        # Decode token
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        
        # Check expiration
        if payload.get("exp"):
            exp_time = datetime.fromtimestamp(payload["exp"])
            if exp_time < datetime.utcnow():
                return None
        
        return payload.get("user")
        
    except jwt.ExpiredSignatureError:
        frappe.log_error("JWT token expired", "JWT Authentication")
        return None
    except jwt.InvalidTokenError:
        frappe.log_error("Invalid JWT token", "JWT Authentication")
        return None
    except Exception as e:
        frappe.log_error(f"JWT verification error: {str(e)}", "JWT Authentication")
        return None


def update_user_activity(user_email):
    """Update user's last activity"""
    try:
        # Update ERP User Profile if exists
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if profile_name:
            frappe.db.set_value(
                "ERP User Profile", 
                profile_name, 
                "last_seen", 
                frappe.utils.now(),
                update_modified=False
            )
            frappe.db.commit()
    except Exception as e:
        frappe.log_error(f"User activity update error: {str(e)}", "JWT Authentication")