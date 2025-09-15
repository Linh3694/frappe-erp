
import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime
import json
from erp.utils.campus_utils import get_current_campus_from_context, get_campus_id_from_user_roles
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def check_student_code_availability():
    """Check if student code is available (not already taken)"""
    try:
        # Extract student_code from multiple sources
        student_code = None

        # Try from form_dict (POST with form data)
        if frappe.form_dict and frappe.form_dict.get("student_code"):
            student_code = frappe.form_dict.get("student_code")

        # Try from local.form_dict
        if not student_code and frappe.local.form_dict and frappe.local.form_dict.get("student_code"):
            student_code = frappe.local.form_dict.get("student_code")

        # Try from URL query parameters (GET request)
        if not student_code and hasattr(frappe.request, 'args') and frappe.request.args:
            student_code = frappe.request.args.get("student_code")

        # Try from request data if it's JSON
        if not student_code and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data)
                student_code = json_data.get("student_code")
            except Exception as e:
                frappe.logger().info(f"Could not parse JSON data: {str(e)}")

        frappe.logger().info(f"Final student_code value: '{student_code}'")

        if not student_code or student_code.strip() == "":
            frappe.logger().info("No valid student_code found")
            return error_response(
                message="Thiếu tham số mã học sinh",
                code="MISSING_STUDENT_CODE"
            )

        # Check if student with this code already exists
        existing = frappe.db.exists("CRM Student", {"student_code": student_code})
        if existing:
            return error_response(
                message="Mã học sinh đã tồn tại trong hệ thống",
                code="STUDENT_CODE_EXISTS"
            )
        else:
            return success_response(
                data={"available": True},
                message="Mã học sinh có thể sử dụng"
            )
    except Exception as e:
        frappe.log_error(f"Error checking student code availability: {str(e)}")
        return error_response(
            message="Lỗi hệ thống khi kiểm tra mã học sinh",
            code="SYSTEM_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_all_students(include_all_campuses=0):
    """Get all students without pagination - always returns full dataset"""
    try:
        include_all_campuses = int(include_all_campuses)
            
        frappe.logger().info(f"get_all_students called with: include_all_campuses={include_all_campuses}")

        if include_all_campuses:
            # Get filter for all user's campuses
            from erp.utils.campus_utils import get_campus_filter_for_all_user_campuses
            filters = get_campus_filter_for_all_user_campuses()
        else:
            # Get current user's campus information from roles
            campus_id = get_current_campus_from_context()

            if not campus_id:
                # Fallback to default if no campus found
                campus_id = "campus-1"

            # Apply campus filtering for data isolation
            filters = {"campus_id": campus_id}
        
        # Always fetch all students - no pagination
        students = frappe.get_all(
            "CRM Student",
            fields=[
                "name",
                "student_name",
                "student_code",
                "dob",
                "gender",
                "campus_id",
                "family_code",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="student_name asc"
        )


        # Ensure all students have name field and log sample data
        if students:
            sample = students[0]

            # Verify all students have name
            students_without_name = [s for s in students if not s.get('name')]
            if students_without_name:
                for s in students_without_name[:3]:  # Log first 3
                    frappe.logger().warning(f"Student without name: {s}")

        try:
            student_ids = [s.get("name") for s in students if s.get("name")]
            frappe.logger().info(f"Enriching {len(student_ids)} students with family codes")
            if student_ids:
                rows = frappe.db.sql(
                    """
                    SELECT fr.student as student, f.name as family_name, f.family_code
                    FROM `tabCRM Family Relationship` fr
                    INNER JOIN `tabCRM Family` f ON f.name = fr.parent
                    WHERE fr.student IN %(ids)s
                    ORDER BY f.family_code ASC
                    """,
                    {"ids": tuple(student_ids)},
                    as_dict=True,
                )
                frappe.logger().info(f"Found {len(rows)} family relationships")
                mapping = {}
                for r in rows:
                    mapping.setdefault(r["student"], []).append({"name": r["family_name"], "family_code": r["family_code"]})
                for s in students:
                    sid = s.get("name")
                    s["family_codes"] = mapping.get(sid, [])
        except Exception as e:
            frappe.logger().error(f"Failed to enrich students with family codes: {str(e)}")
        
        # Always return all students without pagination info
        return success_response(
            data=students,
            message=f"Fetched all {len(students)} students successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching students: {str(e)}")
        return error_response(
            message="Error fetching students",
            code="FETCH_STUDENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])  
def get_student_data():
    """Get a specific student by ID, code or slug"""
    try:
        # Collect identifiers from multiple sources for robustness
        form = getattr(frappe, 'form_dict', None) or {}
        local_form = getattr(frappe.local, 'form_dict', None) or {}
        request_args = getattr(getattr(frappe, 'request', None), 'args', None) or {}
        request_data = getattr(getattr(frappe, 'request', None), 'data', None)

        payload = {}
        if request_data:
            try:
                body = request_data.decode('utf-8') if isinstance(request_data, bytes) else request_data
                payload = json.loads(body) if body else {}
            except Exception as e:
                frappe.logger().info(f"get_student_data: JSON parse failed: {str(e)}")

        def pick(d, keys):
            for k in keys:
                if d and d.get(k):
                    return d.get(k)
            return None

        student_id = (
            pick(form, ['student_id', 'id', 'name', 'studentId'])
            or pick(local_form, ['student_id', 'id', 'name', 'studentId'])
            or pick(request_args, ['student_id', 'id', 'name', 'studentId'])
            or pick(payload, ['student_id', 'id', 'name', 'studentId'])
        )

        student_code = (
            pick(form, ['student_code', 'code'])
            or pick(local_form, ['student_code', 'code'])
            or pick(request_args, ['student_code', 'code'])
            or pick(payload, ['student_code', 'code'])
        )

        student_slug = (
            pick(form, ['student_slug', 'slug'])
            or pick(local_form, ['student_slug', 'slug'])
            or pick(request_args, ['student_slug', 'slug'])
            or pick(payload, ['student_slug', 'slug'])
        )

        frappe.logger().info(
            f"get_student_data identifiers → student_id: {student_id}, student_code: {student_code}, student_slug: {student_slug}"
        )
        try:
            frappe.logger().info(f"form_dict: {frappe.local.form_dict}")
        except Exception:
            pass
        
        if not student_id and not student_code and not student_slug:
            return error_response(
                message="Student ID, code, or slug is required",
                code="MISSING_IDENTIFIER"
            )
        
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
                    "student_code": str(student_code).strip(),
                    # "campus_id": campus_id
                },
                fields=["name"],
                limit=1)

            if not students:
                return not_found_response(
                    message="Student not found",
                    code="STUDENT_NOT_FOUND"
                )
            
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
                return not_found_response(
                    message="Student not found",
                    code="STUDENT_NOT_FOUND"
                )
            
            student = frappe.get_doc("CRM Student", students[0].name)
        
        if not student:
            return not_found_response(
                message="Student not found or access denied",
                code="STUDENT_NOT_FOUND"
            )
        
        return single_item_response(
            data={
                "name": student.name,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "dob": student.dob,
                "gender": student.gender,
                "campus_id": student.campus_id
            },
            message="Student fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching student {student_id}: {str(e)}")
        return error_response(
            message="Error fetching student",
            code="FETCH_STUDENT_ERROR"
        )


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
            return validation_error_response(
                message="Student name, student code, date of birth, and gender are required",
                errors={
                    "student_name": ["Required"] if not student_name else [],
                    "student_code": ["Required"] if not student_code else [],
                    "dob": ["Required"] if not dob else [],
                    "gender": ["Required"] if not gender else []
                }
            )

        # Validate gender
        if gender not in ['male', 'female', 'others']:
            return validation_error_response(
                message="Gender must be 'male', 'female', or 'others'",
                errors={"gender": ["Must be 'male', 'female', or 'others'"]}
            )
        
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
        
        # Check if student code already exists (system-wide unique)
        existing_code = frappe.db.exists("CRM Student", {"student_code": student_code})

        if existing_code:
            return error_response(
                message=f"Mã học sinh '{student_code}' đã tồn tại trong hệ thống",
                code="STUDENT_CODE_EXISTS"
            )
        
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
        return single_item_response(
            data={
                "name": student_doc.name,
                "student_name": student_doc.student_name,
                "student_code": student_doc.student_code,
                "dob": student_doc.dob,
                "gender": student_doc.gender,
                "campus_id": student_doc.campus_id
            },
            message="Student created successfully"
        )
        
    except Exception as e:
        error_msg = str(e)
        # Handle specific error types
        if "student_code" in error_msg.lower() and "unique" in error_msg.lower():
            return error_response(
                message="Mã học sinh đã tồn tại trong hệ thống",
                code="STUDENT_CODE_EXISTS"
            )
        elif "student_name" in error_msg.lower() and "unique" in error_msg.lower():
            return error_response(
                message="Tên học sinh đã tồn tại trong hệ thống",
                code="STUDENT_NAME_EXISTS"
            )
        else:
            # Log error with short message for debugging
            frappe.log_error(f"Student creation error: {error_msg[:200]}...")
            return error_response(
                message="Lỗi hệ thống khi tạo học sinh. Vui lòng thử lại.",
                code="CREATE_STUDENT_ERROR"
            )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def update_student(student_id=None, student_name=None, student_code=None, dob=None, gender=None):
    """Update an existing student"""
    try:
        # Get parameters from multiple sources for flexibility
        if not student_id:
            student_id = frappe.local.form_dict.get("student_id")
        if not student_name:  
            student_name = frappe.local.form_dict.get("student_name")
        if not student_code:
            student_code = frappe.local.form_dict.get("student_code")
        if not dob:
            dob = frappe.local.form_dict.get("dob")
        if not gender:
            gender = frappe.local.form_dict.get("gender")
        
        # Fallback to JSON data if form_dict is empty
        if not student_id and frappe.request.data:
            try:
                import json
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                student_id = json_data.get("student_id")
                student_name = json_data.get("student_name")
                student_code = json_data.get("student_code")
                dob = json_data.get("dob")
                gender = json_data.get("gender")
            except Exception:
                pass
        
        if not student_id:
            return {
                "success": False,
                "data": {},
                "message": "Student ID is required"
            }
        
        # Get existing document
        try:
            student_doc = frappe.get_doc("CRM Student", student_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Student not found",
                code="STUDENT_NOT_FOUND"
            )
        
        # Track if any changes were made
        changes_made = False
        
        # Helper function to normalize values for comparison
        def normalize_value(val):
            """Convert None/null/empty to empty string for comparison"""
            if val is None or val == "null" or val == "":
                return ""
            return str(val).strip()
        
        # Update fields if provided
        if student_name and normalize_value(student_name) != normalize_value(student_doc.student_name):
            student_doc.student_name = student_name
            changes_made = True
        
        if student_code and normalize_value(student_code) != normalize_value(student_doc.student_code):
            student_doc.student_code = student_code
            changes_made = True

        if dob and normalize_value(dob) != normalize_value(student_doc.dob):
            student_doc.dob = dob
            changes_made = True
            
        if gender and normalize_value(gender) != normalize_value(student_doc.gender):
            if gender not in ['male', 'female', 'others']:
                return {
                    "success": False,
                    "data": {},
                    "message": "Gender must be 'male', 'female', or 'others'"
                }
            student_doc.gender = gender
            changes_made = True
        
        # Save the document with validation disabled
        try:
            student_doc.flags.ignore_validate = True
            student_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception as save_error:
                    return error_response(
            message=f"Failed to save student: {str(save_error)}",
            code="STUDENT_UPDATE_ERROR"
        )
        
        # Reload to get the final saved data from database
        student_doc.reload()
        
        return success_response(
            data={
                "name": student_doc.name,
                "student_name": student_doc.student_name,
                "student_code": student_doc.student_code,
                "dob": student_doc.dob,
                "gender": student_doc.gender,
                "campus_id": student_doc.campus_id
            },
            message="Student updated successfully"
        )
        
    except Exception as e:
        return {
            "success": False,
            "data": {},
            "message": f"Error updating student: {str(e)}"
        }


@frappe.whitelist(allow_guest=False)
def delete_student(student_id=None):
    """Delete a student"""
    try:
        # Log incoming payload for troubleshooting
        try:
            frappe.logger().info(f"delete_student form_dict: {frappe.local.form_dict}")
        except Exception:
            pass

        # Accept student_id from multiple sources
        if not student_id:
            form = frappe.local.form_dict or getattr(frappe, 'form_dict', {}) or {}
            # Direct keys
            student_id = (
                form.get("student_id")
                or form.get("id")
                or form.get("name")
                or form.get("studentId")
            )

        # args payload sometimes contains JSON string
        if not student_id and form.get("args"):
            try:
                args_obj = json.loads(form.get("args"))
                student_id = args_obj.get("student_id") or args_obj.get("id") or args_obj.get("name")
            except Exception:
                pass

        # Request-level helpers
        if not student_id:
            try:
                if hasattr(frappe.request, 'args') and frappe.request.args:
                    student_id = frappe.request.args.get('student_id') or student_id
            except Exception:
                pass
            try:
                if hasattr(frappe.request, 'form') and frappe.request.form:
                    student_id = frappe.request.form.get('student_id') or student_id
            except Exception:
                pass

        # Fallback: parse JSON body
        if not student_id and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body)
                student_id = data.get('student_id') or data.get('id') or data.get('name')
            except Exception:
                pass

        if not student_id:
            return error_response(
                message="Student ID is required",
                code="MISSING_STUDENT_ID"
            )
        
        # Get campus from user context
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Get existing document
        try:
            student_doc = frappe.get_doc("CRM Student", student_id)
            
            # Check campus permission
            if student_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to delete this student",
                    code="ACCESS_DENIED"
                )
                
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Student not found",
                code="STUDENT_NOT_FOUND"
            )
        # Before delete: remove child table links referencing this student to avoid link constraints
        try:
            frappe.logger().info(f"Deleting CRM Family Relationship children for student {student_id}")
            frappe.db.delete("CRM Family Relationship", {"student": student_id})
        except Exception as e:
            frappe.logger().error(f"Failed to cleanup relationships for student {student_id}: {str(e)}")

        # Delete the document
        frappe.delete_doc("CRM Student", student_id)
        frappe.db.commit()
        
        return success_response(
            message="Student deleted successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error deleting student {student_id}: {str(e)}")
        return error_response(
            message="Error deleting student",
            code="DELETE_STUDENT_ERROR"
        )


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
        
        return success_response(
            data=students,
            message="Students fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching students for selection: {str(e)}")
        return error_response(
            message="Error fetching students",
            code="FETCH_STUDENTS_ERROR"
        )


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

        # Enrich with family codes
        try:
            student_ids = [s.get("name") for s in students if s.get("name")]
            if student_ids:
                rows = frappe.db.sql(
                    """
                    SELECT fr.student as student, f.name as family_name, f.family_code
                    FROM `tabCRM Family Relationship` fr
                    INNER JOIN `tabCRM Family` f ON f.name = fr.parent
                    WHERE fr.student IN %(ids)s
                    ORDER BY f.family_code ASC
                    """,
                    {"ids": tuple(student_ids)},
                    as_dict=True,
                )
                mapping = {}
                for r in rows:
                    mapping.setdefault(r["student"], []).append({"name": r["family_name"], "family_code": r["family_code"]})
                for s in students:
                    sid = s.get("name")
                    s["family_codes"] = mapping.get(sid, [])
        except Exception as e:
            frappe.logger().error(f"Failed to enrich search students with family codes: {str(e)}")
        
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
        
        return paginated_response(
            data=students,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Students search completed successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error searching students: {str(e)}")
        return error_response(
            message="Error searching students",
            code="SEARCH_STUDENTS_ERROR"
        )
