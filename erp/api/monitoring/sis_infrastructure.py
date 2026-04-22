# Copyright (c) 2025, Wellspring. API metrics hạ tầng cho SIS IT.

"""
Thu thập metric từ máy chạy Frappe, Redis, MariaDB — chỉ role SIS IT.
"""

import os
import socket
from datetime import datetime, timezone

import frappe
from frappe import _


# Các cột MySQL cần trả lên (tránh vài trăm dòng)
_MYSQL_STATUS_NAMES = {
	"Uptime",
	"Queries",
	"Questions",
	"Slow_queries",
	"Threads_connected",
	"Threads_running",
	"Max_used_connections",
	"Table_locks_immediate",
	"Table_locks_waited",
	"Bytes_received",
	"Bytes_sent",
	"Connections",
	"Aborted_connects",
	"Innodb_buffer_pool_read_requests",
	"Innodb_buffer_pool_reads",
	"Innodb_rows_read",
	"Innodb_rows_inserted",
	"Innodb_rows_updated",
	"Innodb_rows_deleted",
	"Open_tables",
	"Table_open_cache_hits",
}

_MYSQL_VARIABLE_NAMES = {
	"version",
	"version_comment",
	"max_connections",
	"thread_cache_size",
	"table_open_cache",
	"innodb_buffer_pool_size",
	"innodb_log_file_size",
	"datadir",
	"character_set_server",
	"max_allowed_packet",
}


def _require_sis_it():
	# Chỉ SIS IT (theo yêu cầu sản phẩm)
	roles = frappe.get_roles(frappe.session.user) or []
	if "SIS IT" not in roles:
		frappe.throw(_("Chỉ SIS IT mới truy cập màn Monitoring"), frappe.PermissionError)


def _host_metrics():
	"""Số liệu OS trên máy đang chạy tiến trình Frappe (Gunicorn)."""
	data = {
		"hostname": socket.gethostname(),
		"python_process_id": os.getpid(),
	}
	try:
		import psutil  # gói kèm Frappe

		vm = psutil.virtual_memory()
		data["memory"] = {
			"total_bytes": vm.total,
			"total_human": _bytes_human(vm.total),
			"available_bytes": vm.available,
			"available_human": _bytes_human(vm.available),
			"percent_used": round(vm.percent, 2),
		}
		disk = psutil.disk_usage("/")
		data["disk_root"] = {
			"total_bytes": disk.total,
			"total_human": _bytes_human(disk.total),
			"free_bytes": disk.free,
			"free_human": _bytes_human(disk.free),
			"percent_used": round(disk.percent, 2),
		}
		try:
			data["loadavg_1_5_15"] = [round(x, 2) for x in os.getloadavg()]
		except (OSError, AttributeError):
			data["loadavg_1_5_15"] = None
		try:
			data["cpu_percent"] = round(psutil.cpu_percent(interval=0.15), 2)
		except Exception:
			data["cpu_percent"] = None
		data["cpu_count"] = psutil.cpu_count(logical=True)
		try:
			boot = psutil.boot_time()
			data["boot_time_utc"] = datetime.fromtimestamp(boot, tz=timezone.utc).isoformat()
		except Exception:
			data["boot_time_utc"] = None
	except Exception as e:
		data["error"] = str(e)
	return data


