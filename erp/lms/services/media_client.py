"""HTTP client gọi lms-media-service."""

import json

import frappe
import requests

from erp.lms.config import get_media_internal_secret, get_media_service_url


class MediaServiceError(Exception):
	pass


def _headers() -> dict:
	secret = get_media_internal_secret()
	if not secret:
		frappe.throw("lms_media_internal_secret chưa cấu hình trong site_config")
	return {
		"Content-Type": "application/json",
		"X-Internal-Token": secret,
	}


def _request(method: str, path: str, payload: dict | None = None) -> dict:
	base = get_media_service_url()
	url = f"{base}{path}"
	try:
		resp = requests.request(
			method,
			url,
			headers=_headers(),
			json=payload,
			timeout=60,
		)
	except requests.RequestException as exc:
		frappe.log_error(title="LMS Media Service", message=str(exc))
		raise MediaServiceError(f"Không kết nối được media service: {exc}") from exc

	try:
		body = resp.json()
	except ValueError:
		body = {"message": resp.text}

	if resp.status_code >= 400 or not body.get("success", True):
		msg = body.get("message") or resp.text
		raise MediaServiceError(msg)

	return body.get("data") or body


def init_upload(asset_id: str, filename: str, content_type: str, file_size: int) -> dict:
	return _request(
		"POST",
		"/api/lms/uploads/init",
		{
			"assetId": asset_id,
			"filename": filename,
			"contentType": content_type,
			"fileSize": int(file_size),
		},
	)


def complete_upload(asset_id: str, raw_object_key: str, upload_id: str, parts: list) -> dict:
	return _request(
		"POST",
		"/api/lms/uploads/complete",
		{
			"assetId": asset_id,
			"rawObjectKey": raw_object_key,
			"uploadId": upload_id,
			"parts": parts,
		},
	)


def presign_file_upload(
	course_id: str,
	section_id: str,
	filename: str,
	content_type: str,
	file_size: int,
	file_id: str | None = None,
) -> dict:
	"""Presigned PUT → MinIO bucket lms-files."""
	return _request(
		"POST",
		"/api/lms/files/presign-upload",
		{
			"courseId": course_id,
			"sectionId": section_id,
			"filename": filename,
			"contentType": content_type,
			"fileSize": int(file_size),
			"fileId": file_id,
		},
	)


def presign_file_download(object_key: str, bucket: str | None = None) -> dict:
	"""Presigned GET — tải file từ lms-files."""
	payload = {"objectKey": object_key}
	if bucket:
		payload["bucket"] = bucket
	return _request("POST", "/api/lms/files/presign-download", payload)
