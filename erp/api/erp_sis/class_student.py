# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


@frappe.whitelist(allow_guest=False)
def get_all_class_students(page=1, limit=20, school_year_id=None, class_id=None):
    """Get all class students with pagination and filters"""
    try:
        page = int(page)
        limit = int(limit)
        
        # Build filters
        filters = {}
        if school_year_id:
            filters['school_year_id'] = school_year_id
        if class_id:
            filters['class_id'] = class_id
            
        # Get campus filter from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if campus_id:
            filters['campus_id'] = campus_id
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get class students
        class_students = frappe.get_all(
            "SIS Class Student",
            filters=filters,
            fields=[
                "name", "class_id", "student_id", "school_year_id", 
                "class_type", "campus_id", "creation", "modified"
            ],
            order_by="creation desc",
            limit_start=offset,
            limit_page_length=limit
        )
        
        # Get total count
        total_count = frappe.db.count("SIS Class Student", filters=filters)
        
        # Calculate pagination
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "success": True,
            "data": class_students,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
            "message": "Class students fetched successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting class students: {str(e)}")
        return {
            "success": False,
            "data": [],
            "message": f"Error fetching class students: {str(e)}"
        }


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def assign_student(class_id=None, student_id=None, school_year_id=None, class_type="regular"):
    """Assign a student to a class"""
    try:
        # Get parameters from multiple sources
        form = frappe.local.form_dict or {}

        # Debug logging
        frappe.logger().info(f"Initial function args - class_id: {class_id}, student_id: {student_id}, school_year_id: {school_year_id}")
        frappe.logger().info(f"form_dict content: {form}")

        # Comprehensive parameter extraction
        class_id = (form.get('class_id') or
                   class_id or
                   frappe.local.request.args.get('class_id') if hasattr(frappe.local, 'request') and frappe.local.request.args else None)

        student_id = (form.get('student_id') or
                     student_id or
                     frappe.local.request.args.get('student_id') if hasattr(frappe.local, 'request') and frappe.local.request.args else None)

        school_year_id = (form.get('school_year_id') or
                         school_year_id or
                         frappe.local.request.args.get('school_year_id') if hasattr(frappe.local, 'request') and frappe.local.request.args else None)

        class_type = (form.get('class_type') or
                     class_type or
                     frappe.local.request.args.get('class_type') if hasattr(frappe.local, 'request') and frappe.local.request.args else None or
                     'regular')

        frappe.logger().info(f"Final parameters - class_id={class_id}, student_id={student_id}, school_year_id={school_year_id}, class_type={class_type}")
        
        # Validate required parameters
        if not class_id or not student_id or not school_year_id:
            return {
                "success": False,
                "message": "Missing required parameters: class_id, student_id, school_year_id"
            }
        
        # Get campus from context
        from erp.utils.campus_utils import get_current_campus_from_context
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"  # Default fallback
        
        # Check if assignment already exists
        existing = frappe.db.exists("SIS Class Student", {
            "class_id": class_id,
            "student_id": student_id,
            "school_year_id": school_year_id
        })
        
        if existing:
            return {
                "success": False,
                "message": "Student is already assigned to this class"
            }
        
        # Create new class student assignment
        class_student = frappe.get_doc({
            "doctype": "SIS Class Student",
            "class_id": class_id,
            "student_id": student_id,
            "school_year_id": school_year_id,
            "class_type": class_type,
            "campus_id": campus_id
        })
        
        class_student.insert()
        frappe.db.commit()
        
        frappe.logger().info(f"Successfully assigned student {student_id} to class {class_id}")
        
        return {
            "success": True,
            "data": {
                "name": class_student.name,
                "class_id": class_student.class_id,
                "student_id": class_student.student_id,
                "school_year_id": class_student.school_year_id,
                "class_type": class_student.class_type,
                "campus_id": class_student.campus_id
            },
            "message": "Student assigned to class successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error assigning student to class: {str(e)}")
        frappe.db.rollback()
        return {
            "success": False,
            "message": f"Error assigning student to class: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def unassign_student(name=None):
    """Remove a student from a class"""
    try:
        # Get parameters from form_dict if not provided
        form = frappe.local.form_dict or {}
        if not name:
            name = form.get('name')
            
        frappe.logger().info(f"unassign_student called with: name={name}")
        
        if not name:
            return {
                "success": False,
                "message": "Missing required parameter: name"
            }
        
        # Check if class student exists
        if not frappe.db.exists("SIS Class Student", name):
            return {
                "success": False,
                "message": "Class student assignment not found"
            }
        
        # Delete the assignment
        frappe.delete_doc("SIS Class Student", name)
        frappe.db.commit()
        
        frappe.logger().info(f"Successfully unassigned class student: {name}")
        
        return {
            "success": True,
            "message": "Student unassigned from class successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"Error unassigning student from class: {str(e)}")
        frappe.db.rollback()
        return {
            "success": False,
            "message": f"Error unassigning student from class: {str(e)}"
        }
