import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    paginated_response,
    single_item_response,
    validation_error_response,
    not_found_response,
    forbidden_response
)


def _clear_teacher_classes_cache():
    """Clear Redis cache for get_teacher_classes API after class changes."""
    try:
        cache = frappe.cache()
        frappe.logger().info("🗑️ Starting cache clear for teacher classes...")
        
        # ⚡ Clear cache using Redis pattern matching (wildcard support)
        # Frappe cache uses Redis backend, so we can use Redis commands directly
        cache_patterns = [
            "teacher_classes:*",
            "teacher_classes_v2:*",
            "teacher_week:*",
            "teacher_week_v2:*",
            "class_week:*"
        ]
        
        total_deleted = 0
        for pattern in cache_patterns:
            try:
                # Get Redis connection from frappe cache
                redis_conn = cache.redis_cache if hasattr(cache, 'redis_cache') else cache
                
                # 🔍 DEBUG: Log Redis connection type
                frappe.logger().info(f"🔍 Redis connection type: {type(redis_conn).__name__}")
                
                # Use SCAN to find and delete keys matching pattern
                if hasattr(redis_conn, 'scan_iter'):
                    keys_to_delete = list(redis_conn.scan_iter(match=pattern, count=100))
                    if keys_to_delete:
                        redis_conn.delete(*keys_to_delete)
                        total_deleted += len(keys_to_delete)
                        frappe.logger().info(f"✅ Deleted {len(keys_to_delete)} cache keys matching '{pattern}'")
                    else:
                        frappe.logger().info(f"ℹ️ No cache keys found matching '{pattern}'")
                else:
                    frappe.logger().warning(f"⚠️ Redis connection does not support scan_iter, trying fallback for '{pattern}'")
                    # Fallback: Try direct delete (may not work with wildcard)
                    cache.delete_key(pattern)
            except Exception as pattern_error:
                frappe.logger().warning(f"❌ Failed to clear pattern '{pattern}': {pattern_error}")
        
        frappe.logger().info(f"✅ Cache clear complete: {total_deleted} total keys deleted")
    except Exception as cache_error:
        frappe.logger().warning(f"❌ Cache clear failed (non-critical): {cache_error}")


@frappe.whitelist(allow_guest=False)
def get_all_classes(school_year_id: str = None, campus_id: str = None):
    """List all classes with optional filter by school_year_id and campus_id."""
    try:
        # Get current user's campus information from roles/JWT
        if not campus_id:
            campus_id = get_current_campus_from_context()

        # If campus cannot be resolved, don't hard-fallback to a fixed campus
        # Allow showing classes across campuses to avoid returning empty lists on mobile

        # Apply campus filtering for data isolation
        filters = {"campus_id": (campus_id or "campus-1")}
        
        # accept school_year_id from query/form/body
        if not school_year_id:
            # Check query parameters first
            try:
                if hasattr(frappe.request, 'args') and frappe.request.args:
                    school_year_id = frappe.request.args.get('school_year_id')
            except Exception:
                pass

            # Check form data
            if not school_year_id:
                form = frappe.local.form_dict or {}
                school_year_id = form.get("school_year_id")

            # Check request body
            if not school_year_id and frappe.request and frappe.request.data:
                try:
                    body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                    data = json.loads(body or '{}')
                    school_year_id = data.get('school_year_id')
                except Exception:
                    pass

        if school_year_id:
            filters["school_year_id"] = school_year_id

        frappe.logger().info(f"Final filters: {filters}")

        classes = frappe.get_all(
            "SIS Class",
            fields=[
                "name",
                "title",
                "short_title",
                "campus_id",
                "school_year_id",
                "education_grade",
                "academic_program",
                "homeroom_teacher",
                "vice_homeroom_teacher",
                "room",
                "class_type",
                "creation",
                "modified",
            ],
            filters=filters,
            order_by="title asc"
        )

        frappe.logger().info(f"Found {len(classes)} classes with filters: {filters}")

        # Enhance classes with teacher information
        enhanced_classes = []
        for class_data in classes:
            enhanced_class = class_data.copy()

            # Get homeroom teacher details
            if class_data.get("homeroom_teacher"):
                teacher_info = frappe.get_all(
                    "SIS Teacher",
                    fields=["user_id"],
                    filters={"name": class_data["homeroom_teacher"]},
                    limit=1
                )

                if teacher_info:
                    teacher = teacher_info[0]
                    if teacher.get("user_id"):
                        # Get user information
                        user_info = frappe.get_all(
                            "User",
                            fields=[
                                "name",
                                "email",
                                "full_name",
                                "first_name",
                                "last_name",
                                "user_image"
                            ],
                            filters={"name": teacher["user_id"]},
                            limit=1
                        )

                        if user_info:
                            enhanced_class["homeroom_teacher_info"] = enrich_teacher_info(
                                teacher["user_id"],
                                class_data["homeroom_teacher"]
                            )

                        # Try to get employee information from Employee doctype (if available)
                        try:
                            employee_info = frappe.get_all(
                                "Employee",
                                fields=[
                                    "employee_number",
                                    "employee_name",
                                    "designation",
                                    "department"
                                ],
                                filters={"user_id": teacher["user_id"]},
                                limit=1
                            )

                            if employee_info and enhanced_class.get("homeroom_teacher_info"):
                                employee = employee_info[0]
                                enhanced_class["homeroom_teacher_info"].update({
                                    "employee_code": employee.get("employee_number"),
                                    "employee_name": employee.get("employee_name"),
                                    "designation": employee.get("designation"),
                                    "department": employee.get("department")
                                })
                        except Exception:
                            # Employee doctype might not exist or be accessible
                            pass

            # Get vice homeroom teacher details
            if class_data.get("vice_homeroom_teacher"):
                teacher_info = frappe.get_all(
                    "SIS Teacher",
                    fields=["user_id"],
                    filters={"name": class_data["vice_homeroom_teacher"]},
                    limit=1
                )

                if teacher_info:
                    teacher = teacher_info[0]
                    if teacher.get("user_id"):
                        # Get user information
                        user_info = frappe.get_all(
                            "User",
                            fields=[
                                "name",
                                "email",
                                "full_name",
                                "first_name",
                                "last_name",
                                "user_image"
                            ],
                            filters={"name": teacher["user_id"]},
                            limit=1
                        )

                        if user_info:
                            enhanced_class["vice_homeroom_teacher_info"] = enrich_teacher_info(
                                teacher["user_id"],
                                class_data["vice_homeroom_teacher"]
                            )

                        # Try to get employee information from Employee doctype (if available)
                        try:
                            employee_info = frappe.get_all(
                                "Employee",
                                fields=[
                                    "employee_number",
                                    "employee_name",
                                    "designation",
                                    "department"
                                ],
                                filters={"user_id": teacher["user_id"]},
                                limit=1
                            )

                            if employee_info and enhanced_class.get("vice_homeroom_teacher_info"):
                                employee = employee_info[0]
                                enhanced_class["vice_homeroom_teacher_info"].update({
                                    "employee_code": employee.get("employee_number"),
                                    "employee_name": employee.get("employee_name"),
                                    "designation": employee.get("designation"),
                                    "department": employee.get("department")
                                })
                        except Exception:
                            # Employee doctype might not exist or be accessible
                            pass

            enhanced_classes.append(enhanced_class)

        return success_response(
            data=enhanced_classes,
            message="Classes fetched successfully"
        )
    except Exception as e:
        frappe.log_error(f"Error fetching classes: {str(e)}")
        return error_response(f"Error fetching classes: {str(e)}")


