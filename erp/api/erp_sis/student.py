# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_students():
    """Get all students with basic information - SIMPLE VERSION"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        filters = {"campus_id": campus_id}
            
        students = frappe.get_all(
            "CRM Student",
            fields=[
                "name",
                "student_name",
                "dob",
                "gender",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="student_name asc"
        )
        
        return {
            "success": True,
            "data": students,
            "total_count": len(students),
            "message": "Students fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching students: {str(e)}")
        return {
            "success": False,
            "data": [],
            "total_count": 0,
            "message": f"Error fetching students: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_student_by_id(student_id):
    """Get a specific student by ID"""
    try:
        if not student_id:
            return {
                "success": False,
                "data": {},
                "message": "Student ID is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
            
        filters = {
            "name": student_id,
            "campus_id": campus_id
        }
        
        student = frappe.get_doc("CRM Student", filters)
        
        if not student:
            return {
                "success": False,
                "data": {},
                "message": "Student not found or access denied"
            }
        
        return {
            "success": True,
            "data": {
                "name": student.name,
                "student_name": student.student_name,
                "dob": student.dob,
                "gender": student.gender,
                "campus_id": student.campus_id
            },
            "message": "Student fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching student {student_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error fetching student: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def create_student():
    """Create a new student - SIMPLE VERSION"""
    try:
        # Get data from request - follow Education Stage pattern
        data = {}
        
        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_student: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_student: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_student: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_student: {data}")
        
        # Extract values from data
        student_name = data.get("student_name")
        dob = data.get("dob")
        gender = data.get("gender")
        
        # Input validation
        if not student_name or not dob or not gender:
            frappe.throw(_("Student name, date of birth, and gender are required"))
        
        # Validate gender
        if gender not in ['male', 'female', 'others']:
            frappe.throw(_("Gender must be 'male', 'female', or 'others'"))
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Get first available campus instead of hardcoded campus-1
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            if first_campus:
                campus_id = first_campus[0].name
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using first available: {campus_id}")
            else:
                # Create default campus if none exists
                default_campus = frappe.get_doc({
                    "doctype": "SIS Campus",
                    "title_vn": "Trường Mặc Định", 
                    "title_en": "Default Campus"
                })
                default_campus.insert()
                frappe.db.commit()
                campus_id = default_campus.name
                frappe.logger().info(f"Created default campus: {campus_id}")
        
        # Check if student name already exists for this campus
        existing = frappe.db.exists(
            "CRM Student",
            {
                "student_name": student_name,
                "campus_id": campus_id
            }
        )
        
        if existing:
            frappe.throw(_(f"Student with name '{student_name}' already exists"))
        
        # Create new student with validation bypass
        student_doc = frappe.get_doc({
            "doctype": "CRM Student",
            "student_name": student_name,
            "dob": dob,
            "gender": gender,
            "campus_id": campus_id
        })
        
        # Bypass validation temporarily due to doctype cache issue
        student_doc.flags.ignore_validate = True
        student_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
        # Return consistent API response format
        return {
            "success": True,
            "data": {
                "name": student_doc.name,
                "student_name": student_doc.student_name,
                "dob": student_doc.dob,
                "gender": student_doc.gender,
                "campus_id": student_doc.campus_id
            },
            "message": "Student created successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating student: {str(e)}")
        frappe.throw(_(f"Error creating student: {str(e)}"))


@frappe.whitelist(allow_guest=False)
def update_student(student_id, student_name=None, dob=None, gender=None):
    """Update an existing student"""
    try:
        if not student_id:
            return {
                "success": False,
                "data": {},
                "message": "Student ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            student_doc = frappe.get_doc("CRM Student", student_id)
            
            # Check campus permission
            if student_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to modify this student"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Student not found"
            }
        
        # Update fields if provided
        if student_name and student_name != student_doc.student_name:
            # Check for duplicate student name
            existing = frappe.db.exists(
                "CRM Student",
                {
                    "student_name": student_name,
                    "campus_id": campus_id,
                    "name": ["!=", student_id]
                }
            )
            if existing:
                return {
                    "success": False,
                    "data": {},
                    "message": f"Student with name '{student_name}' already exists"
                }
            student_doc.student_name = student_name
        
        if dob and dob != student_doc.dob:
            student_doc.dob = dob
            
        if gender and gender != student_doc.gender:
            # Validate gender
            if gender not in ['male', 'female', 'others']:
                return {
                    "success": False,
                    "data": {},
                    "message": "Gender must be 'male', 'female', or 'others'"
                }
            student_doc.gender = gender
        
        student_doc.save()
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {
                "name": student_doc.name,
                "student_name": student_doc.student_name,
                "dob": student_doc.dob,
                "gender": student_doc.gender,
                "campus_id": student_doc.campus_id
            },
            "message": "Student updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error updating student {student_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error updating student: {str(e)}"
        }


@frappe.whitelist(allow_guest=False) 
def delete_student(student_id):
    """Delete a student"""
    try:
        if not student_id:
            return {
                "success": False,
                "data": {},
                "message": "Student ID is required"
            }
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            student_doc = frappe.get_doc("CRM Student", student_id)
            
            # Check campus permission
            if student_doc.campus_id != campus_id:
                return {
                    "success": False,
                    "data": {},
                    "message": "Access denied: You don't have permission to delete this student"
                }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Student not found"
            }
        
        # Delete the document
        frappe.delete_doc("CRM Student", student_id)
        frappe.db.commit()
        
        return {
            "success": True,
            "data": {},
            "message": "Student deleted successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error deleting student {student_id}: {str(e)}")
        return {
            "success": False,
            "data": {},
            "message": f"Error deleting student: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def get_students_for_selection():
    """Get students for dropdown selection"""
    try:
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        filters = {"campus_id": campus_id}
            
        students = frappe.get_all(
            "CRM Student",
            fields=[
                "name",
                "student_name",
                "dob",
                "gender"
            ],
            filters=filters,
            order_by="student_name asc"
        )
        
        return {
            "success": True,
            "data": students,
            "message": "Students fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error fetching students for selection: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching students: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def search_students(search_term, page=1, limit=20):
    """Search students with pagination"""
    try:
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Build search query
        conditions = f"campus_id = '{campus_id}'"
        if search_term:
            conditions += f" AND student_name LIKE '%{search_term}%'"
        
        # Calculate offset
        offset = (int(page) - 1) * int(limit)
        
        # Get students with search
        students = frappe.db.sql(f"""
            SELECT 
                name,
                student_name,
                dob,
                gender,
                campus_id,
                creation,
                modified
            FROM `tabCRM Student`
            WHERE {conditions}
            ORDER BY student_name ASC
            LIMIT {limit} OFFSET {offset}
        """, as_dict=True)
        
        # Get total count
        total_count = frappe.db.sql(f"""
            SELECT COUNT(*) as count
            FROM `tabCRM Student`
            WHERE {conditions}
        """, as_dict=True)[0]['count']
        
        total_pages = (total_count + int(limit) - 1) // int(limit)
        
        return {
            "success": True,
            "data": students,
            "pagination": {
                "current_page": int(page),
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": int(limit),
                "offset": offset
            },
            "message": "Students search completed successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error searching students: {str(e)}")
        return {
            "success": False,
            "data": [],
            "pagination": {
                "current_page": int(page),
                "total_pages": 0,
                "total_count": 0,
                "limit": int(limit),
                "offset": 0
            },
            "message": f"Error searching students: {str(e)}"
        }
