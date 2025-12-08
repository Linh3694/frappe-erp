import frappe
from frappe import _
import json
from datetime import datetime
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import (
    success_response,
    error_response,
    list_response,
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
                "submitted_at", "creation", "modified", "student_id", "parent_id", "owner"
            ],
            order_by="creation desc",
            limit=limit,
            start=offset
        )

        # Get creator names for all owners
        owner_emails = list(set([req.get('owner') for req in leave_requests if req.get('owner')]))
        owner_names_map = {}
        if owner_emails:
            users = frappe.get_all(
                "User",
                filters={"name": ["in", owner_emails]},
                fields=["name", "full_name"]
            )
            for user in users:
                owner_names_map[user.name] = user.full_name or user.name

        # Apply search filter client-side if search is provided
        if search:
            leave_requests = [
                req for req in leave_requests
                if (search.lower() in (req.get('student_name') or '').lower() or
                    search.lower() in (req.get('student_code') or '').lower() or
                    search.lower() in (req.get('reason') or '').lower() or
                    search.lower() in (req.get('parent_name') or '').lower() or
                    search.lower() in (owner_names_map.get(req.get('owner'), '') or '').lower())
            ]

        # Transform reason to Vietnamese for display and add creator name
        reason_mapping = {
            'sick_child': 'Con ốm',
            'family_matters': 'Gia đình có việc bận',
            'other': 'Lý do khác'
        }

        for request in leave_requests:
            request['reason_display'] = reason_mapping.get(request['reason'], request['reason'])
            # Add creator name (owner)
            request['creator_name'] = owner_names_map.get(request.get('owner'), request.get('owner', ''))
            
            # Check if created by parent (check if owner email is from parent portal)
            owner_email = request.get('owner', '')
            request['is_created_by_parent'] = '@parent.wellspring.edu.vn' in str(owner_email)

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

        # Check if created by parent
        owner_email = leave_request.owner or ''
        is_created_by_parent = '@parent.wellspring.edu.vn' in str(owner_email)

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
            "modified": leave_request.modified,
            "owner": leave_request.owner,
            "is_created_by_parent": is_created_by_parent
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
    
    POST body (either class_id OR student_ids required):
    {
        "class_id": "CLASS-001",  # Optional if student_ids provided
        "student_ids": ["STU-001", "STU-002"],  # Optional if class_id provided
        "date": "2025-10-10"
    }
    
    Returns:
    {
        "success": true,
        "data": {
            "STU-001": [{
                "leave_id": "SIS-LEAVE-00001",
                "reason": "sick_child",
                "reason_display": "Con ốm",
                "start_date": "2025-10-09",
                "end_date": "2025-10-11",
                "total_days": 3
            }, ...],
            ...
        }
    }
    """
    try:
        frappe.logger().info("🚀 [Backend] batch_get_active_leaves called")
        
        # Parse request body
        data = json.loads(frappe.request.data.decode('utf-8'))
        class_id = data.get('class_id')
        student_ids = data.get('student_ids', [])
        date = data.get('date')
        
        # Validate date is required
        if not date:
            return validation_error_response("Thiếu tham số", {
                "date": ["Date là bắt buộc"]
            })
        
        # Validate either class_id or student_ids is provided
        if not class_id and (not student_ids or not isinstance(student_ids, list) or len(student_ids) == 0):
            return validation_error_response("Thiếu tham số", {
                "class_id": ["Class ID hoặc student_ids là bắt buộc"] if not class_id else [],
                "student_ids": ["Class ID hoặc student_ids là bắt buộc"] if (not student_ids or not isinstance(student_ids, list) or len(student_ids) == 0) else []
            })
        
        # If class_id provided, get students from class
        if class_id:
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
        else:
            frappe.logger().info(f"📅 [Backend] Getting leaves for {len(student_ids)} students on {date}")
        
        if not student_ids:
            frappe.logger().info("⚠️ [Backend] No students provided")
            return success_response(data={}, message="No students provided")
        
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
                description,
                submitted_at
            FROM `tabSIS Student Leave Request`
            WHERE student_id IN %(student_ids)s
                AND start_date <= %(date)s
                AND end_date >= %(date)s
            ORDER BY creation DESC
        """, {
            "student_ids": student_ids,
            "date": date
        }, as_dict=True)
        
        # Get leave request IDs to fetch attachments
        leave_ids = [leave.name for leave in leaves] if leaves else []
        
        frappe.logger().info(f"📝 [Backend] Found {len(leaves)} active leaves")
        
        # Get attachments for all leave requests in one query for efficiency
        attachments_map = {}
        if leave_ids:
            attachments = frappe.get_all("File",
                filters={
                    "attached_to_doctype": "SIS Student Leave Request",
                    "attached_to_name": ["in", leave_ids],
                    "is_private": 1
                },
                fields=["attached_to_name", "name", "file_name", "file_url", "file_size", "creation"],
                order_by="creation desc"
            )
            
            # Build map: leave_id -> list of attachments
            for attachment in attachments:
                leave_id = attachment.attached_to_name
                if leave_id not in attachments_map:
                    attachments_map[leave_id] = []
                
                # Add full URL for file
                file_url = attachment.file_url
                if file_url and not file_url.startswith('http'):
                    file_url = frappe.utils.get_url(file_url)
                
                attachments_map[leave_id].append({
                    "name": attachment.name,
                    "file_name": attachment.file_name,
                    "file_url": file_url,
                    "file_size": attachment.file_size,
                    "creation": str(attachment.creation)
                })
        
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
                "submitted_at": str(leave.submitted_at) if leave.submitted_at else None,
                "attachments": attachments_map.get(leave.name, [])
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
    """
    Get all attachments for a leave request - ADMIN/STAFF ONLY

    This endpoint is dedicated for admin/staff usage in SIS frontend.
    Parents should use erp.api.parent_portal.leave.get_leave_request_attachments instead.
    """
    try:
        # Try to get leave_request_id from various sources
        leave_request_id = frappe.form_dict.get('leave_request_id') or frappe.request.args.get('leave_request_id')

        if not leave_request_id:
            return validation_error_response("Thiếu leave_request_id", {"leave_request_id": ["Leave request ID là bắt buộc"]})

        # Get the leave request to check campus permissions
        leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

        # ADMIN/STAFF: Check campus permissions for admin/staff access
        user_roles = frappe.get_roles(frappe.session.user)
        admin_roles = ['SIS Admin', 'SIS Manager', 'System Manager']

        frappe.logger().info(f"🔍 [Backend] User: {frappe.session.user}, Roles: {user_roles}")

        if not any(role in user_roles for role in admin_roles):
            frappe.logger().info(f"❌ [Backend] User {frappe.session.user} does not have admin roles")
            return forbidden_response("Bạn không có quyền xem thông tin này")

        # Check campus permissions
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


