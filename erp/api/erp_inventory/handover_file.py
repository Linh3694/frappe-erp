# Copyright (c) 2026, Wellspring International School
# Upload biên bản bàn giao + đăng ký file legacy sau migration

import json
import os
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import get_site_path, now_datetime

from erp.utils.api_response import error_response, not_found_response, success_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import normalize_device_type, parse_request_data


@frappe.whitelist(allow_guest=False)
def upload_handover_report(device_type=None):
	"""Upload BBBG — tương đương POST /api/inventory/{type}s/upload."""
	try:
		dt = normalize_device_type(device_type)
		files = frappe.request.files
		if not files or "file" not in files:
			return validation_error_response(_("Không có file được tải lên"), {"file": ["required"]})

		form = frappe.form_dict
		device_id = form.get(f"{dt}Id") or form.get("device_id") or form.get("laptopId")
		username = form.get("username") or frappe.db.get_value("User", frappe.session.user, "full_name") or "Unknown"

		if not device_id or not frappe.db.exists("ERP Inventory Device", device_id):
			return not_found_response(_("Không tìm thấy thiết bị"))

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
	"""
	Đăng ký file đã rsync vào sites/<site>/public/files/inventory/{folder}/.
	Gọi sau khi chạy scripts/migrate_inventory_files.sh
	"""
	try:
		base = os.path.join(get_site_path("public", "files", "inventory", folder))
		if not os.path.isdir(base):
			return error_response(_("Thư mục không tồn tại: {0}").format(base))

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

			# Cập nhật handover log theo tên file (legacy path)
			logs = frappe.get_all(
				"ERP Inventory Handover Log",
				filters=[
					["document_file_url", "like", f"%{fname}"],
				],
				pluck="name",
			)
			for log_name in logs:
				log_doc = frappe.get_doc("ERP Inventory Handover Log", log_name)
				log_doc.document_file_url = file_url
				log_doc.document_file = file_url
				log_doc.save(ignore_permissions=True)
				updated += 1

		frappe.db.commit()
		return success_response(
			data={"created_files": created, "updated_handover_logs": updated, "folder": folder},
			message=_("Đã đăng ký file legacy"),
		)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.register_legacy_files")
		return error_response(str(e))
