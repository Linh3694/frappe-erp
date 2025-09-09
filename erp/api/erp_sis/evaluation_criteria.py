import frappe
from frappe import _
import json
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response, error_response, paginated_response,
    single_item_response, validation_error_response,
    not_found_response, forbidden_response
)


@frappe.whitelist(allow_guest=False)
def get_all_evaluation_criterias(page=1, limit=20, include_all_campuses=0):
    """Get all evaluation criterias with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        include_all_campuses = int(include_all_campuses)

        frappe.logger().info(f"get_all_evaluation_criterias called with page: {page}, limit: {limit}, include_all_campuses: {include_all_campuses}")

        if include_all_campuses:
            # Get filter for all user's campuses
            from erp.utils.campus_utils import get_campus_filter_for_all_user_campuses
            filters = get_campus_filter_for_all_user_campuses()
            frappe.logger().info(f"Using all user campuses filter: {filters}")
        else:
            # Get current user's campus information from roles
            campus_id = get_current_campus_from_context()

            if not campus_id:
                # Fallback to default if no campus found
                campus_id = "campus-1"
                frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

            frappe.logger().info(f"Using campus_id: {campus_id}")

            # Apply campus filtering for data isolation
            filters = {"campus_id": campus_id}

        frappe.logger().info(f"Final filters applied: {filters}")

        # Calculate offset for pagination
        offset = (page - 1) * limit

        # Get evaluation criterias
        criterias = frappe.get_all(
            "SIS Report Card Evaluation Criteria",
            fields=[
                "name",
                "title",
                "campus_id",
                "creation",
                "modified"
            ],
            filters=filters,
            order_by="title asc",
            limit_start=offset,
            limit_page_length=limit
        )

        frappe.logger().info(f"Found {len(criterias)} evaluation criterias from database")

        # Get total count
        total_count = frappe.db.count("SIS Report Card Evaluation Criteria", filters=filters)

        frappe.logger().info(f"Total count: {total_count}")

        return paginated_response(
            data=criterias,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Evaluation criterias fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching evaluation criterias: {str(e)}")
        return error_response(
            message="Error fetching evaluation criterias",
            code="FETCH_EVALUATION_CRITERIAS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_evaluation_criteria_by_id(criteria_id=None):
    """Get a specific evaluation criteria by ID"""
    try:
        # Get criteria_id from multiple sources
        if not criteria_id:
            criteria_id = frappe.local.form_dict.get("criteria_id")

        # Try from JSON data
        if not criteria_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                criteria_id = json_data.get("criteria_id")
            except Exception:
                pass

        if not criteria_id:
            return error_response(
                message="Evaluation criteria ID is required",
                code="MISSING_CRITERIA_ID"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get the document
        try:
            criteria_doc = frappe.get_doc("SIS Report Card Evaluation Criteria", criteria_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Evaluation criteria not found",
                code="CRITERIA_NOT_FOUND"
            )

        # Check campus permission
        if criteria_doc.campus_id != campus_id:
            return forbidden_response(
                message="Access denied: You don't have permission to access this evaluation criteria",
                code="ACCESS_DENIED"
            )

        # Get options data
        options = []
        if criteria_doc.options:
            for option in criteria_doc.options:
                options.append({
                    "name": option.name,
                    "title": option.title
                })

        return single_item_response(
            data={
                "name": criteria_doc.name,
                "title": criteria_doc.title,
                "campus_id": criteria_doc.campus_id,
                "options": options
            },
            message="Evaluation criteria fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching evaluation criteria {criteria_id}: {str(e)}")
        return error_response(
            message="Error fetching evaluation criteria",
            code="FETCH_CRITERIA_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def create_evaluation_criteria():
    """Create a new evaluation criteria"""
    try:
        # Get data from request
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_evaluation_criteria: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_evaluation_criteria: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_evaluation_criteria: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_evaluation_criteria: {data}")

        # Extract values from data
        title = data.get("title")
        campus_id = data.get("campus_id")
        options = data.get("options", [])

        # Input validation
        if not title or not title.strip():
            return validation_error_response(
                message="Tiêu chí đánh giá là bắt buộc",
                errors={"title": ["Required"]}
            )

        if not options or len(options) == 0:
            return validation_error_response(
                message="Phải có ít nhất một tùy chọn",
                errors={"options": ["Required"]}
            )

        # Validate options
        for i, option in enumerate(options):
            if not option.get("title") or not option.get("title").strip():
                return validation_error_response(
                    message=f"Tên tùy chọn {i+1} là bắt buộc",
                    errors={"options": [f"Option {i+1} title is required"]}
                )

        # Get campus from user context or auto-select
        if not campus_id:
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

        # Validate campus exists
        if not frappe.db.exists("SIS Campus", campus_id):
            return error_response(
                message=f"Không thể tìm thấy Trường học: {campus_id}",
                code="CAMPUS_NOT_FOUND"
            )

        # Check if title already exists for this campus
        existing = frappe.db.exists(
            "SIS Report Card Evaluation Criteria",
            {
                "title": title.strip(),
                "campus_id": campus_id
            }
        )

        if existing:
            return error_response(
                message=f"Tiêu chí đánh giá '{title}' đã tồn tại trong trường này",
                code="CRITERIA_TITLE_EXISTS"
            )

        # Create new evaluation criteria
        criteria_doc = frappe.get_doc({
            "doctype": "SIS Report Card Evaluation Criteria",
            "title": title.strip(),
            "campus_id": campus_id,
            "options": [
                {"title": option.get("title").strip()}
                for option in options
                if option.get("title") and option.get("title").strip()
            ]
        })

        criteria_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get the created document with options
        created_doc = frappe.get_doc("SIS Report Card Evaluation Criteria", criteria_doc.name)

        return single_item_response(
            data={
                "name": created_doc.name,
                "title": created_doc.title,
                "campus_id": created_doc.campus_id,
                "options": [
                    {"name": opt.name, "title": opt.title}
                    for opt in created_doc.options
                ]
            },
            message="Tiêu chí đánh giá đã được tạo thành công"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Error creating evaluation criteria: {error_msg}")
        return error_response(
            message="Lỗi hệ thống khi tạo tiêu chí đánh giá. Vui lòng thử lại.",
            code="CREATE_CRITERIA_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_evaluation_criteria(criteria_id=None):
    """Update an existing evaluation criteria"""
    try:
        # Get criteria_id from multiple sources
        if not criteria_id:
            criteria_id = frappe.local.form_dict.get("criteria_id")

        # Try from JSON data
        if not criteria_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                criteria_id = json_data.get("criteria_id")
            except Exception:
                pass

        if not criteria_id:
            return error_response(
                message="Evaluation criteria ID is required",
                code="MISSING_CRITERIA_ID"
            )

        # Get existing document
        try:
            criteria_doc = frappe.get_doc("SIS Report Card Evaluation Criteria", criteria_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Evaluation criteria not found",
                code="CRITERIA_NOT_FOUND"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Check campus permission
        if criteria_doc.campus_id != campus_id:
            return forbidden_response(
                message="Access denied: You don't have permission to update this evaluation criteria",
                code="ACCESS_DENIED"
            )

        # Get data from request
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
            except (json.JSONDecodeError, TypeError):
                data = frappe.local.form_dict
        else:
            data = frappe.local.form_dict

        # Extract values from data
        title = data.get("title")
        options = data.get("options", [])

        # Update title if provided
        if title and title.strip() and title.strip() != criteria_doc.title:
            # Check if new title already exists for this campus
            existing = frappe.db.exists(
                "SIS Report Card Evaluation Criteria",
                {
                    "title": title.strip(),
                    "campus_id": criteria_doc.campus_id,
                    "name": ["!=", criteria_id]  # Exclude current record
                }
            )

            if existing:
                return error_response(
                    message=f"Tiêu chí đánh giá '{title}' đã tồn tại trong trường này",
                    code="CRITERIA_TITLE_EXISTS"
                )

            criteria_doc.title = title.strip()

        # Update options if provided
        if options:
            # Clear existing options
            criteria_doc.options = []

            # Add new options
            for option in options:
                if option.get("title") and option.get("title").strip():
                    criteria_doc.append("options", {
                        "title": option.get("title").strip()
                    })

        # Save the document
        criteria_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Reload to get the final saved data
        criteria_doc.reload()

        return success_response(
            data={
                "name": criteria_doc.name,
                "title": criteria_doc.title,
                "campus_id": criteria_doc.campus_id,
                "options": [
                    {"name": opt.name, "title": opt.title}
                    for opt in criteria_doc.options
                ]
            },
            message="Tiêu chí đánh giá đã được cập nhật thành công"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Error updating evaluation criteria {criteria_id}: {error_msg}")
        return error_response(
            message="Lỗi hệ thống khi cập nhật tiêu chí đánh giá. Vui lòng thử lại.",
            code="UPDATE_CRITERIA_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_evaluation_criteria(criteria_id=None):
    """Delete an evaluation criteria"""
    try:
        # Get criteria_id from multiple sources
        if not criteria_id:
            criteria_id = frappe.local.form_dict.get("criteria_id")

        # Try from JSON data
        if not criteria_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                criteria_id = json_data.get("criteria_id")
            except Exception:
                pass

        if not criteria_id:
            return error_response(
                message="Evaluation criteria ID is required",
                code="MISSING_CRITERIA_ID"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get existing document
        try:
            criteria_doc = frappe.get_doc("SIS Report Card Evaluation Criteria", criteria_id)

            # Check campus permission
            if criteria_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to delete this evaluation criteria",
                    code="ACCESS_DENIED"
                )

        except frappe.DoesNotExistError:
            return not_found_response(
                message="Evaluation criteria not found",
                code="CRITERIA_NOT_FOUND"
            )

        # Delete the document
        frappe.delete_doc("SIS Report Card Evaluation Criteria", criteria_id)
        frappe.db.commit()

        return success_response(
            message="Tiêu chí đánh giá đã được xóa thành công"
        )

    except Exception as e:
        frappe.log_error(f"Error deleting evaluation criteria {criteria_id}: {str(e)}")
        return error_response(
            message="Lỗi hệ thống khi xóa tiêu chí đánh giá",
            code="DELETE_CRITERIA_ERROR"
        )
