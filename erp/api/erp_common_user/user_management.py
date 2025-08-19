"""
User Management API
Handles user CRUD operations, role management, etc.
Updated to work only with Frappe User core (no ERP User Profile dependency)
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
        active: Filter by active status (maps to enabled)
    """
    try:
        # Read parameters from URL or function args
        all_params = frappe.request.args.to_dict() if hasattr(frappe.request, 'args') else {}
        page = int(all_params.get('page', page) or 1)
        limit = int(all_params.get('limit', limit) or 20)
        search = all_params.get('search', search)
        role = all_params.get('role', role)
        department = all_params.get('department', department)
        active = all_params.get('active', active)
        
        # Build filters
        filters = {"user_type": "System User"}  # Only system users
        
        if active is not None:
            filters["enabled"] = int(active)
        
        # Build search conditions
        search_conditions = []
        if search:
            search_conditions = [
                ["User", "email", "like", f"%{search}%"],
                ["User", "full_name", "like", f"%{search}%"]
            ]
            # Add custom field searches if they exist
            try:
                if frappe.db.has_column("User", "username"):
                    search_conditions.append(["User", "username", "like", f"%{search}%"])
                if frappe.db.has_column("User", "employee_code"):
                    search_conditions.append(["User", "employee_code", "like", f"%{search}%"])
            except:
                pass
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Build WHERE clause
        where_conditions = ["u.user_type = 'System User'"]
        
        if active is not None:
            where_conditions.append(f"u.enabled = {int(active)}")
            
        if department:
            where_conditions.append(f"u.department = '{department}'")
            
        if search:
            search_clause = f"(u.email LIKE '%{search}%' OR u.full_name LIKE '%{search}%'"
            try:
                if frappe.db.has_column("User", "username"):
                    search_clause += f" OR u.username LIKE '%{search}%'"
                if frappe.db.has_column("User", "employee_code"):
                    search_clause += f" OR u.employee_code LIKE '%{search}%'"
            except:
                pass
            search_clause += ")"
            where_conditions.append(search_clause)
        
        where_clause = " AND ".join(where_conditions)
        
        # Get users with role information
        users = frappe.db.sql(f"""
            SELECT 
                u.name,
                u.email as id,
                u.email,
                u.full_name,
                u.first_name,
                u.last_name,
                u.enabled as active,
                u.enabled,
                u.creation as user_created,
                u.user_image,
                '' as username,
                '' as employee_code,
                '' as job_title,
                '' as department,
                '' as user_role,
                'local' as provider,
                NULL as last_login,
                NULL as last_seen
            FROM 
                `tabUser` u
            WHERE 
                {where_clause}
            ORDER BY 
                u.modified DESC
            LIMIT {limit} OFFSET {offset}
        """, as_dict=True)
        
        # Add custom fields if they exist
        for user in users:
            try:
                user_doc = frappe.get_cached_doc("User", user.email)
                for field in ["username", "employee_code", "job_title", "department", "designation", "provider", "last_login", "last_seen"]:
                    if hasattr(user_doc, field):
                        user[field] = getattr(user_doc, field) or ""
                        
                # Map designation to user_role for backward compatibility
                if hasattr(user_doc, "designation"):
                    user["user_role"] = getattr(user_doc, "designation") or "user"
                else:
                    user["user_role"] = "user"
                    
            except:
                pass
        
        # Get total count
        total_count = frappe.db.sql(f"""
            SELECT COUNT(*)
            FROM `tabUser` u
            WHERE {where_clause}
        """)[0][0]
        
        # Get role information for each user
        for user in users:
            try:
                user["roles"] = frappe.get_roles(user.email) or []
            except:
                user["roles"] = []
        
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "status": "success",
            "users": users,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Get users error: {str(e)}", "User Management")
        frappe.throw(_("Error getting users: {0}").format(str(e)))


