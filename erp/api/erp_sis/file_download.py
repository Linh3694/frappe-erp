"""
ERP SIS File Download API
Handles secure file downloads for authenticated staff/admins
"""

import frappe
from frappe import _
from erp.utils.campus_utils import get_current_campus_from_context
from erp.utils.api_response import error_response, forbidden_response, not_found_response
import os


@frappe.whitelist(allow_guest=False)
def download_leave_attachment():
	"""
	Download a leave request attachment file - ADMIN/STAFF ONLY
	Streams file content with proper permission checks
	"""
	try:
		# Get file_name from query params
		file_name = frappe.form_dict.get('file_name') or frappe.request.args.get('file_name')
		
		if not file_name:
			frappe.response['http_status_code'] = 400
			return error_response("Thiếu file_name")

		# Get file document
		file_doc = frappe.get_doc("File", file_name)
		
		if not file_doc:
			frappe.response['http_status_code'] = 404
			return not_found_response("Không tìm thấy file")

		# Check if file is attached to a leave request
		if file_doc.attached_to_doctype != "SIS Student Leave Request":
			frappe.response['http_status_code'] = 403
			return forbidden_response("File không thuộc đơn nghỉ phép")

		# Get leave request to check permissions
		leave_request = frappe.get_doc("SIS Student Leave Request", file_doc.attached_to_name)
		
		# Check campus permissions
		user_roles = frappe.get_roles(frappe.session.user)
		admin_roles = ['SIS Admin', 'SIS Manager', 'System Manager']

		if not any(role in user_roles for role in admin_roles):
			frappe.response['http_status_code'] = 403
			return forbidden_response("Bạn không có quyền tải file này")

		campus_id = get_current_campus_from_context()
		if leave_request.campus_id != campus_id:
			frappe.response['http_status_code'] = 403
			return forbidden_response("Bạn không có quyền tải file đính kèm của đơn này")

		# Get file path
		file_path = file_doc.get_full_path()
		
		if not os.path.exists(file_path):
			frappe.response['http_status_code'] = 404
			return not_found_response("File không tồn tại trên server")

		# Stream file
		frappe.local.response.filename = file_doc.file_name
		frappe.local.response.filecontent = open(file_path, 'rb').read()
		frappe.local.response.type = "download"

	except frappe.DoesNotExistError:
		frappe.response['http_status_code'] = 404
		return not_found_response("Không tìm thấy file")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "ERP SIS Download File Error")
		frappe.response['http_status_code'] = 500
		return error_response(f"Lỗi khi tải file: {str(e)}")

