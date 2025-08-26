# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def get_campus_id_from_user_roles(user_email=None):
    """
    Extract campus_id from user roles
    Campus roles format: "Campus {title_en}" or "Campus {title_vn}"
    """
    try:
        if not user_email:
            user_email = frappe.session.user             
        # Get user roles
        user_roles = frappe.get_roles(user_email)     
        # Find campus roles (roles that start with "Campus ")
        campus_roles = [role for role in user_roles if role.startswith("Campus ")] 
        if not campus_roles:
            return None
        
        # Check if user has multiple campus roles
        if len(campus_roles) > 1:
            frappe.logger().info(f"User {user_email} has multiple campus roles: {campus_roles}")

            # Try to get user's current selected campus first
            current_campus = get_current_user_campus()
            if current_campus:
                frappe.logger().info(f"User {user_email} has selected campus: {current_campus}")
                return current_campus

            # If no current campus selected, use first campus role
            frappe.logger().info(f"Using first campus role for user {user_email} with multiple roles")

        # Extract campus title from role (remove "Campus " prefix)
        campus_role = campus_roles[0]
        campus_title = campus_role.replace("Campus ", "")
        
        # Try to find matching SIS Campus by title
        campus_id = find_campus_id_by_title(campus_title)
        
        if campus_id:
            return campus_id
        
        # If not found, create default campus_id from role index
        # This matches frontend logic: campus-1, campus-2, etc.
        campus_index = campus_roles.index(campus_role) + 1
        default_campus_id = f"campus-{campus_index}"
        
        return default_campus_id
        
    except Exception as e:
        return None


def find_campus_id_by_title(campus_title):
    """
    Find campus_id by matching title_vn or title_en
    """
    try:
        # Try to find by title_vn first
        campus_id = frappe.db.get_value(
            "SIS Campus", 
            {"title_vn": campus_title}, 
            "name"
        )
        
        if campus_id:
            return campus_id
        
        # Try to find by title_en
        campus_id = frappe.db.get_value(
            "SIS Campus", 
            {"title_en": campus_title}, 
            "name"
        )
        
        if campus_id:
            return campus_id
        
        frappe.logger().info(f"No SIS Campus found with title: {campus_title}")
        return None
        
    except Exception as e:
        frappe.logger().error(f"Error finding campus by title: {str(e)}")
        return None


def get_all_campus_ids_from_user_roles(user_email=None):
    """
    Get all campus_ids that user has access to based on roles
    """
    try:
        if not user_email:
            user_email = frappe.session.user

        # Get user roles
        user_roles = frappe.get_roles(user_email)

        # Find all campus roles
        campus_roles = [role for role in user_roles if role.startswith("Campus ")]

        campus_ids = []
        for i, campus_role in enumerate(campus_roles):
            campus_title = campus_role.replace("Campus ", "")
            campus_id = find_campus_id_by_title(campus_title)

            if campus_id:
                campus_ids.append(campus_id)
            else:
                # Use default format
                campus_ids.append(f"campus-{i + 1}")

        frappe.logger().info(f"User {user_email} has access to campuses: {campus_ids}")
        return campus_ids

    except Exception as e:
        frappe.logger().error(f"Error getting all campus IDs from user roles: {str(e)}")
        return []


def get_campus_filter_for_all_user_campuses(user_email=None):
    """
    Get campus filter that includes all campuses user has access to
    Useful for queries that should show data from all user's campuses
    """
    try:
        if not user_email:
            user_email = frappe.session.user

        campus_ids = get_all_campus_ids_from_user_roles(user_email)

        if not campus_ids:
            return {"campus_id": ""}  # Return impossible condition

        if len(campus_ids) == 1:
            return {"campus_id": campus_ids[0]}
        else:
            return {"campus_id": ["in", campus_ids]}

    except Exception as e:
        frappe.logger().error(f"Error getting campus filter for all user campuses: {str(e)}")
        return {"campus_id": ""}


def validate_user_campus_access(user_email, campus_id):
    """
    Check if user has access to specific campus_id
    """
    try:
        user_campus_ids = get_all_campus_ids_from_user_roles(user_email)
        return campus_id in user_campus_ids
        
    except Exception as e:
        frappe.logger().error(f"Error validating user campus access: {str(e)}")
        return False


def get_current_campus_from_context():
    """
    Get current campus_id from current user context
    This replaces the old logic of getting campus directly from User field
    """
    try:
        user = frappe.session.user
        
        # First try to get from request context (if passed from frontend)
        campus_id = frappe.local.form_dict.get("campus_id")
        
        if campus_id:
            # Validate user has access to this campus
            if validate_user_campus_access(user, campus_id):
                return campus_id
            else:
                frappe.logger().warning(f"User {user} does not have access to campus {campus_id}")
        
        # Fall back to user's default campus from roles
        return get_campus_id_from_user_roles(user)
        
    except Exception as e:
        frappe.logger().error(f"Error getting current campus from context: {str(e)}")
        return None
