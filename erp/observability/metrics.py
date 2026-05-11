# Copyright (c) 2026, Wellspring ERP
"""Metric Prometheus RED cho request HTTP ERP (expose qua whitelist method)."""

from __future__ import annotations

import re
from functools import lru_cache

from prometheus_client import CollectorRegistry, Counter, Histogram

# Chuẩn hóa UUID và số dài trong path để giảm cardinality
_RE_UUID = re.compile(
	r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
_RE_LONG_NUM_SEGMENT = re.compile(r"/\d{3,}")

_DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@lru_cache(maxsize=1)
def _registry() -> CollectorRegistry:
	return CollectorRegistry()


@lru_cache(maxsize=1)
def http_requests_counter() -> Counter:
	return Counter(
		"erp_http_requests_total",
		"Số request HTTP được ERP xử lý",
		["method", "path_group", "status"],
		registry=_registry(),
	)


@lru_cache(maxsize=1)
def http_request_duration_histogram() -> Histogram:
	return Histogram(
		"erp_http_request_duration_seconds",
		"Thời gian xử lý request HTTP ERP (giây)",
		["method", "path_group"],
		buckets=_DEFAULT_BUCKETS,
		registry=_registry(),
	)


def normalize_path(path: str) -> str:
	"""Thu gọn path (giảm cardinality)."""
	if not path:
		return "unknown"
	p = _RE_LONG_NUM_SEGMENT.sub("/{num}", path)
	p = _RE_UUID.sub("{uuid}", p)
	if len(p) > 200:
		return p[:200]
	return p


def observe_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
	"""Ghi nhận một request vào Counter + Histogram."""
	try:
		path_g = normalize_path(path or "")
	except Exception:
		path_g = "error_normalizing_path"

	st = str(int(status_code) if status_code is not None else 0)
	method = (method or "UNKNOWN").upper()
	http_requests_counter().labels(method=method, path_group=path_g, status=st).inc()
	http_request_duration_histogram().labels(method=method, path_group=path_g).observe(
		max(0.0, float(duration_seconds))
	)


def generate_metrics_bytes() -> bytes:
	"""Nội dung text exposition cho Prometheus."""
	from prometheus_client import generate_latest

	return generate_latest(_registry())