def _bytes_human(n):
	if n is None:
		return None
	for unit, div in (("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
		if n >= div:
			return f"{n / div:.2f} {unit}B"
	return f"{n} B"


def _safe_info(client, section):
	try:
		return client.info(section)
	except Exception:
		return None


def _redis_section(url, name):
	"""Ẩn user/password trong URL — chỉ hiện host:port/db."""
	if not url:
		return {"name": name, "error": "missing_redis_url"}
	hint = url
	if "@" in url:
		hint = url.split("@", 1)[-1]
	result = {"name": name, "connection_hint": hint}
	try:
		import redis as redis_mod

		client = redis_mod.from_url(url, decode_responses=True)
		result["info_memory"] = _safe_info(client, "memory")
		result["info_clients"] = _safe_info(client, "clients")
		result["info_stats"] = _safe_info(client, "stats")
		result["info_cpu"] = _safe_info(client, "cpu")
		try:
			result["dbsize"] = client.dbsize()
		except Exception:
			result["dbsize"] = None
		result["keyspace"] = _safe_info(client, "keyspace")
		if "/" in url.rsplit(":", 1)[-1]:
			parts = url.rsplit("/", 1)
			if len(parts) == 2 and parts[-1].isdigit():
				result["db_index"] = int(parts[-1])
		client.connection_pool.disconnect()
	except Exception as e:
		result["error"] = str(e)
	return result


def _mysql_combined():
	out = {"status": {}, "variables": {}}
	try:
		rows = frappe.db.sql("SHOW GLOBAL STATUS", as_list=True)
		for k, v in rows:
			if k in _MYSQL_STATUS_NAMES:
				if isinstance(v, (int, float)):
					out["status"][k] = int(v) if float(v) == int(float(v)) else v
				else:
					s = str(v)
					if s.replace(".", "", 1).isdigit() and s.count(".") <= 1:
						try:
							out["status"][k] = int(s) if "." not in s else float(s)
						except ValueError:
							out["status"][k] = v
					else:
						out["status"][k] = v
		vrows = frappe.db.sql("SHOW GLOBAL VARIABLES", as_list=True)
		for k, v in vrows:
			if k in _MYSQL_VARIABLE_NAMES:
				if k == "innodb_buffer_pool_size" and str(v).isdigit():
					out["variables"][k] = int(v)
					out["variables"]["innodb_buffer_pool_size_human"] = _bytes_human(int(v))
				else:
					out["variables"][k] = v
	except Exception as e:
		out["error"] = str(e)
	return out


def _frappe_meta():
	vers = {}
	try:
		vers = frappe.get_versions() or {}
	except Exception:
		pass
	return {
		"site": getattr(frappe.local, "site", None) or frappe.get_site_name(),
		"apps_versions": vers,
		"conf_workers": {
			"gunicorn_workers": frappe.conf.get("gunicorn_workers"),
			"gunicorn_timeout": frappe.conf.get("gunicorn_timeout"),
			"background_workers": frappe.conf.get("background_workers"),
		},
		"db_host": frappe.conf.get("db_host") or "localhost",
		"db_name": frappe.conf.get("db_name"),
		"db_type": frappe.conf.get("db_type", "mariadb"),
	}


@frappe.whitelist()
def get_sis_infrastructure_metrics():
	"""
	Trả về toàn bộ metric SIS IT cần (host Frappe, Redis, MariaDB, meta Frappe).
	Endpoint: /api/method/erp.api.monitoring.sis_infrastructure.get_sis_infrastructure_metrics
	"""
	_require_sis_it()
	payload = {
		"ok": True,
		"collected_at": frappe.utils.now(),
		"frappe": _frappe_meta(),
		"host": _host_metrics(),
		"mariadb": _mysql_combined(),
		"redis_cache": {},
		"redis_queue": {},
		"redis_socketio": {},
		"attendance_buffer": None,
	}
	# Hikvision buffer (chỉ số, không dữ liệu nhạy cảm)
	try:
		from erp.api.attendance.hikvision import get_buffer_length, USE_DIRECT_PROCESSING

		payload["attendance_buffer"] = {
			"pending_events": get_buffer_length(),
			"USE_DIRECT_PROCESSING": USE_DIRECT_PROCESSING,
		}
	except Exception as e:
		payload["attendance_buffer"] = {"error": str(e)}

	rc = frappe.conf.get("redis_cache")
	rq = frappe.conf.get("redis_queue")
	rs = frappe.conf.get("redis_socketio")
	payload["redis_cache"] = _redis_section(rc, "redis_cache")
	payload["redis_queue"] = _redis_section(rq, "redis_queue")
	payload["redis_socketio"] = _redis_section(rs, "redis_socketio")

	return payload
