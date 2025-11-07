"""
User Sync API for Microservices

Endpoints để sync user data cho các microservices (ticket-service, etc.)
Kết hợp với webhook system để real-time sync.
"""

import frappe
from frappe import _


@frappe.whitelist(allow_guest=False)
def get_all_enabled_users():
    """
    Get all enabled users for microservices sync
    
    Returns:
        dict: {
            "success": bool,
            "data": list of user dicts,
            "count": int,
            "user_types": dict with breakdown by user type
        }
    
    Usage:
        GET/POST: /api/method/erp.api.erp_common_user.user_sync.get_all_enabled_users
    """
    try:
        # Query all enabled users với tất cả fields cần thiết
        users = frappe.db.sql("""
            SELECT 
                name,
                email,
                full_name,
                first_name,
                middle_name,
                last_name,
                user_image,
                enabled,
                disabled,
                location,
                department,
                job_title,
                designation,
                employee_code,
                microsoft_id,
                docstatus,
                user_type,
                creation,
                modified
            FROM `tabUser`
            WHERE enabled = 1
            AND user_type IN ('System User', 'Website User')
            AND name NOT IN ('Guest', 'Administrator')
            ORDER BY name ASC
        """, as_dict=True)
        
        # Count by user type
        user_type_stats = {
            'System User': 0,
            'Website User': 0,
            'Other': 0
        }
        
        for user in users:
            user_type = user.get('user_type', 'Other')
            if user_type in user_type_stats:
                user_type_stats[user_type] += 1
            else:
                user_type_stats['Other'] += 1
        
        frappe.logger().info(f"[User Sync] Fetched {len(users)} enabled users")
        
        return {
            "success": True,
            "data": users,
            "count": len(users),
            "user_types": user_type_stats,
            "message": f"Successfully fetched {len(users)} enabled users"
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_all_enabled_users: {str(e)}", "User Sync API Error")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to fetch users"
        }


@frappe.whitelist(allow_guest=False)
def get_user_by_email(email):
    """
    Get single user by email for microservices
    
    Args:
        email (str): User email
        
    Returns:
        dict: User data or error
        
    Usage:
        POST: /api/method/erp.api.erp_common_user.user_sync.get_user_by_email
        Body: {"email": "user@example.com"}
    """
    try:
        if not email:
            return {
                "success": False,
                "error": "Email is required"
            }
        
        user = frappe.db.get_value(
            "User",
            {"email": email, "enabled": 1},
            [
                "name", "email", "full_name", "first_name", "middle_name", "last_name",
                "user_image", "enabled", "disabled", "location", "department",
                "job_title", "designation", "employee_code", "microsoft_id",
                "docstatus", "user_type", "creation", "modified"
            ],
            as_dict=True
        )
        
        if not user:
            return {
                "success": False,
                "error": f"User not found or disabled: {email}"
            }
        
        return {
            "success": True,
            "data": user
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_user_by_email: {str(e)}", "User Sync API Error")
        return {
            "success": False,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def get_users_paginated(start=0, page_length=100, filters=None):
    """
    Get paginated users for large datasets
    
    Args:
        start (int): Offset
        page_length (int): Number of users per page
        filters (dict): Additional filters (optional)
        
    Returns:
        dict: Paginated user data
        
    Usage:
        POST: /api/method/erp.api.erp_common_user.user_sync.get_users_paginated
        Body: {"start": 0, "page_length": 100}
    """
    try:
        start = int(start) if start else 0
        page_length = int(page_length) if page_length else 100
        
        # Base query conditions
        conditions = [
            "enabled = 1",
            "user_type IN ('System User', 'Website User')",
            "name NOT IN ('Guest', 'Administrator')"
        ]
        
        # Additional filters if provided
        if filters:
            if isinstance(filters, str):
                import json
                filters = json.loads(filters)
            
            if filters.get('department'):
                conditions.append(f"department = '{filters['department']}'")
            if filters.get('user_type'):
                conditions.append(f"user_type = '{filters['user_type']}'")
        
        where_clause = " AND ".join(conditions)
        
        # Get total count
        total_count = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabUser`
            WHERE {where_clause}
        """, as_dict=True)[0]['count']
        
        # Get paginated data
        users = frappe.db.sql(f"""
            SELECT 
                name, email, full_name, first_name, middle_name, last_name,
                user_image, enabled, disabled, location, department,
                job_title, designation, employee_code, microsoft_id,
                docstatus, user_type, creation, modified
            FROM `tabUser`
            WHERE {where_clause}
            ORDER BY name ASC
            LIMIT {page_length} OFFSET {start}
        """, as_dict=True)
        
        return {
            "success": True,
            "data": users,
            "count": len(users),
            "total_count": total_count,
            "start": start,
            "page_length": page_length,
            "has_more": (start + page_length) < total_count
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_users_paginated: {str(e)}", "User Sync API Error")
        return {
            "success": False,
            "error": str(e)
        }


@frappe.whitelist(allow_guest=False)
def get_sync_stats():
    """
    Get user sync statistics for monitoring
    
    Returns:
        dict: Statistics about users in system
        
    Usage:
        GET: /api/method/erp.api.erp_common_user.user_sync.get_sync_stats
    """
    try:
        stats = frappe.db.sql("""
            SELECT 
                user_type,
                enabled,
                COUNT(*) as count
            FROM `tabUser`
            WHERE name NOT IN ('Guest', 'Administrator')
            GROUP BY user_type, enabled
        """, as_dict=True)
        
        # Format stats
        formatted_stats = {
            'enabled': {
                'System User': 0,
                'Website User': 0,
                'Other': 0
            },
            'disabled': {
                'System User': 0,
                'Website User': 0,
                'Other': 0
            },
            'total_enabled': 0,
            'total_disabled': 0,
            'total': 0
        }
        
        for stat in stats:
            user_type = stat['user_type'] if stat['user_type'] in ['System User', 'Website User'] else 'Other'
            count = stat['count']
            status = 'enabled' if stat['enabled'] == 1 else 'disabled'
            
            formatted_stats[status][user_type] += count
            formatted_stats[f'total_{status}'] += count
            formatted_stats['total'] += count
        
        return {
            "success": True,
            "stats": formatted_stats,
            "timestamp": frappe.utils.now()
        }
        
    except Exception as e:
        frappe.log_error(f"Error in get_sync_stats: {str(e)}", "User Sync API Error")
        return {
            "success": False,
            "error": str(e)
        }