def enrich_teacher_info(teacher_user_id, teacher_name):
    """Helper function to enrich teacher info with employee code"""
    if not teacher_user_id:
        return None

    try:
        # Get user information
        user_info = frappe.get_all(
            "User",
            fields=[
                "name",
                "email",
                "full_name",
                "first_name",
                "last_name",
                "user_image"
            ],
            filters={"name": teacher_user_id},
            limit=1
        )

        if user_info:
            user = user_info[0]

            # Get employee code from multiple possible fields
            employee_code = user.get("employee_code")
            if not employee_code:
                employee_code = user.get("employee_number") or user.get("employee_id")
            if not employee_code:
                employee_code = user.get("job_title") or user.get("designation")

            teacher_info = {
                "name": teacher_name,
                "user_id": teacher_user_id,
                "email": user.get("email"),
                "full_name": user.get("full_name"),
                "first_name": user.get("first_name"),
                "last_name": user.get("last_name"),
                "user_image": user.get("user_image"),
                "employee_code": employee_code,
                "teacher_name": user.get("full_name") or user.get("name")
            }

            # Try to get additional employee information from Employee doctype
            try:
                employee_info = frappe.get_all(
                    "Employee",
                    fields=[
                        "employee_number",
                        "employee_name",
                        "designation",
                        "department"
                    ],
                    filters={"user_id": teacher_user_id},
                    limit=1
                )

                if employee_info:
                    employee = employee_info[0]
                    teacher_info.update({
                        "employee_name": employee.get("employee_name"),
                        "designation": employee.get("designation"),
                        "department": employee.get("department")
                    })
                    # Override employee_code if Employee doctype has it
                    if employee.get("employee_number"):
                        teacher_info["employee_code"] = employee.get("employee_number")
            except Exception:
                # Employee doctype might not exist or be accessible
                pass

            return teacher_info

    except Exception as e:
        frappe.logger().error(f"Error enriching teacher info for {teacher_user_id}: {str(e)}")

    return None


