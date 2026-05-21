# Webhook / internal — lms-media-service, Nginx auth_request

import jwt
import frappe

from erp.lms.config import get_media_internal_secret
from erp.lms.services import video_asset_service
from erp.lms.utils.permissions import user_can_access_video_asset
from erp.utils.api_response import error_response, success_response


def _validate_internal_token():
	"""X-Internal-Token hoặc Bearer — cùng secret với lms-media-service."""
	secret = get_media_internal_secret()
	if not secret:
		frappe.throw("lms_media_internal_secret chưa cấu hình")

	token = frappe.get_request_header("X-Internal-Token")
	if not token:
		auth = frappe.get_request_header("Authorization") or ""
		if auth.startswith("Bearer "):
			token = auth[7:]

	if token != secret:
		frappe.throw("Unauthorized", frappe.AuthenticationError)


def _resolve_playback_from_jwt(token: str) -> tuple[str, str] | None:
	"""Decode JWT playback token — trả (asset_id, user) hoặc None."""
	secret = get_media_internal_secret()
	if not secret or not token:
		return None
	try:
		payload = jwt.decode(token, secret, algorithms=["HS256"])
		asset_id = payload.get("asset_id")
		user = payload.get("user")
		if asset_id and user:
			return asset_id, user
	except jwt.PyJWTError:
		return None
	return None


@frappe.whitelist(allow_guest=True, methods=["POST"])
def transcode_callback():
	"""
	Webhook sau transcode — gọi từ lms-media-service.
	Auth: X-Internal-Token (cùng lms_media_internal_secret) hoặc API Key Frappe.
	URL: /api/method/erp.api.lms.internal.transcode_callback
	"""
	try:
		# Guest phải có internal token; API Key đã login thì bỏ qua
		if frappe.session.user == "Guest":
			_validate_internal_token()

		payload = frappe.request.json or frappe.form_dict
		data = video_asset_service.apply_transcode_callback(payload)
		return success_response(data=data, message="Transcode callback processed")
	except frappe.AuthenticationError:
		return error_response("Unauthorized", code="UNAUTHORIZED")
	except Exception as exc:
		frappe.log_error(title="LMS transcode_callback", message=frappe.get_traceback())
		return error_response(str(exc))


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def validate_playback():
	"""
	Kiểm tra quyền phát video — Nginx auth_request hoặc media service.
	Query/body: asset_id, user_id (optional), token (JWT playback).
	"""
	try:
		payload = frappe.request.json or frappe.form_dict
		playback_token = (
			payload.get("token")
			or frappe.form_dict.get("token")
			or frappe.get_request_header("X-Playback-Token")
		)

		asset_id = payload.get("asset_id") or payload.get("assetId")
		user_id = payload.get("user_id") or payload.get("userId") or frappe.session.user

		jwt_resolved = False
		if playback_token:
			resolved = _resolve_playback_from_jwt(playback_token)
			if resolved:
				asset_id, user_id = resolved
				jwt_resolved = True

		if not asset_id:
			frappe.local.response.http_status_code = 400
			return error_response("asset_id bắt buộc")

		if not jwt_resolved:
			_validate_internal_token()

		if user_id and user_id != "Guest":
			allowed = user_can_access_video_asset(user_id, asset_id)
		else:
			allowed = False

		if not allowed:
			frappe.local.response.http_status_code = 403
			return error_response("Forbidden", code="FORBIDDEN")

		frappe.local.response.http_status_code = 200
		return success_response(data={"asset_id": asset_id, "allowed": True})
	except frappe.AuthenticationError:
		frappe.local.response.http_status_code = 401
		return error_response("Unauthorized", code="UNAUTHORIZED")
	except Exception as exc:
		frappe.local.response.http_status_code = 500
		return error_response(str(exc))
