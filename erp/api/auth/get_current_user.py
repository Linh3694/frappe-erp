# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _


@frappe.whitelist(allow_guest=False)
def get_current_user_full():
    """
    Get full current user information including all available fields
    """
    try:
        user_email = frappe.session.user
        
        if not user_email or user_email == 'Guest':
            return {
                "success": False,
                "message": "User not authenticated"
            }
        
        # Get full user document
        user_doc = frappe.get_doc('User', user_email)
        
        # Get user roles
        user_roles = frappe.get_roles(user_email)
        
        # Helper function to safely convert datetime to ISO format
        def safe_datetime_to_iso(dt_value):
            if not dt_value:
                return None
            try:
                if hasattr(dt_value, 'isoformat'):
                    return dt_value.isoformat()
                else:
                    # If it's already a string, return as-is
                    return str(dt_value)
            except:
                return None

        # Extract all relevant fields
        user_data = {
            "email": user_doc.email,
            "name": user_doc.name,
            "first_name": user_doc.first_name,
            "last_name": user_doc.last_name,
            "full_name": user_doc.full_name,
            "username": user_doc.username,
            "language": user_doc.language,
            "time_zone": user_doc.time_zone,
            "user_image": user_doc.user_image,
            "avatar_url": user_doc.user_image,  # Alias for compatibility
            "mobile_no": user_doc.mobile_no,
            "phone": user_doc.phone,
            "location": user_doc.location,
            "bio": user_doc.bio,
            "interest": user_doc.interest,
            "banner_image": user_doc.banner_image,
            "desk_theme": user_doc.desk_theme,
            "mute_sounds": user_doc.mute_sounds,
            "enabled": user_doc.enabled,
            "user_type": user_doc.user_type,
            "roles": user_roles,
            "creation": safe_datetime_to_iso(user_doc.creation),
            "modified": safe_datetime_to_iso(user_doc.modified),
            "last_login": safe_datetime_to_iso(user_doc.last_login),
            "last_active": safe_datetime_to_iso(user_doc.last_active),
            "login_after": safe_datetime_to_iso(user_doc.login_after),
            "login_before": safe_datetime_to_iso(user_doc.login_before),
        }
        
        # Add employee info if exists
        try:
            employee = frappe.db.get_value(
                "Employee", 
                {"user_id": user_email}, 
                ["employee_name", "designation", "department", "company", "employee", "cell_number", "personal_email"]
            )
            
            if employee:
                user_data.update({
                    "employee_name": employee[0],
                    "designation": employee[1], 
                    "job_title": employee[1],  # Alias
                    "department": employee[2],
                    "company": employee[3],
                    "employee_code": employee[4],
                    "employee_id": employee[4],  # Alias
                    "cell_number": employee[5],
                    "personal_email": employee[6]
                })
        except Exception as e:
            frappe.logger().debug(f"No employee record found for {user_email}: {str(e)}")
        
        # Add custom fields if they exist
        custom_fields = {}
        for field in user_doc.meta.fields:
            if field.fieldname.startswith('custom_'):
                try:
                    custom_fields[field.fieldname] = getattr(user_doc, field.fieldname)
                except:
                    pass
        
        if custom_fields:
            user_data["custom_fields"] = custom_fields
        
        # Add campus roles analysis
        campus_roles = [role for role in user_roles if role.startswith("Campus ")]
        user_data["campus_roles"] = campus_roles
        user_data["has_campus_access"] = len(campus_roles) > 0
        
        frappe.logger().info(f"Full user data retrieved for {user_email}")
        
        return {
            "success": True,
            "data": user_data,
            "message": "User data retrieved successfully"
        }
        
    except frappe.DoesNotExistError:
        return {
            "success": False,
            "message": "User not found"
        }
    except Exception as e:
        frappe.logger().error(f"Error getting full user data: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())
        
        return {
            "success": False,
            "message": f"Error retrieving user data: {str(e)}"
        }
