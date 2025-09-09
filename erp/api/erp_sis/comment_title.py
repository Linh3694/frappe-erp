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
def get_all_comment_titles(page=1, limit=20, include_all_campuses=0):
    """Get all comment titles with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        include_all_campuses = int(include_all_campuses)

        frappe.logger().info(f"get_all_comment_titles called with page: {page}, limit: {limit}, include_all_campuses: {include_all_campuses}")

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

        # Get comment titles
        titles = frappe.get_all(
            "SIS Report Card Comment Title",
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

        frappe.logger().info(f"Found {len(titles)} comment titles from database")

        # Get total count
        total_count = frappe.db.count("SIS Report Card Comment Title", filters=filters)

        frappe.logger().info(f"Total count: {total_count}")

        return paginated_response(
            data=titles,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Comment titles fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching comment titles: {str(e)}")
        return error_response(
            message="Error fetching comment titles",
            code="FETCH_COMMENT_TITLES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_comment_title_by_id(title_id=None):
    """Get a specific comment title by ID"""
    try:
        # Get title_id from multiple sources
        if not title_id:
            title_id = frappe.local.form_dict.get("title_id")

        # Try from JSON data
        if not title_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                title_id = json_data.get("title_id")
            except Exception:
                pass

        if not title_id:
            return error_response(
                message="Comment title ID is required",
                code="MISSING_TITLE_ID"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get the document
        try:
            title_doc = frappe.get_doc("SIS Report Card Comment Title", title_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Comment title not found",
                code="TITLE_NOT_FOUND"
            )

        # Check campus permission
        if title_doc.campus_id != campus_id:
            return forbidden_response(
                message="Access denied: You don't have permission to access this comment title",
                code="ACCESS_DENIED"
            )

        # Get options data
        options = []
        if title_doc.options:
            for option in title_doc.options:
                options.append({
                    "name": option.name,
                    "title": option.title
                })

        return single_item_response(
            data={
                "name": title_doc.name,
                "title": title_doc.title,
                "campus_id": title_doc.campus_id,
                "options": options
            },
            message="Comment title fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching comment title {title_id}: {str(e)}")
        return error_response(
            message="Error fetching comment title",
            code="FETCH_TITLE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def create_comment_title():
    """Create a new comment title"""
    try:
        # Get data from request
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_comment_title: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_comment_title: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_comment_title: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_comment_title: {data}")

        # Extract values from data
        title = data.get("title")
        campus_id = data.get("campus_id")
        options = data.get("options", [])

        # Input validation
        if not title or not title.strip():
            return validation_error_response(
                message="Tiêu đề nhận xét là bắt buộc",
                errors={"title": ["Required"]}
            )

        if not campus_id:
            return validation_error_response(
                message="Trường học là bắt buộc",
                errors={"campus_id": ["Required"]}
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

        # Get campus from user context if not provided
        if not campus_id:
            campus_id = get_current_campus_from_context()

            if not campus_id:
                # Get first available campus
                first_campus = frappe.get_all("SIS Campus", fields=["name"], limit=1)
                if first_campus:
                    campus_id = first_campus[0].name
                else:
                    return error_response(
                        message="No campus available",
                        code="NO_CAMPUS_AVAILABLE"
                    )

        # Check if title already exists for this campus
        existing = frappe.db.exists(
            "SIS Report Card Comment Title",
            {
                "title": title.strip(),
                "campus_id": campus_id
            }
        )

        if existing:
            return error_response(
                message=f"Tiêu đề nhận xét '{title}' đã tồn tại trong trường này",
                code="TITLE_EXISTS"
            )

        # Create new comment title
        title_doc = frappe.get_doc({
            "doctype": "SIS Report Card Comment Title",
            "title": title.strip(),
            "campus_id": campus_id,
            "options": [
                {"title": option.get("title").strip()}
                for option in options
                if option.get("title") and option.get("title").strip()
            ]
        })

        title_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get the created document with options
        created_doc = frappe.get_doc("SIS Report Card Comment Title", title_doc.name)

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
            message="Tiêu đề nhận xét đã được tạo thành công"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Error creating comment title: {error_msg}")
        return error_response(
            message="Lỗi hệ thống khi tạo tiêu đề nhận xét. Vui lòng thử lại.",
            code="CREATE_TITLE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_comment_title(title_id=None):
    """Update an existing comment title"""
    try:
        # Get title_id from multiple sources
        if not title_id:
            title_id = frappe.local.form_dict.get("title_id")

        # Try from JSON data
        if not title_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                title_id = json_data.get("title_id")
            except Exception:
                pass

        if not title_id:
            return error_response(
                message="Comment title ID is required",
                code="MISSING_TITLE_ID"
            )

        # Get existing document
        try:
            title_doc = frappe.get_doc("SIS Report Card Comment Title", title_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Comment title not found",
                code="TITLE_NOT_FOUND"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Check campus permission
        if title_doc.campus_id != campus_id:
            return forbidden_response(
                message="Access denied: You don't have permission to update this comment title",
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
        if title and title.strip() and title.strip() != title_doc.title:
            # Check if new title already exists for this campus
            existing = frappe.db.exists(
                "SIS Report Card Comment Title",
                {
                    "title": title.strip(),
                    "campus_id": title_doc.campus_id,
                    "name": ["!=", title_id]  # Exclude current record
                }
            )

            if existing:
                return error_response(
                    message=f"Tiêu đề nhận xét '{title}' đã tồn tại trong trường này",
                    code="TITLE_EXISTS"
                )

            title_doc.title = title.strip()

        # Update options if provided
        if options:
            # Clear existing options
            title_doc.options = []

            # Add new options
            for option in options:
                if option.get("title") and option.get("title").strip():
                    title_doc.append("options", {
                        "title": option.get("title").strip()
                    })

        # Save the document
        title_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Reload to get the final saved data
        title_doc.reload()

        return success_response(
            data={
                "name": title_doc.name,
                "title": title_doc.title,
                "campus_id": title_doc.campus_id,
                "options": [
                    {"name": opt.name, "title": opt.title}
                    for opt in title_doc.options
                ]
            },
            message="Tiêu đề nhận xét đã được cập nhật thành công"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Error updating comment title {title_id}: {error_msg}")
        return error_response(
            message="Lỗi hệ thống khi cập nhật tiêu đề nhận xét. Vui lòng thử lại.",
            code="UPDATE_TITLE_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_comment_title(title_id=None):
    """Delete a comment title"""
    try:
        # Get title_id from multiple sources
        if not title_id:
            title_id = frappe.local.form_dict.get("title_id")

        # Try from JSON data
        if not title_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                title_id = json_data.get("title_id")
            except Exception:
                pass

        if not title_id:
            return error_response(
                message="Comment title ID is required",
                code="MISSING_TITLE_ID"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get existing document
        try:
            title_doc = frappe.get_doc("SIS Report Card Comment Title", title_id)

            # Check campus permission
            if title_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to delete this comment title",
                    code="ACCESS_DENIED"
                )

        except frappe.DoesNotExistError:
            return not_found_response(
                message="Comment title not found",
                code="TITLE_NOT_FOUND"
            )

        # Delete the document
        frappe.delete_doc("SIS Report Card Comment Title", title_id)
        frappe.db.commit()

        return success_response(
            message="Tiêu đề nhận xét đã được xóa thành công"
        )

    except Exception as e:
        frappe.log_error(f"Error deleting comment title {title_id}: {str(e)}")
        return error_response(
            message="Lỗi hệ thống khi xóa tiêu đề nhận xét",
            code="DELETE_TITLE_ERROR"
        )
