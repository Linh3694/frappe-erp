# Copyright (c) 2026, Wellspring ERP
"""Whitelist endpoint metrics Prometheus (/api/method/erp.api.observability.prometheus.metrics)."""

from __future__ import annotations

import frappe
from werkzeug.wrappers import Response

_PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@frappe.whitelist(allow_guest=True, methods=["GET"])
def metrics():
	"""
	Expose ERP Prometheus counters/histogram — bắt buộc cấu hình token trong site_config.json:

	"prometheus_metrics_token": "<chuỗi bí mật>"
	Header: Authorization: Bearer <chuỗi> hoặc X-Prometheus-Token: <chuỗi>
	"""

	token_cfg_raw = frappe.conf.get("prometheus_metrics_token") or frappe.conf.get("otel_metrics_token")
	token_cfg = (token_cfg_raw or "").strip()
	if not token_cfg:
		frappe.throw(
			frappe._(
				"Chưa cấu hình prometheus_metrics_token trong site_config.json — không cho expose metrics.",
			),
			frappe.ValidationError,
		)

	hdr = frappe.request.headers
	auth_raw = (hdr.get("Authorization") or "").strip()
	token_hdr = (hdr.get("X-Prometheus-Token") or "").strip()

	# Bearer / token do nginx hoặc file credentials Prometheus đôi khi có khoảng trắng thừa.
	bearer_ok = False
	prefix = "bearer "
	if auth_raw.lower().startswith(prefix):
		bearer_ok = auth_raw[len(prefix) :].strip() == token_cfg

	token_ok = token_hdr == token_cfg
	if not bearer_ok and not token_ok:
		frappe.throw(frappe._("Forbidden"), frappe.AuthenticationError)

	from erp.observability.metrics import generate_metrics_bytes

	body = generate_metrics_bytes()
	return Response(body, mimetype=_PROM_CONTENT_TYPE)
