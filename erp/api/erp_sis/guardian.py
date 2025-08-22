import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_guardians(page=1, limit=20):
    """Get all guardians with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        
        frappe.logger().info(f"get_all_guardians called with page: {page}, limit: {limit}")
        
        # Calculate offset for pagination
        offset = (page - 1) * limit
            
        frappe.logger().info(f"Query pagination: offset={offset}, limit={limit}")
        
        guardians = frappe.get_all(
            "CRM Guardian",
            fields=[
                "name",
                "guardian_id",
                "guardian_name",
                "phone_number",
                "email",
                "creation",
                "modified"
            ],
            order_by="guardian_name asc",
            limit_start=offset,
            limit_page_length=limit
        )
        
        frappe.logger().info(f"Found {len(guardians)} guardians")
        
        # Get total count
        total_count = frappe.db.count("CRM Guardian")
        total_pages = (total_count + limit - 1) // limit
        
        frappe.logger().info(f"Total count: {total_count}, Total pages: {total_pages}")
        
        return {
            "success": True,
            "data": guardians,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Guardians fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardians: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching guardians: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)  
def get_guardian_data():
    """Get a specific guardian by ID"""
    try:
        # Get parameters from form_dict
        guardian_id = frappe.local.form_dict.get("guardian_id")
        
        frappe.logger().info(f"get_guardian_data called - guardian_id: {guardian_id}")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        
        if not guardian_id:
            return {
                "success": False,
                "data": None,
                "message": "Guardian ID is required"
            }
        
        # Get guardian document
        guardian = frappe.get_doc("CRM Guardian", guardian_id)
        
        if not guardian:
            return {
                "success": False,
                "data": None,
                "message": "Guardian not found"
            }
        
        # Convert to dict
        guardian_data = {
            "name": guardian.name,
            "guardian_id": guardian.guardian_id,
            "guardian_name": guardian.guardian_name,
            "phone_number": guardian.phone_number,
            "email": guardian.email,
            "creation": guardian.creation.isoformat() if guardian.creation else None,
            "modified": guardian.modified.isoformat() if guardian.modified else None
        }
        
        return {
            "success": True,
            "data": guardian_data,
            "message": "Guardian data fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching guardian data: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"Error fetching guardian data: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_guardian():
    """Create a new guardian"""
    try:
        # Get data from form_dict
        data = frappe.local.form_dict
        
        frappe.logger().info(f"create_guardian called with data: {data}")
        
        # Validate required fields
        if not data.get("guardian_id"):
            return {
                "success": False,
                "data": None,
                "message": "Guardian ID is required"
            }
        
        if not data.get("guardian_name"):
            return {
                "success": False,
                "data": None,
                "message": "Guardian Name is required"
            }
        
        # Create new guardian document
        guardian = frappe.new_doc("CRM Guardian")
        guardian.guardian_id = data.get("guardian_id")
        guardian.guardian_name = data.get("guardian_name")
        guardian.phone_number = data.get("phone_number", "")
        guardian.email = data.get("email", "")
        
        # Save the document
        guardian.insert()
        
        frappe.logger().info(f"Guardian created successfully: {guardian.name}")
        
        return {
            "success": True,
            "data": {
                "name": guardian.name,
                "guardian_id": guardian.guardian_id,
                "guardian_name": guardian.guardian_name,
                "phone_number": guardian.phone_number,
                "email": guardian.email
            },
            "message": "Guardian created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating guardian: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"Error creating guardian: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def update_guardian():
    """Update an existing guardian"""
    try:
        # Get data from form_dict
        data = frappe.local.form_dict
        
        frappe.logger().info(f"update_guardian called with data: {data}")
        
        guardian_id = data.get("guardian_id")
        if not guardian_id:
            return {
                "success": False,
                "data": None,
                "message": "Guardian ID is required"
            }
        
        # Get existing guardian document
        guardian = frappe.get_doc("CRM Guardian", guardian_id)
        
        if not guardian:
            return {
                "success": False,
                "data": None,
                "message": "Guardian not found"
            }
        
        # Update fields
        if "guardian_name" in data:
            guardian.guardian_name = data["guardian_name"]
        if "phone_number" in data:
            guardian.phone_number = data["phone_number"]
        if "email" in data:
            guardian.email = data["email"]
        
        # Save the document
        guardian.save()
        
        frappe.logger().info(f"Guardian updated successfully: {guardian.name}")
        
        return {
            "success": True,
            "data": {
                "name": guardian.name,
                "guardian_id": guardian.guardian_id,
                "guardian_name": guardian.guardian_name,
                "phone_number": guardian.phone_number,
                "email": guardian.email
            },
            "message": "Guardian updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating guardian: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"Error updating guardian: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_guardian():
    """Delete a guardian"""
    try:
        # Get guardian ID from form_dict
        guardian_id = frappe.local.form_dict.get("guardian_id")
        
        frappe.logger().info(f"delete_guardian called - guardian_id: {guardian_id}")
        
        if not guardian_id:
            return {
                "success": False,
                "data": None,
                "message": "Guardian ID is required"
            }
        
        # Get guardian document
        guardian = frappe.get_doc("CRM Guardian", guardian_id)
        
        if not guardian:
            return {
                "success": False,
                "data": None,
                "message": "Guardian not found"
            }
        
        # Delete the document
        frappe.delete_doc("CRM Guardian", guardian_id)
        
        frappe.logger().info(f"Guardian deleted successfully: {guardian_id}")
        
        return {
            "success": True,
            "data": None,
            "message": "Guardian deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting guardian: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"Error deleting guardian: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def bulk_delete_guardians():
    """Bulk delete multiple guardians"""
    try:
        # Get guardian IDs from form_dict
        guardian_ids = frappe.local.form_dict.get("guardian_ids")
        
        frappe.logger().info(f"bulk_delete_guardians called - guardian_ids: {guardian_ids}")
        
        if not guardian_ids:
            return {
                "success": False,
                "data": None,
                "message": "Guardian IDs are required"
            }
        
        if not isinstance(guardian_ids, list):
            guardian_ids = [guardian_ids]
        
        deleted_count = 0
        errors = []
        
        for guardian_id in guardian_ids:
            try:
                # Check if guardian exists
                if frappe.db.exists("CRM Guardian", guardian_id):
                    frappe.delete_doc("CRM Guardian", guardian_id)
                    deleted_count += 1
                else:
                    errors.append(f"Guardian {guardian_id} not found")
            except Exception as e:
                errors.append(f"Error deleting guardian {guardian_id}: {str(e)}")
        
        frappe.logger().info(f"Bulk delete completed. Deleted: {deleted_count}, Errors: {len(errors)}")
        
        return {
            "success": True,
            "data": {
                "deleted_count": deleted_count,
                "error_count": len(errors),
                "errors": errors
            },
            "message": f"Successfully deleted {deleted_count} guardians"
        }
        
    except Exception as e:
        frappe.log_error(f"Error in bulk delete guardians: {str(e)}")
        return {
            "success": False,
            "data": None,
            "message": f"Error in bulk delete guardians: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def search_guardians():
    """Search guardians by name, ID, phone or email"""
    try:
        # Get search parameters
        search_term = frappe.local.form_dict.get("search_term", "")
        page = int(frappe.local.form_dict.get("page", 1))
        limit = int(frappe.local.form_dict.get("limit", 20))
        
        frappe.logger().info(f"search_guardians called - search_term: {search_term}, page: {page}, limit: {limit}")
        
        # Calculate offset for pagination
        offset = (page - 1) * limit
        
        # Build search filters
        filters = []
        if search_term:
            # Search in multiple fields
            filters.append(["guardian_name", "like", f"%{search_term}%"])
            filters.append(["guardian_id", "like", f"%{search_term}%"])
            filters.append(["phone_number", "like", f"%{search_term}%"])
            filters.append(["email", "like", f"%{search_term}%"])
        
        # Get guardians with search filters
        if search_term:
            # Use OR condition for search
            guardians = frappe.get_all(
                "CRM Guardian",
                fields=[
                    "name",
                    "guardian_id",
                    "guardian_name",
                    "phone_number",
                    "email",
                    "creation",
                    "modified"
                ],
                filters=filters,
                order_by="guardian_name asc",
                limit_start=offset,
                limit_page_length=limit
            )
        else:
            # No search term, get all
            guardians = frappe.get_all(
                "CRM Guardian",
                fields=[
                    "name",
                    "guardian_id",
                    "guardian_name",
                    "phone_number",
                    "email",
                    "creation",
                    "modified"
                ],
                order_by="guardian_name asc",
                limit_start=offset,
                limit_page_length=limit
            )
        
        # Get total count for pagination
        total_count = frappe.db.count("CRM Guardian")
        total_pages = (total_count + limit - 1) // limit
        
        frappe.logger().info(f"Search completed. Found: {len(guardians)}, Total: {total_count}")
        
        return {
            "success": True,
            "data": guardians,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Guardian search completed successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error searching guardians: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error searching guardians: {str(e)}"
        }
