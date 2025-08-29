"""
Authentication API endpoints
Handles user login, logout, password reset, etc.
Updated to work only with Frappe User core (no ERP User Profile dependency)
"""

import frappe
from frappe import _
from frappe.auth import LoginManager
import secrets
import jwt
from datetime import datetime, timedelta
import requests
import json
from erp.utils.api_response import success_response, error_response


def find_user_by_identifier(identifier):
    """Find user by email, username, or employee_code (custom fields on User)"""
    try:
        # First try direct email match
        if frappe.db.exists("User", identifier):
            return frappe.get_doc("User", identifier)
        
        # Try to find by username or employee_code (custom fields on User)
        user_email = None
        
        # Check if User has custom field 'username'
        try:
            user_email = frappe.db.get_value("User", {"username": identifier})
        except:
            pass
            
        # Check if User has custom field 'employee_code'
        if not user_email:
            try:
                user_email = frappe.db.get_value("User", {"employee_code": identifier})
            except:
                pass
                
        if user_email:
            return frappe.get_doc("User", user_email)
            
        return None
        
    except Exception as e:
        frappe.log_error(f"Error finding user by identifier {identifier}: {str(e)}", "User Lookup")
        return None


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
        
        # Find user
        user_doc = find_user_by_identifier(identifier)
        
        if not user_doc:
            frappe.throw(_("User not found"))
        
        # Check if user is enabled
        if not user_doc.enabled:
            frappe.throw(_("Account is disabled"))
        
        # Authenticate based on provider
        if provider == "local":
            if not password:
                frappe.throw(_("Password is required for local authentication"))
            
            # Use Frappe's login manager
            login_manager = LoginManager()
            login_manager.authenticate(user_doc.email, password)
            login_manager.post_login()
            
        elif provider == "microsoft":
            # Microsoft authentication handled separately
            microsoft_id = getattr(user_doc, "microsoft_id", None)
            if not microsoft_id:
                frappe.throw(_("Microsoft authentication not configured"))
        
        elif provider == "apple":
            # Apple authentication handled separately
            apple_id = getattr(user_doc, "apple_id", None)
            if not apple_id:
                frappe.throw(_("Apple authentication not configured"))
        
        # Update last login timestamp on User if custom field exists
        try:
            if hasattr(user_doc, 'last_login'):
                user_doc.last_login = frappe.utils.now()
                user_doc.flags.ignore_permissions = True
                user_doc.save()
        except:
            pass
        
        # Generate JWT token for API access
        token = generate_jwt_token(user_doc.email)
        
        # Collect roles info
        try:
            frappe_roles = frappe.get_roles(user_doc.email) or []
        except Exception:
            frappe_roles = []
        try:
            from frappe import permissions as frappe_permissions
            manual_roles = frappe_permissions.get_roles(user_doc.email, with_standard=False) or []
        except Exception:
            manual_roles = []

        # Build user data from User core fields + custom fields
        user_data = {
            "email": user_doc.email,
            "full_name": user_doc.full_name,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "enabled": user_doc.enabled,
            "roles": frappe_roles,
            "user_roles": manual_roles,
            "provider": getattr(user_doc, "provider", "local"),
            "active": user_doc.enabled,  # Map enabled to active for backward compatibility
            "user_image": user_doc.user_image or "",
            "avatar_url": user_doc.user_image or "",
        }
        
        # Add custom fields if they exist
        for field in ["username", "employee_code", "job_title", "department", "designation", "microsoft_id", "apple_id"]:
            if hasattr(user_doc, field):
                user_data[field] = getattr(user_doc, field)

        return {
            "status": "success",
            "message": _("Login successful"),
            "user": user_data,
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
        # Update last seen timestamp if custom field exists
        if frappe.session.user != "Guest":
            try:
                user_doc = frappe.get_doc("User", frappe.session.user)
                if hasattr(user_doc, 'last_seen'):
                    user_doc.last_seen = frappe.utils.now()
                    user_doc.flags.ignore_permissions = True
                    user_doc.save()
            except:
                pass
        
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
        
        # Use Frappe's built-in password reset
        from frappe.utils.password import update_password_reset_token
        user_doc = frappe.get_doc("User", email)
        token = update_password_reset_token(user_doc)
        
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
        user_email = frappe.db.get_value("User", {
            "reset_password_key": token
        })
        
        if not user_email:
            frappe.throw(_("Invalid or expired reset token"))
        
        user_doc = frappe.get_doc("User", user_email)
        
        # Check token expiry
        from frappe.utils.password import verify_reset_token
        if not verify_reset_token(user_doc, token):
            frappe.throw(_("Invalid or expired reset token"))
        
        # Update password
        user_doc.new_password = new_password
        user_doc.save()
        
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
        # Check for JWT token first
        auth_header = frappe.get_request_header("Authorization") or ""
        alt_header = frappe.get_request_header("X-Auth-Token") or frappe.get_request_header("X-Frappe-Auth-Token") or ""
        token_candidate = None
        jwt_user_email = None
        
        if auth_header.lower().startswith("bearer "):
            token_candidate = auth_header.split(" ", 1)[1].strip()
        elif alt_header:
            token_candidate = alt_header.strip()
            
        if token_candidate:
            try:
                payload = verify_jwt_token(token_candidate)
                if payload:
                    jwt_user_email = (
                        payload.get("email")
                        or payload.get("user")
                        or payload.get("sub")
                    )
                    # If JWT is valid, use it
                    if jwt_user_email and frappe.db.exists("User", jwt_user_email):
                        user_doc = frappe.get_doc("User", jwt_user_email)
                        user_data = build_user_data_response(user_doc)
                        return success_response(
                            data={
                                "user": user_data,
                                "authenticated": True,
                            },
                            message="JWT authentication successful"
                        )
            except Exception as jwt_error:
                # JWT validation failed, continue to session-based auth
                frappe.logger().debug(f"JWT validation failed: {jwt_error}")
        
        # Check session-based authentication
        if frappe.session.user == "Guest":
            return success_response(
                data={
                    "user": None,
                    "authenticated": False
                },
                message="Guest user - not authenticated"
            )

        # Get current user data
        user_doc = frappe.get_doc("User", frappe.session.user)
        user_data = build_user_data_response(user_doc)

        return success_response(
            data={
                "user": user_data,
                "authenticated": True
            },
            message="Session authentication successful"
        )
        
    except Exception as e:
        frappe.log_error(f"Get current user error: {str(e)}", "Authentication")
        frappe.throw(_("Error getting user information: {0}").format(str(e)))


def build_user_data_response(user_doc):
    """Build user data response from User document"""
    user_data = {
        "email": user_doc.email,
        "full_name": user_doc.full_name,
        "first_name": user_doc.first_name,
        "last_name": user_doc.last_name,
        "enabled": user_doc.enabled,
        "active": user_doc.enabled,  # Map for backward compatibility
        "user_image": user_doc.user_image or "",
        "avatar_url": user_doc.user_image or "",
    }
    
    # Add custom fields if they exist
    custom_fields = [
        "username", "employee_code", "job_title", "department", "designation",
        "provider", "microsoft_id", "apple_id", "last_login", "last_seen"
    ]
    
    for field in custom_fields:
        if hasattr(user_doc, field):
            user_data[field] = getattr(user_doc, field)
    
    # Add roles
    try:
        user_data["roles"] = frappe.get_roles(user_doc.email) or []
    except Exception:
        user_data["roles"] = []
        
    try:
        from frappe import permissions as frappe_permissions
        user_data["user_roles"] = frappe_permissions.get_roles(user_doc.email, with_standard=False) or []
    except Exception:
        user_data["user_roles"] = []
    
    return user_data


def generate_jwt_token(user_email):
    """Generate JWT token for API access"""
    try:
        try:
            roles = frappe.get_roles(user_email) or []
        except Exception:
            roles = []

        now = datetime.utcnow()
        payload = {
            "sub": user_email,
            "email": user_email,
            "roles": roles,
            "iss": frappe.utils.get_url(),
            "ver": 1,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=24)).timestamp()),
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
    except Exception:
        return None


