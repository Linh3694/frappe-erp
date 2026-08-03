# Copyright (c) 2026, Dinox Technologies and contributors
# For license information, please see license.txt
"""API cấu hình hệ thống — nguồn sự thật duy nhất cho danh tính trường.

Endpoint chính:
  GET /api/method/erp.api.erp_common_system.config.bootstrap
Cho phép guest vì trang đăng nhập cần logo/màu TRƯỚC khi xác thực.
Chỉ trả dữ liệu công khai — tuyệt đối không thêm field nhạy cảm vào đây.
"""

import hashlib
import json

import frappe

from erp.utils.api_response import error_response, success_response

from ._defaults import (
	DEFAULT_BRANDING,
	DEFAULT_FEATURES,
	DEFAULT_SCHOOL,
	FEATURE_FIELDS,
)

SCHOOL_DTYPE = "ERP School Profile"
BRANDING_DTYPE = "ERP Branding Settings"
FEATURE_DTYPE = "ERP Feature Settings"

CACHE_KEY = "erp:system_config:bootstrap:v1"
CACHE_TTL_SEC = 3600

# Field KHÔNG được lộ ra endpoint guest (phòng khi sau này thêm field nhạy cảm)
PRIVATE_SCHOOL_FIELDS = {"tax_code"}


# ----------------------------------------------------------------------------
# Đọc dữ liệu
# ----------------------------------------------------------------------------
def _read_single(doctype: str, defaults: dict) -> dict:
	"""Đọc Single DocType, thiếu field nào lấy default. Không bao giờ raise."""
	result = dict(defaults)
	if not frappe.db.exists("DocType", doctype):
		return result
	try:
		doc = frappe.get_single(doctype)
		for key in defaults:
			value = doc.get(key)
			if value not in (None, ""):
				result[key] = value
	except Exception as ex:
		frappe.log_error(f"_read_single({doctype}) failed: {ex}", "system_config")
	return result


def _read_features() -> dict:
	# `_campus_overrides` luôn có mặt (mặc định {}) — hợp đồng §3.4 cam kết vậy,
	# client không phải kiểm tra tồn tại trước khi đọc.
	result = dict(DEFAULT_FEATURES)
	result["_campus_overrides"] = {}
	if not frappe.db.exists("DocType", FEATURE_DTYPE):
		return result
	try:
		doc = frappe.get_single(FEATURE_DTYPE)
		for key in FEATURE_FIELDS:
			result[key] = bool(doc.get(key))
		overrides = doc.get("campus_overrides_json")
		if overrides:
			parsed = json.loads(overrides) if isinstance(overrides, str) else overrides
			if isinstance(parsed, dict):
				result["_campus_overrides"] = parsed
	except Exception as ex:
		frappe.log_error(f"_read_features failed: {ex}", "system_config")
	return result


def _public_school(school: dict) -> dict:
	return {k: v for k, v in school.items() if k not in PRIVATE_SCHOOL_FIELDS}


def _build_payload() -> dict:
	school = _read_single(SCHOOL_DTYPE, DEFAULT_SCHOOL)
	branding = _read_single(BRANDING_DTYPE, DEFAULT_BRANDING)
	features = _read_features()

	payload = {
		"school": _public_school(school),
		"branding": branding,
		"features": features,
	}
	payload["version"] = hashlib.sha1(
		json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
	).hexdigest()[:12]
	return payload


# ----------------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------------
def _get_cached_payload() -> dict:
	cached = frappe.cache().get_value(CACHE_KEY)
	if cached:
		return cached
	payload = _build_payload()
	frappe.cache().set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL_SEC)
	return payload


def clear_bootstrap_cache(doc=None, method=None):
	"""Gọi từ on_update của 3 Single và từ hooks doc_events."""
	frappe.cache().delete_value(CACHE_KEY)


