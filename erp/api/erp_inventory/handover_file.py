# Copyright (c) 2026, Wellspring International School
# Upload biên bản bàn giao + đăng ký file legacy sau migration

import json
import os
import shutil
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import get_bench_path, get_site_path, now_datetime

from erp.utils.api_response import error_response, not_found_response, success_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import (
	normalize_device_type,
	read_api_param,
	normalize_api_param,
)
from erp.api.erp_inventory.device import _resolve_device_name


@frappe.whitelist(allow_guest=False, methods=["GET", "POST"])
def upload_handover_report(device_type=None):
	"""Upload BBBG — tương đương POST /api/inventory/{type}s/upload."""
	try:
		form = frappe.form_dict
		dt = normalize_device_type(
			read_api_param("device_type", "deviceType", fallback=device_type)
			or normalize_api_param(form.get("device_type") or form.get("deviceType"))
		)
		device_id = (
			form.get(f"{dt}Id")
			or form.get("device_id")
			or form.get("deviceId")
			or form.get("laptopId")
		)
		device_id = _resolve_device_name(normalize_api_param(device_id), dt)
		if not device_id or not frappe.db.exists("ERP Inventory Device", device_id):
			return not_found_response(_("Không tìm thấy thiết bị"))

		files = frappe.request.files
		if not files or "file" not in files:
			return validation_error_response(_("Không có file được tải lên"), {"file": ["required"]})

		username = form.get("username") or frappe.db.get_value("User", frappe.session.user, "full_name") or "Unknown"

		ext = os.path.splitext(files["file"].filename)[1] or ".pdf"
		date_str = datetime.now().strftime("%Y-%m-%d")
		new_name = f"BBBG-{username}-{date_str}{ext}".replace(" ", "_")

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": new_name,
				"content": files["file"].stream.read(),
				"is_private": 0,
				"folder": "Home/inventory/handovers",
				"attached_to_doctype": "ERP Inventory Device",
				"attached_to_name": device_id,
			}
		)
		file_doc.save(ignore_permissions=True)

		# Cập nhật handover log đang mở
		open_logs = frappe.get_all(
			"ERP Inventory Handover Log",
			filters={"device": device_id, "end_date": ["is", "not set"]},
			pluck="name",
		)
		for log_name in open_logs:
			log_doc = frappe.get_doc("ERP Inventory Handover Log", log_name)
			log_doc.document_file_url = file_doc.file_url
			log_doc.document_file = file_doc.file_url
			log_doc.save(ignore_permissions=True)

		# Nếu có biên bản → Active
		device = frappe.get_doc("ERP Inventory Device", device_id)
		if device.status == "PendingDocumentation":
			device.status = "Active"
			device.save(ignore_permissions=True)

		frappe.db.commit()
		return {
			"message": "Upload thành công",
			"filePath": file_doc.file_url,
			"filename": new_name,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.upload_handover_report")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def register_legacy_files(folder="handovers"):
	"""Đăng ký file đã copy vào sites/<site>/public/files/inventory/{folder}/."""
	try:
		result = register_legacy_files_internal(folder)
		frappe.db.commit()
		return success_response(data=result, message=_("Đã đăng ký file legacy"))
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.register_legacy_files")
		return error_response(str(e))


def _inventory_uploads_path():
	"""Đường dẫn thư mục uploads của inventory-service trên server."""
	cfg = frappe.conf.get("inventory_uploads_path") or frappe.get_site_config().get("inventory_uploads_path")
	if cfg:
		return cfg.rstrip("/")
	return os.path.join(get_bench_path(), "inventory-service", "uploads")


def copy_legacy_upload_files():
	"""Copy file handover/report từ inventory-service sang Frappe public files."""
	source_base = _inventory_uploads_path()
	target_base = os.path.join(get_site_path("public", "files", "inventory"))
	mapping = [("Handovers", "handovers"), ("reports", "reports")]
	copied = 0
	warnings = []

	os.makedirs(target_base, exist_ok=True)
	for src_folder, dst_folder in mapping:
		src = os.path.join(source_base, src_folder)
		dst = os.path.join(target_base, dst_folder)
		os.makedirs(dst, exist_ok=True)
		if not os.path.isdir(src):
			warnings.append(_("Không tìm thấy thư mục nguồn: {0}").format(src))
			continue
		for fname in os.listdir(src):
			spath = os.path.join(src, fname)
			if not os.path.isfile(spath):
				continue
			dpath = os.path.join(dst, fname)
			shutil.copy2(spath, dpath)
			copied += 1

	return {"copied_files": copied, "source": source_base, "target": target_base, "warnings": warnings}


def register_legacy_files_internal(folder="handovers"):
	"""Đăng ký File doc + cập nhật handover log theo tên file."""
	base = os.path.join(get_site_path("public", "files", "inventory", folder))
	if not os.path.isdir(base):
		frappe.throw(_("Thư mục không tồn tại: {0}").format(base))

	created = 0
	updated = 0
	for fname in os.listdir(base):
		fpath = os.path.join(base, fname)
		if not os.path.isfile(fpath):
			continue
		file_url = f"/files/inventory/{folder}/{fname}"
		existing = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not existing:
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": fname,
					"file_url": file_url,
					"is_private": 0,
					"folder": f"Home/inventory/{folder}",
				}
			).insert(ignore_permissions=True)
			created += 1

		logs = frappe.get_all(
			"ERP Inventory Handover Log",
			filters=[["document_file_url", "like", f"%{fname}"]],
			pluck="name",
		)
		for log_name in logs:
			log_doc = frappe.get_doc("ERP Inventory Handover Log", log_name)
			log_doc.document_file_url = file_url
			log_doc.document_file = file_url
			log_doc.save(ignore_permissions=True)
			updated += 1

	return {"created_files": created, "updated_handover_logs": updated, "folder": folder}


def sync_legacy_files_full():
	"""Copy file vật lý + đăng ký File doc (handovers + reports)."""
	copy_result = copy_legacy_upload_files()
	register_handovers = register_legacy_files_internal("handovers")
	register_reports = register_legacy_files_internal("reports")
	frappe.db.commit()
	return {
		**copy_result,
		"handovers": register_handovers,
		"reports": register_reports,
	}
