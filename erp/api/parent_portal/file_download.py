"""
Parent Portal File Download API
Handles secure file downloads for authenticated parents
"""

import frappe
from frappe import _
from erp.utils.api_response import error_response, forbidden_response, not_found_response
import os


def _get_current_parent():
	"""Get current logged in parent/guardian"""
	user_email = frappe.session.user
	if user_email == "Guest":
		return None

	# Extract guardian_id from email (format: guardian_id@parent.wellspring.edu.vn)
	if "@parent.wellspring.edu.vn" not in user_email:
		return None

	guardian_id = user_email.split("@")[0]

	# Get the actual guardian name from guardian_id field
	guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
	return guardian


@frappe.whitelist()
def download_leave_attachment():
	"""
	Download a leave request attachment file - PARENT PORTAL ONLY
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
		
		# Check if current parent owns this leave request
		parent_id = _get_current_parent()
		if not parent_id:
			frappe.response['http_status_code'] = 401
			return error_response("Không tìm thấy thông tin phụ huynh")

		if leave_request.parent_id != parent_id:
			frappe.response['http_status_code'] = 403
			return forbidden_response("Bạn chỉ có thể tải file đính kèm của đơn nghỉ phép của con mình")

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
		frappe.log_error(frappe.get_traceback(), "Parent Portal Download File Error")
		frappe.response['http_status_code'] = 500
		return error_response(f"Lỗi khi tải file: {str(e)}")