# ----------------------------------------------------------------------------
# Endpoint đọc
# ----------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True, methods=["GET"])
def bootstrap():
	"""Cấu hình công khai cho mọi client. KHÔNG chứa dữ liệu nhạy cảm."""
	try:
		payload = _get_cached_payload()
		# Cho phép CDN/browser cache ngắn; FE tự so `version` để biết cần refetch
		frappe.local.response.setdefault("headers", {})
		return success_response(data=payload, message="System configuration")
	except Exception as ex:
		frappe.log_error(f"bootstrap failed: {ex}", "system_config")
		return error_response(
			message="Không lấy được cấu hình hệ thống",
			code="SYSTEM_CONFIG_ERROR",
		)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def config_version():
	"""Endpoint siêu nhẹ để client poll xem cấu hình có đổi không."""
	try:
		return success_response(data={"version": _get_cached_payload().get("version")})
	except Exception:
		return success_response(data={"version": None})


# ----------------------------------------------------------------------------
# Endpoint ghi (chỉ System Manager / SIS Manager)
# ----------------------------------------------------------------------------
def _require_config_role():
	roles = set(frappe.get_roles())
	if not roles & {"System Manager", "SIS Manager", "Administrator"}:
		return error_response(message="Không có quyền sửa cấu hình hệ thống", code="FORBIDDEN")
	return None


def _payload_from_request() -> dict:
	if frappe.request and frappe.request.data:
		raw = frappe.request.data
		if isinstance(raw, bytes):
			raw = raw.decode("utf-8")
		raw = (raw or "").strip()
		if raw.startswith("{"):
			return json.loads(raw)
	return dict(frappe.form_dict or {})


def _update_single(doctype: str, allowed: list, message: str):
	if (resp := _require_config_role()):
		return resp
	data = _payload_from_request()
	try:
		doc = frappe.get_single(doctype)
		for key in allowed:
			if key in data:
				doc.set(key, data[key])
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		clear_bootstrap_cache()
		return success_response(data=_build_payload(), message=message)
	except frappe.ValidationError as ex:
		return error_response(message=str(ex), code="VALIDATION_ERROR")
	except Exception as ex:
		frappe.log_error(f"_update_single({doctype}) failed: {ex}", "system_config")
		return error_response(message="Không lưu được cấu hình", code="SYSTEM_CONFIG_SAVE_ERROR")


@frappe.whitelist(methods=["POST"])
def update_school_profile():
	return _update_single(
		SCHOOL_DTYPE,
		list(DEFAULT_SCHOOL.keys()) + ["tax_code"],
		"Đã cập nhật thông tin trường",
	)


@frappe.whitelist(methods=["POST"])
def update_branding():
	return _update_single(
		BRANDING_DTYPE,
		list(DEFAULT_BRANDING.keys()),
		"Đã cập nhật nhận diện thương hiệu",
	)


@frappe.whitelist(methods=["POST"])
def update_features():
	return _update_single(
		FEATURE_DTYPE,
		FEATURE_FIELDS + ["campus_overrides_json"],
		"Đã cập nhật cấu hình tính năng",
	)


# ----------------------------------------------------------------------------
# Tiện ích cho code backend khác dùng (thay cho hardcode)
# ----------------------------------------------------------------------------
def get_identity_email_domain() -> str:
	"""Domain sinh email định danh phụ huynh. Dùng ở GD3-F thay hardcode."""
	return _read_single(SCHOOL_DTYPE, DEFAULT_SCHOOL)["identity_email_domain"]


def get_school_name(lang: str = "vi") -> str:
	school = _read_single(SCHOOL_DTYPE, DEFAULT_SCHOOL)
	return school["school_name_en"] if lang == "en" else school["school_name_vn"]


def is_feature_enabled(key: str, campus_id: str | None = None) -> bool:
	features = _read_features()
	if campus_id:
		override = (features.get("_campus_overrides") or {}).get(campus_id, {})
		if key in override:
			return bool(override[key])
	return bool(features.get(key, False))
