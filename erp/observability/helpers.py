# Copyright (c) 2026, Wellspring ERP
"""Structured event helpers — log JSON một dòng (Promtail có thể parse)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from erp.observability import pii as pii_module

_LOGGER = logging.getLogger("erp.observability")


def _emit(kind: str, payload: dict[str, Any]) -> None:
	"""Gửi một sự kiện đã được redact."""
	data = dict(payload)
	data["event_kind"] = kind
	data["service_name"] = "erp"
	data = pii_module.redact_json_value(data)
	msg = json.dumps(data, ensure_ascii=False, default=str)
	_LOGGER.info(msg)


def log_authentication(
	user: str,
	action: str,
	ip: str,
	status: str = "success",
	details: Optional[dict[str, Any]] = None,
) -> None:
	"""Ghi sự kiện xác thực."""
	_emit(
		"authentication",
		{
			"user": user,
			"action": action,
			"ip": ip or "",
			"status": status,
			"details": details or {},
		},
	)


def log_crud(
	doctype: str,
	operation: str,
	docname: str,
	user: str,
	changes: Optional[dict[str, Any]] = None,
	details: Optional[dict[str, Any]] = None,
) -> None:
	"""Audit CRUD doctype nhạy cảm."""
	_emit(
		"audit_crud",
		{
			"doctype": doctype,
			"operation": operation,
			"docname": docname,
			"user": user,
			"changes": changes or {},
			"details": details or {},
		},
	)


def log_file_operation(
	user: str,
	operation: str,
	filename: str,
	filesize_kb: float,
	doctype: str,
	docname: str,
	is_private: bool = False,
	details: Optional[dict[str, Any]] = None,
) -> None:
	"""Audit upload/update/delete File."""
	_emit(
		"audit_file",
		{
			"user": user,
			"file_operation": operation,
			"filename": filename or "",
			"filesize_kb": filesize_kb,
			"attached_to_doctype": doctype,
			"attached_to_name": docname,
			"is_private": bool(is_private),
			"details": details or {},
		},
	)


def log_error_audit(
	user: str,
	action: str,
	error_message: str,
	resource: Optional[str] = None,
	details: Optional[dict[str, Any]] = None,
) -> None:
	"""Ghi lỗi kèm audit (không chứa stack trace chi tiết đầy đủ để giảm PII)."""
	_emit(
		"audit_error",
		{
			"user": user or "",
			"action": action,
			"error_message": (error_message or "")[:4000],
			"resource": resource or "",
			"details": details or {},
		},
	)


def log_http_access(
	user: str,
	method: str,
	path: str,
	duration_ms: float,
	status_code: int,
	extras: Optional[dict[str, Any]] = None,
) -> None:
	"""Một request HTTP đã hoàn thành (file log + Loki Promtail pipeline)."""
	_emit(
		"http_access",
		{
			"user": user or "Guest",
			"method": method,
			"path": path or "",
			"response_time_ms": round(duration_ms, 2),
			"status_code": int(status_code),
			"details": extras or {},
		},
	)


def log_slow_parent_portal(
	user: str,
	method: str,
	path: str,
	duration_ms: float,
	guardian: Optional[str],
	extras: Optional[dict[str, Any]] = None,
) -> None:
	"""Thay thế DocType Portal Slow API — chỉ ra log và Loki (event_kind=slow_api)."""
	_emit(
		"slow_api",
		{
			"user": user or "Guest",
			"method": method,
			"path": path or "",
			"response_time_ms": round(duration_ms, 2),
			"guardian_doc": guardian,
			"details": extras or {},
		},
	)
