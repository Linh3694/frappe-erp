"""Nghiệp vụ LMS Video Asset."""

import json
import uuid

import frappe

from erp.lms.constants import (
	VIDEO_STATUS_DRAFT,
	VIDEO_STATUS_PROCESSING,
	VIDEO_STATUS_READY,
	VIDEO_STATUS_UPLOADING,
	VIDEO_STATUS_FAILED,
)
from erp.lms.services import media_client
from erp.lms.utils.permissions import require_lms_staff, user_can_access_video_asset
from erp.utils.campus_utils import get_current_campus_from_context


def create_video_asset(
	title=None,
	course=None,
	filename=None,
	content_type=None,
	file_size=None,
) -> frappe.Document:
	require_lms_staff()
	campus_id = get_current_campus_from_context()
	doc = frappe.get_doc(
		{
			"doctype": "LMS Video Asset",
			"asset_id": str(uuid.uuid4()),
			"title": title or filename or "Untitled video",
			"campus_id": campus_id,
			"course": course,
			"filename": filename,
			"content_type": content_type or "video/mp4",
			"file_size": file_size,
			"status": VIDEO_STATUS_DRAFT,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def start_upload(asset_id: str, filename: str, content_type: str, file_size: int) -> dict:
	require_lms_staff()
	doc = frappe.get_doc("LMS Video Asset", asset_id)
	if doc.status not in (VIDEO_STATUS_DRAFT, VIDEO_STATUS_FAILED, VIDEO_STATUS_UPLOADING):
		frappe.throw(f"Không thể upload khi status={doc.status}")

	media_data = media_client.init_upload(
		asset_id=doc.asset_id,
		filename=filename or doc.filename or "video.mp4",
		content_type=content_type or doc.content_type or "video/mp4",
		file_size=file_size or doc.file_size,
	)

	doc.status = VIDEO_STATUS_UPLOADING
	doc.filename = filename or doc.filename
	doc.content_type = content_type or doc.content_type
	doc.file_size = file_size or doc.file_size
	doc.raw_object_key = media_data.get("rawObjectKey")
	doc.upload_id = media_data.get("uploadId")
	doc.save(ignore_permissions=True)

	return {
		"asset": doc.as_dict(),
		"upload": media_data,
	}


def complete_upload(asset_id: str, parts) -> dict:
	require_lms_staff()
	if isinstance(parts, str):
		parts = json.loads(parts)

	doc = frappe.get_doc("LMS Video Asset", asset_id)
	if not doc.upload_id or not doc.raw_object_key:
		frappe.throw("Chưa init upload")

	media_data = media_client.complete_upload(
		asset_id=doc.asset_id,
		raw_object_key=doc.raw_object_key,
		upload_id=doc.upload_id,
		parts=parts,
	)

	doc.status = VIDEO_STATUS_PROCESSING
	doc.upload_id = None
	doc.save(ignore_permissions=True)

	return {
		"asset": doc.as_dict(),
		"job": media_data,
	}


def apply_transcode_callback(payload: dict) -> dict:
	"""Webhook từ lms-media-service."""
	asset_id = payload.get("asset_id")
	if not asset_id:
		frappe.throw("asset_id bắt buộc")

	if not frappe.db.exists("LMS Video Asset", asset_id):
		frappe.throw(f"Không tìm thấy LMS Video Asset: {asset_id}")

	doc = frappe.get_doc("LMS Video Asset", asset_id)
	status = payload.get("status")

	if status == "ready":
		doc.status = VIDEO_STATUS_READY
		doc.hls_prefix = payload.get("hls_prefix")
		doc.master_playlist = payload.get("master_playlist")
		doc.playback_url = payload.get("playback_url")
		doc.duration_sec = payload.get("duration_sec")
		doc.thumbnail_key = payload.get("thumbnail_key")
		doc.error_message = None
	elif status == "failed":
		doc.status = VIDEO_STATUS_FAILED
		doc.error_message = payload.get("error_message")
	else:
		frappe.throw(f"status không hợp lệ: {status}")

	doc.save(ignore_permissions=True)
	return doc.as_dict()


def get_video_asset_for_user(asset_id: str, user: str | None = None) -> dict:
	user = user or frappe.session.user
	if not user_can_access_video_asset(user, asset_id):
		frappe.throw("Không có quyền xem video", frappe.PermissionError)
	return frappe.get_doc("LMS Video Asset", asset_id).as_dict()
