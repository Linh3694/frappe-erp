"""
User Management Hooks
Auto-create user profiles and handle user events
"""

import frappe
from frappe import _


def create_user_profile_on_user_creation(doc, method):
    """Auto-create user profile when new user is created"""
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return
        
        # Check if profile already exists
        if frappe.db.exists("ERP User Profile", {"user": doc.email}):
            return
        
        # Create user profile
        profile = frappe.get_doc({
            "doctype": "ERP User Profile",
            "user": doc.email,
            "active": 1,
            "provider": "local"
        })
        
        profile.insert(ignore_permissions=True)
        
        frappe.logger().info(f"Auto-created user profile for {doc.email}")
        
    except Exception as e:
        frappe.log_error(f"Error auto-creating user profile for {doc.email}: {str(e)}", "User Profile Creation")


def update_user_profile_on_user_update(doc, method):
    """Update user profile when user is updated"""
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": doc.email})
        if not profile_name:
            return
        
        profile = frappe.get_doc("ERP User Profile", profile_name)
        
        # Update last seen when user is updated
        from datetime import datetime
        profile.last_seen = datetime.now()
        
        # Sync enabled status
        if hasattr(doc, 'enabled'):
            profile.active = doc.enabled
        
        profile.save(ignore_permissions=True)
        
    except Exception as e:
        frappe.log_error(f"Error updating user profile for {doc.email}: {str(e)}", "User Profile Update")


def delete_user_profile_on_user_deletion(doc, method):
    """Delete user profile when user is deleted"""
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": doc.email})
        if profile_name:
            frappe.delete_doc("ERP User Profile", profile_name, ignore_permissions=True)
            frappe.logger().info(f"Auto-deleted user profile for {doc.email}")
        
    except Exception as e:
        frappe.log_error(f"Error deleting user profile for {doc.email}: {str(e)}", "User Profile Deletion")


def validate_user_permissions(doc, method):
    """Validate user permissions based on profile"""
    try:
        # Skip for Guest and Administrator
        if doc.email in ["Guest", "Administrator"]:
            return
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": doc.email})
        if not profile_name:
            return
        
        profile = frappe.get_doc("ERP User Profile", profile_name)
        
        # Check if user is disabled in profile
        if profile.disabled:
            frappe.throw(_("User account is disabled"))
        
        # Check if user is inactive in profile
        if not profile.active:
            frappe.throw(_("User account is inactive"))
        
    except Exception as e:
        # Don't throw error for validation issues, just log
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
        if "erp.common.common_user.hooks.create_user_profile_on_user_creation" not in frappe.get_hooks("doc_events")["User"]["after_insert"]:
            frappe.get_hooks("doc_events")["User"]["after_insert"].append("erp.common.common_user.hooks.create_user_profile_on_user_creation")
        
        if "erp.common.common_user.hooks.update_user_profile_on_user_update" not in frappe.get_hooks("doc_events")["User"]["on_update"]:
            frappe.get_hooks("doc_events")["User"]["on_update"].append("erp.common.common_user.hooks.update_user_profile_on_user_update")
        
        if "erp.common.common_user.hooks.delete_user_profile_on_user_deletion" not in frappe.get_hooks("doc_events")["User"]["before_delete"]:
            frappe.get_hooks("doc_events")["User"]["before_delete"].append("erp.common.common_user.hooks.delete_user_profile_on_user_deletion")
        
        if "erp.common.common_user.hooks.validate_user_permissions" not in frappe.get_hooks("doc_events")["User"]["validate"]:
            frappe.get_hooks("doc_events")["User"]["validate"].append("erp.common.common_user.hooks.validate_user_permissions")
        
        frappe.logger().info("User management hooks setup completed")
        
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