@frappe.whitelist(allow_guest=False, methods=['POST'])
def update_leave_request():
    """
    Update leave request for a student (admin/teacher view)
    Only editable within 24 hours of creation
    
    POST body (multipart/form-data or JSON):
    {
        "id": "SIS-LEAVE-00001",
        "reason": "sick_child",
        "other_reason": "",
        "start_date": "2025-11-06",
        "end_date": "2025-11-07",
        "description": "Optional description",
        "documents[]": <file> (optional, multiple files allowed)
    }
    """
    try:
        # Check if files exist
        has_files = frappe.request.files and len(frappe.request.files) > 0
        
        if has_files:
            # FormData with files - use request.form
            data = frappe.request.form
        elif frappe.request.is_json:
            # JSON request - use request.json
            data = frappe.request.json or {}
        else:
            # Fallback to form_dict
            data = frappe.form_dict

        # Required field
        if 'id' not in data:
            return validation_error_response("Thiếu ID đơn xin nghỉ phép", {"id": ["ID đơn xin nghỉ phép là bắt buộc"]})

        leave_request_id = data['id']

        # Get leave request
        leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

        # Check campus permissions
        campus_id = get_current_campus_from_context()
        if leave_request.campus_id != campus_id:
            return forbidden_response("Bạn không có quyền chỉnh sửa đơn này")

        # Check if within 24 hours (only for teacher-created requests)
        owner_email = leave_request.owner or ''
        is_created_by_parent = '@parent.wellspring.edu.vn' in str(owner_email)
        
        if not is_created_by_parent:
            # Teacher/Admin created - check 24h rule
            if leave_request.submitted_at:
                submitted_time = datetime.strptime(str(leave_request.submitted_at), '%Y-%m-%d %H:%M:%S.%f')
                time_diff = datetime.now() - submitted_time
                if time_diff.total_seconds() > (24 * 60 * 60):
                    return error_response("Đã quá thời hạn chỉnh sửa (24 giờ)")

        # Update fields
        updatable_fields = ['reason', 'other_reason', 'start_date', 'end_date', 'description']

        for field in updatable_fields:
            if field in data:
                leave_request.set(field, data[field])

        # Handle file attachments if any
        if frappe.request.files:
            for file_key, file_obj in frappe.request.files.items():
                if file_key.startswith('documents'):
                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": file_obj.filename,
                        "attached_to_doctype": "SIS Student Leave Request",
                        "attached_to_name": leave_request.name,
                        "content": file_obj.stream.read(),
                        "is_private": 1
                    })
                    file_doc.insert(ignore_permissions=True)

        # Save
        leave_request.flags.ignore_permissions = True
        leave_request.save()
        
        frappe.db.commit()

        return success_response({
            "message": "Đã cập nhật đơn xin nghỉ phép thành công",
            "request": {
                "id": leave_request.name,
                "student_name": leave_request.student_name
            }
        })

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy đơn xin nghỉ phép")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Update Leave Request Error")
        return error_response(f"Lỗi khi cập nhật đơn xin nghỉ phép: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def upload_leave_attachment():
    """
    Upload attachment for a leave request (admin/teacher view)
    
    POST body (multipart/form-data):
    {
        "leave_request_id": "SIS-LEAVE-00001",
        "documents[]": <file> (multiple files allowed)
    }
    """
    try:
        data = frappe.request.form
        leave_request_id = data.get('leave_request_id')
        
        if not leave_request_id:
            return validation_error_response("Thiếu leave_request_id", {"leave_request_id": ["Leave request ID là bắt buộc"]})

        # Get leave request
        leave_request = frappe.get_doc("SIS Student Leave Request", leave_request_id)

        # Check campus permissions
        campus_id = get_current_campus_from_context()
        if leave_request.campus_id != campus_id:
            return forbidden_response("Bạn không có quyền thêm file cho đơn này")

        uploaded_files = []
        
        # Handle file attachments
        if frappe.request.files:
            for file_key, file_obj in frappe.request.files.items():
                if file_key.startswith('documents'):
                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": file_obj.filename,
                        "attached_to_doctype": "SIS Student Leave Request",
                        "attached_to_name": leave_request.name,
                        "content": file_obj.stream.read(),
                        "is_private": 1
                    })
                    file_doc.insert(ignore_permissions=True)
                    uploaded_files.append({
                        "name": file_doc.name,
                        "file_name": file_doc.file_name,
                        "file_url": file_doc.file_url,
                        "file_size": file_doc.file_size
                    })

        frappe.db.commit()

        return success_response({
            "message": f"Đã tải lên {len(uploaded_files)} file thành công",
            "files": uploaded_files
        })

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy đơn xin nghỉ phép")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Upload Leave Attachment Error")
        return error_response(f"Lỗi khi tải file: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def delete_leave_attachment():
    """
    Delete attachment from a leave request (admin/teacher view)
    
    POST body:
    {
        "file_name": "xxx" (File doc name)
    }
    """
    try:
        data = json.loads(frappe.request.data.decode('utf-8'))
        file_name = data.get('file_name')
        
        if not file_name:
            return validation_error_response("Thiếu file_name", {"file_name": ["File name là bắt buộc"]})

        # Get file doc
        file_doc = frappe.get_doc("File", file_name)
        
        # Verify it's attached to a leave request
        if file_doc.attached_to_doctype != "SIS Student Leave Request":
            return forbidden_response("File này không thuộc đơn nghỉ phép")

        # Get leave request and check permissions
        leave_request = frappe.get_doc("SIS Student Leave Request", file_doc.attached_to_name)
        campus_id = get_current_campus_from_context()
        if leave_request.campus_id != campus_id:
            return forbidden_response("Bạn không có quyền xóa file này")

        # Delete file
        frappe.delete_doc("File", file_name, ignore_permissions=True)
        frappe.db.commit()

        return success_response({
            "message": "Đã xóa file thành công"
        })

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy file")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Delete Leave Attachment Error")
        return error_response(f"Lỗi khi xóa file: {str(e)}")