@frappe.whitelist(allow_guest=False)
def get_class(class_id: str = None):
    try:
        if not class_id:
            form = frappe.local.form_dict or {}
            class_id = form.get("class_id") or form.get("name")
            if not class_id and frappe.request and frappe.request.args:
                class_id = frappe.request.args.get('class_id') or frappe.request.args.get('name')
        if not class_id:
            return validation_error_response({"class_id": ["Class ID is required"]})

        doc = frappe.get_doc("SIS Class", class_id)
        class_data = doc.as_dict()

        # Enhance with teacher information
        if class_data.get("homeroom_teacher"):
            teacher_info = frappe.get_all(
                "SIS Teacher",
                fields=["user_id"],
                filters={"name": class_data["homeroom_teacher"]},
                limit=1
            )

            if teacher_info:
                teacher = teacher_info[0]
                if teacher.get("user_id"):
                    # Get user information
                    user_info = frappe.get_all(
                        "User",
                        fields=[
                            "name",
                            "email",
                            "full_name",
                            "first_name",
                            "last_name",
                            "user_image",

                        ],
                        filters={"name": teacher["user_id"]},
                        limit=1
                    )

                    if user_info:
                        class_data["homeroom_teacher_info"] = enrich_teacher_info(
                            teacher["user_id"],
                            class_data["homeroom_teacher"]
                        )

                    # Try to get employee information from Employee doctype (if available)
                    try:
                        employee_info = frappe.get_all(
                            "Employee",
                            fields=[
                                "employee_number",
                                "employee_name",
                                "designation",
                                "department"
                            ],
                            filters={"user_id": teacher["user_id"]},
                            limit=1
                        )

                        if employee_info and class_data.get("homeroom_teacher_info"):
                            employee = employee_info[0]
                            class_data["homeroom_teacher_info"].update({
                                "employee_code": employee.get("name"),  # Use 'name' field as employee code
                                "employee_id": employee.get("name"),    # Alias for compatibility
                                "employee_number": employee.get("employee_number"),  # Keep original field
                                "employee_name": employee.get("employee_name"),
                                "designation": employee.get("designation"),
                                "department": employee.get("department")
                            })
                    except Exception:
                        # Employee doctype might not exist or be accessible
                        pass

        # Get vice homeroom teacher details
        if class_data.get("vice_homeroom_teacher"):
            teacher_info = frappe.get_all(
                "SIS Teacher",
                fields=["user_id"],
                filters={"name": class_data["vice_homeroom_teacher"]},
                limit=1
            )

            if teacher_info:
                teacher = teacher_info[0]
                if teacher.get("user_id"):
                    # Get user information
                    user_info = frappe.get_all(
                        "User",
                        fields=[
                            "name",
                            "email",
                            "full_name",
                            "first_name",
                            "last_name",
                            "user_image",

                        ],
                        filters={"name": teacher["user_id"]},
                        limit=1
                    )

                    if user_info:
                        class_data["vice_homeroom_teacher_info"] = enrich_teacher_info(
                            teacher["user_id"],
                            class_data["vice_homeroom_teacher"]
                        )

                    # Try to get employee information from Employee doctype (if available)
                    try:
                        employee_info = frappe.get_all(
                            "Employee",
                            fields=[
                                "employee_number",
                                "employee_name",
                                "designation",
                                "department"
                            ],
                            filters={"user_id": teacher["user_id"]},
                            limit=1
                        )

                        if employee_info and class_data.get("vice_homeroom_teacher_info"):
                            employee = employee_info[0]
                            class_data["vice_homeroom_teacher_info"].update({
                                "employee_code": employee.get("employee_number"),
                                "employee_name": employee.get("employee_name"),
                                "designation": employee.get("designation"),
                                "department": employee.get("department")
                            })
                    except Exception:
                        # Employee doctype might not exist or be accessible
                        pass

        return single_item_response(class_data, "Class fetched successfully")
    except Exception as e:
        return error_response(f"Error fetching class: {str(e)}")


