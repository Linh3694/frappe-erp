import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
)


@frappe.whitelist(allow_guest=True)
def global_search(search_term: str = None):
    """Global search for both students and classes - single unified endpoint"""
    try:
        # Normalize parameters
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')

        frappe.logger().info(f"global_search called with search_term: '{search_term}'")
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        result = {
            "students": [],
            "classes": []
        }
        
        if not search_term or not str(search_term).strip():
            return success_response(
                data=result,
                message="Empty search term"
            )
        
        search_clean = str(search_term).strip()
        
        # ===== SEARCH STUDENTS =====
        try:
            where_clauses = ["campus_id = %s"]
            params = [campus_id]
            like_contains = f"%{search_clean}%"
            like_prefix = f"{search_clean}%"
            where_clauses.append("(LOWER(student_name) LIKE LOWER(%s) OR LOWER(student_code) LIKE LOWER(%s))")
            params.extend([like_contains, like_prefix])
            
            conditions = " AND ".join(where_clauses)
            
            sql_query = (
                """
                SELECT 
                    name,
                    student_name,
                    student_code,
                    dob,
                    gender,
                    campus_id,
                    creation,
                    modified
                FROM `tabCRM Student`
                WHERE {where}
                ORDER BY student_name ASC
                """
            ).format(where=conditions)
            
            students = frappe.db.sql(sql_query, params, as_dict=True)
            
            # Enrich with photos from SIS Photo
            if students:
                student_ids_for_photos = [s.get('name') for s in students if s.get('name')]
                photos = frappe.db.sql("""
                    SELECT 
                        student_id,
                        photo,
                        upload_date
                    FROM `tabSIS Photo`
                    WHERE student_id IN %(student_ids)s
                        AND type = 'student'
                        AND status = 'Active'
                    ORDER BY upload_date DESC
                """, {"student_ids": student_ids_for_photos}, as_dict=True)
                
                photo_map = {}
                for photo in photos:
                    student_id = photo.get('student_id')
                    if student_id and student_id not in photo_map:
                        photo_url = photo.get('photo')
                        if photo_url:
                            if photo_url.startswith('/files/'):
                                photo_url = frappe.utils.get_url(photo_url)
                            elif not photo_url.startswith('http'):
                                photo_url = frappe.utils.get_url('/files/' + photo_url)
                            photo_map[student_id] = photo_url
                
                for student in students:
                    student_id = student.get('name')
                    student['user_image'] = photo_map.get(student_id)
            
            result["students"] = students
            frappe.logger().info(f"Found {len(students)} students")
        except Exception as e:
            frappe.logger().error(f"Error searching students: {str(e)}")
        
        # ===== SEARCH CLASSES =====
        try:
            where_clauses = ["c.campus_id = %s"]
            params = [campus_id]
            like_contains = f"%{search_clean}%"
            where_clauses.append("(LOWER(c.title) LIKE LOWER(%s))")
            params.extend([like_contains])
            
            conditions = " AND ".join(where_clauses)
            
            sql_query = (
                """
                SELECT 
                    c.name,
                    c.title,
                    c.short_title,
                    c.campus_id,
                    c.school_year_id,
                    sy.title as school_year_name,
                    c.education_grade,
                    c.academic_program,
                    c.homeroom_teacher,
                    c.vice_homeroom_teacher,
                    c.room,
                    c.class_type,
                    c.creation,
                    c.modified
                FROM `tabSIS Class` c
                LEFT JOIN `tabSIS School Year` sy ON c.school_year_id = sy.name
                WHERE {where}
                ORDER BY c.title ASC
                """
            ).format(where=conditions)
            
            classes = frappe.db.sql(sql_query, params, as_dict=True)
            result["classes"] = classes
            frappe.logger().info(f"Found {len(classes)} classes")
        except Exception as e:
            frappe.logger().error(f"Error searching classes: {str(e)}")
        
        return success_response(
            data=result,
            message=f"Search completed - found {len(result['students'])} students and {len(result['classes'])} classes"
        )
        
    except Exception as e:
        frappe.log_error(f"Error in global_search: {str(e)}")
        return error_response(
            message="Error searching",
            code="GLOBAL_SEARCH_ERROR"
        )

