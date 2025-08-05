"""
User Management API
Handles user CRUD operations, role management, etc.
"""

import frappe
from frappe import _
from datetime import datetime
import json


@frappe.whitelist()
def get_users(page=1, limit=20, search=None, role=None, department=None, active=None):
    """
    Get users with filtering and pagination
    
    Args:
        page: Page number
        limit: Items per page
        search: Search term (name, email, username)
        role: Filter by role
        department: Filter by department
        active: Filter by active status
    """
    try:
        # Debug: Log parameters
        frappe.logger().info(f"get_users called with: page={page}, limit={limit}, search={search}, role={role}, department={department}, active={active}")
        
        # Debug: Log request data (an toàn, không crash nếu không có JSON)
        import json
        request_data = {}
        try:
            if frappe.request.is_json:
                request_data = frappe.request.get_json()
        except Exception as e:
            frappe.logger().info(f"Ignore JSON decode error: {e}")
        frappe.logger().info(f"get_users request data: {json.dumps(request_data, default=str)}")
        
        # Debug: Log request form data
        form_data = frappe.request.form.to_dict() if hasattr(frappe.request, 'form') else {}
        frappe.logger().info(f"get_users form data: {json.dumps(form_data, default=str)}")
        
        # Debug: Log all request parameters
        all_params = frappe.request.args.to_dict() if hasattr(frappe.request, 'args') else {}
        frappe.logger().info(f"get_users all params: {json.dumps(all_params, default=str)}")
        
        # Convert parameters to proper types
        try:
            page = int(page) if page else 1
            limit = int(limit) if limit else 20
            frappe.logger().info(f"Converted parameters: page={page} (type: {type(page)}), limit={limit} (type: {type(limit)})")
        except (ValueError, TypeError) as e:
            frappe.logger().error(f"Error converting parameters: {e}")
            page = 1
            limit = 20
        
        # Build filters
        filters = {}
        
        if role:
            filters["user_role"] = role
        if department:
            filters["department"] = department
        if active is not None:
            filters["active"] = active
        
        # Build search conditions
        search_conditions = []
        if search:
            search_conditions = [
                ["ERP User Profile", "user", "like", f"%{search}%"],
                ["ERP User Profile", "username", "like", f"%{search}%"],
                ["User", "full_name", "like", f"%{search}%"]
            ]
        
        # Calculate offset
        offset = (int(page) - 1) * int(limit)
        
        # Debug: Log SQL parameters
        frappe.logger().info(f"SQL parameters: limit={int(limit)}, offset={offset}")
        
        # Get user profiles with joins
        profiles = frappe.db.sql("""
            SELECT 
                p.name,
                p.user,
                p.username,
                p.employee_code,
                p.job_title,
                p.department,
                p.user_role,
                p.provider,
                p.active,
                p.disabled,
                p.last_login,
                p.last_seen,
                u.full_name,
                u.email,
                u.enabled,
                u.creation as user_created
            FROM 
                `tabERP User Profile` p
            LEFT JOIN 
                `tabUser` u ON p.user = u.email
            WHERE 
                p.user IS NOT NULL
                {role_filter}
                {department_filter}
                {active_filter}
                {search_filter}
            ORDER BY 
                p.modified DESC
            LIMIT {limit} OFFSET {offset}
        """.format(
            role_filter=f"AND p.user_role = '{role}'" if role else "",
            department_filter=f"AND p.department = '{department}'" if department else "",
            active_filter=f"AND p.active = {int(active)}" if active is not None else "",
            search_filter=f"AND (p.user LIKE '%{search}%' OR p.username LIKE '%{search}%' OR u.full_name LIKE '%{search}%')" if search else "",
            limit=int(limit),
            offset=offset
        ), as_dict=True)
        
        # Debug: Log result count
        frappe.logger().info(f"Query returned {len(profiles)} users")
        
        # Get total count
        total_count = frappe.db.sql("""
            SELECT COUNT(*)
            FROM `tabERP User Profile` p
            LEFT JOIN `tabUser` u ON p.user = u.email
            WHERE p.user IS NOT NULL
                {role_filter}
                {department_filter}
                {active_filter}
                {search_filter}
        """.format(
            role_filter=f"AND p.user_role = '{role}'" if role else "",
            department_filter=f"AND p.department = '{department}'" if department else "",
            active_filter=f"AND p.active = {int(active)}" if active is not None else "",
            search_filter=f"AND (p.user LIKE '%{search}%' OR p.username LIKE '%{search}%' OR u.full_name LIKE '%{search}%')" if search else ""
        ))[0][0]
        
        # Debug: Log total count
        frappe.logger().info(f"Total users in database: {total_count}")
        
        return {
            "status": "success",
            "users": profiles,
            "pagination": {
                "page": int(page),
                "limit": int(limit),
                "total": total_count,
                "pages": (total_count + int(limit) - 1) // int(limit)
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Get users error: {str(e)}", "User Management")
        frappe.throw(_("Error getting users: {0}").format(str(e)))


@frappe.whitelist()
def get_user_by_id(user_email):
    """Get user details by email"""
    try:
        # Check if user exists
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Get user document
        user_doc = frappe.get_doc("User", user_email)
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        profile = None
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
        
        # Build user data
        user_data = {
            "email": user_doc.email,
            "full_name": user_doc.full_name,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "enabled": user_doc.enabled,
            "creation": user_doc.creation,
            "modified": user_doc.modified,
            "roles": [{"role": role.role} for role in user_doc.roles]
        }
        
        # Add profile data if exists
        if profile:
            user_data.update({
                "username": profile.username,
                "employee_code": profile.employee_code,
                "job_title": profile.job_title,
                "department": profile.department,
                "user_role": profile.user_role,
                "provider": profile.provider,
                "active": profile.active,
                "disabled": profile.disabled,
                "last_login": profile.last_login,
                "last_seen": profile.last_seen,
                "microsoft_id": profile.microsoft_id,
                "apple_id": profile.apple_id,
                "avatar_url": profile.avatar_url,
                "device_token": profile.device_token
            })
        
        return {
            "status": "success",
            "user": user_data
        }
        
    except Exception as e:
        frappe.log_error(f"Get user by ID error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user: {0}").format(str(e)))


@frappe.whitelist()
def create_user(user_data):
    """Create new user with profile"""
    try:
        if isinstance(user_data, str):
            user_data = json.loads(user_data)
        
        # Validate required fields
        if not user_data.get("email"):
            frappe.throw(_("Email is required"))
        if not user_data.get("full_name"):
            frappe.throw(_("Full name is required"))
        
        # Check if user already exists
        if frappe.db.exists("User", user_data["email"]):
            frappe.throw(_("User with email {0} already exists").format(user_data["email"]))
        
        # Create User document
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": user_data["email"],
            "first_name": user_data.get("first_name") or user_data["full_name"].split()[0],
            "last_name": user_data.get("last_name") or " ".join(user_data["full_name"].split()[1:]),
            "full_name": user_data["full_name"],
            "enabled": user_data.get("enabled", 1),
            "send_welcome_email": user_data.get("send_welcome_email", 0)
        })
        
        # Set password if provided
        if user_data.get("password"):
            user_doc.new_password = user_data["password"]
        
        user_doc.insert(ignore_permissions=True)
        
        # Create User Profile
        profile_data = {
            "doctype": "ERP User Profile",
            "user": user_data["email"],
            "username": user_data.get("username"),
            "employee_code": user_data.get("employee_code"),
            "job_title": user_data.get("job_title"),
            "department": user_data.get("department"),
            "user_role": user_data.get("user_role", "user"),
            "provider": user_data.get("provider", "local"),
            "active": user_data.get("active", 1),
            "disabled": user_data.get("disabled", 0)
        }
        
        profile = frappe.get_doc(profile_data)
        profile.insert(ignore_permissions=True)
        
        # Assign roles if provided
        if user_data.get("roles"):
            for role in user_data["roles"]:
                user_doc.append("roles", {"role": role})
            user_doc.save()
        
        return {
            "status": "success",
            "message": _("User created successfully"),
            "user_email": user_doc.email
        }
        
    except Exception as e:
        frappe.log_error(f"Create user error: {str(e)}", "User Management")
        frappe.throw(_("Error creating user: {0}").format(str(e)))


