# Copyright (c) 2026, Wellspring ERP
"""Khởi tạo OTel và logger domain erp.observability (một lần mỗi request/context)."""


def init_observability():
	"""Gọi từ before_request middleware — lazy import để không chặn import app."""
	import frappe

	if getattr(frappe.local, "_wis_obs_init_done", False):
		return True
	frappe.local._wis_obs_init_done = True

	import logging
	import os

	logger = logging.getLogger("erp.observability")
	if not logger.handlers:
		# Formatter đơn giản cho frappe.log đồng thời
		h = logging.StreamHandler()
		h.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
		logger.addHandler(h)
	logger.setLevel(logging.INFO)

	ep = (
		frappe.conf.get("otel_exporter_otlp_endpoint")
		or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
		or ""
	)
	ep = ep.replace("grpc://", "").strip()

	if ep:
		try:
			from erp.observability import tracing_backend

			tracing_backend.configure_otel(endpoint_hostport=ep, service_name="erp")
		except Exception:
			import traceback

			frappe.errprint(f"[observability] OTel init failed: {traceback.format_exc()}")

	return True
