# Copyright (c) 2026, Wellspring ERP
"""Khởi tạo OTel và logger domain erp.observability (một lần mỗi process Frappe).

Logger được gắn RotatingFileHandler ghi thẳng vào sites/<site>/logs/frappe.log
để Promtail tail được. StreamHandler giữ lại cho dev (bench start).

QUAN TRỌNG (lý do thiết kế per-process):
	- Trước đây init dùng cờ `frappe.local._wis_obs_init_done` (per-request) → mỗi request đầu
	  của mỗi worker thread đều chạy lại `_ensure_file_handler`. Khi gunicorn dùng gthread/gevent,
	  nhiều thread cùng init đồng thời → race trong vòng `for h in logger.handlers` → có thể
	  attach N handler trỏ cùng file → mỗi log call ghi N lần → I/O amplification → workers
	  chậm dần → server treo (phải bench restart).
	- Sửa: cờ + threading.Lock ở MODULE LEVEL, init đúng 1 lần per-process, an toàn đa thread.
"""

import logging
import os
import threading
from logging.handlers import RotatingFileHandler

# Định dạng dòng log tương thích regex Promtail Wellspring:
#   '^(?P<ts>[^|]+)' + selector |= "erp.observability" + 'erp\.observability:\s*(?P<obs_json>\{.*\})'
# ⇒ Format ts | level | erp.observability: <json>
_LOG_FORMAT = "%(asctime)s,%(msecs)03d | %(levelname)s | erp.observability: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Mỗi file 100MB, giữ 10 file = 1GB tối đa cho observability log.
_MAX_BYTES = 100 * 1024 * 1024
_BACKUP_COUNT = 10

# Khoá module-level đảm bảo init chỉ chạy 1 lần per-process (Frappe gunicorn worker).
# Dùng cùng lock cho cả gắn StreamHandler/FileHandler để tránh race attach trùng.
_INIT_LOCK = threading.Lock()
_INIT_DONE = False  # set True sau khi init thành công (per-process, không phải per-request)


def _ensure_file_handler(logger: logging.Logger, log_path: str) -> None:
	"""Gắn RotatingFileHandler nếu chưa có handler trỏ tới đúng file.

	GHI CHÚ: chỉ gọi trong block đã giữ `_INIT_LOCK` để không race attach trùng.
	"""
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
	"""Gọi từ before_request middleware — lazy import để không chặn import app.

	Sau lần đầu init thành công, các lần gọi sau return ngay (fast-path, không lock).
	"""
	global _INIT_DONE

	# Fast-path: 99.9% request đi qua đây sau khi init xong → không cost lock.
	if _INIT_DONE:
		return True

	import frappe

	# Slow-path: chỉ 1 thread đầu tiên của process vào critical section.
	with _INIT_LOCK:
		if _INIT_DONE:
			return True

		logger = logging.getLogger("erp.observability")
		logger.setLevel(logging.INFO)
		# Tránh log truyền lên root logger (Frappe có thể double-log).
		logger.propagate = False

		# Stream handler (dev/bench start) — chỉ gắn 1 lần.
		# isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler) → loại trừ file handler.
		if not any(
			isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
			for h in logger.handlers
		):
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

		_INIT_DONE = True

	return True
