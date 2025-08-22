# Copyright (c) 2024, Wellspring International School and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles


@frappe.whitelist(allow_guest=False)
def get_all_students(page=1, limit=20):
    """Get all students with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        
        frappe.logger().info(f"get_all_students called with page: {page}, limit: {limit}")
        
        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")
        
        frappe.logger().info(f"Using campus_id: {campus_id}")
        
        # Temporarily disable campus filtering for debugging
        filters = {}  # {"campus_id": campus_id}
        
        # Calculate offset for pagination
        offset = (page - 1) * limit
            
        frappe.logger().info(f"Query filters: {filters}")
        frappe.logger().info(f"Query pagination: offset={offset}, limit={limit}")
        
        students = frappe.get_all(
            "CRM Student",
            fields=[
                "name",
                "student_name",
                "student_code",
                "dob",
                "gender",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="student_name asc",
            limit_start=offset,
            limit_page_length=limit
        )
        
        frappe.logger().info(f"Found {len(students)} students")
        
        # Get total count
        total_count = frappe.db.count("CRM Student", filters=filters)
        total_pages = (total_count + limit - 1) // limit
        
        frappe.logger().info(f"Total count: {total_count}, Total pages: {total_pages}")
        
        return {
            "success": True,
            "data": students,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
                "offset": offset
            },
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
def get_student_data():
    """Get a specific student by ID or code"""
    try:
        # Get parameters from form_dict
        student_id = frappe.local.form_dict.get("student_id")
        student_code = frappe.local.form_dict.get("student_code")
        student_slug = frappe.local.form_dict.get("student_slug")
        
        frappe.logger().info(f"get_student_data called - student_id: {student_id}, student_code: {student_code}, student_slug: {student_slug}")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        
        if not student_id and not student_code and not student_slug:
            return {
                "success": False,
                "data": {},
                "message": "Student ID, code, or slug is required"
            }
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Build filters based on what parameter we have
        if student_id:
            # Temporarily disable campus filtering for debugging
            student = frappe.get_doc("CRM Student", student_id)
            # Temporarily disable campus verification
            # if student.campus_id != campus_id:
            #     return {
            #         "success": False,
            #         "data": {},
            #         "message": "Student not found or access denied"
            #     }
        elif student_code:
            # Search by student_code without campus filtering (for debugging)
            students = frappe.get_all("CRM Student", 
                filters={
                    "student_code": student_code,
                    # "campus_id": campus_id
                }, 
                fields=["name"], 
                limit=1)
            
            if not students:
                return {
                    "success": False,
                    "data": {},
                    "message": "Student not found"
                }
            
            student = frappe.get_doc("CRM Student", students[0].name)
        elif student_slug:
            # Convert slug back to name pattern and search by student_name
            # Convert "nguyen-van-a" to "nguyen van a" for searching
            search_name = student_slug.replace('-', ' ')
            frappe.logger().info(f"Searching for student with name pattern: {search_name}")
            
            # Search by student_name without campus filtering - use LIKE for flexible matching
            students = frappe.db.sql("""
                SELECT name, student_name 
                FROM `tabCRM Student` 
                WHERE LOWER(student_name) LIKE %s 
                LIMIT 1
            """, (f'%{search_name.lower()}%',), as_dict=True)
            
            if not students:
                return {
                    "success": False,
                    "data": {},
                    "message": "Student not found"
                }
            
            student = frappe.get_doc("CRM Student", students[0].name)
        
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
                "student_code": student.student_code,
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
        student_code = data.get("student_code")
        dob = data.get("dob")
        gender = data.get("gender")
        
        # Input validation
        if not student_name or not student_code or not dob or not gender:
            frappe.throw(_("Student name, student code, date of birth, and gender are required"))
        
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
        existing_name = frappe.db.exists(
            "CRM Student",
            {
                "student_name": student_name,
                "campus_id": campus_id
            }
        )
        
        if existing_name:
            frappe.throw(_(f"Student with name '{student_name}' already exists"))
        
        # Check if student code already exists for this campus
        existing_code = frappe.db.exists(
            "CRM Student",
            {
                "student_code": student_code,
                "campus_id": campus_id
            }
        )
        
        if existing_code:
            frappe.throw(_(f"Student with code '{student_code}' already exists"))
        
        # Create new student with validation bypass
        student_doc = frappe.get_doc({
            "doctype": "CRM Student",
            "student_name": student_name,
            "student_code": student_code,
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
                "student_code": student_doc.student_code,
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
def update_student():
    """Update an existing student"""
    try:
        def get_param(key):
            value = frappe.local.form_dict.get(key)
            if value:
                return value
                
            if hasattr(frappe, 'form_dict') and frappe.form_dict.get(key):
                return frappe.form_dict.get(key)
            
            if frappe.request.data:
                try:
                    import json
                    json_data = json.loads(frappe.request.data.decode('utf-8'))
                    if isinstance(json_data, dict) and key in json_data:
                        return json_data[key]
                except:
                    try:
                        import urllib.parse
                        parsed = urllib.parse.parse_qs(frappe.request.data.decode('utf-8'))
                        if key in parsed and parsed[key]:
                            return parsed[key][0]  # parse_qs returns lists
                    except:
                        pass
                        
            # Try request.form if available
            if hasattr(frappe.local, 'request') and hasattr(frappe.local.request, 'form'):
                value = frappe.local.request.form.get(key)
                if value:
                    return value
                    
            return None
            
        student_id = get_param("student_id")
        student_name = get_param("student_name")
        student_code = get_param("student_code") 
        dob = get_param("dob")
        gender = get_param("gender")
        
        frappe.logger().info(f"=== REQUEST DEBUG INFO ===")
        frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        frappe.logger().info(f"request.data: {frappe.request.data}")
        frappe.logger().info(f"request.method: {getattr(frappe.request, 'method', 'unknown')}")
        frappe.logger().info(f"request.headers: {getattr(frappe.request, 'headers', {})}")
        
        frappe.logger().info(f"Received data - student_id: {student_id}, student_name: {student_name}, student_code: {student_code}, dob: {dob}, gender: {gender}")
        
        # Try to decode request data for debug
        decoded_data = "Unable to decode"
        if frappe.request.data:
            try:
                decoded_data = frappe.request.data.decode('utf-8')
            except:
                decoded_data = str(frappe.request.data)
        
        frappe.msgprint(f"DEBUG: update_student called - ID: {student_id}")
        frappe.msgprint(f"DEBUG: Request data decoded: {decoded_data}")
        frappe.msgprint(f"DEBUG: Received data: name={student_name}, code={student_code}, dob={dob}, gender={gender}")
        
        # Also add to response for debugging
        debug_info = {
            "form_dict": dict(frappe.local.form_dict),
            "request_data_decoded": decoded_data,
            "student_id": student_id,
            "student_name": student_name, 
            "student_code": student_code,
            "dob": dob,
            "gender": gender
        }
        
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
        
        frappe.logger().info(f"Using campus_id: {campus_id}")
        
        # Get existing document
        try:
            student_doc = frappe.get_doc("CRM Student", student_id)
            frappe.logger().info(f"Found student doc: {student_doc.name}, current values - name: {student_doc.student_name}, code: {student_doc.student_code}, dob: {student_doc.dob}, gender: {student_doc.gender}")
            frappe.logger().info(f"Student campus_id: {student_doc.campus_id}, user campus_id: {campus_id}")
            
            # Temporarily disable campus permission check for debugging
            # if student_doc.campus_id != campus_id:
            #     return {
            #         "success": False,
            #         "data": {},
            #         "message": "Access denied: You don't have permission to modify this student"
            #     }
                
        except frappe.DoesNotExistError:
            return {
                "success": False,
                "data": {},
                "message": "Student not found"
            }
        
        # Track if any changes were made
        changes_made = False
        
        # Helper function to normalize values for comparison
        def normalize_value(val):
            """Convert None/null/empty to empty string for comparison"""
            if val is None or val == "null" or val == "":
                return ""
            return str(val).strip()
        
        # Update fields if provided
        frappe.logger().info(f"Checking student_name: '{student_name}' vs current '{student_doc.student_name}' (normalized: '{normalize_value(student_name)}' vs '{normalize_value(student_doc.student_name)}')")
        if student_name and normalize_value(student_name) != normalize_value(student_doc.student_name):
            frappe.logger().info(f"Updating student_name from '{student_doc.student_name}' to '{student_name}'")
            # Check for duplicate student name (temporarily disable campus filtering)
            existing_name = frappe.db.exists(
                "CRM Student",
                {
                    "student_name": student_name,
                    # "campus_id": campus_id,
                    "name": ["!=", student_id]
                }
            )
            if existing_name:
                frappe.logger().info(f"Duplicate student name found: {existing_name}")
                return {
                    "success": False,
                    "data": {},
                    "message": f"Student with name '{student_name}' already exists"
                }
            student_doc.student_name = student_name
            changes_made = True
        
        frappe.logger().info(f"Checking student_code: '{student_code}' vs current '{student_doc.student_code}' (normalized: '{normalize_value(student_code)}' vs '{normalize_value(student_doc.student_code)}')")
        print(f"[DEBUG] Comparing student_code: '{student_code}' vs current '{student_doc.student_code}'")
        print(f"[DEBUG] Normalized comparison: '{normalize_value(student_code)}' vs '{normalize_value(student_doc.student_code)}'")
        print(f"[DEBUG] Are they different? {normalize_value(student_code) != normalize_value(student_doc.student_code)}")
        
        if student_code and normalize_value(student_code) != normalize_value(student_doc.student_code):
            print(f"[DEBUG] WILL UPDATE student_code from '{student_doc.student_code}' to '{student_code}'")
            frappe.logger().info(f"Updating student_code from '{student_doc.student_code}' to '{student_code}'")
            # Check for duplicate student code (temporarily disable campus filtering)
            existing_code = frappe.db.exists(
                "CRM Student",
                {
                    "student_code": student_code,
                    # "campus_id": campus_id,
                    "name": ["!=", student_id]
                }
            )
            if existing_code:
                frappe.logger().info(f"Duplicate student code found: {existing_code}")
                return {
                    "success": False,
                    "data": {},
                    "message": f"Student with code '{student_code}' already exists"
                }
            student_doc.student_code = student_code
            changes_made = True
            print(f"[DEBUG] student_code UPDATED successfully, changes_made = {changes_made}")
        else:
            print(f"[DEBUG] NO UPDATE needed for student_code")

        frappe.logger().info(f"Checking dob: '{dob}' vs current '{student_doc.dob}' (normalized: '{normalize_value(dob)}' vs '{normalize_value(student_doc.dob)}')")
        if dob and normalize_value(dob) != normalize_value(student_doc.dob):
            frappe.logger().info(f"Updating dob from '{student_doc.dob}' to '{dob}'")
            student_doc.dob = dob
            changes_made = True
            
        frappe.logger().info(f"Checking gender: '{gender}' vs current '{student_doc.gender}' (normalized: '{normalize_value(gender)}' vs '{normalize_value(student_doc.gender)}')")
        if gender and normalize_value(gender) != normalize_value(student_doc.gender):
            frappe.logger().info(f"Updating gender from '{student_doc.gender}' to '{gender}'")
            # Validate gender
            if gender not in ['male', 'female', 'others']:
                return {
                    "success": False,
                    "data": {},
                    "message": "Gender must be 'male', 'female', or 'others'"
                }
            student_doc.gender = gender
            changes_made = True
            
        frappe.logger().info(f"Changes made: {changes_made}")
        
        if not changes_made:
            frappe.logger().info("No changes detected, but proceeding with save anyway")
        
        
        # Force reload to get fresh data before saving
        student_doc.reload()
        frappe.logger().info(f"Before save - doc values: name={student_doc.student_name}, code={student_doc.student_code}, dob={student_doc.dob}, gender={student_doc.gender}")
        print(f"[DEBUG] Before save - doc values: name={student_doc.student_name}, code={student_doc.student_code}, dob={student_doc.dob}, gender={student_doc.gender}")
        print(f"[DEBUG] Changes made flag: {changes_made}")
        
        try:
            print(f"[DEBUG] About to save document...")
            student_doc.save()
            print(f"[DEBUG] Document saved successfully!")
            frappe.logger().info(f"Document saved successfully")
        except Exception as save_error:
            print(f"[DEBUG] ERROR during save: {str(save_error)}")
            frappe.logger().error(f"Error during save: {str(save_error)}")
            raise save_error
            
        try:
            print(f"[DEBUG] About to commit to database...")
            frappe.db.commit()
            print(f"[DEBUG] Database committed successfully!")
            frappe.logger().info(f"Database committed successfully")
        except Exception as commit_error:
            print(f"[DEBUG] ERROR during commit: {str(commit_error)}")
            frappe.logger().error(f"Error during commit: {str(commit_error)}")
            raise commit_error
        
        # Reload again to get the saved data
        student_doc.reload()
        frappe.logger().info(f"After save - doc values: name={student_doc.student_name}, code={student_doc.student_code}, dob={student_doc.dob}, gender={student_doc.gender}")
        print(f"[DEBUG] After save - doc values: name={student_doc.student_name}, code={student_doc.student_code}, dob={student_doc.dob}, gender={student_doc.gender}")
        
        response_data = {
            "success": True,
            "data": {
                "name": student_doc.name,
                "student_name": student_doc.student_name,
                "student_code": student_doc.student_code,
                "dob": student_doc.dob,
                "gender": student_doc.gender,
                "campus_id": student_doc.campus_id
            },
            "message": f"Student updated successfully{' (with changes)' if changes_made else ' (no changes detected)'}",
            "debug_info": debug_info,
            "changes_made": changes_made
        }
        
        frappe.msgprint(f"DEBUG: Returning response with changes_made={changes_made}")
        print(f"[DEBUG] Returning response: {response_data}")
        return response_data
        
    except Exception as e:
        # Get student_id from locals if not available in scope
        student_id_for_error = frappe.local.form_dict.get("student_id", "unknown")
        frappe.log_error(f"Error updating student {student_id_for_error}: {str(e)}")
        frappe.logger().error(f"Full error updating student {student_id_for_error}: {str(e)}")
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
                "student_code",
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
def search_students(search_term=None, page=1, limit=20):
    """Search students with pagination"""
    try:
        # Normalize parameters: prefer form_dict values if provided
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')
        # Coerce page/limit from form if present
        page = int(form.get('page', page))
        limit = int(form.get('limit', limit))

        frappe.logger().info(f"search_students called with search_term: '{search_term}', page: {page}, limit: {limit}")
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Build search terms and campus filter (use parameterized queries)
        where_clauses = ["campus_id = %s"]
        params = [campus_id]
        if search_term and str(search_term).strip():
            like = f"%{str(search_term).strip()}%"
            where_clauses.append("(LOWER(student_name) LIKE LOWER(%s) OR LOWER(student_code) LIKE LOWER(%s))")
            params.extend([like, like])
        conditions = " AND ".join(where_clauses)
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Calculate offset
        offset = (page - 1) * limit
        
        # Get students with search (parameterized)
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
            LIMIT %s OFFSET %s
            """
        ).format(where=conditions)

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params + [limit, offset]}")

        students = frappe.db.sql(sql_query, params + [limit, offset], as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(students)} students")

        # Post-filter in Python for better VN diacritics handling and strict contains
        def normalize_text(text: str) -> str:
            try:
                import unicodedata
                if not text:
                    return ''
                text = unicodedata.normalize('NFD', text)
                text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
                # Handle Vietnamese specific characters
                text = text.replace('đ', 'd').replace('Đ', 'D')
                return text.lower()
            except Exception:
                return (text or '').lower()

        if search_term and str(search_term).strip():
            norm_q = normalize_text(str(search_term).strip())
            pre_count = len(students)
            students = [
                s for s in students
                if (
                    normalize_text(s.get('student_name', '')) .find(norm_q) != -1
                    or (s.get('student_code') or '').lower().find(norm_q.lower()) != -1
                )
            ]
            frappe.logger().info(f"POST-FILTERED {pre_count} -> {len(students)} using normalized query='{norm_q}'")
        
        # Get total count (parameterized)
        count_query = (
            """
            SELECT COUNT(*) as count
            FROM `tabCRM Student`
            WHERE {where}
            """
        ).format(where=conditions)
        
        frappe.logger().info(f"EXECUTING COUNT QUERY: {count_query} | params={params}")
        
        total_count = frappe.db.sql(count_query, params, as_dict=True)[0]['count']
        
        frappe.logger().info(f"COUNT QUERY RETURNED: {total_count}")
        
        total_pages = (total_count + limit - 1) // limit
        
        return {
            "success": True,
            "data": students,
            "total_count": total_count,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "limit": limit,
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
                "current_page": page,
                "total_pages": 0,
                "total_count": 0,
                "limit": limit,
                "offset": 0
            },
            "message": f"Error searching students: {str(e)}"
        }
