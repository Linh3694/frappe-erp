# Copyright (c) 2026, Wellspring ERP
"""Đăng ký before_request / after_request cho metric + log ERP."""

from __future__ import annotations

import re
import time

import frappe

# Chỉ theo các module Parent Portal giống bản hooks_handlers/api_logger.py cũ
PARENT_PORTAL_MODULES = {
	"Announcements": r"/api/method/erp\.api\.parent_portal\.announcements",
	"Attendance": r"/api/method/erp\.api\.parent_portal\.attendance",
	"Bus": r"/api/method/erp\.api\.parent_portal\.bus",
	"Calendar": r"/api/method/erp\.api\.parent_portal\.calendar",
	"Communication": r"/api/method/erp\.api\.parent_portal\.contact_log",
	"Feedback": r"/api/method/erp\.api\.parent_portal\.feedback",
	"Leave": r"/api/method/erp\.api\.parent_portal\.leave",
	"Menu": r"/api/method/erp\.api\.parent_portal\.daily_menu",
	"News": r"/api/method/erp\.api\.parent_portal\.news",
	"Report Card": r"/api/method/erp\.api\.parent_portal\.report_card",
	"Timetable": r"/api/method/erp\.api\.parent_portal\.timetable",
}


def detect_module(endpoint: str):
	"""Ghép endpoint với một module cố định Parent Portal."""
	for module_name, pattern in PARENT_PORTAL_MODULES.items():
		if re.search(pattern, endpoint):
			return module_name
	return None


def log_api_request_start(**kwargs):
	from erp.observability.bootstrap import init_observability

	init_observability()

	try:
		frappe.local.wis_obs_request_start_ns = time.perf_counter_ns()
		frappe.local.request_path = frappe.request.path
		frappe.local.request_method = frappe.request.method
	except Exception as exc:
		frappe.errprint(f"log_api_request_start: {exc!s}")


def log_api_request_end(**kwargs):
	from erp.observability.bootstrap import init_observability

	init_observability()

	if not getattr(frappe.local, "wis_obs_request_start_ns", None):
		return

	elapsed_ns = time.perf_counter_ns() - frappe.local.wis_obs_request_start_ns
	elapsed_ms = elapsed_ns / 1e6
	elapsed_s = elapsed_ns / 1e9

	path = getattr(frappe.local, "request_path", None) or (frappe.request.path if frappe.request else "")
	pl = path.lower()

	if any(x in pl for x in ["/health", "/api/ping", "/__pycache__", "/api/client.get_count"]):
		return
	# Scrape Prometheus không tính vào RPS dashboard (tránh ~1/30s làm nhiễu).
	if "erp.api.observability.prometheus.metrics" in path:
		return
	if pl.endswith(".js") or pl.endswith(".css"):
		return

	method = getattr(frappe.local, "request_method", None) or (frappe.request.method if frappe.request else "GET")
	user = frappe.session.user if frappe.session else "Guest"

	status_code = 200
	try:
		if hasattr(frappe, "response") and isinstance(frappe.response, dict):
			code = frappe.response.get("_status_code", 200)
			if code is not None:
				status_code = int(str(code).split()[0])
		if frappe.local.response and hasattr(frappe.local.response, "status_code"):
			status_code = int(frappe.local.response.status_code)
	except Exception:
		status_code = 200

	if method == "OPTIONS":
		return

	ip = frappe.get_request_header("X-Forwarded-For") or frappe.request.remote_addr or "unknown"
	if ip and "," in ip:
		ip = ip.split(",")[0].strip()

	ua = frappe.get_request_header("User-Agent") or "unknown"
	if ua != "unknown" and len(ua) > 100:
		ua = ua[:100]

	module_name = detect_module(path)

	# Dedup chỉ áp dụng cho parent portal (spam click)
	if "parent_portal" in path.lower():
		parent_key = f"obs_log_pp:{user}:{path}"
		if frappe.cache().get_value(parent_key):
			return
		frappe.cache().set_value(parent_key, True, expires_in_sec=3)

	from erp.observability.helpers import log_http_access, log_slow_parent_portal
	from erp.observability.metrics import observe_http_request

	observe_http_request(method, path, status_code, elapsed_s)

	details_base = {"ip": ip, "user_agent": ua, "module": module_name}

	log_http_access(user, method, path, elapsed_ms, status_code, details_base)

	try:
		if "parent_portal" in path.lower() and elapsed_ms > 1000:
			extras_s = dict(details_base)
			guardian_name = None
			if user and "@parent.wellspring.edu.vn" in user:
				gid = user.split("@")[0]
				try:
					guardian_name = frappe.db.get_value("CRM Guardian", {"guardian_id": gid}, "name")
				except Exception:
					pass
			req_params = None
			try:
				if frappe.request and frappe.request.args:
					req_params = dict(frappe.request.args)
			except Exception:
				req_params = None
			extras_s["request_params"] = req_params or {}
			extras_s["severity"] = (
				"very_slow"
				if elapsed_ms > 5000
				else ("slow" if elapsed_ms > 3000 else "medium")
			)
			log_slow_parent_portal(user, method, path, elapsed_ms, guardian_name, extras_s)
	except Exception as exc_s:
		frappe.errprint(f"log_slow_parent_portal: {exc_s!s}")