@frappe.whitelist()
def create_user(user_data):
    """Create new user"""
    try:
        if isinstance(user_data, str):
            user_data = json.loads(user_data)
        
        # Check required fields
        if not user_data.get("email"):
            frappe.throw(_("Email is required"))
        
        # Check if user already exists
        if frappe.db.exists("User", user_data["email"]):
            frappe.throw(_("User with email {0} already exists").format(user_data["email"]))
        
        # Create User document
        user_doc = frappe.get_doc({
            "doctype": "User",
            "email": user_data["email"],
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "full_name": user_data.get("full_name", f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()),
            "enabled": user_data.get("enabled", 1),
            "send_welcome_email": user_data.get("send_welcome_email", 0),
            "user_type": "System User",
        })
        
        # Add custom fields if they exist and are provided
        custom_fields = [
            "username", "employee_code", "job_title", "department", "designation",
            "provider", "microsoft_id", "apple_id"
        ]
        
        for field in custom_fields:
            if field in user_data and hasattr(user_doc, field):
                setattr(user_doc, field, user_data[field])
        
        # Set password if provided
        if user_data.get("new_password"):
            user_doc.new_password = user_data["new_password"]
        
        user_doc.flags.ignore_permissions = True
        user_doc.insert()
        
        # Assign roles if provided
        if user_data.get("roles"):
            for role in user_data["roles"]:
                user_doc.add_roles(role)
        
        return {
            "status": "success",
            "message": _("User created successfully"),
            "user": {
                "email": user_doc.email,
                "full_name": user_doc.full_name,
                "enabled": user_doc.enabled
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Create user error: {str(e)}", "User Management")
        frappe.throw(_("Error creating user: {0}").format(str(e)))


@frappe.whitelist()
def update_user(user_data):
    """Update existing user"""
    try:
        if isinstance(user_data, str):
            user_data = json.loads(user_data)
        
        user_email = user_data.get("email")
        if not user_email:
            frappe.throw(_("Email is required"))
        
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Get user document
        user_doc = frappe.get_doc("User", user_email)
        
        # Update basic fields
        updateable_fields = [
            "first_name", "last_name", "full_name", "enabled", "user_image"
        ]
        
        for field in updateable_fields:
            if field in user_data:
                setattr(user_doc, field, user_data[field])
        
        # Update custom fields if they exist
        custom_fields = [
            "username", "employee_code", "job_title", "department", "designation",
            "provider", "microsoft_id", "apple_id"
        ]
        
        for field in custom_fields:
            if field in user_data and hasattr(user_doc, field):
                setattr(user_doc, field, user_data[field])
        
        # Update password if provided
        if user_data.get("new_password"):
            user_doc.new_password = user_data["new_password"]
        
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        return {
            "status": "success",
            "message": _("User updated successfully"),
            "user": {
                "email": user_doc.email,
                "full_name": user_doc.full_name,
                "enabled": user_doc.enabled
            }
        }
        
    except Exception as e:
        frappe.log_error(f"Update user error: {str(e)}", "User Management")
        frappe.throw(_("Error updating user: {0}").format(str(e)))


@frappe.whitelist()
def delete_user(user_email):
    """Delete user"""
    try:
        if not user_email:
            frappe.throw(_("User email is required"))
        
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Don't allow deleting current user
        if user_email == frappe.session.user:
            frappe.throw(_("Cannot delete your own account"))
        
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
def toggle_user_status(user_email, enabled):
    """Toggle user enabled/disabled status"""
    try:
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        user_doc = frappe.get_doc("User", user_email)
        user_doc.enabled = int(enabled)
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        status_text = "enabled" if int(enabled) else "disabled"
        
        return {
            "status": "success",
            "message": _("User {0} successfully").format(status_text)
        }
        
    except Exception as e:
        frappe.log_error(f"Toggle user status error: {str(e)}", "User Management")
        frappe.throw(_("Error toggling user status: {0}").format(str(e)))


@frappe.whitelist()
def send_password_reset(user_email):
    """Send password reset email to user"""
    try:
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        # Use Frappe's built-in password reset
        from frappe.utils.password import update_password_reset_token
        user_doc = frappe.get_doc("User", user_email)
        token = update_password_reset_token(user_doc)
        
        # Send reset email using auth.py function
        from erp.api.erp_common_user.auth import send_password_reset_email
        success = send_password_reset_email(user_email, token)
        
        if success:
            return {
                "status": "success",
                "message": _("Password reset email sent to {0}").format(user_email)
            }
        else:
            frappe.throw(_("Error sending password reset email"))
            
    except Exception as e:
        frappe.log_error(f"Send password reset error: {str(e)}", "User Management")
        frappe.throw(_("Error sending password reset: {0}").format(str(e)))


@frappe.whitelist()
def get_user_stats():
    """Get user management statistics"""
    try:
        stats = {
            "total_users": frappe.db.count("User", {"user_type": "System User"}),
            "enabled_users": frappe.db.count("User", {"user_type": "System User", "enabled": 1}),
            "disabled_users": frappe.db.count("User", {"user_type": "System User", "enabled": 0}),
        }
        
        # Add custom field stats if they exist
        try:
            if frappe.db.has_column("User", "provider"):
                stats.update({
                    "microsoft_users": frappe.db.count("User", {"user_type": "System User", "provider": "microsoft"}),
                    "apple_users": frappe.db.count("User", {"user_type": "System User", "provider": "apple"}),
                    "local_users": frappe.db.count("User", {"user_type": "System User", "provider": ["in", ["local", ""]]}),
                })
        except:
            stats.update({
                "microsoft_users": 0,
                "apple_users": 0, 
                "local_users": stats["total_users"]
            })
        
        # Users by role
        role_stats = frappe.db.sql("""
            SELECT r.role, COUNT(*) as count
            FROM `tabHas Role` r
            INNER JOIN `tabUser` u ON r.parent = u.name
            WHERE u.user_type = 'System User'
            AND u.enabled = 1
            GROUP BY r.role
            ORDER BY count DESC
        """, as_dict=True)
        
        stats["role_distribution"] = role_stats
        
        # Users by department (if custom field exists)
        dept_stats = []
        try:
            if frappe.db.has_column("User", "department"):
                dept_stats = frappe.db.sql("""
                    SELECT department, COUNT(*) as count
                    FROM `tabUser`
                    WHERE user_type = 'System User'
                    AND department IS NOT NULL AND department != ''
                    GROUP BY department
                    ORDER BY count DESC
                    LIMIT 10
                """, as_dict=True)
        except:
            pass
            
        stats["department_distribution"] = dept_stats
        
        # Recent activity (users created in last 7 days)
        from datetime import datetime, timedelta
        week_ago = datetime.now() - timedelta(days=7)
        
        recent_users = frappe.db.count("User", {
            "user_type": "System User",
            "creation": [">=", week_ago]
        })
        
        stats["recent_new_users"] = recent_users
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        frappe.log_error(f"Get user stats error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user statistics: {0}").format(str(e)))


@frappe.whitelist()
def get_user_roles(user_email):
    """Get roles for a specific user"""
    try:
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        roles = frappe.get_roles(user_email) or []
        
        return {
            "status": "success",
            "user_email": user_email,
            "roles": roles
        }
        
    except Exception as e:
        frappe.log_error(f"Get user roles error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user roles: {0}").format(str(e)))


