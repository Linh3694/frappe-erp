# Copyright (c) 2026, Wellspring ERP
"""Ẩn dữ liệu nhậy cảm trước khi ghi log (PII masking)."""

from __future__ import annotations

import re
from typing import Any

_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RE_PHONE = re.compile(r"(\+84|84|0)(\d[\d\s\-().]{8,})\d")


def mask_email(text: str) -> str:
	"""Che email trong chuỗi."""
	return _RE_EMAIL.sub("[email]", text or "") if text else ""


def mask_phone(text: str) -> str:
	"""Che số điện thoại (VN) đại khái."""
	return _RE_PHONE.sub("[phone]", text or "") if text else ""


def redact_json_value(value: Any) -> Any:
	"""Đệ quy làm sạch dict/list chứa có thể là PII (string đơn giản mask email/phone)."""
	if isinstance(value, str):
		return mask_phone(mask_email(value))
	if isinstance(value, dict):
		return {k: redact_json_value(v) for k, v in value.items()}
	if isinstance(value, list):
		return [redact_json_value(v) for v in value]
	return value
