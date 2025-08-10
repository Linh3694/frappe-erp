"""
User Management Hooks
Auto-create user profiles and handle user events
"""

import frappe
from frappe import _


def create_user_profile_on_user_creation(doc, method):
    """Trước đây: auto-create ERP User Profile.

    Hiện tại: chỉ publish sự kiện tạo user để microservices đồng bộ.
    Không còn tạo `ERP User Profile`.
    """
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return

        # Publish user_created event (feature-flagged)
        try:
            from .redis_events import publish_user_event, is_user_events_enabled
            if is_user_events_enabled():
                publish_user_event('user_created', doc.email)
        except Exception:
            pass

    except Exception as e:
        frappe.log_error(f"Error handling user creation for {doc.email}: {str(e)}", "User Creation Hook")


def update_user_profile_on_user_update(doc, method):
    """Trước đây: cập nhật ERP User Profile khi User cập nhật.

    Hiện tại: không đụng tới profile, chỉ publish user_updated để realtime tới services.
    """
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return

        # Publish user_updated event (feature-flagged)
        try:
            from .redis_events import publish_user_event, is_user_events_enabled
            if is_user_events_enabled():
                publish_user_event('user_updated', doc.email)
        except Exception:
            pass

    except Exception as e:
        try:
            frappe.logger("user_profile").exception(f"Error in user update hook for {doc.email}: {str(e)}")
        except Exception:
            print("User Update Hook error:", str(e))


def delete_user_profile_on_user_deletion(doc, method):
    """Trước đây: xóa ERP User Profile khi xóa User.

    Hiện tại: chỉ publish user_deleted; không cần thao tác profile.
    """
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return

        # Publish user_deleted event (feature-flagged)
        try:
            from .redis_events import publish_user_event, is_user_events_enabled
            if is_user_events_enabled():
                publish_user_event('user_deleted', doc.email)
        except Exception:
            pass

    except Exception as e:
        frappe.log_error(f"Error in user deletion hook for {doc.email}: {str(e)}", "User Deletion Hook")


def validate_user_permissions(doc, method):
    """Validate quyền trực tiếp từ `User`.

    - Dùng `enabled` của core `User` để quyết định trạng thái
    - Không còn phụ thuộc `ERP User Profile`
    """
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return

        # Nếu user bị disable ở core
        if hasattr(doc, 'enabled') and not bool(doc.enabled):
            frappe.throw(_("User account is disabled"))

    except Exception as e:
        # Just log
        frappe.log_error(f"User permission validation error for {doc.email}: {str(e)}", "User Validation")


def setup_user_management_hooks():
    """Setup all user management hooks"""
    try:
        # User document hooks
        frappe.get_hooks("doc_events").setdefault("User", {})
        frappe.get_hooks("doc_events")["User"].setdefault("after_insert", [])
        frappe.get_hooks("doc_events")["User"].setdefault("on_update", [])
        frappe.get_hooks("doc_events")["User"].setdefault("before_delete", [])
        frappe.get_hooks("doc_events")["User"].setdefault("validate", [])
        
        # Add our hooks
        if "erp.common.hooks.create_user_profile_on_user_creation" not in frappe.get_hooks("doc_events")["User"]["after_insert"]:
            frappe.get_hooks("doc_events")["User"]["after_insert"].append("erp.common.hooks.create_user_profile_on_user_creation")
        
        if "erp.common.hooks.update_user_profile_on_user_update" not in frappe.get_hooks("doc_events")["User"]["on_update"]:
            frappe.get_hooks("doc_events")["User"]["on_update"].append("erp.common.hooks.update_user_profile_on_user_update")
        
        if "erp.common.hooks.delete_user_profile_on_user_deletion" not in frappe.get_hooks("doc_events")["User"]["before_delete"]:
            frappe.get_hooks("doc_events")["User"]["before_delete"].append("erp.common.hooks.delete_user_profile_on_user_deletion")
        
        if "erp.common.hooks.validate_user_permissions" not in frappe.get_hooks("doc_events")["User"]["validate"]:
            frappe.get_hooks("doc_events")["User"]["validate"].append("erp.common.hooks.validate_user_permissions")
        
    
        
    except Exception as e:
        frappe.log_error(f"Error setting up user management hooks: {str(e)}", "Hook Setup")


def on_login(login_manager):
    """Handle user login event"""
    try:
        user_email = login_manager.user
        
        # Skip for Guest and Administrator
        if user_email in ["Guest", "Administrator"]:
            return
        
        # Update last login in user profile
        from erp.user_management.api.auth import update_last_login
        update_last_login(user_email)
        
    except Exception as e:
        frappe.log_error(f"Error handling login event for {login_manager.user}: {str(e)}", "Login Event")


def on_logout(login_manager):
    """Handle user logout event"""
    try:
        user_email = login_manager.user
        
        # Skip for Guest and Administrator
        if user_email in ["Guest", "Administrator"]:
            return
        
        # Update last seen in user profile
        from erp.user_management.api.auth import update_last_seen
        update_last_seen(user_email)
        
    except Exception as e:
        frappe.log_error(f"Error handling logout event for {login_manager.user}: {str(e)}", "Logout Event")