@frappe.whitelist()
def update_user(user_email, user_data):
    """Update user and profile"""
    try:
        if isinstance(user_data, str):
            user_data = json.loads(user_data)
        
        # Check if user exists
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Update User document
        user_doc = frappe.get_doc("User", user_email)
        
        # Update allowed User fields
        user_fields = ["first_name", "last_name", "full_name", "enabled"]
        for field in user_fields:
            if field in user_data:
                setattr(user_doc, field, user_data[field])
        
        # Update password if provided
        if user_data.get("password"):
            user_doc.new_password = user_data["password"]
        
        user_doc.save()
        
        # Update User Profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
        else:
            # Create profile if doesn't exist
            profile = frappe.get_doc({
                "doctype": "ERP User Profile",
                "user": user_email
            })
        
        # Update profile fields
        profile_fields = [
            "username", "employee_code", "job_title", "department", 
            "user_role", "active", "disabled", "avatar_url", "device_token"
        ]
        
        for field in profile_fields:
            if field in user_data:
                setattr(profile, field, user_data[field])
        
        profile.save()
        
        # Update roles if provided
        if user_data.get("roles"):
            # Clear existing roles
            user_doc.roles = []
            
            # Add new roles
            for role in user_data["roles"]:
                user_doc.append("roles", {"role": role})
            
            user_doc.save()
        
        return {
            "status": "success",
            "message": _("User updated successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Update user error: {str(e)}", "User Management")
        frappe.throw(_("Error updating user: {0}").format(str(e)))


@frappe.whitelist()
def delete_user(user_email):
    """Delete user and profile"""
    try:
        # Check if user exists
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Don't allow deleting Administrator
        if user_email == "Administrator":
            frappe.throw(_("Cannot delete Administrator user"))
        
        # Don't allow deleting current user
        if user_email == frappe.session.user:
            frappe.throw(_("Cannot delete your own account"))
        
        # Delete user profile first
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if profile_name:
            frappe.delete_doc("ERP User Profile", profile_name, ignore_permissions=True)
        
        # Delete user
        frappe.delete_doc("User", user_email, ignore_permissions=True)
        
        return {
            "status": "success",
            "message": _("User deleted successfully")
        }
        
    except Exception as e:
        frappe.log_error(f"Delete user error: {str(e)}", "User Management")
        frappe.throw(_("Error deleting user: {0}").format(str(e)))


@frappe.whitelist()
def enable_disable_user(user_email, enabled):
    """Enable or disable user"""
    try:
        # Check if user exists
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Update User document
        user_doc = frappe.get_doc("User", user_email)
        user_doc.enabled = int(enabled)
        user_doc.save()
        
        # Update User Profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if profile_name:
            profile = frappe.get_doc("ERP User Profile", profile_name)
            profile.active = int(enabled)
            profile.save()
        
        status_text = "enabled" if int(enabled) else "disabled"
        
        return {
            "status": "success",
            "message": _("User {0} successfully").format(status_text)
        }
        
    except Exception as e:
        frappe.log_error(f"Enable/disable user error: {str(e)}", "User Management")
        frappe.throw(_("Error updating user status: {0}").format(str(e)))


@frappe.whitelist()
def reset_user_password(user_email):
    """Reset user password and send email"""
    try:
        # Check if user exists
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Get user profile
        profile_name = frappe.db.get_value("ERP User Profile", {"user": user_email})
        if not profile_name:
            frappe.throw(_("User profile not found"))
        
        profile = frappe.get_doc("ERP User Profile", profile_name)
        
        # Generate reset token
        token = profile.generate_reset_token()
        
        # Send reset email
        from erp.user_management.api.auth import send_password_reset_email
        send_password_reset_email(user_email, token)
        
        return {
            "status": "success",
            "message": _("Password reset email sent")
        }
        
    except Exception as e:
        frappe.log_error(f"Reset user password error: {str(e)}", "User Management")
        frappe.throw(_("Error resetting user password: {0}").format(str(e)))


@frappe.whitelist()
def get_user_roles():
    """Get available user roles"""
    try:
        roles = [
            {"value": "admin", "label": "Admin"},
            {"value": "teacher", "label": "Teacher"},
            {"value": "parent", "label": "Parent"},
            {"value": "registrar", "label": "Registrar"},
            {"value": "admission", "label": "Admission"},
            {"value": "bos", "label": "Board of Studies"},
            {"value": "principal", "label": "Principal"},
            {"value": "service", "label": "Service"},
            {"value": "superadmin", "label": "Super Admin"},
            {"value": "technical", "label": "Technical"},
            {"value": "marcom", "label": "Marketing Communications"},
            {"value": "hr", "label": "Human Resources"},
            {"value": "bod", "label": "Board of Directors"},
            {"value": "user", "label": "User"},
            {"value": "librarian", "label": "Librarian"}
        ]
        
        return {
            "status": "success",
            "roles": roles
        }
        
    except Exception as e:
        frappe.log_error(f"Get user roles error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user roles: {0}").format(str(e)))


