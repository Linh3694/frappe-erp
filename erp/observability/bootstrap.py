# Copyright (c) 2026, Wellspring ERP
"""Khởi tạo OTel và logger domain erp.observability (một lần mỗi process Frappe).

Logger được gắn RotatingFileHandler ghi thẳng vào sites/<site>/logs/frappe.log
để Promtail tail được. StreamHandler giữ lại cho dev (bench start).
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# Định dạng dòng log tương thích regex Promtail Wellspring:
#   '^(?P<ts>[^|]+)' + selector |= "erp.observability" + 'erp\.observability:\s*(?P<obs_json>\{.*\})'
# ⇒ Format ts | level | erp.observability: <json>
_LOG_FORMAT = "%(asctime)s,%(msecs)03d | %(levelname)s | erp.observability: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Mỗi file 100MB, giữ 10 file = 1GB tối đa cho observability log.
_MAX_BYTES = 100 * 1024 * 1024
_BACKUP_COUNT = 10


def _ensure_file_handler(logger: logging.Logger, log_path: str) -> None:
	"""Gắn RotatingFileHandler nếu chưa có handler trỏ tới đúng file."""
	for h in logger.handlers:
		if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == log_path:
			return
	try:
		os.makedirs(os.path.dirname(log_path), exist_ok=True)
		fh = RotatingFileHandler(log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
		fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
		fh.setLevel(logging.INFO)
		logger.addHandler(fh)
	except Exception:
		import traceback

		# Không raise — nếu fail vẫn còn StreamHandler / log mặc định.
		try:
			import frappe

			frappe.errprint(f"[observability] add file handler failed: {traceback.format_exc()}")
		except Exception:
			pass


def init_observability():
	"""Gọi từ before_request middleware — lazy import để không chặn import app."""
	import frappe

	# Cờ per-request để không setup lại nhiều lần trong cùng request.
	if getattr(frappe.local, "_wis_obs_init_done", False):
		return True
	frappe.local._wis_obs_init_done = True

	logger = logging.getLogger("erp.observability")
	logger.setLevel(logging.INFO)
	# Tránh log truyền lên root logger (Frappe có thể double-log).
	logger.propagate = False

	# Stream handler (dev/bench start) — chỉ gắn 1 lần.
	if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in logger.handlers):
		sh = logging.StreamHandler()
		sh.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
		sh.setLevel(logging.INFO)
		logger.addHandler(sh)

	# File handler trỏ vào sites/<site>/logs/frappe.log — đây là file Promtail tail.
	try:
		site_path = frappe.get_site_path()  # absolute path tới sites/<site>
		log_path = os.path.join(site_path, "logs", "frappe.log")
		_ensure_file_handler(logger, log_path)
	except Exception:
		import traceback

		frappe.errprint(f"[observability] resolve site log path failed: {traceback.format_exc()}")

	# OTel optional.
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
