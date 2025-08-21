# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, getdate
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_school_years():
    """Get all school years with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        school_years = frappe.get_all(
            "SIS School Year",
            fields=[
                "name",
                "title_vn",
                "title_en", 
                "start_date",
                "end_date",
                "is_enable",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="start_date desc"
        )
        
        return {
            "success": True,
            "data": school_years,
            "total_count": len(school_years),
            "message": "School years fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching school years: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching school years: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_school_year_by_id(school_year_id):
    """Get a specific school year by ID"""
    try:
        if not school_year_id:
            return {
                "success": False,
                "data": {},
                "message": "School Year ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": school_year_id,
            "campus_id": campus_id
        }
        
        school_year = frappe.get_doc("SIS School Year", filters)
        
        if not school_year:
            return {
                "success": False,
                "data": {},
                "message": "School year not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": school_year.name,
                "title_vn": school_year.title_vn,
                "title_en": school_year.title_en,
                "start_date": school_year.start_date,
                "end_date": school_year.end_date,
                "is_enable": school_year.is_enable,
                "campus_id": school_year.campus_id
            },
            "message": "School year fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching school year {school_year_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching school year: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_school_year(title_vn, title_en, start_date, end_date, is_enable=1):
    """Create a new school year - SIMPLE VERSION"""
    try:
        # Input validation
        if not title_vn or not start_date or not end_date:
            return {
                "success": False,
                "data": {},
                "message": "Title VN, start date and end date are required"
            }
        
        # Validate dates
        try:
            start_date = getdate(start_date)
            end_date = getdate(end_date)
            
            if start_date >= end_date:
                return {
                    "success": False,
                    "data": {},
                    "message": "Start date must be before end date"
                }
        except Exception:
            return {
                "success": False,
                "data": {},
                "message": "Invalid date format"
            }
        
        # Get campus from user context - simplified
        try:
            campus_id = get_current_campus_from_context()
        except Exception as e:
            frappe.logger().error(f"Error getting campus context: {str(e)}")
            campus_id = None
        
        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        # Check if school year title already exists for this campus
        existing = frappe.db.exists(
            "SIS School Year",
            {
                "title_vn": title_vn,
                "campus_id": campus_id
            }
        )
        
        if existing:
            return {
                "success": False,
                "data": {},
                "message": f"School year with title '{title_vn}' already exists"
            }
        
        # Create new school year - with detailed debugging
        frappe.logger().info(f"Creating SIS School Year with data: title_vn={title_vn}, title_en={title_en}, start_date={start_date}, end_date={end_date}, is_enable={is_enable}, campus_id={campus_id}")
        
        try:
            school_year_doc = frappe.get_doc({
                "doctype": "SIS School Year",
                "title_vn": title_vn,
                "title_en": title_en or "",  # Provide default empty string
                "start_date": start_date,
                "end_date": end_date,
                "is_enable": int(is_enable),
                "campus_id": campus_id
            })
            
            frappe.logger().info(f"School year doc created: {school_year_doc}")
            
            school_year_doc.insert()
            frappe.logger().info("School year doc inserted successfully")
            
            frappe.db.commit()
            frappe.logger().info("Database committed successfully")
            
        except Exception as doc_error:
            frappe.logger().error(f"Error creating/inserting school year doc: {str(doc_error)}")
            raise doc_error
        
        # Return the created data
        return {
            "success": True,
            "data": {
                "name": school_year_doc.name,
                "title_vn": school_year_doc.title_vn,
                "title_en": school_year_doc.title_en,
                "start_date": str(school_year_doc.start_date),
                "end_date": str(school_year_doc.end_date),
                "is_enable": school_year_doc.is_enable,
                "campus_id": school_year_doc.campus_id
            },
            "message": "School year created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating school year: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error creating school year: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def update_school_year(school_year_id, title_vn=None, title_en=None, start_date=None, end_date=None, is_enable=None):
    """Update an existing school year"""
    try:
        if not school_year_id:
            return {
                "success": False,
                "data": {},
                "message": "School Year ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            school_year_doc = frappe.get_doc("SIS School Year", school_year_id)
            
            # Check campus permission
            if school_year_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this school year"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "School year not found"
            }
        
        # Update fields if provided
        if title_vn and title_vn != school_year_doc.title_vn:
            # Check for duplicate school year title
            existing = frappe.db.exists(
                "SIS School Year",
                {
                    "title_vn": title_vn,
                    "campus_id": campus_id,
                    "name": ["!=", school_year_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"School year with title '{title_vn}' already exists"
                }
            school_year_doc.title_vn = title_vn
        
        if title_en and title_en != school_year_doc.title_en:
            school_year_doc.title_en = title_en
            
        if start_date and str(start_date) != str(school_year_doc.start_date):
            try:
                start_date = getdate(start_date)
                school_year_doc.start_date = start_date
            except Exception:
                return {
                    "success": False,
                    "data": {},
                    "message": "Invalid start date format"
                }
                
        if end_date and str(end_date) != str(school_year_doc.end_date):
            try:
                end_date = getdate(end_date)
                school_year_doc.end_date = end_date
            except Exception:
                return {
                    "success": False,
                    "data": {},
                    "message": "Invalid end date format"
                }
                
        # Validate date range after updates
        if school_year_doc.start_date >= school_year_doc.end_date:
            return {
                "success": False,
                "data": {},
                "message": "Start date must be before end date"
            }
            
        if is_enable is not None:
            school_year_doc.is_enable = int(is_enable)
        
        school_year_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": school_year_doc.name,
                "title_vn": school_year_doc.title_vn,
                "title_en": school_year_doc.title_en,
                "start_date": str(school_year_doc.start_date),
                "end_date": str(school_year_doc.end_date),
                "is_enable": school_year_doc.is_enable,
                "campus_id": school_year_doc.campus_id
            },
            "message": "School year updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating school year {school_year_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating school year: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_school_year(school_year_id):
    """Delete a school year"""
    try:
        if not school_year_id:
            return {
                "success": False,
                "data": {},
                "message": "School Year ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            school_year_doc = frappe.get_doc("SIS School Year", school_year_id)
            
            # Check campus permission
            if school_year_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this school year"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "School year not found"
            }
        
        # Delete the document
        frappe.delete_doc("SIS School Year", school_year_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "School year deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting school year {school_year_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting school year: {str(e)}"
        }


@frappe.whitelist(allow_guest=True)
def test_debug():
    """Debug function to test basic operations"""
    try:
        frappe.logger().info("=== DEBUG TEST CALLED ===")
        
        # Test 1: Basic info
        user = frappe.session.user
        frappe.logger().info(f"Current user: {user}")
        
        # Test 2: Check campus
        campus_list = frappe.get_all("SIS Campus", fields=["name", "title_vn"], limit=5)
        frappe.logger().info(f"Available campuses: {campus_list}")
        
        # Test 3: Check if campus-1 exists
        campus_1_exists = frappe.db.exists("SIS Campus", "campus-1")
        frappe.logger().info(f"Campus-1 exists: {campus_1_exists}")
        
        # Test 4: Try creating doc without inserting
        test_doc_data = {
            "doctype": "SIS School Year",
            "title_vn": "Test Debug 2024",
            "title_en": "Test Debug 2024",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "is_enable": 1,
            "campus_id": "campus-1"
        }
        
        test_doc = frappe.get_doc(test_doc_data)
        frappe.logger().info(f"Test doc created: {test_doc}")
        
        return {
            "success": True,
            "user": user,
            "campuses_count": len(campus_list),
            "campus_1_exists": campus_1_exists,
            "test_doc_created": True,
            "message": "Debug test completed successfully"
        }
        
    except Exception as e:
        frappe.logger().error(f"DEBUG TEST ERROR: {str(e)}")
        import traceback
        error_trace = traceback.format_exc()
        frappe.logger().error(f"Full traceback: {error_trace}")
        
        return {
            "success": False,
            "error": str(e),
            "traceback": error_trace,
            "message": "Debug test failed"
        }
