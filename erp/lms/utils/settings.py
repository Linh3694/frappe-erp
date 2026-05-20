"""Đọc LMS Settings — feature flag theo campus."""

import json

import frappe


def is_grade_sync_enabled(campus_id: str | None = None) -> bool:
	"""Kiểm tra bật grade sync — global hoặc override theo campus."""
	try:
		settings = frappe.get_single("LMS Settings")
	except Exception:
		return bool(frappe.conf.get("lms_enable_grade_sync"))

	if campus_id and settings.campus_overrides_json:
		overrides = settings.campus_overrides_json
		if isinstance(overrides, str):
			overrides = json.loads(overrides)
		if isinstance(overrides, dict) and campus_id in overrides:
			return bool(overrides[campus_id].get("enable_grade_sync"))

	return bool(settings.enable_grade_sync)
