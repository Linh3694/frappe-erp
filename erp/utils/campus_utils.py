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

        frappe.logger().info(f"Processing campus_role: '{campus_role}' -> campus_title: '{campus_title}'")

        # Try to find matching SIS Campus by title
        campus_id = find_campus_id_by_title(campus_title)

        if campus_id:
            frappe.logger().info(f"Found campus_id: '{campus_id}' for title: '{campus_title}'")
            return campus_id

        # If not found, create default campus_id from role index
        # This matches frontend logic: campus-1, campus-2, etc.
        campus_index = campus_roles.index(campus_role) + 1
        default_campus_id = f"campus-{campus_index}"
        frappe.logger().warning(f"SIS Campus not found for title '{campus_title}', using default: '{default_campus_id}'")

        return default_campus_id
        
    except Exception as e:
        return None


def find_campus_id_by_title(campus_title):
    """
    Find campus_id by matching title_vn or title_en
    Handles both exact match and partial match
    """
    try:
        frappe.logger().info(f"Searching for SIS Campus with title: '{campus_title}'")

        # Get all campuses for debugging
        all_campuses = frappe.db.get_all("SIS Campus", fields=["name", "title_vn", "title_en"])
        frappe.logger().info(f"All available SIS Campuses: {all_campuses}")

        # Extract campus name from role (remove "Campus " prefix)
        campus_name = campus_title.replace("Campus ", "").strip()
        frappe.logger().info(f"Extracted campus name: '{campus_name}'")

        # Try to find by title_vn first (exact match)
        campus_id = frappe.db.get_value(
            "SIS Campus",
            {"title_vn": campus_name},
            "name"
        )

        if campus_id:
            frappe.logger().info(f"Found SIS Campus by title_vn exact match: '{campus_id}'")
            return campus_id

        # Try to find by title_en (exact match)
        campus_id = frappe.db.get_value(
            "SIS Campus",
            {"title_en": campus_name},
            "name"
        )

        if campus_id:
            frappe.logger().info(f"Found SIS Campus by title_en exact match: '{campus_id}'")
            return campus_id

        # Try partial match for title_vn (contains campus_name)
        for campus in all_campuses:
            if campus_name.lower() in campus.get("title_vn", "").lower():
                frappe.logger().info(f"Found SIS Campus by title_vn partial match: '{campus['name']}'")
                return campus['name']

        # Try partial match for title_en (contains campus_name)
        for campus in all_campuses:
            if campus_name.lower() in campus.get("title_en", "").lower():
                frappe.logger().info(f"Found SIS Campus by title_en partial match: '{campus['name']}'")
                return campus['name']

        frappe.logger().warning(f"No SIS Campus found with title: '{campus_title}' (campus_name: '{campus_name}')")
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
        # Try to resolve user from JWT Bearer token (mobile apps)
        try:
            auth_header = frappe.get_request_header("Authorization") or ""
            token_candidate = None
            if auth_header.lower().startswith("bearer "):
                token_candidate = auth_header.split(" ", 1)[1].strip()
            if token_candidate:
                from erp.api.erp_common_user.auth import verify_jwt_token  # Lazy import to avoid cycles
                payload = verify_jwt_token(token_candidate)
                jwt_user_email = (
                    payload.get("email")
                    or payload.get("user")
                    or payload.get("sub")
                    if payload
                    else None
                )
                if jwt_user_email and frappe.db.exists("User", jwt_user_email):
                    user = jwt_user_email
        except Exception:
            pass
        frappe.logger().info(f"get_current_campus_from_context called for user: {user}")

        # First try to get from request context (if passed from frontend)
        campus_id = frappe.local.form_dict.get("campus_id")
        frappe.logger().info(f"Campus_id from form_dict: '{campus_id}'")

        if campus_id:
            # Validate user has access to this campus
            if validate_user_campus_access(user, campus_id):
                frappe.logger().info(f"User {user} has access to campus {campus_id}, returning it")
                return campus_id
            else:
                frappe.logger().warning(f"User {user} does not have access to campus {campus_id}")

        # Try to get from query parameters (for GET requests)
        try:
            if hasattr(frappe.request, 'args') and frappe.request.args:
                campus_id_from_args = frappe.request.args.get('campus_id')
                frappe.logger().info(f"Campus_id from query args: '{campus_id_from_args}'")
                if campus_id_from_args and validate_user_campus_access(user, campus_id_from_args):
                    frappe.logger().info(f"User {user} has access to campus from query args {campus_id_from_args}, returning it")
                    return campus_id_from_args
        except Exception as e:
            frappe.logger().error(f"Error getting campus_id from query args: {str(e)}")

        # Try to get from filters parameter (for GET requests with filters)
        filters = frappe.local.form_dict.get("filters")
        if filters:
            try:
                if isinstance(filters, str):
                    import json
                    filters = json.loads(filters)
                if isinstance(filters, dict) and "campus_id" in filters:
                    campus_id_from_filters = filters["campus_id"]
                    frappe.logger().info(f"Campus_id from filters: '{campus_id_from_filters}'")
                    if validate_user_campus_access(user, campus_id_from_filters):
                        frappe.logger().info(f"User {user} has access to campus from filters {campus_id_from_filters}, returning it")
                        return campus_id_from_filters
            except Exception as e:
                frappe.logger().error(f"Error parsing filters for campus_id: {str(e)}")

        # Try to get from request body (for POST/PUT requests)
        if frappe.request and frappe.request.data:
            try:
                import json
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
                campus_id_from_body = data.get('campus_id')
                if campus_id_from_body:
                    frappe.logger().info(f"Campus_id from request body: '{campus_id_from_body}'")
                    if validate_user_campus_access(user, campus_id_from_body):
                        frappe.logger().info(f"User {user} has access to campus from body {campus_id_from_body}, returning it")
                        return campus_id_from_body
            except Exception as e:
                frappe.logger().error(f"Error parsing request body for campus_id: {str(e)}")

        # Fall back to user's default campus from roles
        frappe.logger().info(f"No campus_id in context, falling back to user roles for user: {user}")
        role_based_campus = get_campus_id_from_user_roles(user)
        frappe.logger().info(f"Role-based campus for user {user}: '{role_based_campus}'")
        # Final fallback: default active campus for mobile
        return role_based_campus or "campus-1"

    except Exception as e:
        frappe.logger().error(f"Error getting current campus from context: {str(e)}")
        return None
