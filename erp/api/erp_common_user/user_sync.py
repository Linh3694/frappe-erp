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
        # Get all fields available in User doctype
        user_meta = frappe.get_meta("User")
        available_fields = [field.fieldname for field in user_meta.fields]
        
        # Standard fields we want
        desired_fields = [
            'name', 'email', 'full_name', 'first_name', 'middle_name', 'last_name',
            'user_image', 'enabled', 'disabled', 'location', 'department',
            'job_title', 'designation', 'employee_code', 'microsoft_id',
            'user_type', 'creation', 'modified'
        ]
        
        # Only query fields that exist
        fields_to_query = ['name']  # name is always available
        for field in desired_fields:
            if field in available_fields or field in ['name', 'owner', 'creation', 'modified']:
                fields_to_query.append(field)
        
        # Remove duplicates
        fields_to_query = list(set(fields_to_query))
        
        # Use frappe.get_all for safe querying
        users = frappe.get_all(
            "User",
            filters={
                "enabled": 1,
                "user_type": ["in", ["System User", "Website User"]],
                "name": ["not in", ["Guest", "Administrator"]]
            },
            fields=fields_to_query,
            order_by="name asc"
        )
        
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
        
        user = frappe.get_all(
            "User",
            filters={"email": email, "enabled": 1},
            fields=["*"],  # Get all available fields
            limit=1
        )
        
        if not user:
            return {
                "success": False,
                "error": f"User not found or disabled: {email}"
            }
        
        user = user[0]  # Get first result
        
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
        
        # Build filters
        frappe_filters = {
            "enabled": 1,
            "user_type": ["in", ["System User", "Website User"]],
            "name": ["not in", ["Guest", "Administrator"]]
        }
        
        # Additional filters if provided
        if filters:
            if isinstance(filters, str):
                import json
                filters = json.loads(filters)
            
            if filters.get('department'):
                frappe_filters['department'] = filters['department']
            if filters.get('user_type'):
                frappe_filters['user_type'] = filters['user_type']
        
        # Get total count
        total_count = frappe.db.count("User", frappe_filters)
        
        # Get paginated data
        users = frappe.get_all(
            "User",
            filters=frappe_filters,
            fields=["*"],
            order_by="name asc",
            start=start,
            page_length=page_length
        )
        
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
        # Get user counts by type and status
        all_users = frappe.get_all(
            "User",
            filters={"name": ["not in", ["Guest", "Administrator"]]},
            fields=["user_type", "enabled"]
        )
        
        stats = []
        # Count manually
        from collections import Counter
        for (user_type, enabled), count in Counter((u.get('user_type'), u.get('enabled')) for u in all_users).items():
            stats.append({
                'user_type': user_type,
                'enabled': enabled,
                'count': count
            })
        
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