@frappe.whitelist()
def get_user_dashboard_stats():
    """Get user dashboard statistics"""
    try:
        stats = {
            "total_users": frappe.db.count("User"),
            "total_profiles": frappe.db.count("ERP User Profile"),
            "active_users": frappe.db.count("ERP User Profile", {"active": 1}),
            "disabled_users": frappe.db.count("ERP User Profile", {"disabled": 1}),
            "enabled_users": frappe.db.count("User", {"enabled": 1}),
            "microsoft_users": frappe.db.count("ERP User Profile", {"provider": "microsoft"}),
            "apple_users": frappe.db.count("ERP User Profile", {"provider": "apple"}),
            "local_users": frappe.db.count("ERP User Profile", {"provider": "local"})
        }
        
        # Users by role
        role_stats = frappe.db.sql("""
            SELECT user_role, COUNT(*) as count
            FROM `tabERP User Profile`
            GROUP BY user_role
            ORDER BY count DESC
        """, as_dict=True)
        
        stats["users_by_role"] = {role["user_role"] or "user": role["count"] for role in role_stats}
        
        # Users by department
        dept_stats = frappe.db.sql("""
            SELECT department, COUNT(*) as count
            FROM `tabERP User Profile`
            WHERE department IS NOT NULL AND department != ''
            GROUP BY department
            ORDER BY count DESC
            LIMIT 10
        """, as_dict=True)
        
        stats["users_by_department"] = {dept["department"]: dept["count"] for dept in dept_stats}
        
        # Recent logins (last 7 days)
        from datetime import datetime, timedelta
        week_ago = datetime.now() - timedelta(days=7)
        
        recent_logins = frappe.db.count("ERP User Profile", {
            "last_login": [">=", week_ago]
        })
        
        stats["recent_logins"] = recent_logins
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        frappe.log_error(f"Get user dashboard stats error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user dashboard stats: {0}").format(str(e)))