"""Nghiệp vụ LMS Video Asset."""

import json
import uuid
from datetime import timedelta

import jwt
import frappe
from frappe.utils import get_datetime, get_timestamp, now_datetime

from erp.lms.config import get_hls_playback_base, get_media_internal_secret, get_media_public_url
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

# TTL token phát HLS (giờ)
PLAYBACK_TOKEN_TTL_HOURS = 4


def _resolve_hls_manifest_url(doc) -> str:
	"""URL master.m3u8 — ưu tiên proxy media-service khi bucket MinIO private."""
	playback_base = get_hls_playback_base()
	asset_key = doc.asset_id or doc.name
	if playback_base:
		return f"{playback_base}/{asset_key}/master.m3u8"

	if doc.playback_url:
		return doc.playback_url.split("?")[0]

	public_base = get_media_public_url()
	if not public_base:
		return ""

	if doc.master_playlist:
		return f"{public_base}/lms-hls/{str(doc.master_playlist).lstrip('/')}"

	if doc.hls_prefix:
		return f"{public_base}/lms-hls/{doc.hls_prefix}master.m3u8"

	return f"{public_base}/lms-hls/hls/{asset_key}/master.m3u8"


def create_video_asset(
	title=None,
	course=None,
	filename=None,
	content_type=None,
	file_size=None,
):
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
	if not file_size or int(file_size) <= 0:
		frappe.throw("file_size bắt buộc và phải > 0")
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

	# Alias cho frontend — media service trả `parts`, không phải `partUrls`
	if media_data.get("parts") and not media_data.get("partUrls"):
		media_data = {**media_data, "partUrls": media_data["parts"]}

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


def list_video_assets(course: str | None = None, include_draft: bool = True) -> list:
	"""Danh sách video asset cho picker Module Builder."""
	require_lms_staff()
	filters = {}
	if course:
		filters["course"] = course
	rows = frappe.get_all(
		"LMS Video Asset",
		filters=filters,
		fields=[
			"name", "title", "course", "status", "duration_sec",
			"filename", "asset_id", "modified",
		],
		order_by="modified desc",
		limit_page_length=200,
	)
	if not include_draft:
		rows = [r for r in rows if r.status == VIDEO_STATUS_READY]
	return rows


def get_playback_token(asset_id: str, user: str | None = None) -> dict:
	"""JWT ngắn hạn cho HLS playback — enrollment đã kiểm tra."""
	user = user or frappe.session.user
	if not user_can_access_video_asset(user, asset_id):
		frappe.throw("Không có quyền xem video", frappe.PermissionError)

	doc = frappe.get_doc("LMS Video Asset", asset_id)
	if doc.status != VIDEO_STATUS_READY:
		frappe.throw("Video chưa sẵn sàng phát")

	secret = get_media_internal_secret()
	if not secret:
		frappe.throw("lms_media_internal_secret chưa cấu hình trong site_config")

	expires_at = get_datetime(now_datetime()) + timedelta(hours=PLAYBACK_TOKEN_TTL_HOURS)
	payload = {
		"asset_id": doc.asset_id or asset_id,
		"user": user,
		"exp": int(get_timestamp(expires_at)),
	}
	token = jwt.encode(payload, secret, algorithm="HS256")
	if isinstance(token, bytes):
		token = token.decode()

	manifest_url = _resolve_hls_manifest_url(doc)
	if not manifest_url:
		frappe.throw("Chưa cấu hình URL phát HLS (lms_hls_playback_base hoặc lms_media_public_url)")

	sep = "&" if "?" in manifest_url else "?"
	signed_url = f"{manifest_url}{sep}token={token}"

	return {
		"token": token,
		"playback_url": signed_url,
		"expires_at": expires_at,
		"asset_id": asset_id,
	}