@frappe.whitelist()
def assign_user_roles(user_email, roles):
    """Assign roles to user"""
    try:
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        if isinstance(roles, str):
            roles = json.loads(roles)
        
        user_doc = frappe.get_doc("User", user_email)
        
        # Remove existing roles first
        user_doc.set("roles", [])
        
        # Add new roles
        for role in roles:
            user_doc.add_roles(role)
        
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        return {
            "status": "success",
            "message": _("Roles assigned successfully"),
            "user_email": user_email,
            "roles": roles
        }
        
    except Exception as e:
        frappe.log_error(f"Assign user roles error: {str(e)}", "User Management")
        frappe.throw(_("Error assigning user roles: {0}").format(str(e)))


@frappe.whitelist()
def get_available_roles():
    """Get list of available roles"""
    try:
        roles = frappe.get_all("Role", 
            filters={"disabled": 0},
            fields=["name", "role_name"],
            order_by="role_name"
        )
        
        return {
            "status": "success",
            "roles": roles
        }
        
    except Exception as e:
        frappe.log_error(f"Get available roles error: {str(e)}", "User Management")
        frappe.throw(_("Error getting available roles: {0}").format(str(e)))


@frappe.whitelist()
def bulk_update_users(user_emails, update_data):
    """Bulk update multiple users"""
    try:
        if isinstance(user_emails, str):
            user_emails = json.loads(user_emails)
        if isinstance(update_data, str):
            update_data = json.loads(update_data)
            
        if not user_emails:
            frappe.throw(_("No users selected"))
        
        updated_count = 0
        failed_count = 0
        
        for user_email in user_emails:
            try:
                if frappe.db.exists("User", user_email):
                    user_doc = frappe.get_doc("User", user_email)
                    
                    # Update allowed fields
                    for field, value in update_data.items():
                        if hasattr(user_doc, field) and field in ["enabled", "department", "designation", "job_title"]:
                            setattr(user_doc, field, value)
                    
                    user_doc.flags.ignore_permissions = True
                    user_doc.save()
                    updated_count += 1
                    
            except Exception as e:
                failed_count += 1
                frappe.log_error(f"Bulk update error for {user_email}: {str(e)}", "Bulk User Update")
        
        return {
            "status": "success",
            "message": _("Bulk update completed"),
            "updated_count": updated_count,
            "failed_count": failed_count
        }
        
    except Exception as e:
        frappe.log_error(f"Bulk update users error: {str(e)}", "User Management")
        frappe.throw(_("Error bulk updating users: {0}").format(str(e)))


@frappe.whitelist()
def export_users(filters=None):
    """Export users to CSV format"""
    try:
        if isinstance(filters, str):
            filters = json.loads(filters)
        
        # Build WHERE clause
        where_conditions = ["user_type = 'System User'"]
        
        if filters:
            if filters.get("enabled") is not None:
                where_conditions.append(f"enabled = {int(filters['enabled'])}")
            if filters.get("department"):
                where_conditions.append(f"department = '{filters['department']}'")
        
        where_clause = " AND ".join(where_conditions)
        
        # Get user data
        users = frappe.db.sql(f"""
            SELECT 
                email,
                full_name,
                first_name,
                last_name,
                enabled,
                creation,
                modified
            FROM `tabUser`
            WHERE {where_clause}
            ORDER BY full_name
        """, as_dict=True)
        
        # Add custom fields if they exist
        for user in users:
            try:
                user_doc = frappe.get_cached_doc("User", user.email)
                for field in ["username", "employee_code", "job_title", "department", "provider"]:
                    if hasattr(user_doc, field):
                        user[field] = getattr(user_doc, field) or ""
            except:
                pass
        
        return {
            "status": "success",
            "users": users,
            "total_count": len(users)
        }
        
    except Exception as e:
        frappe.log_error(f"Export users error: {str(e)}", "User Management")
        frappe.throw(_("Error exporting users: {0}").format(str(e)))