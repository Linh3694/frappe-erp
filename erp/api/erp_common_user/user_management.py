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
        
        # Loại bỏ các user có email đuôi @parent.wellspring.edu.vn (tài khoản phụ huynh)
        where_conditions.append("u.email NOT LIKE '%@parent.wellspring.edu.vn'")
        
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
        
        if role:
            where_conditions.append(
                f"u.name IN (SELECT parent FROM `tabHas Role` WHERE role = {frappe.db.escape(role)} AND parenttype = 'User')"
            )
        
        where_clause = " AND ".join(where_conditions)
        
        # Debug logging
        frappe.logger().info(f"=== GET USERS DEBUG ===")
        frappe.logger().info(f"Active parameter: {active}")
        frappe.logger().info(f"WHERE clause: {where_clause}")
        frappe.logger().info(f"Limit: {limit}, Offset: {offset}")
        
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
                NULL as last_active
            FROM 
                `tabUser` u
            WHERE 
                {where_clause}
            ORDER BY 
                u.modified DESC
            LIMIT {limit} OFFSET {offset}
        """, as_dict=True)
        
        frappe.logger().info(f"Query returned {len(users)} users")
        
        # Add custom fields if they exist
        for user in users:
            try:
                user_doc = frappe.get_cached_doc("User", user.email)
                for field in ["username", "employee_code", "job_title", "department", "designation", "provider", "last_login", "last_active"]:
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
def update_user(user_data=None):
    """Update existing user"""
    try:
        # Read from multiple sources: function arg, form_dict, or request.json
        if not user_data:
            # Try form_dict first
            user_data = frappe.form_dict.get('user_data')
            
            # Try request.json if still not found
            if not user_data and hasattr(frappe.request, 'json') and frappe.request.json:
                user_data = frappe.request.json.get('user_data')
        
        # Validate user_data exists
        if not user_data:
            frappe.throw(_("User data is required"))
        
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
        # Loại trừ các user có email đuôi @parent.wellspring.edu.vn (tài khoản phụ huynh)
        exclude_parent_condition = "email NOT LIKE '%@parent.wellspring.edu.vn'"
        
        stats = {
            "total_users": frappe.db.sql(f"""
                SELECT COUNT(*) FROM `tabUser` 
                WHERE user_type = 'System User' AND {exclude_parent_condition}
            """)[0][0],
            "enabled_users": frappe.db.sql(f"""
                SELECT COUNT(*) FROM `tabUser` 
                WHERE user_type = 'System User' AND enabled = 1 AND {exclude_parent_condition}
            """)[0][0],
            "disabled_users": frappe.db.sql(f"""
                SELECT COUNT(*) FROM `tabUser` 
                WHERE user_type = 'System User' AND enabled = 0 AND {exclude_parent_condition}
            """)[0][0],
        }
        
        # Add custom field stats if they exist
        try:
            if frappe.db.has_column("User", "provider"):
                stats.update({
                    "microsoft_users": frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tabUser` 
                        WHERE user_type = 'System User' AND provider = 'microsoft' AND {exclude_parent_condition}
                    """)[0][0],
                    "apple_users": frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tabUser` 
                        WHERE user_type = 'System User' AND provider = 'apple' AND {exclude_parent_condition}
                    """)[0][0],
                    "local_users": frappe.db.sql(f"""
                        SELECT COUNT(*) FROM `tabUser` 
                        WHERE user_type = 'System User' AND (provider = 'local' OR provider = '' OR provider IS NULL) AND {exclude_parent_condition}
                    """)[0][0],
                })
        except:
            stats.update({
                "microsoft_users": 0,
                "apple_users": 0, 
                "local_users": stats["total_users"]
            })
        
        # Users by role (loại trừ tài khoản phụ huynh)
        role_stats = frappe.db.sql(f"""
            SELECT r.role, COUNT(*) as count
            FROM `tabHas Role` r
            INNER JOIN `tabUser` u ON r.parent = u.name
            WHERE u.user_type = 'System User'
            AND u.enabled = 1
            AND u.email NOT LIKE '%@parent.wellspring.edu.vn'
            GROUP BY r.role
            ORDER BY count DESC
        """, as_dict=True)
        
        stats["role_distribution"] = role_stats
        
        # Users by department (if custom field exists, loại trừ tài khoản phụ huynh)
        dept_stats = []
        try:
            if frappe.db.has_column("User", "department"):
                dept_stats = frappe.db.sql(f"""
                    SELECT department, COUNT(*) as count
                    FROM `tabUser`
                    WHERE user_type = 'System User'
                    AND department IS NOT NULL AND department != ''
                    AND {exclude_parent_condition}
                    GROUP BY department
                    ORDER BY count DESC
                    LIMIT 10
                """, as_dict=True)
        except:
            pass
            
        stats["department_distribution"] = dept_stats
        
        # Recent activity (users created in last 7 days, loại trừ tài khoản phụ huynh)
        from datetime import datetime, timedelta
        week_ago = datetime.now() - timedelta(days=7)
        
        recent_users = frappe.db.sql(f"""
            SELECT COUNT(*) FROM `tabUser`
            WHERE user_type = 'System User' 
            AND creation >= %s
            AND {exclude_parent_condition}
        """, (week_ago,))[0][0]
        
        stats["recent_new_users"] = recent_users
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        frappe.log_error(f"Get user stats error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user statistics: {0}").format(str(e)))


@frappe.whitelist()
def get_user_roles(user_email=None):
    """Get roles for a specific user"""
    try:
        # Read from request args or form_dict (for GET and POST requests)
        if not user_email:
            all_params = {}
            if hasattr(frappe.request, 'args') and frappe.request.args:
                all_params.update(frappe.request.args.to_dict())
            if frappe.form_dict:
                all_params.update(frappe.form_dict)
            user_email = all_params.get('user_email')
        
        if not user_email:
            frappe.throw(_("User email is required"))
        
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
def assign_user_roles(user_email=None, roles=None):
    """Assign roles to user"""
    try:
        # Read from form_dict or request.json if not provided
        if not user_email:
            user_email = frappe.form_dict.get('user_email')
            if not user_email and hasattr(frappe.request, 'json') and frappe.request.json:
                user_email = frappe.request.json.get('user_email')
        
        if not roles:
            roles = frappe.form_dict.get('roles')
            if not roles and hasattr(frappe.request, 'json') and frappe.request.json:
                roles = frappe.request.json.get('roles')
        
        if not user_email:
            frappe.throw(_("User email is required"))
        
        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))
        
        if isinstance(roles, str):
            roles = json.loads(roles)
        
        # Filter out system roles that are automatically added by Frappe
        # These roles are not stored in Has Role table but returned by frappe.get_roles()
        system_roles = ["All", "Guest"]
        roles = [r for r in roles if r not in system_roles]
        
        # Validate that roles list is not empty (should have at least some roles)
        if not roles:
            frappe.throw(_("At least one role is required"))
        
        user_doc = frappe.get_doc("User", user_email)
        
        # Remove existing roles first
        user_doc.set("roles", [])
        
        # Add new roles - use append directly to avoid any filtering by add_roles
        for role in roles:
            # Check if role exists before adding
            if frappe.db.exists("Role", role):
                user_doc.append("roles", {"role": role})
            else:
                frappe.log_error(f"Role '{role}' does not exist, skipping", "User Management")
        
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        
        # Return the actual roles after save
        final_roles = frappe.get_roles(user_email)
        
        return {
            "status": "success",
            "message": _("Roles assigned successfully"),
            "user_email": user_email,
            "roles": final_roles
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
        
        # Loại bỏ các user có email đuôi @parent.wellspring.edu.vn (tài khoản phụ huynh)
        where_conditions.append("email NOT LIKE '%@parent.wellspring.edu.vn'")
        
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


@frappe.whitelist()
def get_user_activity(user_email=None, activity_type="all", page=1, limit=20):
    """
    Lịch sử hoạt động gộp: Activity Log (đăng nhập), Access Log, Version, Comment.

    Args:
        user_email: Email User cần xem
        activity_type: all | login | access | changes | comments
        page, limit: phân trang
    """
    try:
        # Đọc tham số từ query string (GET)
        if hasattr(frappe.request, "args") and frappe.request.args:
            ad = frappe.request.args.to_dict()
            user_email = ad.get("user_email") or user_email
            activity_type = ad.get("activity_type", activity_type)
            page = int(ad.get("page", page) or 1)
            limit = int(ad.get("limit", limit) or 20)

        page = max(1, int(page or 1))
        limit = min(100, max(1, int(limit or 20)))

        if not user_email or not str(user_email).strip():
            frappe.throw(_("user_email is required"))

        user_email = str(user_email).strip()

        if not frappe.db.exists("User", user_email):
            frappe.throw(_("User not found"))

        # Chỉ System Manager (hoặc Administrator) xem lịch sử user khác
        if frappe.session.user == "Guest":
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        session_roles = frappe.get_roles(frappe.session.user)
        if "System Manager" not in session_roles and frappe.session.user != "Administrator":
            frappe.throw(_("Not permitted"), frappe.PermissionError)

        activity_type = (activity_type or "all").lower()
        if activity_type not in ("all", "login", "access", "changes", "comments"):
            activity_type = "all"

        offset = (page - 1) * limit
        items = []

        # Khi chỉ một loại: phân trang đúng qua limit_start / db.count
        def _single_pagination(doctype, filters):
            return frappe.db.count(doctype, filters)

        # 1. Activity Log — đăng nhập / đăng xuất / impersonate
        if activity_type in ("all", "login"):
            al_filters = {"user": user_email}
            if activity_type == "all":
                fetch_n = min(2000, max(limit * page * 2, limit * 2))
                al_logs = frappe.get_all(
                    "Activity Log",
                    filters=al_filters,
                    fields=[
                        "subject",
                        "content",
                        "communication_date",
                        "operation",
                        "status",
                        "ip_address",
                    ],
                    order_by="communication_date desc",
                    limit_page_length=fetch_n,
                )
            else:
                total_al = _single_pagination("Activity Log", al_filters)
                al_logs = frappe.get_all(
                    "Activity Log",
                    filters=al_filters,
                    fields=[
                        "subject",
                        "content",
                        "communication_date",
                        "operation",
                        "status",
                        "ip_address",
                    ],
                    order_by="communication_date desc",
                    limit_start=offset,
                    limit_page_length=limit,
                )
            for row in al_logs:
                content = row.get("content") or ""
                items.append(
                    {
                        "type": "login",
                        "subject": row.get("subject") or "",
                        "detail": content[:500] if content else "",
                        "timestamp": row.get("communication_date"),
                        "ip_address": row.get("ip_address") or "",
                        "status": row.get("status") or "",
                        "operation": row.get("operation") or "",
                        "reference_doctype": None,
                        "reference_name": None,
                    }
                )
            if activity_type == "login":
                total_count = _single_pagination("Activity Log", al_filters)
                return {
                    "status": "success",
                    "activities": items,
                    "pagination": {
                        "current_page": page,
                        "total_count": total_count,
                        "limit": limit,
                        "has_more": offset + limit < total_count,
                    },
                }

        # 2. Access Log — export, in, tải
        if activity_type in ("all", "access"):
            ac_filters = {"user": user_email}
            if activity_type == "all":
                fetch_n = min(2000, max(limit * page * 2, limit * 2))
                access_logs = frappe.get_all(
                    "Access Log",
                    filters=ac_filters,
                    fields=[
                        "export_from",
                        "reference_document",
                        "timestamp",
                        "report_name",
                        "file_type",
                        "method",
                    ],
                    order_by="timestamp desc",
                    limit_page_length=fetch_n,
                )
            else:
                access_logs = frappe.get_all(
                    "Access Log",
                    filters=ac_filters,
                    fields=[
                        "export_from",
                        "reference_document",
                        "timestamp",
                        "report_name",
                        "file_type",
                        "method",
                    ],
                    order_by="timestamp desc",
                    limit_start=offset,
                    limit_page_length=limit,
                )
            for row in access_logs:
                detail_parts = []
                if row.get("export_from"):
                    detail_parts.append(_("From: {0}").format(row.get("export_from")))
                if row.get("report_name"):
                    detail_parts.append(_("Report: {0}").format(row.get("report_name")))
                if row.get("reference_document"):
                    detail_parts.append(_("Document: {0}").format(row.get("reference_document")))
                items.append(
                    {
                        "type": "access",
                        "subject": row.get("export_from") or _("Access / Export"),
                        "detail": " | ".join(detail_parts),
                        "timestamp": row.get("timestamp"),
                        "ip_address": None,
                        "status": None,
                        "operation": None,
                        "reference_doctype": None,
                        "reference_name": row.get("reference_document"),
                    }
                )
            if activity_type == "access":
                total_count = _single_pagination("Access Log", ac_filters)
                return {
                    "status": "success",
                    "activities": items,
                    "pagination": {
                        "current_page": page,
                        "total_count": total_count,
                        "limit": limit,
                        "has_more": offset + limit < total_count,
                    },
                }

        # 3. Version — chỉnh sửa tài liệu (owner = người tạo bản ghi version)
        if activity_type in ("all", "changes"):
            ver_filters = {"owner": user_email}
            if activity_type == "all":
                fetch_n = min(2000, max(limit * page * 2, limit * 2))
                versions = frappe.get_all(
                    "Version",
                    filters=ver_filters,
                    fields=["ref_doctype", "docname", "creation"],
                    order_by="creation desc",
                    limit_page_length=fetch_n,
                )
            else:
                versions = frappe.get_all(
                    "Version",
                    filters=ver_filters,
                    fields=["ref_doctype", "docname", "creation"],
                    order_by="creation desc",
                    limit_start=offset,
                    limit_page_length=limit,
                )
            for row in versions:
                items.append(
                    {
                        "type": "change",
                        "subject": _("Edited {0}").format(row.get("ref_doctype") or ""),
                        "detail": row.get("docname") or "",
                        "timestamp": row.get("creation"),
                        "ip_address": None,
                        "status": None,
                        "operation": None,
                        "reference_doctype": row.get("ref_doctype"),
                        "reference_name": row.get("docname"),
                    }
                )
            if activity_type == "changes":
                total_count = _single_pagination("Version", ver_filters)
                return {
                    "status": "success",
                    "activities": items,
                    "pagination": {
                        "current_page": page,
                        "total_count": total_count,
                        "limit": limit,
                        "has_more": offset + limit < total_count,
                    },
                }

        # 4. Comment
        if activity_type in ("all", "comments"):
            cm_filters = {"comment_email": user_email}
            if activity_type == "all":
                fetch_n = min(2000, max(limit * page * 2, limit * 2))
                comments = frappe.get_all(
                    "Comment",
                    filters=cm_filters,
                    fields=[
                        "comment_type",
                        "subject",
                        "content",
                        "reference_doctype",
                        "reference_name",
                        "creation",
                    ],
                    order_by="creation desc",
                    limit_page_length=fetch_n,
                )
            else:
                comments = frappe.get_all(
                    "Comment",
                    filters=cm_filters,
                    fields=[
                        "comment_type",
                        "subject",
                        "content",
                        "reference_doctype",
                        "reference_name",
                        "creation",
                    ],
                    order_by="creation desc",
                    limit_start=offset,
                    limit_page_length=limit,
                )
            for row in comments:
                content = row.get("content") or ""
                subj = row.get("subject") or row.get("comment_type") or _("Comment")
                items.append(
                    {
                        "type": "comment",
                        "subject": subj,
                        "detail": content[:500] if content else "",
                        "timestamp": row.get("creation"),
                        "ip_address": None,
                        "status": None,
                        "operation": None,
                        "reference_doctype": row.get("reference_doctype"),
                        "reference_name": row.get("reference_name"),
                    }
                )
            if activity_type == "comments":
                total_count = _single_pagination("Comment", cm_filters)
                return {
                    "status": "success",
                    "activities": items,
                    "pagination": {
                        "current_page": page,
                        "total_count": total_count,
                        "limit": limit,
                        "has_more": offset + limit < total_count,
                    },
                }

        # activity_type == "all": gộp 4 nguồn đã thu thập vào items, sort, cắt trang
        def _ts_key(it):
            t = it.get("timestamp")
            return str(t) if t else ""

        items.sort(key=_ts_key, reverse=True)

        total_count = len(items)
        paginated = items[offset : offset + limit]

        return {
            "status": "success",
            "activities": paginated,
            "pagination": {
                "current_page": page,
                "total_count": total_count,
                "limit": limit,
                "has_more": offset + limit < total_count,
            },
        }

    except frappe.PermissionError:
        raise
    except Exception as e:
        frappe.log_error(f"get_user_activity error: {str(e)}", "User Management")
        frappe.throw(_("Error getting user activity: {0}").format(str(e)))