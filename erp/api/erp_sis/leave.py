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

        # Get leave requests for these students
        leave_requests = frappe.get_all(
            "SIS Student Leave Request",
            filters={"student_id": ["in", student_ids]},
            fields=[
                "name", "student_name", "parent_name", "reason", "other_reason",
                "start_date", "end_date", "total_days", "description",
                "submitted_at", "creation", "modified", "student_id", "parent_id"
            ],
            order_by="creation desc"
        )

        # Transform reason to Vietnamese for display
        reason_mapping = {
            'sick_child': 'Con ốm',
            'family_matters': 'Gia đình có việc bận',
            'other': 'Lý do khác'
        }

        for request in leave_requests:
            request['reason_display'] = reason_mapping.get(request['reason'], request['reason'])

        return success_response({
            "leave_requests": leave_requests,
            "total": len(leave_requests),
            "class_name": class_doc.class_name
        })

    except frappe.DoesNotExistError:
        return not_found_response("Không tìm thấy lớp học hoặc đơn nghỉ phép")
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "ERP SIS Get Class Leave Requests Error")
        return error_response(f"Lỗi khi lấy danh sách đơn nghỉ phép: {str(e)}")


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
