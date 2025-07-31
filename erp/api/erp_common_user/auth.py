"""
Authentication API endpoints
Handles user login, logout, password reset, etc.
"""

import frappe
from frappe import _
from frappe.auth import LoginManager
import secrets
import jwt
from datetime import datetime, timedelta
import requests
import json


@frappe.whitelist(allow_guest=True)
def login(email=None, username=None, password=None, provider="local"):
    """
    User login with multiple authentication providers
    
    Args:
        email: User email
        username: Username or employee code
        password: Password
        provider: Authentication provider (local, microsoft, apple)
    """
    try:
        # Find user by identifier
        identifier = email or username
        if not identifier:
            frappe.throw(_("Email or username is required"))
        
        # Get user profile
        from erp.user_management.doctype.erp_user_profile.erp_user_profile import ERPUserProfile
        profile = ERPUserProfile.find_by_login_identifier(identifier)
        
        if not profile:
            frappe.throw(_("User not found"))
        
        # Check if user is active
        if not profile.active or profile.disabled:
            frappe.throw(_("Account is disabled"))
        
        # Authenticate based on provider
        if provider == "local":
            if not password:
                frappe.throw(_("Password is required for local authentication"))
            
            # Verify password with Frappe's authentication
            user_doc = profile.get_user_doc()
            if not user_doc:
                frappe.throw(_("User account not found"))
            
            # Use Frappe's login manager
            login_manager = LoginManager()
            login_manager.authenticate(user_doc.email, password)
            login_manager.post_login()
            
        elif provider == "microsoft":
            # Microsoft authentication handled separately
            if not profile.microsoft_id:
                frappe.throw(_("Microsoft authentication not configured"))
        
        elif provider == "apple":
            # Apple authentication handled separately
            if not profile.apple_id:
                frappe.throw(_("Apple authentication not configured"))
        
        # Update login timestamps
        profile.update_last_login()
        
        # Generate JWT token for API access
        token = generate_jwt_token(profile.user)
        
        return {
            "status": "success",
            "message": _("Login successful"),
            "user": {
                "email": profile.user,
                "username": profile.username,
                "full_name": profile.get_user_doc().full_name,
                "job_title": profile.job_title,
                "department": profile.department,
                "role": profile.user_role,
                "provider": profile.provider
            },
            "token": token,
            "expires_in": 24 * 60 * 60  # 24 hours
        }
        
    except Exception as e:
        frappe.log_error(f"Login error: {str(e)}", "Authentication")
        frappe.throw(_("Login failed: {0}").format(str(e)))


@frappe.whitelist()
def logout():
    """User logout"""
    try:
        # Update last seen
        if frappe.session.user != "Guest":
            from erp.user_management.doctype.erp_user_profile.erp_user_profile import update_last_seen
            update_last_seen(frappe.session.user)
        
        # Use Frappe's logout
        frappe.local.login_manager.logout()
        
        return {
            "status": "success",
            "message": _("Logout successful")
        }
        
    except Exception as e:
        frappe.log_error(f"Logout error: {str(e)}", "Authentication")
        return {
            "status": "error",
            "message": str(e)
        }


@frappe.whitelist(allow_guest=True)
def forgot_password(email):
    """Request password reset"""
    try:
        # Check if user exists
        if not frappe.db.exists("User", email):
            frappe.throw(_("User with email {0} not found").format(email))
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": email})
        if not profile_name:
            frappe.throw(_("User profile not found"))
        
        profile = frappe.get_doc("ERP User Profile", profile_name)
        
        # Generate reset token
        token = profile.generate_reset_token()
        
        # Send reset email
        send_password_reset_email(email, token)
        
        return {
            "status": "success",
            "message": _("Password reset email sent")
        }
        
    except Exception as e:
        frappe.log_error(f"Forgot password error: {str(e)}", "Authentication")
        frappe.throw(_("Error sending password reset email: {0}").format(str(e)))


@frappe.whitelist(allow_guest=True)
def reset_password(token, new_password):
    """Reset password using token"""
    try:
        # Find user with valid token
        profile_name = frappe.db.get_value("ERP User Profile", {
            "reset_password_token": token,
            "reset_password_expire": [">", datetime.now()]
        })
        
        if not profile_name:
            frappe.throw(_("Invalid or expired reset token"))
        
        profile = frappe.get_doc("ERP User Profile", profile_name)
        
        # Verify token
        if not profile.verify_reset_token(token):
            frappe.throw(_("Invalid or expired reset token"))
        
        # Update user password
        user_doc = profile.get_user_doc()
        user_doc.new_password = new_password
        user_doc.save()
        
        # Clear reset token
        profile.clear_reset_token()
        
        return {
            "status": "success",
            "message": _("Password reset successful")
        }
        
    except Exception as e:
        frappe.log_error(f"Reset password error: {str(e)}", "Authentication")
        frappe.throw(_("Error resetting password: {0}").format(str(e)))


