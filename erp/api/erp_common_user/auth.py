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
        from erp.common.doctype.erp_user_profile.erp_user_profile import ERPUserProfile
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
        
        # Collect roles info (Frappe roles and manual roles)
        try:
            frappe_roles = frappe.get_roles(profile.user) or []
        except Exception:
            frappe_roles = []
        try:
            from frappe import permissions as frappe_permissions
            manual_roles = frappe_permissions.get_roles(profile.user, with_standard=False) or []
        except Exception:
            manual_roles = []

        user_doc = profile.get_user_doc()
        avatar_url = None
        try:
            avatar_url = profile.avatar_url or (user_doc.user_image if user_doc else "") or ""
        except Exception:
            avatar_url = ""

        return {
            "status": "success",
            "message": _("Login successful"),
            "user": {
                "email": profile.user,
                "username": profile.username,
                "full_name": user_doc.full_name if user_doc else profile.username,
                "job_title": profile.job_title,
                "department": profile.department,
                "employee_code": getattr(profile, "employee_code", None),
                "role": profile.user_role,
                "roles": frappe_roles,
                "user_roles": manual_roles,
                "provider": profile.provider or "local",
                "active": bool(profile.active),
                "user_image": getattr(user_doc, "user_image", "") if user_doc else "",
                "avatar_url": avatar_url,
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
            from erp.common.doctype.erp_user_profile.erp_user_profile import update_last_seen
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


@frappe.whitelist(allow_guest=True)
def get_current_user():
    """Get current user information"""
    try:
        # Nếu chưa có session hợp lệ, thử xác thực bằng Bearer JWT
        if frappe.session.user == "Guest":
            try:
                # Hỗ trợ nhiều header đề phòng proxy strip Authorization
                auth_header = frappe.get_request_header("Authorization") or ""
                alt_header = frappe.get_request_header("X-Auth-Token") or frappe.get_request_header("X-Frappe-Auth-Token") or ""
                token_candidate = None
                if auth_header.lower().startswith("bearer "):
                    token_candidate = auth_header.split(" ", 1)[1].strip()
                elif alt_header:
                    token_candidate = alt_header.strip()
                if token_candidate:
                    bearer = token_candidate
                    payload = verify_jwt_token(bearer)
                    user_email = None
                    if payload:
                        user_email = (
                            payload.get("email")
                            or payload.get("user")
                            or payload.get("sub")
                        )
                    if user_email:
                        # Khi xác thực qua JWT, vẫn trả về user data (không tạo session)
                        user_doc = frappe.get_doc("User", user_email)
                        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
                        user_data = {
                            "email": user_doc.email,
                            "full_name": user_doc.full_name,
                            "first_name": user_doc.first_name,
                            "last_name": user_doc.last_name,
                            "enabled": user_doc.enabled,
                            "user_image": user_doc.user_image or "",
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
                                "last_seen": profile.last_seen,
                                "avatar_url": profile.avatar_url or user_doc.user_image or "",
                            })
                        # Bổ sung roles
                        try:
                            user_data["roles"] = frappe.get_roles(user_email) or []
                        except Exception:
                            user_data["roles"] = []
                        try:
                            from frappe import permissions as frappe_permissions
                            user_data["user_roles"] = frappe_permissions.get_roles(user_email, with_standard=False) or []
                        except Exception:
                            user_data["user_roles"] = []
                        return {
                            "status": "success",
                            "user": user_data,
                            "authenticated": True,
                        }
            except Exception:
                pass
            # Không xác thực được
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
            "enabled": user_doc.enabled,
            "user_image": user_doc.user_image or "",
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
                "last_seen": profile.last_seen,
                "avatar_url": profile.avatar_url or user_doc.user_image or "",
            })
        
        # Add frappe roles for current user (ensure consistent fields for FE)
        try:
            user_data["roles"] = frappe.get_roles(frappe.session.user) or []
        except Exception:
            user_data["roles"] = []
        try:
            from frappe import permissions as frappe_permissions
            user_data["user_roles"] = frappe_permissions.get_roles(frappe.session.user, with_standard=False) or []
        except Exception:
            user_data["user_roles"] = []
        else:
            # If no profile exists, still provide avatar from user_image
            user_data["avatar_url"] = user_doc.user_image or ""
        
        return {
            "status": "success",
            "user": user_data,
            "authenticated": True
        }
        
    except Exception as e:
        frappe.log_error(f"Get current user error: {str(e)}", "Authentication")
        frappe.throw(_("Error getting user information: {0}").format(str(e)))