@frappe.whitelist(allow_guest=False)
def create_class():
    try:
        data = {}
        if frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
            except Exception:
                data = frappe.local.form_dict or {}
        else:
            data = frappe.local.form_dict or {}

        required = ["title", "school_year_id", "education_grade", "academic_program", "campus_id"]
        for field in required:
            if not data.get(field):
                return validation_error_response({field: [f"{field} is required"]})

        # Resolve campus id robustly in case FE sends display text or alias
        campus_input = data.get("campus_id")
        campus_id = None
        if campus_input and frappe.db.exists("SIS Campus", campus_input):
            campus_id = campus_input
        else:
            # Try resolve by titles
            try:
                hit = frappe.get_all(
                    "SIS Campus",
                    filters={"title_vn": campus_input},
                    fields=["name"],
                    limit=1,
                ) or frappe.get_all(
                    "SIS Campus",
                    filters={"title_en": campus_input},
                    fields=["name"],
                    limit=1,
                )
                if hit:
                    campus_id = hit[0].name
            except Exception:
                pass
        # Fallback to current campus from context, then first campus
        if not campus_id:
            try:
                ctx = get_current_campus_from_context()
                if ctx and frappe.db.exists("SIS Campus", ctx):
                    campus_id = ctx
            except Exception:
                pass
        if not campus_id:
            first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
            campus_id = first_campus[0].name if first_campus else None
        if not campus_id:
            return not_found_response("Campus not found")

        # Resolve education_grade and academic_program robustly
        # These are required fields, so validate they can be resolved
        education_grade_input = data.get("education_grade")
        education_grade = None
        if education_grade_input and frappe.db.exists("SIS Education Grade", education_grade_input):
            education_grade = education_grade_input
        else:
            # Try resolve by grade_name or titles
            try:
                hit = frappe.get_all(
                    "SIS Education Grade",
                    filters={"grade_name": education_grade_input},
                    fields=["name"],
                    limit=1,
                ) or frappe.get_all(
                    "SIS Education Grade",
                    filters={"title_vn": education_grade_input},
                    fields=["name"],
                    limit=1,
                ) or frappe.get_all(
                    "SIS Education Grade",
                    filters={"title_en": education_grade_input},
                    fields=["name"],
                    limit=1,
                )
                if hit:
                    education_grade = hit[0].name
            except Exception:
                pass

        academic_program_input = data.get("academic_program")
        academic_program = None
        if academic_program_input and frappe.db.exists("SIS Academic Program", academic_program_input):
            academic_program = academic_program_input
        else:
            # Try resolve by titles
            try:
                hit = frappe.get_all(
                    "SIS Academic Program",
                    filters={"title_vn": academic_program_input},
                    fields=["name"],
                    limit=1,
                ) or frappe.get_all(
                    "SIS Academic Program",
                    filters={"title_en": academic_program_input},
                    fields=["name"],
                    limit=1,
                )
                if hit:
                    academic_program = hit[0].name
            except Exception:
                pass

        # Validate required resolved fields
        if not education_grade:
            return validation_error_response({"education_grade": ["Education grade not found or invalid"]})
        if not academic_program:
            return validation_error_response({"academic_program": ["Academic program not found or invalid"]})

        # Sanitize select-type fields to avoid validation edge-cases
        raw_class_type = (data.get("class_type") or "").strip()

        payload = {
            "doctype": "SIS Class",
            "title": data.get("title"),
            "short_title": data.get("short_title"),
            "campus_id": campus_id,
            "school_year_id": data.get("school_year_id"),
            "education_grade": education_grade,
            "academic_program": academic_program,
            "homeroom_teacher": data.get("homeroom_teacher"),
            "vice_homeroom_teacher": data.get("vice_homeroom_teacher"),
            "room": data.get("room"),
        }
        doc = frappe.get_doc(payload)
        doc.flags.ignore_validate = True
        doc.insert(ignore_permissions=True)

        try:
            if raw_class_type:
                allowed_ct = ["regular", "mixed", "club"]
                class_type_mapping = {
                    "lớp chính quy": "regular",
                    "lớp chạy": "mixed",
                    "câu lạc bộ": "club",
                    "regular class": "regular",
                    "mixed class": "mixed",
                    "club": "club"
                }

                # First try direct mapping for Vietnamese terms
                if raw_class_type.lower() in class_type_mapping:
                    raw_class_type = class_type_mapping[raw_class_type.lower()]
                elif raw_class_type not in allowed_ct:
                    # Fallback to existing logic
                    for opt in allowed_ct:
                        if opt.lower() == raw_class_type.lower():
                            raw_class_type = opt
                            break
                frappe.db.set_value("SIS Class", doc.name, "class_type", raw_class_type)
        except Exception:
            pass
        frappe.db.commit()
        
        # ⚡ CLEAR CACHE: Invalidate teacher classes cache after class creation
        _clear_teacher_classes_cache()

        # Enhance the response with teacher information
        response_data = doc.as_dict()

        # Add homeroom teacher info
        if response_data.get("homeroom_teacher"):
            teacher_info = frappe.get_all(
                "SIS Teacher",
                fields=["user_id"],
                filters={"name": response_data["homeroom_teacher"]},
                limit=1
            )
            if teacher_info:
                teacher = teacher_info[0]
                if teacher.get("user_id"):
                    response_data["homeroom_teacher_info"] = enrich_teacher_info(
                        teacher["user_id"],
                        response_data["homeroom_teacher"]
                    )

                    # Try to populate employee info for homeroom teacher
                    try:
                        employee_info = frappe.get_all(
                            "Employee",
                            fields=["name", "employee_number", "employee_name", "designation", "department"],
                            filters={"user_id": teacher["user_id"]},
                            limit=1
                        )
                        if employee_info and response_data.get("homeroom_teacher_info"):
                            employee = employee_info[0]
                            response_data["homeroom_teacher_info"].update({
                                "employee_code": employee.get("name"),
                                "employee_id": employee.get("name"),
                                "employee_number": employee.get("employee_number"),
                                "employee_name": employee.get("employee_name"),
                                "designation": employee.get("designation"),
                                "department": employee.get("department")
                            })
                    except Exception:
                            pass

        # Add vice homeroom teacher info
        if response_data.get("vice_homeroom_teacher"):
            teacher_info = frappe.get_all(
                "SIS Teacher",
                fields=["user_id"],
                filters={"name": response_data["vice_homeroom_teacher"]},
                limit=1
            )
            if teacher_info:
                teacher = teacher_info[0]
                if teacher.get("user_id"):
                    user_info = frappe.get_all(
                        "User",
                        fields=["full_name", "first_name", "last_name", "user_image", "email"],
                        filters={"name": teacher["user_id"]},
                        limit=1
                    )
                    if user_info:
                        user = user_info[0]
                        response_data["vice_homeroom_teacher_info"] = {
                            "name": response_data["vice_homeroom_teacher"],
                            "user_id": teacher["user_id"],
                            "teacher_name": user.get("full_name") or user.get("name"),
                            "email": user.get("email"),
                            "full_name": user.get("full_name"),
                            "first_name": user.get("first_name"),
                            "last_name": user.get("last_name"),
                            "user_image": user.get("user_image"),
                            "employee_code": "",  # Will be populated if employee exists
                            "employee_name": "",
                            "designation": "",
                            "department": ""
                        }

                    # Try to populate employee info for vice homeroom teacher
                    try:
                        employee_info = frappe.get_all(
                            "Employee",
                            fields=["name", "employee_number", "employee_name", "designation", "department"],
                            filters={"user_id": teacher["user_id"]},
                            limit=1
                        )
                        if employee_info and response_data.get("vice_homeroom_teacher_info"):
                            employee = employee_info[0]
                            response_data["vice_homeroom_teacher_info"].update({
                                "employee_code": employee.get("name"),
                                "employee_id": employee.get("name"),
                                "employee_number": employee.get("employee_number"),
                                "employee_name": employee.get("employee_name"),
                                "designation": employee.get("designation"),
                                "department": employee.get("department")
                            })
                    except Exception:
                            pass

        return single_item_response(response_data, "Class created successfully")
    except Exception as e:
        error_str = str(e)
        frappe.log_error(f"Error creating class: {error_str}")

        # Check for duplicate entry errors
        if "Duplicate entry" in error_str and "for key 'title'" in error_str:
            return error_response(
                message="Tên lớp đã tồn tại. Vui lòng chọn tên khác.",
                code="DUPLICATE_CLASS_TITLE",
                debug_info={"original_error": error_str}
            )
        elif "IntegrityError" in error_str or "1062" in error_str:
            return error_response(
                message="Lỗi dữ liệu không hợp lệ khi tạo lớp",
                code="INTEGRITY_ERROR",
                debug_info={"original_error": error_str}
            )
        else:
            return error_response(
                message="Không thể tạo lớp. Vui lòng thử lại.",
                code="CLASS_CREATION_FAILED",
                debug_info={"original_error": error_str}
            )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_class(class_id: str = None):
    try:
        # Get data consistently like create_class
        data = {}
        if frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
            except Exception:
                data = frappe.local.form_dict or {}
        else:
            data = frappe.local.form_dict or {}
            
        class_id = class_id or data.get("class_id") or data.get("name")
        if not class_id:
            return validation_error_response({"class_id": ["Class ID is required"]})
            
        # Get existing doc
        existing_doc = frappe.get_doc("SIS Class", class_id)
        
        # Prepare update data
        update_data = {}
        for key in ["title", "short_title", "campus_id", "school_year_id", "education_grade", "academic_program", "homeroom_teacher", "vice_homeroom_teacher", "room"]:
            if data.get(key) is not None:
                value = data.get(key)
                
                # ⚡ FIX: Convert empty string to None for Link fields
                # When user selects "Không chọn" in frontend, it sends empty string ''
                # But Frappe Link fields need None to clear the value
                if key in ["homeroom_teacher", "vice_homeroom_teacher", "room"] and value == '':
                    value = None
                    frappe.logger().info(f"🔄 Converting empty string to None for {key}")
                
                update_data[key] = value
        
        # 🔍 DEBUG: Log homeroom teacher changes
        if "homeroom_teacher" in update_data or "vice_homeroom_teacher" in update_data:
            frappe.logger().info(f"🔄 Updating class {class_id} - homeroom_teacher: '{update_data.get('homeroom_teacher', 'NOT_SET')}' (type: {type(update_data.get('homeroom_teacher', 'NOT_SET')).__name__})")
            frappe.logger().info(f"🔄 Updating class {class_id} - vice_homeroom_teacher: '{update_data.get('vice_homeroom_teacher', 'NOT_SET')}' (type: {type(update_data.get('vice_homeroom_teacher', 'NOT_SET')).__name__})")
        
        # Handle class_type separately to avoid validation issues
        raw_class_type = (data.get("class_type") or "").strip()
        
        # Update basic fields first
        if update_data:
            frappe.db.set_value("SIS Class", class_id, update_data)
        
        # Handle class_type
        if raw_class_type:
            allowed_ct = ["regular", "mixed", "club"]
            class_type_mapping = {
                "lớp chính quy": "regular",
                "lớp chạy": "mixed",
                "câu lạc bộ": "club",
                "regular class": "regular",
                "mixed class": "mixed",
                "club": "club"
            }

            # First try direct mapping for Vietnamese terms
            if raw_class_type.lower() in class_type_mapping:
                normalized_ct = class_type_mapping[raw_class_type.lower()]
            elif raw_class_type not in allowed_ct:
                # Fallback to existing logic
                normalized_ct = raw_class_type
                for opt in allowed_ct:
                    if opt.lower() == raw_class_type.lower():
                        normalized_ct = opt
                        break
            else:
                normalized_ct = raw_class_type

            frappe.db.set_value("SIS Class", class_id, "class_type", normalized_ct)
        
        frappe.db.commit()
        
        # ⚡ CLEAR CACHE: Invalidate teacher classes cache after class update
        _clear_teacher_classes_cache()
        
        # Return updated data with teacher information
        updated_doc = frappe.get_doc("SIS Class", class_id)
        response_data = updated_doc.as_dict()

        # Add homeroom teacher info
        if response_data.get("homeroom_teacher"):
            teacher_info = frappe.get_all(
                "SIS Teacher",
                fields=["user_id"],
                filters={"name": response_data["homeroom_teacher"]},
                limit=1
            )
            if teacher_info:
                teacher = teacher_info[0]
                if teacher.get("user_id"):
                    response_data["homeroom_teacher_info"] = enrich_teacher_info(
                        teacher["user_id"],
                        response_data["homeroom_teacher"]
                    )

                    # Try to populate employee info for homeroom teacher
                    try:
                        employee_info = frappe.get_all(
                            "Employee",
                            fields=["name", "employee_number", "employee_name", "designation", "department"],
                            filters={"user_id": teacher["user_id"]},
                            limit=1
                        )
                        if employee_info and response_data.get("homeroom_teacher_info"):
                            employee = employee_info[0]
                            response_data["homeroom_teacher_info"].update({
                                "employee_code": employee.get("name"),
                                "employee_id": employee.get("name"),
                                "employee_number": employee.get("employee_number"),
                                "employee_name": employee.get("employee_name"),
                                "designation": employee.get("designation"),
                                "department": employee.get("department")
                            })
                    except Exception:
                            pass

        # Add vice homeroom teacher info
        if response_data.get("vice_homeroom_teacher"):
            teacher_info = frappe.get_all(
                "SIS Teacher",
                fields=["user_id"],
                filters={"name": response_data["vice_homeroom_teacher"]},
                limit=1
            )
            if teacher_info:
                teacher = teacher_info[0]
                if teacher.get("user_id"):
                    user_info = frappe.get_all(
                        "User",
                        fields=["full_name", "first_name", "last_name", "user_image", "email"],
                        filters={"name": teacher["user_id"]},
                        limit=1
                    )
                    if user_info:
                        user = user_info[0]
                        response_data["vice_homeroom_teacher_info"] = {
                            "name": response_data["vice_homeroom_teacher"],
                            "user_id": teacher["user_id"],
                            "teacher_name": user.get("full_name") or user.get("name"),
                            "email": user.get("email"),
                            "full_name": user.get("full_name"),
                            "first_name": user.get("first_name"),
                            "last_name": user.get("last_name"),
                            "user_image": user.get("user_image"),
                            "employee_code": "",  # Will be populated if employee exists
                            "employee_name": "",
                            "designation": "",
                            "department": ""
                        }

                    # Try to populate employee info for vice homeroom teacher
                    try:
                        employee_info = frappe.get_all(
                            "Employee",
                            fields=["name", "employee_number", "employee_name", "designation", "department"],
                            filters={"user_id": teacher["user_id"]},
                            limit=1
                        )
                        if employee_info and response_data.get("vice_homeroom_teacher_info"):
                            employee = employee_info[0]
                            response_data["vice_homeroom_teacher_info"].update({
                                "employee_code": employee.get("name"),
                                "employee_id": employee.get("name"),
                                "employee_number": employee.get("employee_number"),
                                "employee_name": employee.get("employee_name"),
                                "designation": employee.get("designation"),
                                "department": employee.get("department")
                            })
                    except Exception:
                            pass

        return single_item_response(response_data, "Class updated successfully")

    except Exception as e:
        error_str = str(e)
        frappe.log_error(f"Error updating class: {error_str}")

        # Check for duplicate entry errors
        if "Duplicate entry" in error_str and "for key 'title'" in error_str:
            return error_response(
                message="Tên lớp đã tồn tại. Vui lòng chọn tên khác.",
                code="DUPLICATE_CLASS_TITLE",
                debug_info={"original_error": error_str}
            )
        elif "IntegrityError" in error_str or "1062" in error_str:
            return error_response(
                message="Lỗi dữ liệu không hợp lệ khi cập nhật lớp",
                code="INTEGRITY_ERROR",
                debug_info={"original_error": error_str}
            )
        else:
            return error_response(
                message="Không thể cập nhật lớp. Vui lòng thử lại.",
                code="CLASS_UPDATE_FAILED",
                debug_info={"original_error": error_str}
            )


