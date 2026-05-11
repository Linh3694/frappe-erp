# Copyright (c) 2026, Wellspring ERP
"""Structured event helpers — log JSON một dòng (Promtail có thể parse)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from erp.observability import pii as pii_module

_LOGGER = logging.getLogger("erp.observability")

# Cap kích thước payload sau khi serialize (bytes). Audit CRUD doctype lớn
# (Student, Class, Photo có base64) có thể tạo JSON vài MB → mỗi request log
# tốn CPU + disk → workers chậm dần → gunicorn timeout 120s → cascading hang.
# 32KB đủ cho 99% event hợp lệ; nếu lớn hơn coi như abnormal → truncate kèm marker.
_MAX_LOG_BYTES = 32 * 1024

# Cap độ sâu đệ quy cho redact_json_value: nested dict/list cực sâu (vd doc.meta
# có many2many child table) gây stack tăng + regex chạy lặp lại → tốn CPU.
# Default Python recursion limit 1000, nhưng ở đây cứ 10 là quá đủ event log.
_MAX_REDACT_DEPTH = 8


def _safe_redact(value: Any, depth: int = 0) -> Any:
	"""Bọc redact_json_value với giới hạn độ sâu — tránh CPU spike + RecursionError.

	Vượt độ sâu → giữ nguyên kiểu nhưng KHÔNG đệ quy thêm (đối với dict/list lớn).
	Vẫn redact email/phone cho string ở mọi tầng.
	"""
	if depth >= _MAX_REDACT_DEPTH:
		# Đến tầng cuối: chỉ redact string trực tiếp, dict/list trả nguyên (đã bound depth).
		if isinstance(value, str):
			return pii_module.mask_phone(pii_module.mask_email(value))
		return value
	if isinstance(value, dict):
		return {k: _safe_redact(v, depth + 1) for k, v in value.items()}
	if isinstance(value, list):
		return [_safe_redact(v, depth + 1) for v in value]
	if isinstance(value, str):
		return pii_module.mask_phone(pii_module.mask_email(value))
	return value


def _emit(kind: str, payload: dict[str, Any]) -> None:
	"""Gửi một sự kiện đã được redact, có CAP kích thước chống log khổng lồ."""
	try:
		data = dict(payload)
		data["event_kind"] = kind
		data["service_name"] = "erp"
		data = _safe_redact(data)
		msg = json.dumps(data, ensure_ascii=False, default=str)

		# Cap kích thước log line: nếu vượt _MAX_LOG_BYTES, drop `details`/`changes`
		# và emit phiên bản gọn kèm marker để analyst biết có truncate.
		if len(msg.encode("utf-8", errors="ignore")) > _MAX_LOG_BYTES:
			compact: dict[str, Any] = {
				"event_kind": kind,
				"service_name": "erp",
				"_truncated": True,
				"_orig_bytes": len(msg.encode("utf-8", errors="ignore")),
			}
			# Giữ lại các field nhận diện cốt lõi nhưng KHÔNG giữ payload chi tiết.
			for k in ("user", "method", "path", "doctype", "operation", "docname", "status_code"):
				if k in data:
					v = data.get(k)
					if isinstance(v, str) and len(v) > 256:
						v = v[:256] + "..."
					compact[k] = v
			msg = json.dumps(compact, ensure_ascii=False, default=str)

		_LOGGER.info(msg)
	except Exception:
		# Logger KHÔNG được phép throw — sẽ huỷ request handler nếu propagate.
		try:
			import frappe

			frappe.errprint(f"[observability._emit] failed kind={kind}")
		except Exception:
			pass


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