def generate_jwt_token(user_email):
    """Generate JWT token for API access (HS256 shared secret).

    Claims:
      - sub: user email (subject)
      - email: user email (explicit)
      - roles: list of frappe roles
      - iss: issuer (site url)
      - ver: token schema version
      - iat, exp: issued/expiry
    """
    try:
        try:
            roles = frappe.get_roles(user_email) or []
        except Exception:
            roles = []

        payload = {
            "sub": user_email,
            "email": user_email,
            "roles": roles,
            "iss": frappe.utils.get_url(),
            "ver": 1,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=24),
        }

        secret = (
            frappe.conf.get("jwt_secret")
            or frappe.get_site_config().get("jwt_secret")
            or "default_jwt_secret_change_in_production"
        )
        token = jwt.encode(payload, secret, algorithm="HS256")

        return token

    except Exception as e:
        frappe.log_error(f"JWT token generation error: {str(e)}", "Authentication")
        return None


def verify_jwt_token(token):
    """Verify JWT token and return payload dict on success, else None"""
    try:
        secret = (
            frappe.conf.get("jwt_secret")
            or frappe.get_site_config().get("jwt_secret")
            or "default_jwt_secret_change_in_production"
        )
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
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
        
        # Sync avatar_url to User.user_image if avatar_url is updated
        if "avatar_url" in profile_data:
            user_doc = frappe.get_doc("User", frappe.session.user)
            user_doc.user_image = profile_data["avatar_url"]
            user_doc.save()
        
        return {
            "status": "success",
            "message": _("Profile updated successfully"),
            "profile": profile.as_dict()
        }
        
    except Exception as e:
        frappe.log_error(f"Update profile error: {str(e)}", "Authentication")
        frappe.throw(_("Error updating profile: {0}").format(str(e)))


@frappe.whitelist()
def delete_avatar():
    """Delete user avatar"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to delete avatar"))
        
        # Get current avatar
        profile_name = frappe.db.get_value("ERP User Profile", {"user": frappe.session.user})
        current_avatar = None
        
        if profile_name:
            current_avatar = frappe.db.get_value("ERP User Profile", profile_name, "avatar_url")
        
        if not current_avatar:
            current_avatar = frappe.db.get_value("User", frappe.session.user, "user_image")
        
        # Delete file if exists
        if current_avatar and current_avatar.startswith("/files/Avatar/"):
            file_path = frappe.get_site_path("public", current_avatar.lstrip("/"))
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
        
        # Update profile
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
            profile.avatar_url = ""
            profile.save()
        
        # Update User
        user_doc = frappe.get_doc("User", frappe.session.user)
        user_doc.user_image = ""
        user_doc.save()
        
        return {
            "status": "success",
            "message": _("Avatar deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Delete avatar error: {str(e)}", "Authentication")
        frappe.throw(_("Error deleting avatar: {0}").format(str(e)))


@frappe.whitelist()
def upload_avatar():
    """Upload user avatar"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to upload avatar"))
        
        # Get uploaded file
        files = frappe.request.files
        if not files or 'avatar' not in files:
            frappe.throw(_("No avatar file provided"))
        
        avatar_file = files['avatar']
        
        # Validate file type
        allowed_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp']
        file_extension = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else ''
        
        if file_extension not in allowed_extensions:
            frappe.throw(_("Invalid file type. Allowed types: {0}").format(', '.join(allowed_extensions)))
        
        # Validate file size (max 5MB)
        avatar_file.seek(0, 2)  # Move to end
        file_size = avatar_file.tell()
        avatar_file.seek(0)  # Reset to beginning
        
        max_size = 5 * 1024 * 1024  # 5MB
        if file_size > max_size:
            frappe.throw(_("File size too large. Maximum allowed: 5MB"))
        
        # Create filename & ensure extension
        import uuid
        import os
        file_id = str(uuid.uuid4())
        filename = f"{file_id}.{file_extension or 'jpg'}"
        
        # Create Avatar directory if it doesn't exist
        from frappe.utils.file_manager import get_file_path
        upload_dir = frappe.get_site_path("public", "files", "Avatar")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
        
        # Save file (read stream safely)
        file_path = os.path.join(upload_dir, filename)
        avatar_file.stream.seek(0)
        with open(file_path, 'wb') as f:
            f.write(avatar_file.stream.read())
        
        # Create file URL
        avatar_url = f"/files/Avatar/{filename}"
        
        # Update avatar via lightweight DB operations to avoid triggering heavy hooks
        profile_name = frappe.db.get_value("ERP User Profile", {"user": frappe.session.user})
        if profile_name:
            frappe.db.set_value("ERP User Profile", profile_name, "avatar_url", avatar_url)
        # Update User.user_image for compatibility (avoid full save to skip hooks)
        frappe.db.set_value("User", frappe.session.user, "user_image", avatar_url)
        # Ensure changes are flushed immediately
        frappe.db.commit()
        
        return {
            "status": "success",
            "message": _("Avatar uploaded successfully"),
            "avatar_url": avatar_url
        }
        
    except Exception as e:
        # Tránh dùng log_error (ghi DB) khi DB connection có vấn đề; log ra file thay thế
        try:
            frappe.logger("avatar_upload").exception(f"Upload avatar error: {str(e)}")
        except Exception:
            # Fallback cuối cùng
            print("Upload avatar error:", str(e))
        frappe.throw(_("Error uploading avatar: {0}").format(str(e)))