@frappe.whitelist()
def change_password(current_password, new_password):
    """Change user password"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to change password"))
        
        # Get current user
        user_doc = frappe.get_doc("User", frappe.session.user)
        
        # Verify current password
        if not user_doc.check_password(current_password):
            frappe.throw(_("Current password is incorrect"))
        
        # Update password
        user_doc.new_password = new_password
        user_doc.save()
        
        return {
            "status": "success",
            "message": _("Password changed successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Change password error: {str(e)}", "Authentication")
        frappe.throw(_("Error changing password: {0}").format(str(e)))


@frappe.whitelist()
def get_current_user():
    """Get current user information"""
    try:
        if frappe.session.user == "Guest":
            return {
                "status": "success",
                "user": None,
                "authenticated": False
            }
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": frappe.session.user})
        user_doc = frappe.get_doc("User", frappe.session.user)
        
        user_data = {
            "email": user_doc.email,
            "full_name": user_doc.full_name,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "enabled": user_doc.enabled
        }
        
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
            user_data.update({
                "username": profile.username,
                "employee_code": profile.employee_code,
                "job_title": profile.job_title,
                "department": profile.department,
                "role": profile.user_role,
                "provider": profile.provider,
                "active": profile.active,
                "last_login": profile.last_login,
                "last_seen": profile.last_seen
            })
        
        return {
            "status": "success",
            "user": user_data,
            "authenticated": True
        }
        
    except Exception as e:
        frappe.log_error(f"Get current user error: {str(e)}", "Authentication")
        frappe.throw(_("Error getting user information: {0}").format(str(e)))


def generate_jwt_token(user_email):
    """Generate JWT token for API access"""
    try:
        payload = {
            "user": user_email,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=24)
        }
        
        secret = frappe.conf.get("jwt_secret") or frappe.get_site_config().get("jwt_secret") or "default_jwt_secret_change_in_production"
        token = jwt.encode(payload, secret, algorithm="HS256")
        
        return token
        
    except Exception as e:
        frappe.log_error(f"JWT token generation error: {str(e)}", "Authentication")
        return None


def verify_jwt_token(token):
    """Verify JWT token"""
    try:
        secret = frappe.conf.get("jwt_secret") or frappe.get_site_config().get("jwt_secret") or "default_jwt_secret_change_in_production"
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        
        return payload.get("user")
        
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def send_password_reset_email(email, token):
    """Send password reset email"""
    try:
        # Get user
        user_doc = frappe.get_doc("User", email)
        
        # Create reset URL
        reset_url = f"{frappe.utils.get_url()}/reset-password?token={token}"
        
        # Email template
        subject = _("Password Reset Request")
        message = f"""
        Hello {user_doc.full_name},
        
        You have requested to reset your password. Please click the link below to reset your password:
        
        {reset_url}
        
        This link will expire in 1 hour.
        
        If you did not request this, please ignore this email.
        
        Best regards,
        System Team
        """
        
        # Send email
        frappe.sendmail(
            recipients=[email],
            subject=subject,
            message=message
        )
        
        return True
        
    except Exception as e:
        frappe.log_error(f"Password reset email error: {str(e)}", "Authentication")
        return False


@frappe.whitelist()
def refresh_token():
    """Refresh JWT token"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to refresh token"))
        
        # Generate new token
        token = generate_jwt_token(frappe.session.user)
        
        if not token:
            frappe.throw(_("Error generating token"))
        
        return {
            "status": "success",
            "token": token,
            "expires_in": 24 * 60 * 60
        }
        
    except Exception as e:
        frappe.log_error(f"Token refresh error: {str(e)}", "Authentication")
        frappe.throw(_("Error refreshing token: {0}").format(str(e)))


@frappe.whitelist()
def update_profile(profile_data):
    """Update user profile"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to update profile"))
        
        if isinstance(profile_data, str):
            import json
            profile_data = json.loads(profile_data)
        
        # Get or create user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": frappe.session.user})
        
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
        else:
            profile = frappe.get_doc({
                "doctype": "ERP User Profile",
                "user": frappe.session.user
            })
        
        # Update allowed fields
        allowed_fields = [
            "username", "job_title", "department", "avatar_url", 
            "device_token", "notes"
        ]
        
        for field in allowed_fields:
            if field in profile_data:
                setattr(profile, field, profile_data[field])
        
        profile.save()
        
        return {
            "status": "success",
            "message": _("Profile updated successfully"),
            "profile": profile.as_dict()
        }
        
    except Exception as e:
        frappe.log_error(f"Update profile error: {str(e)}", "Authentication")
        frappe.throw(_("Error updating profile: {0}").format(str(e)))