@frappe.whitelist(allow_guest=False)
def get_teacher_classes(teacher_user_id: str = None, school_year_id: str = None):
    """Get classes where teacher is homeroom teacher or teaching (based on timetable).
    This is optimized to avoid fetching all classes and filtering client-side.
    
    ⚡ Performance: Cached for 5 minutes per teacher/week
    """
    try:
        # Get teacher_user_id from current user if not provided
        if not teacher_user_id:
            teacher_user_id = frappe.session.user
        
        if not teacher_user_id:
            return validation_error_response({"teacher_user_id": ["Teacher user ID is required"]})

        # Get current school year if not provided
        if not school_year_id:
            current_year = frappe.get_all(
                "SIS School Year",
                filters={"is_enable": 1},
                fields=["name"],
                limit=1
            )
            if current_year:
                school_year_id = current_year[0].name

        # Get current campus
        campus_id = get_current_campus_from_context()
        
        # ⚡ CACHE: Check Redis cache first (5 min TTL)
        from datetime import datetime, timedelta
        now = datetime.now()
        day = now.weekday()
        monday = now - timedelta(days=day)
        week_start = monday.strftime('%Y-%m-%d')
        
        cache_key = f"teacher_classes:{teacher_user_id}:{school_year_id}:{campus_id}:{week_start}"
        
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                frappe.logger().info(f"✅ Cache HIT for {teacher_user_id} (week {week_start})")
                return success_response(
                    data=cached_data,
                    message="Teacher classes fetched successfully (cached)"
                )
        except Exception as cache_error:
            frappe.logger().warning(f"Cache read failed: {cache_error}")
        
        frappe.logger().info(f"❌ Cache MISS for {teacher_user_id} (week {week_start}) - fetching from DB")
        
        # 1. Get homeroom classes (where teacher is homeroom_teacher or vice_homeroom_teacher)
        # First get teacher record to find teacher name from user_id
        teacher_records = frappe.get_all(
            "SIS Teacher",
            filters={"user_id": teacher_user_id},
            fields=["name"],
            limit=1
        )
        
        homeroom_classes = []
        teaching_class_ids = set()
        
        if teacher_records:
            teacher_name = teacher_records[0].name
            
            # Get homeroom classes
            homeroom_filters = {
                "campus_id": campus_id or "campus-1"
            }
            if school_year_id:
                homeroom_filters["school_year_id"] = school_year_id
                
            homeroom_classes = frappe.get_all(
                "SIS Class",
                fields=[
                    "name", "title", "short_title", "campus_id", "school_year_id",
                    "education_grade", "academic_program", "homeroom_teacher",
                    "vice_homeroom_teacher", "room", "class_type", "creation", "modified"
                ],
                filters=homeroom_filters,
                or_filters=[
                    {"homeroom_teacher": teacher_name},
                    {"vice_homeroom_teacher": teacher_name}
                ],
                order_by="title asc"
            )

        # 2. Get teaching classes using optimized multi-source approach
        # (week_start already calculated above for cache key)
        sunday = monday + timedelta(days=6)
        week_end = sunday.strftime('%Y-%m-%d')
        
        frappe.logger().info(f"Getting teaching classes for user {teacher_user_id} (week {week_start} to {week_end})")
        
        if teacher_records:
            teacher_name = teacher_records[0].name
            teacher_keys = [teacher_name, teacher_user_id]  # Try both teacher name and user_id
            
            # PRIORITY 1: Try Teacher Timetable (materialized view - fastest)
            try:
                # ⚡ Use SQL DISTINCT for better performance
                teaching_class_ids_sql = frappe.db.sql("""
                    SELECT DISTINCT class_id
                    FROM `tabSIS Teacher Timetable`
                    WHERE teacher_id = %s
                        AND date BETWEEN %s AND %s
                    LIMIT 100
                """, (teacher_name, week_start, week_end), as_dict=False)
                
                for (class_id,) in teaching_class_ids_sql:
                    if class_id:
                        teaching_class_ids.add(class_id)
                
                frappe.logger().info(f"Teacher Timetable: Found {len(teaching_class_ids_sql)} classes for current week")
                
            except Exception as e:
                frappe.logger().warning(f"Teacher Timetable query failed: {str(e)} - falling back to other methods")
            
            # PRIORITY 2: Subject Assignment (for long-term assignments)
            try:
                # ⚡ Use SQL DISTINCT for better performance
                assignment_class_ids_sql = frappe.db.sql("""
                    SELECT DISTINCT class_id
                    FROM `tabSIS Subject Assignment`
                    WHERE teacher_id = %s
                        AND campus_id = %s
                    LIMIT 100
                """, (teacher_name, campus_id or "campus-1"), as_dict=False)
                
                assignment_class_count = len(teaching_class_ids)
                for (class_id,) in assignment_class_ids_sql:
                    if class_id and school_year_id:
                        # Verify class belongs to current school year
                        class_year = frappe.db.get_value("SIS Class", class_id, "school_year_id")
                        if class_year == school_year_id:
                            teaching_class_ids.add(class_id)
                    elif class_id:
                        teaching_class_ids.add(class_id)
                
                frappe.logger().info(f"Subject Assignment: Added {len(teaching_class_ids) - assignment_class_count} classes")
            except Exception as e:
                frappe.logger().warning(f"Subject Assignment query failed: {str(e)}")
            
            # PRIORITY 3: Custom Timetable Overrides (for special events/cell-level edits)
            try:
                # Use direct SQL for custom override table (non-doctype implementation)
                overrides = frappe.db.sql("""
                    SELECT DISTINCT target_id as class_id
                    FROM `tabTimetable_Date_Override`
                    WHERE (teacher_1_id = %s OR teacher_2_id = %s)
                    AND target_type = 'Class' 
                    AND date BETWEEN %s AND %s
                    AND override_type IN ('replace', 'add')
                """, (teacher_name, teacher_name, week_start, week_end), as_dict=True) or []
                
                override_class_count = len(teaching_class_ids)
                for override in overrides:
                    if override.get("class_id"):
                        teaching_class_ids.add(override.get("class_id"))
                        
                frappe.logger().info(f"Custom Timetable Override: Added {len(teaching_class_ids) - override_class_count} classes from {len(overrides)} overrides")
                
            except Exception as e:
                frappe.logger().warning(f"Custom Timetable Override query failed (table may not exist): {str(e)}")
                
                # Fallback to doctype-based overrides if custom table doesn't exist
                try:
                    override_classes = frappe.get_all(
                        "SIS Timetable Override",
                        fields=["target_id"],
                        filters={
                            "teacher_1_id": ["in", teacher_keys],
                            "target_type": "Class",
                            "date": ["between", [week_start, week_end]],
                            "override_type": ["in", ["replace", "add"]]
                        },
                        distinct=True,
                        limit=1000
                    ) or []
                    
                    override_classes_2 = frappe.get_all(
                        "SIS Timetable Override",
                        fields=["target_id"],
                        filters={
                            "teacher_2_id": ["in", teacher_keys],
                            "target_type": "Class", 
                            "date": ["between", [week_start, week_end]],
                            "override_type": ["in", ["replace", "add"]]
                        },
                        distinct=True,
                        limit=1000
                    ) or []
                    
                    override_class_count = len(teaching_class_ids)
                    for record in override_classes + override_classes_2:
                        if record.target_id:
                            teaching_class_ids.add(record.target_id)
                            
                    frappe.logger().info(f"Doctype Timetable Override: Added {len(teaching_class_ids) - override_class_count} classes from {len(override_classes + override_classes_2)} overrides")
                    
                except Exception as fallback_error:
                    frappe.logger().warning(f"Both custom table and doctype override queries failed: {str(fallback_error)}")
            
            # PRIORITY 4: Fallback to Timetable Instance Rows (current implementation)
            if len(teaching_class_ids) == 0:
                frappe.logger().info("No classes found from optimized methods, falling back to instance rows")
                
                rows_1 = frappe.get_all(
                    "SIS Timetable Instance Row",
                    fields=["parent"],
                    filters={"teacher_1_id": ["in", teacher_keys]},
                    limit=1000,
                ) or []
                
                rows_2 = frappe.get_all(
                    "SIS Timetable Instance Row", 
                    fields=["parent"],
                    filters={"teacher_2_id": ["in", teacher_keys]},
                    limit=1000,
                ) or []
                
                # Get unique parent instance IDs
                parent_ids = list({r.get("parent") for r in rows_1 + rows_2 if r.get("parent")})
                
                if parent_ids:
                    instances = frappe.get_all(
                        "SIS Timetable Instance",
                        fields=["class_id", "start_date", "end_date"],
                        filters=[
                            ["name", "in", parent_ids],
                            ["start_date", "<=", week_end],
                            ["end_date", ">=", week_start]
                        ]
                    )
                    
                    for instance in instances:
                        if instance.class_id:
                            teaching_class_ids.add(instance.class_id)
                    
                    frappe.logger().info(f"Instance Rows Fallback: Found {len(instances)} instances, {len(teaching_class_ids)} classes")
                        
            frappe.logger().info(f"TOTAL unique teaching classes: {len(teaching_class_ids)} (from all sources)")
        
        # Get teaching classes data (don't exclude homeroom classes - teacher can teach in their own homeroom)
        # homeroom_class_names = {cls.name for cls in homeroom_classes}
        # teaching_class_ids = teaching_class_ids - homeroom_class_names  # Removed this exclusion
        
        teaching_classes = []
        if teaching_class_ids:
            teaching_filters = {
                "name": ["in", list(teaching_class_ids)]
            }
            if campus_id:
                teaching_filters["campus_id"] = campus_id
            if school_year_id:
                teaching_filters["school_year_id"] = school_year_id
                
            teaching_classes = frappe.get_all(
                "SIS Class",
                fields=[
                    "name", "title", "short_title", "campus_id", "school_year_id",
                    "education_grade", "academic_program", "homeroom_teacher", 
                    "vice_homeroom_teacher", "room", "class_type", "creation", "modified"
                ],
                filters=teaching_filters,
                order_by="title asc"
            )

        # 3. ⚡ OPTIMIZED: Batch fetch teacher info to avoid N+1 queries
        # Collect all unique teacher IDs first
        all_teacher_ids = set()
        for cls in homeroom_classes + teaching_classes:
            if cls.get("homeroom_teacher"):
                all_teacher_ids.add(cls["homeroom_teacher"])
            if cls.get("vice_homeroom_teacher"):
                all_teacher_ids.add(cls["vice_homeroom_teacher"])
        
        # Batch fetch all teachers and users in ONE query each
        teacher_user_map = {}
        user_info_map = {}
        
        if all_teacher_ids:
            # Fetch all teachers
            teachers = frappe.get_all(
                "SIS Teacher",
                fields=["name", "user_id"],
                filters={"name": ["in", list(all_teacher_ids)]},
                limit=500
            )
            
            # Fetch all users
            user_ids = [t.user_id for t in teachers if t.get("user_id")]
            if user_ids:
                users = frappe.get_all(
                    "User",
                    fields=["name", "full_name", "first_name", "middle_name", "last_name"],
                    filters={"name": ["in", user_ids]},
                    limit=500
                )
                for u in users:
                    display = u.get("full_name")
                    if not display:
                        parts = [u.get("first_name"), u.get("middle_name"), u.get("last_name")]
                        display = " ".join([p for p in parts if p]) or u.get("name")
                    user_info_map[u.name] = {
                        "user_id": u.name,
                        "full_name": display,
                        "name": u.name
                    }
            
            # Build teacher -> user map
            for t in teachers:
                if t.get("user_id") and t.user_id in user_info_map:
                    teacher_user_map[t.name] = user_info_map[t.user_id]
        
        # Enhance classes (now just lookup, no queries!)
        for cls in homeroom_classes:
            if cls.get("homeroom_teacher") and cls["homeroom_teacher"] in teacher_user_map:
                cls["homeroom_teacher_info"] = teacher_user_map[cls["homeroom_teacher"]]
            if cls.get("vice_homeroom_teacher") and cls["vice_homeroom_teacher"] in teacher_user_map:
                cls["vice_homeroom_teacher_info"] = teacher_user_map[cls["vice_homeroom_teacher"]]
        
        for cls in teaching_classes:
            if cls.get("homeroom_teacher") and cls["homeroom_teacher"] in teacher_user_map:
                cls["homeroom_teacher_info"] = teacher_user_map[cls["homeroom_teacher"]]
            if cls.get("vice_homeroom_teacher") and cls["vice_homeroom_teacher"] in teacher_user_map:
                cls["vice_homeroom_teacher_info"] = teacher_user_map[cls["vice_homeroom_teacher"]]

        frappe.logger().info(f"Teacher classes fetched: {len(homeroom_classes)} homeroom, {len(teaching_classes)} teaching for user {teacher_user_id}")
        
        # Build result (week_start, week_end already calculated above)
        result = {
            "homeroom_classes": homeroom_classes,
            "teaching_classes": teaching_classes,
            "teacher_user_id": teacher_user_id,
            "school_year_id": school_year_id,
            "week_range": {"start": week_start, "end": week_end}
        }
        
        # ⚡ CACHE: Store result in Redis (5 min = 300 sec)
        try:
            frappe.cache().set_value(cache_key, result, expires_in_sec=300)
            frappe.logger().info(f"✅ Cached result for {teacher_user_id} (key: {cache_key})")
        except Exception as cache_error:
            frappe.logger().warning(f"Cache write failed: {cache_error}")

        return success_response(
            data=result,
            message="Teacher classes fetched successfully"
        )
        
    except Exception as e:
        frappe.log_error(f"Error fetching teacher classes: {str(e)}")
        return error_response(f"Error fetching teacher classes: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_class(class_id: str = None):
    try:
        form = frappe.local.form_dict or {}
        class_id = class_id or form.get("class_id") or form.get("name")
        if not class_id and frappe.request and frappe.request.args:
            class_id = frappe.request.args.get('class_id') or frappe.request.args.get('name')
        if not class_id and frappe.request and frappe.request.data:
            try:
                body = frappe.request.data.decode('utf-8') if isinstance(frappe.request.data, bytes) else frappe.request.data
                data = json.loads(body or '{}')
                class_id = data.get('class_id') or data.get('name')
            except Exception:
                pass
        if not class_id:
            return validation_error_response({"class_id": ["Class ID is required"]})
        frappe.delete_doc("SIS Class", class_id)
        frappe.db.commit()
        
        # ⚡ CLEAR CACHE: Invalidate teacher classes cache after class deletion
        _clear_teacher_classes_cache()
        
        return success_response(message="Class deleted successfully")
    except Exception as e:
        frappe.log_error(f"Error deleting class: {str(e)}")
        return error_response(f"Error deleting class: {str(e)}")


