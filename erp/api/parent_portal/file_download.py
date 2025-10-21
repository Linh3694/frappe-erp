"""
Parent Portal File Download API
Handles secure file downloads for authenticated parents
"""

import frappe
from frappe import _
import os


def _resolve_user_from_jwt():
	"""Resolve user email from JWT token in Authorization header"""
	try:
		auth_header = frappe.get_request_header("Authorization") or ""
		token = None
		if auth_header.lower().startswith("bearer "):
			token = auth_header.split(" ", 1)[1].strip()
		if token:
			from erp.api.erp_common_user.auth import verify_jwt_token
			payload = verify_jwt_token(token)
			if payload:
				user_email = payload.get("email") or payload.get("user") or payload.get("sub")
				if user_email and frappe.db.exists("User", user_email):
					return user_email
	except Exception:
		pass
	return None


def _get_current_parent():
	"""Get current logged in parent/guardian"""
	# Try JWT first
	user_email = _resolve_user_from_jwt()
	
	# Fall back to session user
	if not user_email:
		user_email = frappe.session.user
	
	frappe.logger().info(f"🔍 [Get Parent] user_email: {user_email}")
	
	if user_email == "Guest" or not user_email:
		frappe.logger().info(f"❌ [Get Parent] User is Guest or empty")
		return None

	# Extract guardian_id from email (format: guardian_id@parent.wellspring.edu.vn)
	if "@parent.wellspring.edu.vn" not in user_email:
		frappe.logger().info(f"❌ [Get Parent] Email format invalid: {user_email}")
		return None

	guardian_id = user_email.split("@")[0]
	frappe.logger().info(f"🔍 [Get Parent] guardian_id: {guardian_id}")

	# Get the actual guardian name from guardian_id field
	guardian = frappe.db.get_value("CRM Guardian", {"guardian_id": guardian_id}, "name")
	frappe.logger().info(f"🔍 [Get Parent] Found guardian: {guardian}")
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
		
		frappe.logger().info(f"🔍 [File Download] Requested file_name: {file_name}")
		frappe.logger().info(f"🔍 [File Download] User: {frappe.session.user}")
		
		if not file_name:
			frappe.logger().error("❌ [File Download] Missing file_name")
			frappe.throw(_("Thiếu file_name"), frappe.PermissionError)

		# Get file document
		try:
			file_doc = frappe.get_doc("File", file_name)
			frappe.logger().info(f"🔍 [File Download] File doc: {file_doc.file_name}, attached_to: {file_doc.attached_to_doctype}/{file_doc.attached_to_name}")
		except frappe.DoesNotExistError:
			frappe.logger().error(f"❌ [File Download] File not found: {file_name}")
			frappe.throw(_("Không tìm thấy file"), frappe.DoesNotExistError)

		# Check if file is attached to a leave request
		if file_doc.attached_to_doctype != "SIS Student Leave Request":
			frappe.logger().error(f"❌ [File Download] File not attached to leave request: {file_doc.attached_to_doctype}")
			frappe.throw(_("File không thuộc đơn nghỉ phép"), frappe.PermissionError)

		# Get leave request to check permissions
		try:
			leave_request = frappe.get_doc("SIS Student Leave Request", file_doc.attached_to_name)
			frappe.logger().info(f"🔍 [File Download] Leave request parent_id: {leave_request.parent_id}")
		except frappe.DoesNotExistError:
			frappe.logger().error(f"❌ [File Download] Leave request not found: {file_doc.attached_to_name}")
			frappe.throw(_("Không tìm thấy đơn nghỉ phép"), frappe.DoesNotExistError)
		
		# Check if current parent owns this leave request
		parent_id = _get_current_parent()
		frappe.logger().info(f"🔍 [File Download] Current parent_id: {parent_id}")
		
		if not parent_id:
			frappe.logger().error("❌ [File Download] Parent not found")
			debug_info = {
				"user_email": frappe.session.user,
				"expected_format": "guardian_id@parent.wellspring.edu.vn"
			}
			frappe.throw(_(f"Không tìm thấy thông tin phụ huynh. Debug: {debug_info}"), frappe.PermissionError)

		if leave_request.parent_id != parent_id:
			frappe.logger().error(f"❌ [File Download] Permission denied: leave parent={leave_request.parent_id} vs current={parent_id}")
			debug_info = {
				"leave_request_parent_id": leave_request.parent_id,
				"current_parent_id": parent_id,
				"user_email": frappe.session.user
			}
			frappe.throw(_(f"Bạn chỉ có thể tải file đính kèm của đơn nghỉ phép của con mình. Debug: {debug_info}"), frappe.PermissionError)

		# Get file path
		file_path = file_doc.get_full_path()
		frappe.logger().info(f"🔍 [File Download] File path: {file_path}")
		
		if not os.path.exists(file_path):
			frappe.logger().error(f"❌ [File Download] File not found on disk: {file_path}")
			frappe.throw(_("File không tồn tại trên server"), frappe.DoesNotExistError)

		# Stream file
		frappe.logger().info(f"✅ [File Download] Streaming file: {file_doc.file_name}")
		
		with open(file_path, 'rb') as f:
			frappe.local.response.filename = file_doc.file_name
			frappe.local.response.filecontent = f.read()
			frappe.local.response.type = "download"

	except frappe.PermissionError as e:
		frappe.logger().error(f"❌ [File Download] PermissionError: {str(e)}")
		frappe.response['http_status_code'] = 403
		frappe.response['message'] = str(e)
		raise
	except frappe.DoesNotExistError as e:
		frappe.logger().error(f"❌ [File Download] DoesNotExistError: {str(e)}")
		frappe.response['http_status_code'] = 404
		frappe.response['message'] = str(e)
		raise
	except Exception as e:
		frappe.logger().error(f"❌ [File Download] Exception: {str(e)}")
		frappe.log_error(frappe.get_traceback(), "Parent Portal Download File Error")
		frappe.response['http_status_code'] = 500
		frappe.response['message'] = f"Lỗi khi tải file: {str(e)}"
		raise