@frappe.whitelist(allow_guest=False, methods=['POST'])
def create_leave_request():
    """
    Create leave request for a student (admin/teacher view)
    
    POST body:
    {
        "student_id": "STU-001",
        "reason": "sick_child",
        "other_reason": "",  # Required if reason is "other"
        "start_date": "2025-11-06",
        "end_date": "2025-11-07",
        "description": "Optional description"
    }
    """
    try:
        # Parse request body
        data = json.loads(frappe.request.data.decode('utf-8'))
        
        student_id = data.get('student_id')
        reason = data.get('reason')
        other_reason = data.get('other_reason', '')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        description = data.get('description', '')
        
        # Validate required fields
        if not student_id:
            return validation_error_response("Thiếu tham số", {
                "student_id": ["Student ID là bắt buộc"]
            })
        
        if not reason:
            return validation_error_response("Thiếu tham số", {
                "reason": ["Lý do nghỉ là bắt buộc"]
            })
        
        if not start_date or not end_date:
            return validation_error_response("Thiếu tham số", {
                "start_date": ["Ngày bắt đầu là bắt buộc"] if not start_date else [],
                "end_date": ["Ngày kết thúc là bắt buộc"] if not end_date else []
            })
        
        # Validate reason
        valid_reasons = ['sick_child', 'family_matters', 'other']
        if reason not in valid_reasons:
            return validation_error_response("Lý do không hợp lệ", {
                "reason": ["Lý do phải là một trong: sick_child, family_matters, other"]
            })
        
        # Validate other_reason if reason is 'other'
        if reason == 'other' and not other_reason.strip():
            return validation_error_response("Vui lòng nhập lý do khác", {
                "other_reason": ["Vui lòng nhập lý do cụ thể khi chọn 'Lý do khác'"]
            })
        
        # Get student info
        try:
            student = frappe.get_doc("CRM Student", student_id)
        except frappe.DoesNotExistError:
            return not_found_response("Không tìm thấy học sinh")
        
        # Get campus from student
        campus_id = student.campus_id
        if not campus_id:
            return error_response("Học sinh chưa có trường học")
        
        # Check campus permissions
        user_campus = get_current_campus_from_context()
        if campus_id != user_campus:
            return forbidden_response("Bạn không có quyền tạo đơn nghỉ phép cho học sinh này")
        
        # Get parent_id from student (get first parent from family relationship)
        family_relationships = frappe.get_all(
            "CRM Family Relationship",
            filters={"student": student_id},
            fields=["parent"],
            limit=1
        )
        
        if not family_relationships:
            return error_response("Học sinh chưa có phụ huynh được liên kết")
        
        parent_id = family_relationships[0].parent
        
        # Create leave request
        leave_request = frappe.get_doc({
            "doctype": "SIS Student Leave Request",
            "student_id": student_id,
            "parent_id": parent_id,
            "campus_id": campus_id,
            "reason": reason,
            "other_reason": other_reason,
            "start_date": start_date,
            "end_date": end_date,
            "description": description,
            "submitted_at": datetime.now()
        })
        
        leave_request.insert(ignore_permissions=True)
        leave_request.save()
        
        # Send push notification to parent
        try:
            from erp.utils.notification_handler import send_bulk_parent_notifications
            
            # Reason mapping for display
            reason_mapping = {
                'sick_child': 'Con ốm',
                'family_matters': 'Gia đình có việc bận',
                'other': other_reason if other_reason else 'Lý do khác'
            }
            reason_display = reason_mapping.get(reason, reason)
            
            # Format date for display
            start_date_display = datetime.strptime(start_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            end_date_display = datetime.strptime(end_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            
            # Notification title and body
            notification_title = "Đơn xin nghỉ"
            notification_body = f"Thông tin đơn xin nghỉ, lý do: {reason_display}, ngày nghỉ: {start_date_display} - {end_date_display}"
            
            # Send notification
            notification_result = send_bulk_parent_notifications(
                recipient_type="leave",
                recipients_data={
                    "student_ids": [student_id],
                    "leave_request_id": leave_request.name
                },
                title=notification_title,
                body=notification_body,
                icon="/icon.png",
                data={
                    "type": "leave",
                    "student_id": student_id,
                    "student_name": leave_request.student_name,
                    "leave_request_id": leave_request.name,
                    "reason": reason,
                    "reason_display": reason_display,
                    "start_date": start_date,
                    "end_date": end_date
                }
            )
            
            frappe.logger().info(f"📬 [Leave Notification] Sent to {notification_result.get('total_parents', 0)} parents for leave request {leave_request.name}")
        except Exception as e:
            # Don't fail the request if notification fails
            frappe.logger().error(f"❌ [Leave Notification] Failed to send notification: {str(e)}")
            frappe.log_error(f"Leave Notification Error: {str(e)}", "Leave Notification")
        
        return success_response({
            "id": leave_request.name,
            "student_id": leave_request.student_id,
            "student_name": leave_request.student_name,
            "message": "Đã tạo đơn nghỉ phép thành công"
        })
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Create Leave Request Error")
        return error_response(f"Lỗi khi tạo đơn nghỉ phép: {str(e)}")
