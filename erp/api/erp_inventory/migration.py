# Copyright (c) 2026, Wellspring International School
# Migration IT Inventory: đồng bộ một nút từ inventory-service → Frappe

import os
import re
import uuid

import frappe
from frappe import _

from erp.utils.api_response import success_response, error_response
from erp.api.erp_inventory.inventory_helpers import DEVICE_TYPES, require_migration_role
from erp.api.erp_inventory.import_excel import (
	import_activities_from_excel_file,
	import_devices_from_excel_file,
	import_inspections_from_excel_file,
)
from erp.api.erp_inventory.handover_file import sync_legacy_files_full

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


def _inventory_service_base_url():
	return (
		frappe.conf.get("inventory_service_url")
		or frappe.get_site_config().get("inventory_service_url")
		or "http://172.16.20.113:5010"
	).rstrip("/")


def _inventory_service_headers():
	"""JWT user hoặc service token — dùng cho proxy export / đồng bộ."""
	headers = {"Accept": "*/*"}
	auth = frappe.get_request_header("Authorization")
	if auth:
		headers["Authorization"] = auth
		return headers

	token = frappe.conf.get("inventory_internal_token") or frappe.get_site_config().get("inventory_internal_token")
	if token:
		headers["X-Service-Token"] = token
		return headers

	frappe.throw(_("Không xác thực được với inventory-service. Cấu hình inventory_internal_token hoặc đăng nhập lại."))


def _filename_from_disposition(disposition, fallback):
	if not disposition:
		return fallback
	match = re.search(r'filename="?([^";\n]+)"?', disposition)
	return match.group(1) if match else fallback


def _fetch_migration_excel(path, fallback_filename):
	"""Gọi inventory-service, lưu Excel tạm, trả về đường dẫn file."""
	import requests

	url = f"{_inventory_service_base_url()}{path}"
	try:
		resp = requests.get(url, headers=_inventory_service_headers(), timeout=600)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "erp_inventory.migration.fetch")
		frappe.throw(_("Không kết nối được inventory-service: {0}").format(exc))

	if resp.status_code != 200:
		message = resp.text[:500] if resp.text else resp.reason
		try:
			payload = resp.json()
			message = payload.get("message") or payload.get("error") or message
		except Exception:
			pass
		frappe.throw(_("Lấy dữ liệu thất bại ({0}): {1}").format(resp.status_code, message))

	content_type = resp.headers.get("Content-Type", "")
	if "json" in content_type:
		try:
			payload = resp.json()
			frappe.throw(payload.get("message") or _("inventory-service trả về JSON thay vì Excel"))
		except Exception:
			frappe.throw(_("Phản hồi không phải file Excel"))

	filename = _filename_from_disposition(resp.headers.get("Content-Disposition"), fallback_filename)
	ext = os.path.splitext(filename)[1] or ".xlsx"
	temp_path = os.path.join(
		frappe.get_site_path("private", "files"),
		f"inv_sync_{uuid.uuid4().hex}{ext}",
	)
	os.makedirs(os.path.dirname(temp_path), exist_ok=True)
	with open(temp_path, "wb") as f:
		f.write(resp.content)
	return temp_path


def _proxy_migration_download(path, fallback_filename):
	"""Proxy download Excel cho FE (giữ tương thích nút export thủ công)."""
	require_migration_role()
	temp_path = _fetch_migration_excel(path, fallback_filename)
	try:
		with open(temp_path, "rb") as f:
			content = f.read()
	finally:
		try:
			os.remove(temp_path)
		except Exception:
			pass
	frappe.local.response.filename = fallback_filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "download"


def _get_migration_counts():
	actual = {}
	for dt in DEVICE_TYPES:
		actual[dt] = frappe.db.count("ERP Inventory Device", {"device_type": dt})
	actual["handover"] = frappe.db.count("ERP Inventory Handover Log")
	actual["inspection"] = frappe.db.count("ERP Inventory Inspection")
	actual["activity"] = frappe.db.count("ERP Inventory Activity Log")
	return actual


