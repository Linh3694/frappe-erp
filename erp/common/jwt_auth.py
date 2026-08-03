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


def resolve_verified_user_from_jwt(token):
    """
    Verify chữ ký JWT (HS256, jwt_secret) và trả về email User hợp lệ.

    Dùng cho các endpoint allow_guest nhận Bearer token thủ công (đăng ký push token
    mobile/PWA). Khác verify_jwt_token ở chỗ: chấp nhận payload của cả staff
    (`user`/`email`) lẫn guardian (`sub`/`email`), và với tài khoản Parent Portal
    thì kiểm tra thêm token_version (force logout) qua verify_guardian_jwt_token.

    Returns:
        str: email User nếu token hợp lệ và User tồn tại, ngược lại None.
    """
    if not token:
        return None
    try:
        secret = (
            frappe.conf.get("jwt_secret")
            or frappe.get_site_config().get("jwt_secret")
            or "default_jwt_secret_change_in_production"
        )
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None

    user_email = (
        payload.get("email")
        or payload.get("sub")
        or payload.get("user")
        or payload.get("username")
    )
    if not user_email or not frappe.db.exists("User", user_email):
        return None

    # Tài khoản phụ huynh: tôn trọng cơ chế thu hồi phiên (jwt_token_version)
    if "@parent.wellspring.edu.vn" in user_email:
        try:
            from erp.api.parent_portal.guardian_auth import verify_guardian_jwt_token

            if not verify_guardian_jwt_token(token):
                return None
        except Exception:
            return None

    return user_email


def update_user_activity(user_email):
    """Update user's last activity - no longer needed after removing ERP User Profile"""
    pass