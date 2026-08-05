"""
User Management API
Handles user CRUD operations, role management, etc.
Updated to work only with Frappe User core (no ERP User Profile dependency)
"""

import frappe
from frappe import _
from datetime import datetime
import json

from erp.utils.search import (
    build_search_condition,
    order_rows_by_names,
    sort_by_relevance,
    sql_unaccent,
    strip_accents,
)


# Cột được phép lọc — bám đúng các cột FilterBuilder khai báo ở UserListV2.
# Text -> chuẩn search chung (bỏ dấu, token, đầu từ). Exact/bool -> khớp giá trị lưu.
_USER_FILTER_TEXT_COLUMNS = ("full_name", "email", "department", "job_title")
_USER_FILTER_EXACT_COLUMNS = ("provider",)
_USER_FILTER_BOOL_COLUMNS = ("enabled",)
# Cột luôn có trên tabUser (không cần has_column) — phần còn lại là custom field.
_USER_CORE_COLUMNS = {"full_name", "email", "enabled"}


def _user_has_column(fieldname):
    """True nếu `tabUser` thực sự có cột (custom field có thể chưa cài trên site)."""
    if fieldname in _USER_CORE_COLUMNS:
        return True
    try:
        return bool(frappe.db.has_column("User", fieldname))
    except Exception:
        return False


def _user_search_fields():
    """Cột dùng cho thanh tìm kiếm — đồng bộ với placeholder ở FE (tên, email, phòng ban…)."""
    fields = ["full_name", "email"]
    for optional in ("username", "employee_code", "department", "job_title"):
        if _user_has_column(optional):
            fields.append(optional)
    return fields


def _text_filter_condition(column, operator, value):
    """Điều kiện SQL cho cột text — cùng ngữ nghĩa `erp/utils/search.py` (bỏ dấu, đầu từ).

    Dùng IFNULL để bản ghi rỗng vẫn tham gia được vế phủ định (NULL LIKE ... = NULL).
    """
    col_expr = f"IFNULL(u.`{column}`, '')"
    if operator in ("contains", "not_contains"):
        frag, params = build_search_condition([col_expr], value)
        if not frag:
            return None, []
        return (f"NOT {frag}" if operator == "not_contains" else frag), params

    normalized_col = sql_unaccent(col_expr)
    needle = strip_accents(value)
    if operator == "is":
        return f"{normalized_col} = %s", [needle]
    if operator == "is_not":
        return f"{normalized_col} != %s", [needle]
    if operator == "starts_with":
        return f"{normalized_col} LIKE %s", [f"{needle}%"]
    if operator == "ends_with":
        return f"{normalized_col} LIKE %s", [f"%{needle}"]
    return None, []


def _exact_filter_condition(column, operator, value):
    """Điều kiện SQL cho cột dropdown (enum/link) — khớp CHÍNH XÁC trên giá trị lưu."""
    col_expr = f"IFNULL(u.`{column}`, '')"
    op_map = {"is": "=", "is_not": "!=", "contains": "LIKE", "not_contains": "NOT LIKE",
              "starts_with": "LIKE", "ends_with": "LIKE"}
    if operator not in op_map:
        return None, []
    if operator in ("contains", "not_contains"):
        cmp_value = f"%{value}%"
    elif operator == "starts_with":
        cmp_value = f"{value}%"
    elif operator == "ends_with":
        cmp_value = f"%{value}"
    else:
        cmp_value = value
    return f"{col_expr} {op_map[operator]} %s", [cmp_value]


def _parse_user_filters(raw):
    """FilterBuilder (JSON) -> (danh sách fragment SQL, params).

    Mỗi điều kiện FE: {"column", "operator", "value"} — AND giữa các điều kiện,
    khớp đúng ngữ nghĩa client ở `src/utils/filterUtils.ts`.
    """
    if not raw:
        return [], []
    try:
        conditions = frappe.parse_json(raw) if isinstance(raw, str) else raw
    except Exception:
        return [], []
    if not isinstance(conditions, list):
        return [], []

    fragments, params = [], []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        column = condition.get("column")
        operator = condition.get("operator")
        value = condition.get("value")
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if not column or not _user_has_column(column):
            continue

        if column in _USER_FILTER_BOOL_COLUMNS:
            truthy = 1 if str(value).lower() in ("1", "true", "yes") else 0
            fragments.append(f"IFNULL(u.`{column}`, 0) {'!=' if operator == 'is_not' else '='} %s")
            params.append(truthy)
            continue

        if column in _USER_FILTER_EXACT_COLUMNS:
            fragment, fragment_params = _exact_filter_condition(column, operator, value)
        elif column in _USER_FILTER_TEXT_COLUMNS:
            fragment, fragment_params = _text_filter_condition(column, operator, value)
        else:
            continue

        if fragment:
            fragments.append(f"({fragment})")
            params.extend(fragment_params)

    return fragments, params


