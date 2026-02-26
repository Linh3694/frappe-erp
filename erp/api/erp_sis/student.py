
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
                # user_image will be added from SIS Photo in enrichment step below
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
        
        # ✨ Enrich with photos from SIS Photo (batch query) - same as batch_get_students
        # Wrapped in try-except to ensure API returns data even if photo enrichment fails
        try:
            if len(students) > 0:
                student_ids_for_photos = [s.get('name') for s in students if s.get('name')]
                if student_ids_for_photos:
                    frappe.logger().info(f"📸 [get_all_students] Enriching {len(student_ids_for_photos)} students with photos from SIS Photo")
                    
                    # Lấy năm học hiện tại đang active
                    current_school_year = frappe.db.get_value(
                        "SIS School Year",
                        {"is_enable": 1},
                        "name",
                        order_by="start_date desc"
                    )
                    
                    # Get all active photos for these students in one query
                    # Ưu tiên: 1) Năm học hiện tại trước, 2) Upload date mới nhất, 3) Creation mới nhất
                    photos = frappe.db.sql("""
                        SELECT 
                            student_id,
                            photo,
                            upload_date,
                            school_year_id
                        FROM `tabSIS Photo`
                        WHERE student_id IN %(student_ids)s
                            AND type = 'student'
                            AND status = 'Active'
                        ORDER BY 
                            CASE WHEN school_year_id = %(current_year)s THEN 0 ELSE 1 END,
                            upload_date DESC,
                            creation DESC
                    """, {"student_ids": student_ids_for_photos, "current_year": current_school_year}, as_dict=True)
                    
                    frappe.logger().info(f"📸 [get_all_students] Found {len(photos)} photos from SIS Photo")
                    
                    # Create mapping: student_id -> photo URL
                    photo_map = {}
                    for photo in photos:
                        student_id = photo.get('student_id')
                        if student_id and student_id not in photo_map:
                            photo_url = photo.get('photo')
                            if photo_url:
                                # Convert to full URL if needed
                                if photo_url.startswith('/files/'):
                                    photo_url = frappe.utils.get_url(photo_url)
                                elif not photo_url.startswith('http'):
                                    photo_url = frappe.utils.get_url('/files/' + photo_url)
                                photo_map[student_id] = photo_url
                    
                    # Enrich students with photo URLs (overwrites user_image from CRM Student if SIS Photo exists)
                    for student in students:
                        student_id = student.get('name')
                        sis_photo = photo_map.get(student_id)
                        if sis_photo:
                            student['user_image'] = sis_photo
                    
                    frappe.logger().info(f"✅ [get_all_students] Enriched {len(photo_map)} students with SIS Photo images")
        except Exception as e:
            # Log error but DON'T fail the API - students without photos is better than no students at all
            frappe.logger().error(f"❌ [get_all_students] Failed to enrich students with photos: {str(e)}")
            frappe.logger().error(f"❌ [get_all_students] Traceback: {frappe.get_traceback()}")
        
        # Always return all students without pagination info
        return success_response(
            data=students,
            message=f"Fetched all {len(students)} students successfully"
        )
        
    except Exception as e:
        error_msg = f"Error fetching students: {str(e)}"
        frappe.logger().error(f"❌ [get_all_students] {error_msg}")
        frappe.logger().error(f"❌ [get_all_students] Full traceback: {frappe.get_traceback()}")
        frappe.log_error(error_msg)
        return error_response(
            message=error_msg,
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
        
        # Get student photo if exists
        student_photo = None
        try:
            # Lấy năm học hiện tại đang active
            current_school_year = frappe.db.get_value(
                "SIS School Year",
                {"is_enable": 1},
                "name",
                order_by="start_date desc"
            )
            
            # Find the most recent active student photo
            # Ưu tiên: 1) Năm học hiện tại trước, 2) Upload date mới nhất, 3) Creation mới nhất
            photos = frappe.db.sql("""
                SELECT photo
                FROM `tabSIS Photo`
                WHERE student_id = %s
                    AND type = 'student'
                    AND status = 'Active'
                ORDER BY 
                    CASE WHEN school_year_id = %s THEN 0 ELSE 1 END,
                    upload_date DESC,
                    creation DESC
                LIMIT 1
            """, (student.name, current_school_year), as_dict=True)

            if photos and photos[0].get("photo"):
                student_photo = photos[0]["photo"]
                frappe.logger().info(f"✅ Found photo for student {student.name}: {student_photo}")
            else:
                frappe.logger().info(f"ℹ️ No photo found for student {student.name}")
        except Exception as photo_err:
            frappe.logger().warning(f"⚠️ Error fetching photo for student {student.name}: {str(photo_err)}")

        return single_item_response(
            data={
                "name": student.name,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "dob": student.dob,
                "gender": student.gender,
                "campus_id": student.campus_id,
                "photo": student_photo
            },
            message="Student fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching student {student_id}: {str(e)}")
        return error_response(
            message="Error fetching student",
            code="FETCH_STUDENT_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def batch_get_students():
    """Get multiple students by IDs in a single request
    
    ⚡ Performance: Cached for 15 minutes (master data)
    
    Request body:
    {
        "student_ids": ["STU-001", "STU-002", ...]
    }
    
    Returns:
    {
        "success": true,
        "data": [
            { "name": "STU-001", "student_name": "...", ... },
            { "name": "STU-002", "student_name": "...", ... }
        ]
    }
    """
    try:
        frappe.logger().info("🚀 [Backend] batch_get_students called")
        
        # Parse request data
        data = {}
        if frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                frappe.logger().info(f"📥 [Backend] Raw request body: {body[:200] if len(str(body)) > 200 else body}")
                data = json.loads(body) if body else {}
                frappe.logger().info(f"📦 [Backend] Parsed data keys: {list(data.keys())}")
            except Exception as e:
                frappe.logger().error(f"❌ [Backend] batch_get_students: JSON parse failed: {str(e)}")
                return error_response(
                    message="Invalid JSON data",
                    code="INVALID_JSON"
                )
        
        # Get student_ids from request
        student_ids = data.get('student_ids', [])
        
        if not student_ids or not isinstance(student_ids, list):
            return validation_error_response(
                message="student_ids is required and must be an array",
                errors={"student_ids": ["Required array field"]}
            )
        
        if len(student_ids) == 0:
            return success_response(
                data=[],
                message="No students requested"
            )
        
        # ⚡ CACHE: Try to get from individual student caches first (15 min TTL - master data)
        cached_students = {}
        missing_ids = []
        
        try:
            cache = frappe.cache()
            for sid in student_ids:
                cache_key = f"student:{sid}"
                cached = cache.get_value(cache_key)
                if cached:
                    cached_students[sid] = cached
                else:
                    missing_ids.append(sid)
            
            if cached_students:
                frappe.logger().info(f"✅ Cache HIT for {len(cached_students)}/{len(student_ids)} students")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
            missing_ids = student_ids  # Fetch all if cache fails
        
        if not missing_ids:
            # All students from cache
            return success_response(
                data=list(cached_students.values()),
                message=f"Successfully fetched {len(cached_students)} students (all from cache)"
            )
        
        frappe.logger().info(f"❌ Cache MISS for {len(missing_ids)} students - fetching from DB")
        frappe.logger().info(f"🔍 [Backend] batch_get_students: Fetching {len(missing_ids)} students from DB")
        
        # Get current user's campus (for permission check)
        campus_id = get_current_campus_from_context()
        
        # Batch query only missing students by IDs
        students = frappe.get_all(
            "CRM Student",
            filters={"name": ["in", missing_ids]},
            fields=[
                "name",
                "student_name", 
                "student_code",
                "dob",
                "gender",
                "campus_id"
            ]
        )
        
        # Filter by campus if campus_id is set (for multi-tenancy)
        if campus_id:
            students = [s for s in students if s.get('campus_id') == campus_id]
        
        frappe.logger().info(f"✅ [Backend] batch_get_students: Found {len(students)} students")
        
        # ✨ Enrich với ảnh từ SIS Photo (batch query)
        if len(students) > 0:
            try:
                frappe.logger().info(f"📸 [Backend] Enriching {len(students)} students with photos")
                
                # Lấy năm học hiện tại đang active
                current_school_year = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1},
                    "name",
                    order_by="start_date desc"
                )
                
                # Get all active photos for these students in one query
                # Ưu tiên: 1) Năm học hiện tại trước, 2) Upload date mới nhất, 3) Creation mới nhất
                student_ids_for_photos = [s.get('name') for s in students]
                photos = frappe.db.sql("""
                    SELECT 
                        student_id,
                        photo,
                        upload_date,
                        school_year_id
                    FROM `tabSIS Photo`
                    WHERE student_id IN %(student_ids)s
                        AND type = 'student'
                        AND status = 'Active'
                    ORDER BY 
                        CASE WHEN school_year_id = %(current_year)s THEN 0 ELSE 1 END,
                        upload_date DESC,
                        creation DESC
                """, {"student_ids": student_ids_for_photos, "current_year": current_school_year}, as_dict=True)
                
                # Create mapping: student_id -> photo URL
                photo_map = {}
                for photo in photos:
                    student_id = photo.get('student_id')
                    if student_id and student_id not in photo_map:
                        photo_url = photo.get('photo')
                        if photo_url:
                            # Convert to full URL if needed
                            if photo_url.startswith('/files/'):
                                photo_url = frappe.utils.get_url(photo_url)
                            elif not photo_url.startswith('http'):
                                photo_url = frappe.utils.get_url('/files/' + photo_url)
                            photo_map[student_id] = photo_url
                
                # Enrich students with photo URLs
                for student in students:
                    student_id = student.get('name')
                    student['user_image'] = photo_map.get(student_id)
                
                frappe.logger().info(f"📸 [Backend] Enriched {len(photo_map)} students with photos")
                
            except Exception as photo_error:
                # Don't fail the whole request if photo loading fails
                frappe.logger().warning(f"⚠️ [Backend] Failed to load photos: {str(photo_error)}")
        
        # ⚡ CACHE: Store individual students in cache (15 min = 900 sec)
        try:
            for student in students:
                cache_key = f"student:{student['name']}"
                cache.set_value(cache_key, student, expires_in_sec=900)
            frappe.logger().info(f"✅ Cached {len(students)} students individually")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")
        
        # Combine cached and freshly fetched students
        all_students = list(cached_students.values()) + students
        
        return success_response(
            data=all_students,
            message=f"Successfully fetched {len(all_students)} students ({len(cached_students)} from cache, {len(students)} from DB)"
        )
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        # Log to console (full detail)
        frappe.logger().error(f"❌ [Backend] batch_get_students error: {str(e)}")
        frappe.logger().error(f"❌ [Backend] Full traceback: {error_detail}")
        # Log to Error Log (shortened to avoid character limit)
        frappe.log_error(f"batch_get_students: {str(e)[:100]}", "Batch Get Students Error")
        return error_response(
            message=f"Failed to fetch students: {str(e)}",
            code="BATCH_GET_STUDENTS_ERROR"
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
def search_students(search_term=None):
    """Search students - returns all matching results without pagination"""
    try:
        # Normalize parameters: prefer form_dict values if provided
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')

        frappe.logger().info(f"search_students called with search_term: '{search_term}'")
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        
        if not campus_id:
            campus_id = "campus-1"
        
        # Build search terms and campus filter (use parameterized queries)
        where_clauses = ["campus_id = %s"]
        params = [campus_id]
        if search_term and str(search_term).strip():
            # For student_code: prefix match (starts with)
            # For student_name: contains match (can be anywhere)
            search_clean = str(search_term).strip()
            like_prefix = f"{search_clean}%"  # Starts with (for student_code)
            like_contains = f"%{search_clean}%"  # Contains (for student_name)
            where_clauses.append("(LOWER(student_name) LIKE LOWER(%s) OR LOWER(student_code) LIKE LOWER(%s))")
            params.extend([like_contains, like_prefix])
        conditions = " AND ".join(where_clauses)
        frappe.logger().info(f"FINAL WHERE: {conditions} | params: {params}")
        
        # Get all matching students without pagination
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

        frappe.logger().info(f"EXECUTING SQL QUERY: {sql_query} | params={params}")

        students = frappe.db.sql(sql_query, params, as_dict=True)

        frappe.logger().info(f"SQL QUERY RETURNED {len(students)} students")
        if students:
            frappe.logger().info(f"FIRST 5 RESULTS: {[f'{s.student_name} ({s.student_code})' for s in students[:5]]}")

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
            search_lower = str(search_term).strip().lower()
            pre_count = len(students)
            students = [
                s for s in students
                if (
                    # student_name: contains match (can be anywhere)
                    normalize_text(s.get('student_name', '')).find(norm_q) != -1
                    # student_code: prefix match (must start with)
                    or (s.get('student_code') or '').lower().startswith(search_lower)
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
        
        # Enrich với thông tin lớp hiện tại (năm học đang active)
        try:
            student_ids = [s.get("name") for s in students if s.get("name")]
            if student_ids:
                # Lấy năm học hiện tại (is_enable = 1)
                current_school_year = frappe.db.get_value(
                    "SIS School Year",
                    {"is_enable": 1, "campus_id": campus_id},
                    "name",
                    order_by="start_date desc"
                )
                # Fallback nếu không có campus filter
                if not current_school_year:
                    current_school_year = frappe.db.get_value(
                        "SIS School Year",
                        {"is_enable": 1},
                        "name",
                        order_by="start_date desc"
                    )
                
                if current_school_year:
                    # Lấy thông tin lớp của học sinh trong năm học hiện tại
                    class_rows = frappe.db.sql(
                        """
                        SELECT 
                            cs.student_id,
                            c.name as class_id,
                            c.title as class_title
                        FROM `tabSIS Class Student` cs
                        INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
                        WHERE cs.student_id IN %(ids)s
                          AND cs.school_year_id = %(year)s
                          AND c.school_year_id = %(year)s
                        """,
                        {"ids": tuple(student_ids), "year": current_school_year},
                        as_dict=True,
                    )
                    # Tạo mapping: student_id -> class info
                    class_mapping = {}
                    for r in class_rows:
                        class_mapping[r["student_id"]] = {
                            "class_id": r["class_id"],
                            "class_title": r["class_title"]
                        }
                    # Gán vào students
                    for s in students:
                        sid = s.get("name")
                        if sid in class_mapping:
                            s["current_class_id"] = class_mapping[sid]["class_id"]
                            s["current_class_title"] = class_mapping[sid]["class_title"]
        except Exception as e:
            frappe.logger().error(f"Failed to enrich search students with class info: {str(e)}")
        
        # Return all search results without pagination
        return success_response(
            data=students,
            message=f"Search completed successfully - found {len(students)} students"
        )
        
    except Exception as e:
        frappe.log_error(f"Error searching students: {str(e)}")
        return error_response(
            message="Error searching students",
            code="SEARCH_STUDENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def search_students_by_school_year(search_term=None, school_year_id=None):
    """
    Search students by school year - returns students enrolled in the specified school year
    Gets data from SIS Class Student to include current class information
    """
    try:
        # Debug: Log all request parameters
        frappe.logger().info(f"🔍 DEBUG - Request parameters:")
        frappe.logger().info(f"  - form_dict: {frappe.local.form_dict}")
        frappe.logger().info(f"  - function args: search_term={search_term}, school_year_id={school_year_id}")
        if hasattr(frappe.request, 'args'):
            frappe.logger().info(f"  - request.args: {frappe.request.args}")
        
        # Normalize parameters - prefer form_dict values
        form = frappe.local.form_dict or {}
        if 'search_term' in form and (search_term is None or str(search_term).strip() == ''):
            search_term = form.get('search_term')
        if 'school_year_id' in form and (school_year_id is None or str(school_year_id).strip() == ''):
            school_year_id = form.get('school_year_id')
        
        # Also try from request.args (GET parameters)
        if hasattr(frappe.request, 'args') and not school_year_id:
            school_year_id = frappe.request.args.get('school_year_id')
        
        # Clean and validate school_year_id
        school_year_id = str(school_year_id).strip() if school_year_id else None
        
        frappe.logger().info(f"search_students_by_school_year called with school_year_id: '{school_year_id}', search_term: '{search_term}'")
        
        if not school_year_id or school_year_id == '' or school_year_id == 'None':
            return error_response(
                message="Thiếu tham số năm học (school_year_id)",
                code="MISSING_SCHOOL_YEAR"
            )
        
        # Get current user's campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"
        
        # Query to get students enrolled in the school year with their class info
        # JOIN with SIS Class Student to get only students in this school year
        # and include their class information
        sql_query = """
            SELECT DISTINCT
                s.name,
                s.student_name,
                s.student_code,
                s.dob,
                s.gender,
                s.campus_id,
                s.creation,
                s.modified,
                c.title as current_class_title,
                c.name as current_class_id
            FROM `tabCRM Student` s
            INNER JOIN `tabSIS Class Student` cs ON cs.student_id = s.name
            INNER JOIN `tabSIS Class` c ON c.name = cs.class_id
            WHERE s.campus_id = %s
              AND cs.school_year_id = %s
              AND c.school_year_id = %s
        """
        
        params = [campus_id, school_year_id, school_year_id]
        
        # Add search term filter if provided
        if search_term and str(search_term).strip():
            search_clean = str(search_term).strip()
            like_prefix = f"{search_clean}%"
            like_contains = f"%{search_clean}%"
            sql_query += " AND (LOWER(s.student_name) LIKE LOWER(%s) OR LOWER(s.student_code) LIKE LOWER(%s))"
            params.extend([like_contains, like_prefix])
        
        sql_query += " ORDER BY s.student_name ASC"
        
        frappe.logger().info(f"EXECUTING SQL: {sql_query} | params={params}")
        
        students = frappe.db.sql(sql_query, params, as_dict=True)
        
        # Format data to include current_class object
        for student in students:
            if student.get('current_class_title'):
                student['current_class'] = {
                    'name': student.get('current_class_id'),
                    'title': student.get('current_class_title')
                }
            # Remove redundant fields
            student.pop('current_class_title', None)
            student.pop('current_class_id', None)
        
        frappe.logger().info(f"Found {len(students)} students in school year '{school_year_id}'")
        
        return success_response(
            data=students,
            message=f"Found {len(students)} students in school year"
        )
        
    except Exception as e:
        frappe.log_error(f"Error searching students by school year: {str(e)}")
        return error_response(
            message="Error searching students by school year",
            code="SEARCH_STUDENTS_BY_YEAR_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def get_student_profile():
    """
    Get comprehensive student profile information including:
    - Basic info (name, code, dob, gender, avatar)
    - Homeroom class with teachers and academic program
    - Running classes
    - Student subjects
    """
    try:
        # Get student_id from multiple sources
        form = getattr(frappe, 'form_dict', None) or {}
        local_form = getattr(frappe.local, 'form_dict', None) or {}
        request = getattr(frappe, 'request', None)
        request_args = getattr(request, 'args', None) if request else {}
        request_data = getattr(request, 'data', None) if request else None

        payload = {}
        if request_data:
            try:
                body = request_data.decode('utf-8') if isinstance(request_data, bytes) else request_data
                payload = json.loads(body) if body else {}
            except Exception as e:
                frappe.logger().info(f"get_student_profile: JSON parse failed: {str(e)}")

        def pick(d, keys):
            for k in keys:
                if d and d.get(k):
                    return d.get(k)
            return None

        student_id = (
            pick(form, ['student_id', 'id', 'name'])
            or pick(local_form, ['student_id', 'id', 'name'])
            or pick(request_args, ['student_id', 'id', 'name'])
            or pick(payload, ['student_id', 'id', 'name'])
        )

        school_year_id = (
            pick(form, ['school_year_id', 'schoolYearId'])
            or pick(local_form, ['school_year_id', 'schoolYearId'])
            or pick(request_args, ['school_year_id', 'schoolYearId'])
            or pick(payload, ['school_year_id', 'schoolYearId'])
        )

        if not student_id:
            return error_response(message="Student ID is required")

        # Get current campus
        campus_id = get_current_campus_from_context()
        if not campus_id:
            campus_id = "campus-1"

        # Get student basic info
        student = frappe.get_doc("CRM Student", student_id)
        
        # Determine school year to use (cần xác định trước để lấy ảnh theo năm học)
        if not school_year_id:
            # Get current school year if not provided
            current_school_year = frappe.db.get_value(
                "SIS School Year",
                filters={"is_enable": 1, "campus_id": campus_id},
                fieldname="name"
            )
            if current_school_year:
                school_year_id = current_school_year
        
        # Lấy ảnh học sinh - ưu tiên ảnh theo năm học hiện tại
        student_photo = None
        try:
            # Bước 1: Lấy ảnh theo năm học (nếu có school_year_id)
            if school_year_id:
                photos = frappe.get_all(
                    "SIS Photo",
                    filters={
                        "student_id": student.name,
                        "type": "student",
                        "status": "Active",
                        "school_year_id": school_year_id
                    },
                    fields=["photo"],
                    order_by="creation desc",
                    limit=1
                )
                if photos and photos[0].get("photo"):
                    student_photo = photos[0]["photo"]
            
            # Bước 2: Fallback - lấy ảnh mới nhất nếu không có ảnh năm học
            if not student_photo:
                photos = frappe.get_all(
                    "SIS Photo",
                    filters={
                        "student_id": student.name,
                        "type": "student",
                        "status": "Active"
                    },
                    fields=["photo"],
                    order_by="creation desc",
                    limit=1
                )
                if photos and photos[0].get("photo"):
                    student_photo = photos[0]["photo"]
        except Exception as photo_err:
            frappe.logger().warning(f"Error fetching photo for student {student.name}: {str(photo_err)}")

        # Build SQL query parameters
        sql_params = {"student_id": student_id}
        school_year_filter = ""
        if school_year_id:
            school_year_filter = "AND cs.school_year_id = %(school_year_id)s"
            sql_params["school_year_id"] = school_year_id

        # Get homeroom class (Regular class type)
        homeroom_class = None
        homeroom_class_student = frappe.db.sql("""
            SELECT
                cs.name as class_student_id,
                cs.class_id,
                c.title as class_name,
                c.short_title as class_short_title,
                c.homeroom_teacher,
                c.vice_homeroom_teacher,
                c.academic_program,
                c.room,
                t1.user_id as homeroom_teacher_user_id,
                u1.full_name as homeroom_teacher_name,
                u1.email as homeroom_teacher_email,
                u1.user_image as homeroom_teacher_user_image,
                t2.user_id as vice_homeroom_teacher_user_id,
                u2.full_name as vice_homeroom_teacher_name,
                u2.email as vice_homeroom_teacher_email,
                u2.user_image as vice_homeroom_teacher_user_image,
                ap.title_vn as academic_program_name
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            LEFT JOIN `tabSIS Teacher` t1 ON c.homeroom_teacher = t1.name
            LEFT JOIN `tabUser` u1 ON t1.user_id = u1.name
            LEFT JOIN `tabSIS Teacher` t2 ON c.vice_homeroom_teacher = t2.name
            LEFT JOIN `tabUser` u2 ON t2.user_id = u2.name
            LEFT JOIN `tabSIS Academic Program` ap ON c.academic_program = ap.name
            WHERE cs.student_id = %(student_id)s
                AND c.class_type = 'Regular'
                {school_year_filter}
            LIMIT 1
        """.format(school_year_filter=school_year_filter), sql_params, as_dict=True)

        if homeroom_class_student and len(homeroom_class_student) > 0:
            homeroom_class = homeroom_class_student[0]

        # Build SQL query parameters for running classes
        sql_params_running = {"student_id": student_id}
        school_year_filter_running = ""
        if school_year_id:
            school_year_filter_running = "AND cs.school_year_id = %(school_year_id)s"
            sql_params_running["school_year_id"] = school_year_id

        # Get mixed classes (running/extra-curricular classes)
        running_classes = frappe.db.sql("""
            SELECT
                cs.name as class_student_id,
                cs.class_id,
                c.title as class_name,
                c.short_title as class_short_title,
                c.homeroom_teacher,
                c.room,
                t1.user_id as homeroom_teacher_user_id,
                u1.full_name as homeroom_teacher_name,
                u1.user_image as homeroom_teacher_user_image
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            LEFT JOIN `tabSIS Teacher` t1 ON c.homeroom_teacher = t1.name
            LEFT JOIN `tabUser` u1 ON t1.user_id = u1.name
            WHERE cs.student_id = %(student_id)s
                AND c.class_type = 'mixed'
                {school_year_filter}
            ORDER BY c.title ASC
        """.format(school_year_filter=school_year_filter_running), sql_params_running, as_dict=True)

        # Build SQL query parameters for student subjects
        sql_params_subjects = {"student_id": student_id}
        school_year_filter_subjects = ""
        if school_year_id:
            school_year_filter_subjects = "AND ss.school_year_id = %(school_year_id)s"
            sql_params_subjects["school_year_id"] = school_year_id

        # Get student subjects with teacher information
        student_subjects = frappe.db.sql("""
            SELECT
                ss.name,
                ss.subject_id,
                s.title as subject_name,
                s.title as subject_name_en,
                ss.actual_subject_id,
                acts.title_vn as actual_subject_name,
                ss.class_id,
                c.title as class_name,
                -- Teacher information from Subject Assignment (concatenated)
                GROUP_CONCAT(DISTINCT CONCAT(
                    t.user_id, '|',
                    u.full_name, '|',
                    u.email, '|',
                    COALESCE(u.user_image, '')
                ) SEPARATOR ';') as teachers_info
            FROM `tabSIS Student Subject` ss
            INNER JOIN `tabSIS Subject` s ON ss.subject_id = s.name
            LEFT JOIN `tabSIS Actual Subject` acts ON ss.actual_subject_id = acts.name
            LEFT JOIN `tabSIS Class` c ON ss.class_id = c.name
            LEFT JOIN `tabSIS Subject Assignment` sa ON sa.class_id = ss.class_id AND sa.actual_subject_id = ss.actual_subject_id
            LEFT JOIN `tabSIS Teacher` t ON sa.teacher_id = t.name
            LEFT JOIN `tabUser` u ON t.user_id = u.name
            WHERE ss.student_id = %(student_id)s
                AND sa.teacher_id IS NOT NULL
            GROUP BY ss.name, ss.subject_id, s.title, s.title, ss.actual_subject_id, acts.title_vn, ss.class_id, c.title
            ORDER BY s.title ASC
        """, sql_params_subjects, as_dict=True)

        # Process teachers_info to create teacher arrays
        for subject in student_subjects:
            if subject.get('teachers_info'):
                teachers = []
                for teacher_info in subject['teachers_info'].split(';'):
                    if teacher_info.strip():
                        parts = teacher_info.split('|')
                        if len(parts) >= 3:
                            teachers.append({
                                'user_id': parts[0],
                                'full_name': parts[1],
                                'email': parts[2],
                                'user_image': parts[3] if len(parts) > 3 and parts[3] else None
                            })
                subject['teachers'] = teachers
                # Keep backward compatibility with single teacher fields
                if teachers:
                    subject['teacher_id'] = teachers[0].get('teacher_id')
                    subject['teacher_user_id'] = teachers[0].get('user_id')
                    subject['teacher_name'] = teachers[0].get('full_name')
                    subject['teacher_email'] = teachers[0].get('email')
                    subject['teacher_user_image'] = teachers[0].get('user_image')
                else:
                    subject['teachers'] = []
                    subject['teacher_id'] = None
                    subject['teacher_user_id'] = None
                    subject['teacher_name'] = None
                    subject['teacher_email'] = None
                    subject['teacher_user_image'] = None
            else:
                subject['teachers'] = []
                subject['teacher_id'] = None
                subject['teacher_user_id'] = None
                subject['teacher_name'] = None
                subject['teacher_email'] = None
                subject['teacher_user_image'] = None

        # Build response
        profile_data = {
            "basic_info": {
                "student_id": student.name,
                "student_name": student.student_name,
                "student_code": student.student_code,
                "dob": student.dob,
                "gender": student.gender,
                "photo": student_photo,
                "campus_id": student.campus_id
            },
            "homeroom_class": homeroom_class,
            "running_classes": running_classes,
            "student_subjects": student_subjects
        }

        return success_response(
            data=profile_data,
            message="Student profile fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching student profile: {str(e)}")
        return error_response(
            message="Error fetching student profile",
            code="FETCH_STUDENT_PROFILE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['GET', 'POST'])
def check_homeroom_teacher_permission():
    """
    Check if current user has permission to view student's family/services tabs.
    Permission granted if:
    - User is homeroom teacher or vice-homeroom teacher of student's regular class
    - User has role SIS Manager or SIS BOD
    """
    try:
        # Get student_id from request
        form = getattr(frappe, 'form_dict', None) or {}
        local_form = getattr(frappe.local, 'form_dict', None) or {}
        request_args = getattr(getattr(frappe, 'request', None), 'args', None) or {}
        request_data = getattr(getattr(frappe, 'request', None), 'data', None)

        payload = {}
        if request_data:
            try:
                body = request_data.decode('utf-8') if isinstance(request_data, bytes) else request_data
                payload = json.loads(body) if body else {}
            except Exception:
                pass

        def pick(d, keys):
            for k in keys:
                if d and d.get(k):
                    return d.get(k)
            return None

        student_id = (
            pick(form, ['student_id', 'id'])
            or pick(local_form, ['student_id', 'id'])
            or pick(request_args, ['student_id', 'id'])
            or pick(payload, ['student_id', 'id'])
        )

        if not student_id:
            return error_response(message="Student ID is required")

        current_user = frappe.session.user
        
        # Check if user has SIS Manager or SIS BOD role
        user_roles = frappe.get_roles(current_user)
        if "SIS Manager" in user_roles or "SIS BOD" in user_roles:
            return success_response(
                data={"has_permission": True, "reason": "SIS Manager or SIS BOD role"},
                message="Permission granted"
            )

        # Get teacher record(s) for current user
        teacher_records = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": current_user},
            fields=["name"]
        )

        if not teacher_records:
            return success_response(
                data={"has_permission": False, "reason": "Not a teacher"},
                message="Permission denied"
            )

        teacher_ids = [t.name for t in teacher_records]

        # Get student's regular class
        student_class = frappe.db.sql("""
            SELECT 
                c.name as class_id,
                c.homeroom_teacher,
                c.vice_homeroom_teacher
            FROM `tabSIS Class Student` cs
            INNER JOIN `tabSIS Class` c ON cs.class_id = c.name
            WHERE cs.student_id = %(student_id)s
                AND c.class_type = 'Regular'
            LIMIT 1
        """, {"student_id": student_id}, as_dict=True)

        if not student_class:
            return success_response(
                data={"has_permission": False, "reason": "Student has no regular class"},
                message="Permission denied"
            )

        class_doc = student_class[0]
        
        # Check if teacher is homeroom or vice-homeroom
        is_homeroom = (
            class_doc.homeroom_teacher in teacher_ids or 
            class_doc.vice_homeroom_teacher in teacher_ids
        )

        if is_homeroom:
            return success_response(
                data={"has_permission": True, "reason": "Homeroom or vice-homeroom teacher"},
                message="Permission granted"
            )

        return success_response(
            data={"has_permission": False, "reason": "Not homeroom teacher of student's class"},
            message="Permission denied"
        )

    except Exception as e:
        frappe.log_error(f"Error checking homeroom teacher permission: {str(e)}")
        return error_response(
            message="Error checking permission",
            code="CHECK_PERMISSION_ERROR"
        )
