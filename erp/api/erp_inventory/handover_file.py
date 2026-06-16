# Copyright (c) 2026, Wellspring International School
# Upload biên bản bàn giao + đăng ký file legacy sau migration

import json
import os
import re
import shutil
import unicodedata
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


def slugify_ascii(text):
	"""Bỏ dấu tiếng Việt + ký tự đặc biệt để tên file an toàn khi nginx serve.

	Tên file chứa ký tự Unicode (vd: Hiếu_Nguyễn) khiến nginx trả 500 khi xem lại.
	Chuyển về ASCII: "Hiếu Nguyễn Duy" -> "Hieu_Nguyen_Duy".
	"""
	if not text:
		return ""
	# đ/Đ không tách dấu được bằng NFD nên xử lý riêng
	text = text.replace("đ", "d").replace("Đ", "D")
	text = unicodedata.normalize("NFD", text)
	text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
	# Chỉ giữ chữ, số, gạch ngang, gạch dưới, chấm; còn lại -> gạch dưới
	text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
	return text.strip("_") or "file"


def _ensure_inventory_folder(folder="handovers"):
	"""Đảm bảo folder File Home/inventory/<folder> tồn tại trước khi lưu file."""
	# Tạo folder gốc Home/inventory nếu chưa có
	if not frappe.db.exists("File", {"is_folder": 1, "file_name": "inventory", "folder": "Home"}):
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "inventory",
				"is_folder": 1,
				"folder": "Home",
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)

	# Tạo folder con Home/inventory/<folder> nếu chưa có
	if not frappe.db.exists("File", {"is_folder": 1, "file_name": folder, "folder": "Home/inventory"}):
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": folder,
				"is_folder": 1,
				"folder": "Home/inventory",
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _save_inventory_file(folder, filename, content):
	"""Ghi file vật lý vào public/files/inventory/<folder>/ và trả về (file_url, tên cuối).

	Frappe lưu file qua `content` sẽ đặt ở public/files/ phẳng (file_url=/files/<tên>),
	không khớp đường dẫn /files/inventory/<folder>/ mà FE dựng để xem lại → 500.
	Vì vậy ghi trực tiếp vào đúng thư mục legacy và đặt file_url tương ứng.
	"""
	target_dir = get_site_path("public", "files", "inventory", folder)
	os.makedirs(target_dir, exist_ok=True)

	# Chuẩn hoá tên file về ASCII để nginx serve được (tránh 500 do ký tự Unicode)
	base, ext = os.path.splitext(filename)
	filename = f"{slugify_ascii(base)}{ext}"

	# Tránh ghi đè file trùng tên: thêm hậu tố -1, -2, ...
	base, ext = os.path.splitext(filename)
	final_name = filename
	counter = 1
	while os.path.exists(os.path.join(target_dir, final_name)):
		final_name = f"{base}-{counter}{ext}"
		counter += 1

	with open(os.path.join(target_dir, final_name), "wb") as f:
		f.write(content)

	return f"/files/inventory/{folder}/{final_name}", final_name


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

		# Lấy tên người ĐƯỢC bàn giao (Bên Nhận) từ handover log đang mở của thiết bị
		open_logs = frappe.get_all(
			"ERP Inventory Handover Log",
			filters={"device": device_id, "end_date": ["is", "not set"]},
			fields=["name", "fullname_snapshot", "user"],
		)
		recipient_name = None
		if open_logs:
			recipient_name = open_logs[0].get("fullname_snapshot") or frappe.db.get_value(
				"User", open_logs[0].get("user"), "full_name"
			)
		# Fallback: username FE gửi lên hoặc người đang đăng nhập
		recipient_name = (
			recipient_name
			or form.get("username")
			or frappe.db.get_value("User", frappe.session.user, "full_name")
			or "Unknown"
		)

		ext = os.path.splitext(files["file"].filename)[1] or ".pdf"
		date_str = datetime.now().strftime("%Y-%m-%d")
		safe_username = slugify_ascii(recipient_name)
		new_name = f"BBBG-{safe_username}-{date_str}{ext}"

		_ensure_inventory_folder("handovers")

		file_url, new_name = _save_inventory_file("handovers", new_name, files["file"].stream.read())

		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": new_name,
				"file_url": file_url,
				"is_private": 0,
				"folder": "Home/inventory/handovers",
				"attached_to_doctype": "ERP Inventory Device",
				"attached_to_name": device_id,
			}
		)
		file_doc.insert(ignore_permissions=True)

		# Cập nhật handover log đang mở (dùng lại danh sách đã lấy ở trên)
		for log_row in open_logs:
			log_doc = frappe.get_doc("ERP Inventory Handover Log", log_row.get("name"))
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