def _provider_options(base_where, base_params):
    """Giá trị `provider` có thật trong tập user — cho dropdown lọc (không phụ thuộc trang)."""
    if not _user_has_column("provider"):
        return []
    try:
        rows = frappe.db.sql(
            f"SELECT DISTINCT u.provider FROM `tabUser` u WHERE {base_where} AND IFNULL(u.provider, '') != ''",
            base_params,
        )
    except Exception:
        return []
    return sorted({row[0] for row in rows if row and row[0]})


@frappe.whitelist()
def get_users(page=1, limit=20, search=None, role=None, department=None, active=None, filters=None):
    """
    Get users with filtering and pagination
    
    Args:
        page: Page number
        limit: Items per page
        search: Search term (name, email, username)
        role: Filter by role
        department: Filter by department  
        active: Filter by active status (maps to enabled)
        filters: JSON list điều kiện FilterBuilder [{column, operator, value}]
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
        filters = all_params.get('filters', filters)

        # Calculate offset
        offset = (page - 1) * limit

        # Build WHERE clause (parameterized — tránh SQL injection)
        where_conditions = ["u.user_type = 'System User'", "u.email NOT LIKE %s"]
        query_params = ["%@parent.wellspring.edu.vn"]

        if active is not None:
            where_conditions.append("u.enabled = %s")
            query_params.append(int(active))

        if department:
            where_conditions.append("u.department = %s")
            query_params.append(department)

        # Dropdown provider lấy trên toàn tập user (trước search/filter) để không đổi theo trang
        provider_options = _provider_options(" AND ".join(where_conditions), list(query_params))

        rank_fields = []
        if search:
            # token + bỏ dấu + đầu từ (đồng bộ mọi field)
            rank_fields = _user_search_fields()
            search_fields = [f"u.{f}" for f in rank_fields]
            search_frag, search_params = build_search_condition(search_fields, search)
            if search_frag:
                where_conditions.append(search_frag)
                query_params.extend(search_params)

        # Bộ lọc nâng cao từ FilterBuilder
        filter_frags, filter_params = _parse_user_filters(filters)
        where_conditions.extend(filter_frags)
        query_params.extend(filter_params)

        if role:
            where_conditions.append(
                "u.name IN (SELECT parent FROM `tabHas Role` WHERE role = %s AND parenttype = 'User')"
            )
            query_params.append(role)

        where_clause = " AND ".join(where_conditions)

        # Có search -> xếp hạng theo độ khớp trên TOÀN BỘ kết quả rồi mới cắt trang,
        # để trang 1 là người khớp nhất chứ không phải người sửa gần nhất.
        page_where, page_params, page_limit, ranked_page = (
            where_clause, list(query_params), f"LIMIT {limit} OFFSET {offset}", None
        )
        if search and rank_fields:
            matched = frappe.db.sql(
                f"SELECT u.name, {', '.join('u.' + f for f in rank_fields)} "
                f"FROM `tabUser` u WHERE {where_clause} ORDER BY u.modified DESC",
                query_params, as_dict=True,
            )
            ranked = [r["name"] for r in sort_by_relevance(matched, rank_fields, search)]
            ranked_page = ranked[offset:offset + limit]
            placeholders = ", ".join(["%s"] * len(ranked_page)) or "NULL"
            page_where, page_params, page_limit = f"u.name IN ({placeholders})", list(ranked_page), ""

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
                {page_where}
            ORDER BY
                u.modified DESC
            {page_limit}
        """, page_params, as_dict=True)

        if ranked_page is not None:
            users = order_rows_by_names(users, ranked_page)

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
        """, query_params)[0][0]
        
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
            },
            "filter_options": {
                "providers": provider_options
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

        # Đồng bộ User Permission với Role Campus * (CRM + Desk list view)
        from erp.sis.utils.campus_permissions import sync_user_campus_permissions_from_roles
        sync_user_campus_permissions_from_roles(user_email)
        
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

