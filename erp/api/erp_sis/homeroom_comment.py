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
def get_all_homeroom_comments(page=1, limit=20, include_all_campuses=0):
    """Get all homeroom comments with basic information and pagination"""
    try:
        # Get parameters with defaults
        page = int(page)
        limit = int(limit)
        include_all_campuses = int(include_all_campuses)

        frappe.logger().info(f"get_all_homeroom_comments called with page: {page}, limit: {limit}, include_all_campuses: {include_all_campuses}")

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

        # Get homeroom comments
        comments = frappe.get_all(
            "SIS Report Card Homeroom Comment",
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

        frappe.logger().info(f"Found {len(comments)} homeroom comments from database")

        # Get total count
        total_count = frappe.db.count("SIS Report Card Homeroom Comment", filters=filters)

        frappe.logger().info(f"Total count: {total_count}")

        return paginated_response(
            data=comments,
            current_page=page,
            total_count=total_count,
            per_page=limit,
            message="Homeroom comments fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching homeroom comments: {str(e)}")
        return error_response(
            message="Error fetching homeroom comments",
            code="FETCH_HOMEROOM_COMMENTS_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_homeroom_comment_by_id(comment_id=None):
    """Get a specific homeroom comment by ID"""
    try:
        # Get comment_id from multiple sources
        if not comment_id:
            comment_id = frappe.local.form_dict.get("comment_id")

        # Try from JSON data
        if not comment_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                comment_id = json_data.get("comment_id")
            except Exception:
                pass

        if not comment_id:
            return error_response(
                message="Homeroom comment ID is required",
                code="MISSING_COMMENT_ID"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get the document
        try:
            comment_doc = frappe.get_doc("SIS Report Card Homeroom Comment", comment_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Homeroom comment not found",
                code="COMMENT_NOT_FOUND"
            )

        # Check campus permission
        if comment_doc.campus_id != campus_id:
            return forbidden_response(
                message="Access denied: You don't have permission to access this homeroom comment",
                code="ACCESS_DENIED"
            )

        # Get options data
        options = []
        if comment_doc.options:
            for option in comment_doc.options:
                options.append({
                    "name": option.name,
                    "title": option.title
                })

        return single_item_response(
            data={
                "name": comment_doc.name,
                "title": comment_doc.title,
                "campus_id": comment_doc.campus_id,
                "options": options
            },
            message="Homeroom comment fetched successfully"
        )

    except Exception as e:
        frappe.log_error(f"Error fetching homeroom comment {comment_id}: {str(e)}")
        return error_response(
            message="Error fetching homeroom comment",
            code="FETCH_COMMENT_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def create_homeroom_comment():
    """Create a new homeroom comment"""
    try:
        # Get data from request
        data = {}

        # First try to get JSON data from request body
        if frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data)
                if json_data:
                    data = json_data
                    frappe.logger().info(f"Received JSON data for create_homeroom_comment: {data}")
                else:
                    data = frappe.local.form_dict
                    frappe.logger().info(f"Received form data for create_homeroom_comment: {data}")
            except (json.JSONDecodeError, TypeError):
                # If JSON parsing fails, use form_dict
                data = frappe.local.form_dict
                frappe.logger().info(f"JSON parsing failed, using form data for create_homeroom_comment: {data}")
        else:
            # Fallback to form_dict
            data = frappe.local.form_dict
            frappe.logger().info(f"No request data, using form_dict for create_homeroom_comment: {data}")

        # Extract values from data
        title = data.get("title")
        options = data.get("options", [])

        # Input validation
        if not title or not title.strip():
            return validation_error_response(
                message="Nhận xét chủ nhiệm là bắt buộc",
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

        # Get campus from user context or use default campus-1 (like other APIs)
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"
            frappe.logger().warning(f"No campus found for user {frappe.session.user}, using default: {campus_id}")

        # Don't validate campus exists - let Frappe handle it, like other APIs do

        # Check if title already exists for this campus
        existing = frappe.db.exists(
            "SIS Report Card Homeroom Comment",
            {
                "title": title.strip(),
                "campus_id": campus_id
            }
        )

        if existing:
            return error_response(
                message=f"Nhận xét chủ nhiệm '{title}' đã tồn tại trong trường này",
                code="COMMENT_EXISTS"
            )

        # Create new homeroom comment
        comment_doc = frappe.get_doc({
            "doctype": "SIS Report Card Homeroom Comment",
            "title": title.strip(),
            "campus_id": campus_id,
            "options": [
                {"title": option.get("title").strip()}
                for option in options
                if option.get("title") and option.get("title").strip()
            ]
        })

        comment_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        # Get the created document with options
        created_doc = frappe.get_doc("SIS Report Card Homeroom Comment", comment_doc.name)

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
            message="Nhận xét chủ nhiệm đã được tạo thành công"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Error creating homeroom comment: {error_msg}")
        return error_response(
            message="Lỗi hệ thống khi tạo nhận xét chủ nhiệm. Vui lòng thử lại.",
            code="CREATE_COMMENT_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_homeroom_comment(comment_id=None):
    """Update an existing homeroom comment"""
    try:
        # Get comment_id from multiple sources
        if not comment_id:
            comment_id = frappe.local.form_dict.get("comment_id")

        # Try from JSON data
        if not comment_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                comment_id = json_data.get("comment_id")
            except Exception:
                pass

        if not comment_id:
            return error_response(
                message="Homeroom comment ID is required",
                code="MISSING_COMMENT_ID"
            )

        # Get existing document
        try:
            comment_doc = frappe.get_doc("SIS Report Card Homeroom Comment", comment_id)
        except frappe.DoesNotExistError:
            return not_found_response(
                message="Homeroom comment not found",
                code="COMMENT_NOT_FOUND"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Check campus permission
        if comment_doc.campus_id != campus_id:
            return forbidden_response(
                message="Access denied: You don't have permission to update this homeroom comment",
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
        if title and title.strip() and title.strip() != comment_doc.title:
            # Check if new title already exists for this campus
            existing = frappe.db.exists(
                "SIS Report Card Homeroom Comment",
                {
                    "title": title.strip(),
                    "campus_id": comment_doc.campus_id,
                    "name": ["!=", comment_id]  # Exclude current record
                }
            )

            if existing:
                return error_response(
                    message=f"Nhận xét chủ nhiệm '{title}' đã tồn tại trong trường này",
                    code="COMMENT_EXISTS"
                )

            comment_doc.title = title.strip()

        # Update options if provided
        if options:
            # Clear existing options
            comment_doc.options = []

            # Add new options
            for option in options:
                if option.get("title") and option.get("title").strip():
                    comment_doc.append("options", {
                        "title": option.get("title").strip()
                    })

        # Save the document
        comment_doc.save(ignore_permissions=True)
        frappe.db.commit()

        # Reload to get the final saved data
        comment_doc.reload()

        return success_response(
            data={
                "name": comment_doc.name,
                "title": comment_doc.title,
                "campus_id": comment_doc.campus_id,
                "options": [
                    {"name": opt.name, "title": opt.title}
                    for opt in comment_doc.options
                ]
            },
            message="Nhận xét chủ nhiệm đã được cập nhật thành công"
        )

    except Exception as e:
        error_msg = str(e)
        frappe.log_error(f"Error updating homeroom comment {comment_id}: {error_msg}")
        return error_response(
            message="Lỗi hệ thống khi cập nhật nhận xét chủ nhiệm. Vui lòng thử lại.",
            code="UPDATE_COMMENT_ERROR"
        )


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_homeroom_comment(comment_id=None):
    """Delete a homeroom comment"""
    try:
        # Get comment_id from multiple sources
        if not comment_id:
            comment_id = frappe.local.form_dict.get("comment_id")

        # Try from JSON data
        if not comment_id and frappe.request.data:
            try:
                json_data = json.loads(frappe.request.data.decode('utf-8'))
                comment_id = json_data.get("comment_id")
            except Exception:
                pass

        if not comment_id:
            return error_response(
                message="Homeroom comment ID is required",
                code="MISSING_COMMENT_ID"
            )

        # Get current user's campus
        campus_id = get_current_campus_from_context()

        if not campus_id:
            campus_id = "campus-1"

        # Get existing document
        try:
            comment_doc = frappe.get_doc("SIS Report Card Homeroom Comment", comment_id)

            # Check campus permission
            if comment_doc.campus_id != campus_id:
                return forbidden_response(
                    message="Access denied: You don't have permission to delete this homeroom comment",
                    code="ACCESS_DENIED"
                )

        except frappe.DoesNotExistError:
            return not_found_response(
                message="Homeroom comment not found",
                code="COMMENT_NOT_FOUND"
            )

        # Delete the document
        frappe.delete_doc("SIS Report Card Homeroom Comment", comment_id)
        frappe.db.commit()

        return success_response(
            message="Nhận xét chủ nhiệm đã được xóa thành công"
        )

    except Exception as e:
        frappe.log_error(f"Error deleting homeroom comment {comment_id}: {str(e)}")
        return error_response(
            message="Lỗi hệ thống khi xóa nhận xét chủ nhiệm",
            code="DELETE_COMMENT_ERROR"
        )
