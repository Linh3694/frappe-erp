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
            "classes": [],
            "_debug": {
                "campus_id": campus_id,
                "search_term": search_term,
                "logs": []
            }
        }
        
        if not search_term or not str(search_term).strip():
            result["_debug"]["logs"].append("Empty search term")
            return success_response(
                data=result,
                message="Empty search term"
            )
        
        search_clean = str(search_term).strip()
        
        frappe.logger().info(f"[GLOBAL_SEARCH] campus_id={campus_id}, search_term={search_term}, search_clean={search_clean}")
        
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
            
            debug_msg = f"Students SQL: {sql_query} | params: {params}"
            result["_debug"]["logs"].append(debug_msg)
            frappe.logger().info(f"[GLOBAL_SEARCH] {debug_msg}")
            students = frappe.db.sql(sql_query, params, as_dict=True)
            result["_debug"]["logs"].append(f"Found {len(students)} students from DB")
            
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
            where_clauses = ["campus_id = %s"]
            params = [campus_id]
            like_contains = f"%{search_clean}%"
            where_clauses.append("(LOWER(title) LIKE LOWER(%s))")
            params.extend([like_contains])
            
            conditions = " AND ".join(where_clauses)
            
            sql_query = (
                """
                SELECT 
                    name,
                    title,
                    short_title,
                    campus_id,
                    school_year_id,
                    education_grade,
                    academic_program,
                    homeroom_teacher,
                    vice_homeroom_teacher,
                    room,
                    class_type,
                    creation,
                    modified
                FROM `tabSIS Class`
                WHERE {where}
                ORDER BY title ASC
                """
            ).format(where=conditions)
            
            debug_msg = f"Classes SQL: {sql_query} | params: {params}"
            result["_debug"]["logs"].append(debug_msg)
            frappe.logger().info(f"[GLOBAL_SEARCH] {debug_msg}")
            classes = frappe.db.sql(sql_query, params, as_dict=True)
            result["_debug"]["logs"].append(f"Found {len(classes)} classes from DB")
            
            # Get school year names for each class
            if classes:
                school_year_ids = list(set([c.get('school_year_id') for c in classes if c.get('school_year_id')]))
                if school_year_ids:
                    school_years = frappe.get_all(
                        "SIS School Year",
                        filters={"name": ["in", school_year_ids]},
                        fields=["name", "title"]
                    )
                    school_year_map = {sy['name']: sy['title'] for sy in school_years}
                    
                    for cls in classes:
                        cls['school_year_name'] = school_year_map.get(cls.get('school_year_id'), '')
            
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