@frappe.whitelist(allow_guest=False)
def run_full_sync(sync_files=1):
	"""
	Đồng bộ toàn bộ: gọi inventory-service → import DB → copy file handover/report.
	Một nút trên FE, không cần export/import Excel thủ công.
	"""
	require_migration_role()
	logs = []
	steps = {}
	all_errors = []

	try:
		sync_files_flag = cint_safe(sync_files) != 0

		# 1) Import 6 loại thiết bị + handover history
		for dt in DEVICE_TYPES:
			logs.append(_("Đang đồng bộ thiết bị: {0}").format(dt))
			frappe.publish_progress(percent=(DEVICE_TYPES.index(dt) + 1) * 8, title=_("Đồng bộ Inventory IT"))
			temp_path = None
			try:
				path = EXPORT_PATHS["devices"].format(device_type=dt)
				temp_path = _fetch_migration_excel(path, f"migration-{dt}.xlsx")
				result = import_devices_from_excel_file(temp_path, dt)
				steps[f"devices_{dt}"] = result
				all_errors.extend(result.get("errors") or [])
			finally:
				if temp_path and os.path.exists(temp_path):
					try:
						os.remove(temp_path)
					except Exception:
						pass

		# 2) Inspections
		logs.append(_("Đang đồng bộ kiểm tra thiết bị"))
		frappe.publish_progress(percent=55, title=_("Đồng bộ Inventory IT"))
		temp_path = None
		try:
			temp_path = _fetch_migration_excel(EXPORT_PATHS["inspections"], "migration-inspections.xlsx")
			insp_result = import_inspections_from_excel_file(temp_path)
			steps["inspections"] = insp_result
			all_errors.extend(insp_result.get("errors") or [])
		finally:
			if temp_path and os.path.exists(temp_path):
				try:
					os.remove(temp_path)
				except Exception:
					pass

		# 3) Activities
		logs.append(_("Đang đồng bộ nhật ký sửa chữa"))
		frappe.publish_progress(percent=70, title=_("Đồng bộ Inventory IT"))
		temp_path = None
		try:
			temp_path = _fetch_migration_excel(EXPORT_PATHS["activities"], "migration-activities.xlsx")
			act_result = import_activities_from_excel_file(temp_path)
			steps["activities"] = act_result
			all_errors.extend(act_result.get("errors") or [])
		finally:
			if temp_path and os.path.exists(temp_path):
				try:
					os.remove(temp_path)
				except Exception:
					pass

		# 4) Copy file vật lý + đăng ký File doc
		files_result = None
		if sync_files_flag:
			logs.append(_("Đang copy file handover và báo cáo"))
			frappe.publish_progress(percent=85, title=_("Đồng bộ Inventory IT"))
			files_result = sync_legacy_files_full()
			steps["files"] = files_result

		frappe.publish_progress(percent=100, title=_("Hoàn tất"))
		counts = _get_migration_counts()
		ok = len(all_errors) == 0

		return success_response(
			data={
				"ok": ok,
				"counts": counts,
				"steps": steps,
				"errors": all_errors[:100],
				"error_count": len(all_errors),
				"logs": logs,
			},
			message=_("Đồng bộ hoàn tất") if ok else _("Đồng bộ xong với {0} lỗi").format(len(all_errors)),
			logs=logs,
		)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.run_full_sync")
		return error_response(str(e), logs=logs)


@frappe.whitelist(allow_guest=False)
def export_migration_devices(device_type=None):
	dt = (device_type or frappe.form_dict.get("device_type") or "").strip().lower()
	if dt not in DEVICE_TYPES:
		frappe.throw(_("Loại thiết bị không hợp lệ: {0}").format(device_type))
	path = EXPORT_PATHS["devices"].format(device_type=dt)
	return _proxy_migration_download(path, f"migration-{dt}.xlsx")


@frappe.whitelist(allow_guest=False)
def export_migration_activities():
	return _proxy_migration_download(EXPORT_PATHS["activities"], "migration-activities.xlsx")


@frappe.whitelist(allow_guest=False)
def export_migration_inspections():
	return _proxy_migration_download(EXPORT_PATHS["inspections"], "migration-inspections.xlsx")


@frappe.whitelist(allow_guest=False)
def get_migration_status():
	require_migration_role()
	return success_response(data=_get_migration_counts(), message=_("Trạng thái dữ liệu Inventory IT"))


@frappe.whitelist(allow_guest=False)
def reconcile_migration_counts(expected_counts=None):
	try:
		import json

		require_migration_role()
		data = expected_counts
		if isinstance(data, str):
			data = json.loads(data) if data else {}
		if not data and frappe.form_dict.get("expected_counts"):
			raw = frappe.form_dict.get("expected_counts")
			data = json.loads(raw) if isinstance(raw, str) else raw

		actual = _get_migration_counts()
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
