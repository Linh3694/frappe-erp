# Upload video — proxy lms-media-service

import json

import frappe

from erp.lms.services import video_asset_service
from erp.utils.api_response import error_response, success_response, single_item_response


@frappe.whitelist(methods=["POST"])
def create_video_asset():
	"""Tạo LMS Video Asset (draft) trước khi upload."""
	try:
		data = frappe.request.json or frappe.form_dict
		doc = video_asset_service.create_video_asset(
			title=data.get("title"),
			course=data.get("course"),
			filename=data.get("filename"),
			content_type=data.get("content_type"),
			file_size=data.get("file_size"),
		)
		return single_item_response(doc.as_dict(), message="Video asset created")
	except Exception as exc:
		frappe.log_error(title="LMS create_video_asset", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def init_upload():
	"""
	Bắt đầu multipart upload — trả presigned URLs.
	Body: asset_id, filename, content_type, file_size
	"""
	try:
		data = frappe.request.json or frappe.form_dict
		asset_id = data.get("asset_id")
		if not asset_id:
			return error_response("asset_id bắt buộc", code="VALIDATION_ERROR")

		file_size = data.get("file_size")
		if file_size is not None:
			file_size = int(file_size)

		result = video_asset_service.start_upload(
			asset_id=asset_id,
			filename=data.get("filename"),
			content_type=data.get("content_type"),
			file_size=file_size,
		)
		return success_response(data=result, message="Upload initialized")
	except Exception as exc:
		frappe.log_error(title="LMS init_upload", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["POST"])
def complete_upload():
	"""Hoàn tất multipart — enqueue transcode."""
	try:
		data = frappe.request.json or frappe.form_dict
		asset_id = data.get("asset_id")
		parts = data.get("parts")
		if isinstance(parts, str):
			parts = json.loads(parts)
		if not asset_id or not parts:
			return error_response("asset_id và parts bắt buộc", code="VALIDATION_ERROR")

		result = video_asset_service.complete_upload(asset_id=asset_id, parts=parts)
		return success_response(data=result, message="Upload completed")
	except Exception as exc:
		frappe.log_error(title="LMS complete_upload", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_video_asset(asset_id=None):
	"""Chi tiết video asset + playback URL (nếu ready)."""
	try:
		asset_id = asset_id or frappe.form_dict.get("asset_id")
		if not asset_id:
			return error_response("asset_id bắt buộc", code="VALIDATION_ERROR")
		data = video_asset_service.get_video_asset_for_user(asset_id)
		return single_item_response(data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def list_video_assets():
	"""Danh sách video asset theo course — picker Module Builder."""
	try:
		course = frappe.form_dict.get("course") or frappe.form_dict.get("course_id")
		include_draft = frappe.form_dict.get("include_draft", "1") != "0"
		data = video_asset_service.list_video_assets(course=course, include_draft=include_draft)
		return success_response(data=data)
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		return error_response(str(exc))


@frappe.whitelist(methods=["GET"])
def get_playback_token(asset_id=None):
	"""JWT signed URL cho HLS playback."""
	try:
		asset_id = asset_id or frappe.form_dict.get("asset_id")
		if not asset_id:
			return error_response("asset_id bắt buộc", code="VALIDATION_ERROR")
		data = video_asset_service.get_playback_token(asset_id)
		return single_item_response(data, message="Playback token issued")
	except frappe.PermissionError:
		return error_response("Không có quyền", code="FORBIDDEN")
	except Exception as exc:
		frappe.log_error(title="LMS get_playback_token", message=frappe.get_traceback())
		return error_response(str(exc))
