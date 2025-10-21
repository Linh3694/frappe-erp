import frappe
from frappe import _
import json
from datetime import datetime
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
def get_class_leave_requests(class_id=None):
    """Get all leave requests for a specific class (admin view)"""
    try:
        # Try to get class_id from various sources
        if not class_id:
            class_id = frappe.form_dict.get('class_id') or frappe.request.args.get('class_id')

        if not class_id:
            return validation_error_response("Thiếu class_id", {"class_id": ["Class ID là bắt buộc"]})

        # Get pagination and search parameters
        page = int(frappe.form_dict.get('page', 1))
        limit = int(frappe.form_dict.get('limit', 20))
        search = frappe.form_dict.get('search', '').strip()

        offset = (page - 1) * limit

        # Check if class exists
        class_doc = frappe.get_doc("SIS Class", class_id)
        if not class_doc:
            return not_found_response("Không tìm thấy lớp học")

        # Get current user's campus for permission check
        campus_id = get_current_campus_from_context()

        # Check if user has access to this class's campus
        if class_doc.campus_id != campus_id:
            return forbidden_response("Bạn không có quyền xem thông tin lớp này")

        # Get all students in the class
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id},
            fields=["student_id"]
        )

        student_ids = [cs.student_id for cs in class_students]

        if not student_ids:
            return success_response({"leave_requests": [], "total": 0})

        # Build filters for leave requests
        filters = {"student_id": ["in", student_ids]}

        # Add search filter if provided
        if search:
            # Search in student_name, student_code, or reason_display
            search_filters = []
            if search:
                # We can't directly search in multiple fields, so we'll get all and filter later
                # For better performance, we could implement full-text search or indexed search
                pass

        # Get total count first (without pagination)
        total_count = frappe.db.count("SIS Student Leave Request", filters=filters)

        # Get leave requests with pagination
        leave_requests = frappe.get_all(
            "SIS Student Leave Request",
            filters=filters,
            fields=[
                "name", "student_name", "parent_name", "reason", "other_reason", "student_code",
                "start_date", "end_date", "total_days", "description",
                "submitted_at", "creation", "modified", "student_id", "parent_id"
            ],
            order_by="creation desc",
            limit=limit,
            start=offset
        )

        # Apply search filter client-side if search is provided
        if search:
            leave_requests = [
                req for req in leave_requests
                if (search.lower() in (req.get('student_name') or '').lower() or
                    search.lower() in (req.get('student_code') or '').lower() or
                    search.lower() in (req.get('reason') or '').lower() or
                    search.lower() in (req.get('parent_name') or '').lower())
            ]

        # Transform reason to Vietnamese for display
        reason_mapping = {
            'sick_child': 'Con ốm',
            'family_matters': 'Gia đình có việc bận',
            'other': 'Lý do khác'
        }

        for request in leave_requests:
            request['reason_display'] = reason_mapping.get(request['reason'], request['reason'])

        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit  # Ceiling division

        return success_response({
            "leave_requests": leave_requests,
            "total": total_count,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            "class_name": class_doc.title
        })

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy lớp học hoặc đơn nghỉ phép")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Get Class Leave Requests Error")
        return error_response(f"Lỗi khi lấy danh sách đơn nghỉ phép: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_student_photo(student_id=None):
    """Get student photo URL"""
    try:
        # Try to get student_id from various sources
        if not student_id:
            student_id = frappe.form_dict.get('student_id') or frappe.request.args.get('student_id')

        if not student_id:
            return validation_error_response("Thiếu student_id", {"student_id": ["Student ID là bắt buộc"]})

        # Get active student photo
        photo = frappe.get_all(
            "SIS Photo",
            filters={
                "student_id": student_id,
                "type": "student",
                "status": "Active"
            },
            fields=["name", "photo", "upload_date"],
            order_by="upload_date desc",
            limit=1
        )

        if photo and photo[0].photo:
            # Get full file URL
            file_url = photo[0].photo
            if file_url.startswith('/files/'):
                file_url = frappe.utils.get_url(file_url)
            elif not file_url.startswith('http'):
                file_url = frappe.utils.get_url('/files/' + file_url)

            return success_response({
                "photo_url": file_url,
                "photo_name": photo[0].name,
                "upload_date": photo[0].upload_date
            })

        # Return default response if no photo found
        return success_response({
            "photo_url": None,
            "photo_name": None,
            "upload_date": None
        })

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Get Student Photo Error")
        return error_response(f"Lỗi khi lấy ảnh học sinh: {str(e)}")


@frappe.whitelist(allow_guest=False)
def get_leave_request_details(leave_request_id=None):
    """Get detailed information of a specific leave request"""
    try:
        # Try to get leave_request_id from various sources
        if not leave_request_id:
            leave_request_id = frappe.form_dict.get('leave_request_id') or frappe.request.args.get('leave_request_id')

        if not leave_request_id:
            return validation_error_response("Thiếu leave_request_id", {"leave_request_id": ["Leave request ID là bắt buộc"]})

        # Get leave request
        leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

        # Get current user's campus for permission check
        campus_id = get_current_campus_from_context()

        # Check if user has access to this request's campus
        if leave_request.campus_id != campus_id:
            return forbidden_response("Bạn không có quyền xem thông tin đơn này")

        # Transform reason to Vietnamese for display
        reason_mapping = {
            'sick_child': 'Con ốm',
            'family_matters': 'Gia đình có việc bận',
            'other': 'Lý do khác'
        }

        result = {
            "id": leave_request.name,
            "student_id": leave_request.student_id,
            "student_name": leave_request.student_name,
            "parent_id": leave_request.parent_id,
            "parent_name": leave_request.parent_name,
            "reason": leave_request.reason,
            "reason_display": reason_mapping.get(leave_request.reason, leave_request.reason),
            "other_reason": leave_request.other_reason,
            "start_date": leave_request.start_date,
            "end_date": leave_request.end_date,
            "total_days": leave_request.total_days,
            "description": leave_request.description,
            "submitted_at": leave_request.submitted_at,
            "campus_id": leave_request.campus_id,
            "creation": leave_request.creation,
            "modified": leave_request.modified
        }

        return single_item_response(result)

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy đơn xin nghỉ phép")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Get Leave Request Details Error")
        return error_response(f"Lỗi khi lấy thông tin đơn nghỉ phép: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def batch_get_active_leaves():
    """
    Get active leaves for students on a specific date
    Used by attendance view to show which students have approved leaves
    
    POST body:
    {
        "class_id": "CLASS-001",
        "date": "2025-10-10"
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "STU-001": {
                "leave_id": "SIS-LEAVE-00001",
                "reason": "sick_child",
                "reason_display": "Con ốm",
                "start_date": "2025-10-09",
                "end_date": "2025-10-11",
                "total_days": 3
            },
            ...
        }
    }
    """
    try:
        frappe.logger().info("🚀 [Backend] batch_get_active_leaves called")
        
        # Parse request body
        data = json.loads(frappe.request.data.decode('utf-8'))
        class_id = data.get('class_id')
        date = data.get('date')
        
        if not class_id or not date:
            return validation_error_response("Thiếu tham số", {
                "class_id": ["Class ID là bắt buộc"] if not class_id else [],
                "date": ["Date là bắt buộc"] if not date else []
            })
        
        frappe.logger().info(f"📅 [Backend] Getting leaves for class {class_id} on {date}")
        
        # Get all students in the class
        class_students = frappe.get_all(
            "SIS Class Student",
            filters={"class_id": class_id},
            fields=["student_id"]
        )
        
        student_ids = [cs.student_id for cs in class_students]
        
        if not student_ids:
            frappe.logger().info("⚠️ [Backend] No students in class")
            return success_response(data={}, message="No students in class")
        
        # Get active leaves for these students on the specified date
        # Leave is active if: start_date <= date <= end_date
        leaves = frappe.db.sql("""
            SELECT 
                name,
                student_id,
                student_name,
                student_code,
                reason,
                other_reason,
                start_date,
                end_date,
                total_days,
                description
            FROM `tabSIS Student Leave Request`
            WHERE student_id IN %(student_ids)s
                AND start_date <= %(date)s
                AND end_date >= %(date)s
            ORDER BY creation DESC
        """, {
            "student_ids": student_ids,
            "date": date
        }, as_dict=True)
        
        frappe.logger().info(f"📝 [Backend] Found {len(leaves)} active leaves")
        
        # Transform reason to Vietnamese
        reason_mapping = {
            'sick_child': 'Con ốm',
            'family_matters': 'Gia đình có việc bận',
            'other': 'Lý do khác'
        }
        
        # Build result map: student_id -> array of leave info
        result = {}
        for leave in leaves:
            if leave.student_id not in result:
                result[leave.student_id] = []

            result[leave.student_id].append({
                "leave_id": leave.name,
                "student_name": leave.student_name,
                "student_code": leave.student_code,
                "reason": leave.reason,
                "reason_display": reason_mapping.get(leave.reason, leave.reason),
                "other_reason": leave.other_reason,
                "start_date": str(leave.start_date),
                "end_date": str(leave.end_date),
                "total_days": leave.total_days,
                "description": leave.description,
                "submitted_at": str(leave.submitted_at) if leave.submitted_at else None
            })

        # Sort leaves by submission time (newest first) for each student
        for student_id in result:
            result[student_id].sort(key=lambda x: x.get('submitted_at') or '', reverse=True)
        
        frappe.logger().info(f"✅ [Backend] Returning leaves for {len(result)} students")
        
        return success_response(
            data=result,
            message=f"Found {len(result)} students with active leaves"
        )
        
    except Exception as e:
        frappe.logger().error(f"❌ [Backend] batch_get_active_leaves error: {str(e)}")
        frappe.log_error(f"batch_get_active_leaves error: {str(e)}", "Batch Get Active Leaves Error")
        return error_response(
            message=f"Failed to get active leaves: {str(e)}",
            code="BATCH_GET_LEAVES_ERROR"
        )


@frappe.whitelist(allow_guest=False)
def get_leave_request_attachments():
    """Get all attachments for a leave request (admin access)"""
    try:
        # Try to get leave_request_id from various sources
        leave_request_id = frappe.form_dict.get('leave_request_id') or frappe.request.args.get('leave_request_id')

        frappe.logger().info(f"🔍 [Backend] get_leave_request_attachments called")
        frappe.logger().info(f"🔍 [Backend] leave_request_id: {leave_request_id}")
        frappe.logger().info(f"🔍 [Backend] frappe.form_dict: {frappe.form_dict}")
        frappe.logger().info(f"🔍 [Backend] frappe.request.args: {dict(frappe.request.args) if hasattr(frappe.request, 'args') else 'No args'}")

        if not leave_request_id:
            return validation_error_response("Thiếu leave_request_id", {"leave_request_id": ["Leave request ID là bắt buộc"]})

        # Get the leave request to check campus permissions
        leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

        # Check campus permissions for admin
        campus_id = get_current_campus_from_context()
        if leave_request.campus_id != campus_id:
            return forbidden_response("Bạn không có quyền xem file đính kèm của đơn này")

        # Get all files attached to this leave request
        attachments = frappe.get_all("File",
            filters={
                "attached_to_doctype": "SIS Student Leave Request",
                "attached_to_name": leave_request_id,
                "is_private": 1
            },
            fields=["name", "file_name", "file_url", "file_size", "creation"],
            order_by="creation desc"
        )

        # Add full URLs for files
        for attachment in attachments:
            if attachment.file_url and not attachment.file_url.startswith('http'):
                attachment.file_url = frappe.utils.get_url(attachment.file_url)

        return list_response(attachments)

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy đơn xin nghỉ phép")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Get Leave Request Attachments Error")
        return error_response(f"Lỗi khi lấy file đính kèm: {str(e)}")
