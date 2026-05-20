# File storage — MinIO lms-files (presigned upload/download)

import frappe

from erp.lms.services import file_storage_service
from erp.utils.api_response import error_response, single_item_response, success_response


@frappe.whitelist(methods=["POST"])
def presign_upload():
	"""
	Presigned PUT upload — browser → MinIO lms-files.
	Body: course_id, section_id, filename, content_type, file_size
	"""
	try:
		data = frappe.request.json or frappe.form_dict
		result = file_storage_service.presign_upload(
			course_id=data.get("course_id"),
			section_id=data.get("section_id"),
			filename=data.get("filename"),
			content_type=data.get("content_type"),
			file_size=int(data.get("file_size") or 0),
		)
		return success_response(data=result, message="Presigned upload")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET", "POST"])
def get_download_url():
	"""Presigned GET — tải file đã upload."""
	try:
		fd = frappe.form_dict
		if frappe.request.method == "POST":
			fd = frappe.request.json or fd
		object_key = fd.get("object_key")
		bucket = fd.get("bucket")
		if not object_key:
			return error_response("object_key bắt buộc", code="VALIDATION_ERROR")
		result = file_storage_service.get_download_url(object_key=object_key, bucket=bucket)
		return success_response(data=result)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_course_file():
	"""LMS File trong module tree — metadata MinIO hoặc legacy."""
	try:
		file_id = frappe.form_dict.get("file_id")
		if not file_id:
			return error_response("file_id bắt buộc", code="VALIDATION_ERROR")
		result = file_storage_service.get_lms_file(file_id)
		return single_item_response(result)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_course_files():
	"""Danh sách LMS File trong section."""
	try:
		section_id = frappe.form_dict.get("section_id")
		if not section_id:
			return error_response("section_id bắt buộc", code="VALIDATION_ERROR")
		rows = file_storage_service.list_lms_files(section_id)
		return success_response(data=rows)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def create_course_file():
	"""Tạo LMS File — metadata MinIO sau presign upload."""
	try:
		data = frappe.request.json or frappe.form_dict
		result = file_storage_service.create_lms_file(data)
		return single_item_response(result, message="File created")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))
