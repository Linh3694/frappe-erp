# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from erp.utils.api_response import success_response, error_response


@frappe.whitelist(allow_guest=False)
def get_current_user_full():
    """
    Get full current user information including all available fields
    """
    try:
        user_email = frappe.session.user
        
        if not user_email or user_email == 'Guest':
            return error_response(
                message="User not authenticated",
                code="USER_NOT_AUTHENTICATED"
            )
        
        # Get full user document
        user_doc = frappe.get_doc('User', user_email)
        
        # Get user roles
        user_roles = frappe.get_roles(user_email)
        
        # Helper function to safely get field value
        def safe_get_field(doc, fieldname, default=None):
            try:
                value = getattr(doc, fieldname, default)
                # Convert None to empty string for display fields
                if value is None and fieldname in ['first_name', 'last_name', 'full_name']:
                    return ""
                return value
            except:
                return default

        # Extract essential fields safely
        user_data = {
            # Core identification
            "email": safe_get_field(user_doc, 'email', ''),
            "name": safe_get_field(user_doc, 'name', ''),
            
            # Name fields
            "first_name": safe_get_field(user_doc, 'first_name', ''),
            "last_name": safe_get_field(user_doc, 'last_name', ''),
            "full_name": safe_get_field(user_doc, 'full_name', ''),
            "username": safe_get_field(user_doc, 'username', ''),
            
            # Profile fields
            "user_image": safe_get_field(user_doc, 'user_image', ''),
            "avatar_url": safe_get_field(user_doc, 'user_image', ''),  # Alias for compatibility
            "mobile_no": safe_get_field(user_doc, 'mobile_no', ''),
            "phone": safe_get_field(user_doc, 'phone', ''),
            "location": safe_get_field(user_doc, 'location', ''),
            "bio": safe_get_field(user_doc, 'bio', ''),
            "language": safe_get_field(user_doc, 'language', 'vi'),
            "time_zone": safe_get_field(user_doc, 'time_zone', 'Asia/Ho_Chi_Minh'),
            
            # Status fields
            "enabled": safe_get_field(user_doc, 'enabled', 1),
            "user_type": safe_get_field(user_doc, 'user_type', 'System User'),
            
            # Roles and permissions
            "roles": user_roles,
            "active": True,  # Default to active if enabled
            
            # Provider info (for compatibility)
            "provider": "frappe",
        }
        
        # Add employee info if exists (optional)
        try:
            # Check if Employee table exists and is accessible
            if frappe.db.table_exists("Employee"):
                # Use get_all for more reliable query with better error handling
                employee_records = frappe.get_all(
                    "Employee",
                    filters={"user_id": user_email},
                    fields=["employee_name", "designation", "department", "company", "name", "employee_number"],
                    limit=1
                )

                if employee_records and len(employee_records) > 0:
                    emp = employee_records[0]
                    user_data.update({
                        "employee_name": emp.get("employee_name") or "",
                        "designation": emp.get("designation") or "",
                        "job_title": emp.get("designation") or "",  # Alias
                        "department": emp.get("department") or "",
                        "company": emp.get("company") or "",
                        "employee_code": emp.get("employee_number") or emp.get("name") or "",
                        "employee_id": emp.get("name") or "",
                        "employee_number": emp.get("employee_number") or ""
                    })
                    frappe.logger().info(f"Employee data found for {user_email}: employee_code={emp.get('employee_number') or emp.get('name')}")
                else:
                    frappe.logger().debug(f"No employee record found for {user_email}")
            else:
                frappe.logger().warning("Employee table does not exist or is not accessible")

        except Exception as e:
            frappe.logger().error(f"Error retrieving employee data for {user_email}: {str(e)}")
            # Don't fail the entire request, just log the error
        
        # Add campus roles analysis
        campus_roles = [role for role in user_roles if role.startswith("Campus ")]
        user_data["campus_roles"] = campus_roles
        user_data["has_campus_access"] = len(campus_roles) > 0
        
        frappe.logger().info(f"Full user data retrieved for {user_email}")

        return success_response(
            data=user_data,
            message="User data retrieved successfully"
        )
        
    except frappe.DoesNotExistError:
        return error_response(
            message="User not found",
            code="USER_NOT_FOUND"
        )
    except Exception as e:
        frappe.logger().error(f"Error getting full user data: {str(e)}")
        import traceback
        frappe.logger().error(traceback.format_exc())

        return error_response(
            message=f"Error retrieving user data: {str(e)}",
            code="USER_DATA_RETRIEVAL_ERROR"
        )