def send_password_reset_email(email, token):
    """Send password reset email"""
    try:
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
    """Update user profile - works directly with User custom fields"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to update profile"))
        
        if isinstance(profile_data, str):
            import json
            profile_data = json.loads(profile_data)
        
        # Get user document
        user_doc = frappe.get_doc("User", frappe.session.user)
        
        # Update allowed custom fields
        allowed_fields = [
            "username", "job_title", "department", "designation", "user_image"
        ]
        
        for field in allowed_fields:
            if field in profile_data and hasattr(user_doc, field):
                setattr(user_doc, field, profile_data[field])
        
        # Special handling for avatar_url -> user_image
        if "avatar_url" in profile_data:
            user_doc.user_image = profile_data["avatar_url"]
        
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        return {
            "status": "success",
            "message": _("Profile updated successfully"),
            "user": build_user_data_response(user_doc)
        }
        
    except Exception as e:
        frappe.log_error(f"Update profile error: {str(e)}", "Authentication")
        frappe.throw(_("Error updating profile: {0}").format(str(e)))


@frappe.whitelist(allow_guest=True)
def debug_jwt_token():
    """Debug JWT token validation"""
    try:
        auth_header = frappe.get_request_header("Authorization") or ""
        token_candidate = None
        
        if auth_header.lower().startswith("bearer "):
            token_candidate = auth_header.split(" ", 1)[1].strip()
        
        if not token_candidate:
            return error_response(
                message="No Bearer token found",
                code="NO_BEARER_TOKEN",
                errors={
                    "debug": {
                        "auth_header": auth_header[:50] + "..." if len(auth_header) > 50 else auth_header,
                        "headers": dict(frappe.request.headers) if frappe.request else {}
                    }
                }
            )
        
        # Test JWT decoding
        try:
            secret = (
                frappe.conf.get("jwt_secret")
                or frappe.get_site_config().get("jwt_secret")
                or "default_jwt_secret_change_in_production"
            )
            
            payload = jwt.decode(token_candidate, secret, algorithms=["HS256"])
            user_email = payload.get("email") or payload.get("sub")
            
            # Check if user exists
            user_exists = frappe.db.exists("User", user_email) if user_email else False

            return success_response(
                message="JWT token valid",
                data={
                    "debug": {
                        "token_preview": token_candidate[:30] + "...",
                        "secret_preview": secret[:10] + "..." if secret else None,
                        "payload": payload,
                        "user_email": user_email,
                        "user_exists": user_exists
                    }
                }
            )
            
        except jwt.ExpiredSignatureError:
            return error_response(
                message="Token expired",
                code="TOKEN_EXPIRED",
                errors={
                    "debug": {"token_preview": token_candidate[:30] + "..."}
                }
            )
        except jwt.InvalidTokenError as e:
            return error_response(
                message=f"Invalid token: {str(e)}",
                code="INVALID_TOKEN",
                errors={
                    "debug": {"token_preview": token_candidate[:30] + "..."}
                }
            )
            
    except Exception as e:
        return error_response(
            message=f"Debug error: {str(e)}",
            code="DEBUG_ERROR",
            errors={
                "debug": {"error": str(e)}
            }
        )


@frappe.whitelist()
def delete_avatar():
    """Delete user avatar"""
    try:
        if frappe.session.user == "Guest":
            frappe.throw(_("Please login to delete avatar"))
        
        user_doc = frappe.get_doc("User", frappe.session.user)
        current_avatar = user_doc.user_image
        
        # Delete file if exists
        if current_avatar and current_avatar.startswith("/files/Avatar/"):
            file_path = frappe.get_site_path("public", current_avatar.lstrip("/"))
            import os
            if os.path.exists(file_path):
                os.remove(file_path)
        
        # Update User
        user_doc.user_image = ""
        user_doc.flags.ignore_permissions = True
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
        avatar_file.seek(0, 2)
        file_size = avatar_file.tell()
        avatar_file.seek(0)
        
        max_size = 5 * 1024 * 1024  # 5MB
        if file_size > max_size:
            frappe.throw(_("File size too large. Maximum allowed: 5MB"))
        
        # Create filename
        import uuid
        import os
        file_id = str(uuid.uuid4())
        filename = f"{file_id}.{file_extension or 'jpg'}"
        
        # Create Avatar directory if it doesn't exist
        upload_dir = frappe.get_site_path("public", "files", "Avatar")
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
        
        # Save file
        file_path = os.path.join(upload_dir, filename)
        avatar_file.stream.seek(0)
        with open(file_path, 'wb') as f:
            f.write(avatar_file.stream.read())
        
        # Create file URL
        avatar_url = f"/files/Avatar/{filename}"
        
        # Update User.user_image
        frappe.db.set_value("User", frappe.session.user, "user_image", avatar_url)
        frappe.db.commit()
        
        return {
            "status": "success",
            "message": _("Avatar uploaded successfully"),
            "avatar_url": avatar_url
        }
        
    except Exception as e:
        frappe.log_error(f"Upload avatar error: {str(e)}", "Authentication")
        frappe.throw(_("Error uploading avatar: {0}").format(str(e)))