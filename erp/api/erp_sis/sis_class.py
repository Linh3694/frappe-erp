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
def get_all_classes(page: int = 1, limit: int = 20, school_year_id: str = None):
    """List classes with optional filter by school_year_id."""
    try:
        page = int(page or 1)
        limit = int(limit or 20)
        offset = (page - 1) * limit

        # Get current user's campus information from roles
        campus_id = get_current_campus_from_context()

        if not campus_id:
            # Fallback to default if no campus found
            campus_id = "campus-1"

        # Apply campus filtering for data isolation
        filters = {"campus_id": campus_id}
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
                "short_title",
                "campus_id",
                "school_year_id",
                "education_grade",
                "academic_program",
                "homeroom_teacher",
                "vice_homeroom_teacher",
                "room",
                "academic_level",
                "start_date",
                "end_date",
                "class_type",
                "creation",
                "modified",
            ],
            filters=filters,
            order_by="title asc",
            limit_start=offset,
            limit_page_length=limit,
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

        total_count = frappe.db.count("SIS Class", filters=filters)
        total_pages = (total_count + limit - 1) // limit

        return paginated_response(
            data=enhanced_classes,
            current_page=page,
            total_count=total_count,
            per_page=limit,
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
                        user = user_info[0]
                        class_data["homeroom_teacher_info"] = {
                            "name": class_data["homeroom_teacher"],
                            "user_id": teacher["user_id"],
                            "email": user.get("email"),
                            "full_name": user.get("full_name"),
                            "first_name": user.get("first_name"),
                            "last_name": user.get("last_name"),
                            "user_image": user.get("user_image"),
                            "teacher_name": user.get("full_name") or user.get("name")
                        }

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
                        user = user_info[0]
                        class_data["vice_homeroom_teacher_info"] = {
                            "name": class_data["vice_homeroom_teacher"],
                            "user_id": teacher["user_id"],
                            "email": user.get("email"),
                            "full_name": user.get("full_name"),
                            "first_name": user.get("first_name"),
                            "last_name": user.get("last_name"),
                            "user_image": user.get("user_image"),
                            "teacher_name": user.get("full_name") or user.get("name")
                        }

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
        raw_academic_level = (data.get("academic_level") or "").strip()
        raw_class_type = (data.get("class_type") or "").strip()

        print(f"Received academic_level from frontend: '{raw_academic_level}'")
        print(f"Academic_level type: {type(raw_academic_level)}")
        print(f"Academic_level length: {len(raw_academic_level) if raw_academic_level else 0}")
        # Only set academic_level in payload if it's a valid single value
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
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
        }

        # Set academic_level in payload only if it's a valid single value
        if raw_academic_level and raw_academic_level in ["Level 1", "Level 2", "Level 3", "Level 4"]:
            payload["academic_level"] = raw_academic_level
            print(f"Including academic_level in payload: '{raw_academic_level}'")
        else:
            print(f"Not including academic_level in payload: '{raw_academic_level}'")
        doc = frappe.get_doc(payload)
        doc.flags.ignore_validate = True
        doc.insert(ignore_permissions=True)

        print(f"Document created with academic_level in payload: '{payload.get('academic_level')}'")
        print(f"Document after insert has academic_level: '{doc.academic_level}'")
        try:
            if raw_class_type:
                allowed_ct = ["regular", "mixed"]
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
                    user_info = frappe.get_all(
                        "User",
                        fields=["full_name", "first_name", "last_name", "user_image", "email"],
                        filters={"name": teacher["user_id"]},
                        limit=1
                    )
                    if user_info:
                        user = user_info[0]
                        response_data["homeroom_teacher_info"] = {
                            "name": response_data["homeroom_teacher"],
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

        print(f"Final response academic_level: '{response_data.get('academic_level')}'")
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
        for key in ["title", "short_title", "campus_id", "school_year_id", "education_grade", "academic_program", "homeroom_teacher", "vice_homeroom_teacher", "room", "start_date", "end_date"]:
            if data.get(key) is not None:
                update_data[key] = data.get(key)
        
        # Handle academic_level and class_type separately to avoid validation issues
        raw_academic_level = (data.get("academic_level") or "").strip()
        raw_class_type = (data.get("class_type") or "").strip()
        
        # Update basic fields first
        if update_data:
            frappe.db.set_value("SIS Class", class_id, update_data)
        
        # Handle academic_level
        if raw_academic_level:
            allowed = ["Level 1", "Level 2", "Level 3", "Level 4"]
            normalized = raw_academic_level
            if raw_academic_level not in allowed:
                for opt in allowed:
                    if opt.lower() == raw_academic_level.lower():
                        normalized = opt
                        break
            frappe.db.set_value("SIS Class", class_id, "academic_level", normalized)
        
        # Handle class_type
        if raw_class_type:
            allowed_ct = ["regular", "mixed"]
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
                    user_info = frappe.get_all(
                        "User",
                        fields=["full_name", "first_name", "last_name", "user_image", "email"],
                        filters={"name": teacher["user_id"]},
                        limit=1
                    )
                    if user_info:
                        user = user_info[0]
                        response_data["homeroom_teacher_info"] = {
                            "name": response_data["homeroom_teacher"],
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


