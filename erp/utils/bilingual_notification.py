# Copyright (c) 2026, Wellspring và contributors
"""Tiện ích chuẩn hoá nội dung thông báo song ngữ Việt / Anh."""

from __future__ import annotations

from typing import Any, Dict, Union

BilingualText = Dict[str, str]
TitleBody = Union[str, BilingualText]


def bi(vi: str, en: str) -> BilingualText:
	"""Tạo payload {vi, en} cho ERP Notification và notification-service."""
	return {"vi": (vi or "").strip(), "en": (en or "").strip()}


def is_bilingual(value: Any) -> bool:
	return isinstance(value, dict) and ("vi" in value or "en" in value)


def coerce_title_body(value: Any) -> Union[str, BilingualText]:
	"""Giữ nguyên dict bilingual; chuỗi thường trả về str."""
	if is_bilingual(value):
		return value
	return str(value or "").strip()


def resolve_text(text_or_obj: TitleBody, language: str = "vi") -> str:
	"""Lấy chuỗi hiển thị theo ngôn ngữ (dùng cho push Expo trực tiếp)."""
	from erp.api.parent_portal.realtime_notification import get_notification_text

	return get_notification_text(text_or_obj, language=language)
