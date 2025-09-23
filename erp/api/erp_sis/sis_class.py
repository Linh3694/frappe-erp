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

        # Sanitize select-type fields to avoid validation edge-cases
        raw_class_type = (data.get("class_type") or "").strip()

        payload = {
            "doctype": "SIS Class",
            "title": data.get("title"),
            "short_title": data.get("short_title"),
            "campus_id": campus_id,
            "school_year_id": data.get("school_year_id"),
            "education_grade": data.get("education_grade"),
            "academic_program": data.get("academic_program"),
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
                if raw_class_type not in allowed_ct:
                    for opt in allowed_ct:
                        if opt.lower() == raw_class_type.lower():
                            raw_class_type = opt
                            break
                frappe.db.set_value("SIS Class", doc.name, "class_type", raw_class_type)
        except Exception:
            pass
        frappe.db.commit()

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
        frappe.log_error(f"Error creating class: {str(e)}")
        return error_response(f"Error creating class: {str(e)}")


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
                update_data[key] = data.get(key)
        
        # Handle class_type separately to avoid validation issues
        raw_class_type = (data.get("class_type") or "").strip()
        
        # Update basic fields first
        if update_data:
            frappe.db.set_value("SIS Class", class_id, update_data)
        
        # Handle class_type
        if raw_class_type:
            allowed_ct = ["regular", "mixed", "club"]
            normalized_ct = raw_class_type
            if raw_class_type not in allowed_ct:
                for opt in allowed_ct:
                    if opt.lower() == raw_class_type.lower():
                        normalized_ct = opt
                        break
            frappe.db.set_value("SIS Class", class_id, "class_type", normalized_ct)
        
        frappe.db.commit()
        
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
        frappe.log_error(f"Error updating class: {str(e)}")
        return error_response(f"Error updating class: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_teacher_classes(teacher_user_id: str = None, school_year_id: str = None):
    """Get classes where teacher is homeroom teacher or teaching (based on timetable).
    This is optimized to avoid fetching all classes and filtering client-side.
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
        from datetime import datetime, timedelta
        now = datetime.now()
        day = now.weekday()  # Monday = 0, Sunday = 6
        monday = now - timedelta(days=day)
        sunday = monday + timedelta(days=6)
        
        week_start = monday.strftime('%Y-%m-%d')
        week_end = sunday.strftime('%Y-%m-%d')
        
        frappe.logger().info(f"Getting teaching classes for user {teacher_user_id} (optimized approach)")
        
        if teacher_records:
            teacher_name = teacher_records[0].name
            teacher_keys = [teacher_name, teacher_user_id]  # Try both teacher name and user_id
            
            # PRIORITY 1: Try Teacher Timetable (materialized view - fastest)
            try:
                teacher_timetable_classes = frappe.get_all(
                    "SIS Teacher Timetable",
                    fields=["class_id"],
                    filters={
                        "teacher_id": teacher_name,
                        "date": ["between", [week_start, week_end]]
                    },
                    distinct=True,
                    limit=1000
                ) or []
                
                for record in teacher_timetable_classes:
                    if record.class_id:
                        teaching_class_ids.add(record.class_id)
                        
                frappe.logger().info(f"Teacher Timetable: Found {len(teacher_timetable_classes)} class records for current week")
                
            except Exception as e:
                frappe.logger().warning(f"Teacher Timetable query failed: {str(e)} - falling back to other methods")
            
            # PRIORITY 2: Subject Assignment (for long-term assignments)
            subject_assignments = frappe.get_all(
                "SIS Subject Assignment",
                fields=["class_id"],
                filters={
                    "teacher_id": teacher_name,
                    "campus_id": campus_id or "campus-1"
                },
                limit=1000
            ) or []
            
            assignment_class_count = len(teaching_class_ids)
            for assignment in subject_assignments:
                if assignment.class_id and school_year_id:
                    # Verify class belongs to current school year
                    class_year = frappe.db.get_value("SIS Class", assignment.class_id, "school_year_id")
                    if class_year == school_year_id:
                        teaching_class_ids.add(assignment.class_id)
                elif assignment.class_id:
                    teaching_class_ids.add(assignment.class_id)
            
            frappe.logger().info(f"Subject Assignment: Added {len(teaching_class_ids) - assignment_class_count} classes from {len(subject_assignments)} assignments")
            
            # PRIORITY 3: Timetable Overrides (for special events/replacements)
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
                        
                frappe.logger().info(f"Timetable Override: Added {len(teaching_class_ids) - override_class_count} classes from {len(override_classes + override_classes_2)} overrides")
                
            except Exception as e:
                frappe.logger().warning(f"Timetable Override query failed: {str(e)}")
            
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
        
        # Get teaching classes data (exclude homeroom classes to avoid duplicates)
        homeroom_class_names = {cls.name for cls in homeroom_classes}
        teaching_class_ids = teaching_class_ids - homeroom_class_names
        
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

        # 3. Enhance with teacher information (reuse existing logic)
        def enhance_classes_with_teacher_info(classes):
            enhanced = []
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
                    if teacher_info and teacher_info[0].get("user_id"):
                        enhanced_class["homeroom_teacher_info"] = enrich_teacher_info(
                            teacher_info[0]["user_id"],
                            class_data["homeroom_teacher"]
                        )

                # Get vice homeroom teacher details  
                if class_data.get("vice_homeroom_teacher"):
                    teacher_info = frappe.get_all(
                        "SIS Teacher",
                        fields=["user_id"],
                        filters={"name": class_data["vice_homeroom_teacher"]},
                        limit=1
                    )
                    if teacher_info and teacher_info[0].get("user_id"):
                        enhanced_class["vice_homeroom_teacher_info"] = enrich_teacher_info(
                            teacher_info[0]["user_id"],
                            class_data["vice_homeroom_teacher"]
                        )
                
                enhanced.append(enhanced_class)
            return enhanced

        homeroom_classes = enhance_classes_with_teacher_info(homeroom_classes)
        teaching_classes = enhance_classes_with_teacher_info(teaching_classes)

        result = {
            "homeroom_classes": homeroom_classes,
            "teaching_classes": teaching_classes,
            "teacher_user_id": teacher_user_id,
            "school_year_id": school_year_id,
            "week_range": {"start": week_start, "end": week_end}
        }

        frappe.logger().info(f"Teacher classes fetched: {len(homeroom_classes)} homeroom, {len(teaching_classes)} teaching for user {teacher_user_id}")

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
        return success_response(message="Class deleted successfully")
    except Exception as e:
        frappe.log_error(f"Error deleting class: {str(e)}")
        return error_response(f"Error deleting class: {str(e)}")


