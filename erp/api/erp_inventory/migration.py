# Copyright (c) 2026, Wellspring International School
# Migration IT Inventory: proxy export từ Node + đối chiếu count

import re

import frappe
from frappe import _

from erp.utils.api_response import success_response, error_response

DEVICE_TYPES = ("laptop", "monitor", "printer", "projector", "phone", "tool")
MIGRATION_ROLES = ("System Manager", "SIS IT")
EXPORT_PATHS = {
	"devices": "/api/inventory/migration/full-export/{device_type}",
	"activities": "/api/inventory/migration/activity-export",
	"inspections": "/api/inventory/migration/inspect-export",
}


def cint_safe(v):
	try:
		return int(v)
	except Exception:
		return 0


def _require_migration_role():
	roles = frappe.get_roles(frappe.session.user)
	if not any(r in roles for r in MIGRATION_ROLES):
		frappe.throw(_("Chỉ System Manager hoặc SIS IT được thực hiện migration"), frappe.PermissionError)


def _inventory_service_base_url():
	return (
		frappe.conf.get("inventory_service_url")
		or frappe.get_site_config().get("inventory_service_url")
		or "http://172.16.20.113:5010"
	).rstrip("/")


def _inventory_service_headers():
	"""Forward JWT user hoặc dùng service token cấu hình trên site."""
	headers = {"Accept": "*/*"}
	auth = frappe.get_request_header("Authorization")
	if auth:
		headers["Authorization"] = auth
		return headers

	token = frappe.conf.get("inventory_internal_token") or frappe.get_site_config().get("inventory_internal_token")
	if token:
		headers["X-Service-Token"] = token
		return headers

	frappe.throw(_("Không xác thực được với inventory-service. Vui lòng đăng nhập lại."))


def _filename_from_disposition(disposition, fallback):
	if not disposition:
		return fallback
	match = re.search(r'filename="?([^";\n]+)"?', disposition)
	return match.group(1) if match else fallback


def _proxy_migration_download(path, fallback_filename):
	import requests

	_require_migration_role()
	url = f"{_inventory_service_base_url()}{path}"
	try:
		resp = requests.get(url, headers=_inventory_service_headers(), timeout=600)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.migration.proxy")
		frappe.throw(_("Không kết nối được inventory-service: {0}").format(exc))

	if resp.status_code != 200:
		message = resp.text[:500] if resp.text else resp.reason
		try:
			payload = resp.json()
			message = payload.get("message") or payload.get("error") or message
		except Exception:
			pass
		frappe.throw(_("Export thất bại ({0}): {1}").format(resp.status_code, message))

	content_type = resp.headers.get("Content-Type", "")
	if "json" in content_type:
		try:
			payload = resp.json()
			frappe.throw(payload.get("message") or _("Export trả về JSON thay vì file Excel"))
		except Exception:
			frappe.throw(_("Export không trả về file Excel hợp lệ"))

	filename = _filename_from_disposition(resp.headers.get("Content-Disposition"), fallback_filename)
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = resp.content
	frappe.local.response.type = "download"
	return


@frappe.whitelist(allow_guest=False)
def export_migration_devices(device_type=None):
	"""Proxy export Excel thiết bị + lịch sử bàn giao từ inventory-service."""
	dt = (device_type or frappe.form_dict.get("device_type") or "").strip().lower()
	if dt not in DEVICE_TYPES:
		frappe.throw(_("Loại thiết bị không hợp lệ: {0}").format(device_type))
	path = EXPORT_PATHS["devices"].format(device_type=dt)
	return _proxy_migration_download(path, f"migration-{dt}.xlsx")


@frappe.whitelist(allow_guest=False)
def export_migration_activities():
	"""Proxy export activity log từ inventory-service."""
	return _proxy_migration_download(EXPORT_PATHS["activities"], "migration-activities.xlsx")


@frappe.whitelist(allow_guest=False)
def export_migration_inspections():
	"""Proxy export inspection từ inventory-service."""
	return _proxy_migration_download(EXPORT_PATHS["inspections"], "migration-inspections.xlsx")


@frappe.whitelist(allow_guest=False)
def get_migration_status():
	"""Số lượng bản ghi hiện có trên Frappe (sau import)."""
	_require_migration_role()
	actual = {}
	for dt in DEVICE_TYPES:
		actual[dt] = frappe.db.count("ERP Inventory Device", {"device_type": dt})
	actual["handover"] = frappe.db.count("ERP Inventory Handover Log")
	actual["inspection"] = frappe.db.count("ERP Inventory Inspection")
	actual["activity"] = frappe.db.count("ERP Inventory Activity Log")
	return success_response(data=actual, message=_("Trạng thái dữ liệu Inventory IT"))


@frappe.whitelist(allow_guest=False)
def reconcile_migration_counts(expected_counts=None):
	"""
	Đối chiếu số lượng bản ghi sau import.
	expected_counts: JSON {"laptop": 10, "monitor": 5, ..., "handover": 100, "inspection": 20, "activity": 30}
	"""
	try:
		import json

		_require_migration_role()
		data = expected_counts
		if isinstance(data, str):
			data = json.loads(data) if data else {}
		if not data and frappe.form_dict.get("expected_counts"):
			raw = frappe.form_dict.get("expected_counts")
			data = json.loads(raw) if isinstance(raw, str) else raw

		actual = {}
		for dt in DEVICE_TYPES:
			actual[dt] = frappe.db.count("ERP Inventory Device", {"device_type": dt})
		actual["handover"] = frappe.db.count("ERP Inventory Handover Log")
		actual["inspection"] = frappe.db.count("ERP Inventory Inspection")
		actual["activity"] = frappe.db.count("ERP Inventory Activity Log")

		diff = {}
		for key, exp in (data or {}).items():
			act = actual.get(key, 0)
			if cint_safe(exp) != act:
				diff[key] = {"expected": cint_safe(exp), "actual": act, "delta": act - cint_safe(exp)}

		return success_response(
			data={"actual": actual, "expected": data or {}, "diff": diff, "ok": len(diff) == 0},
			message=_("Đối chiếu migration"),
		)
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.reconcile_migration_counts")
		return error_response(str(e))
