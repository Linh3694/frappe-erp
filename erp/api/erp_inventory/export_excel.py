# Copyright (c) 2026, Wellspring International School
# Export Excel thiết bị IT từ Frappe (sau cutover)

import io
import os
import tempfile

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from erp.api.erp_inventory.inventory_helpers import (
	DEVICE_TYPES,
	normalize_device_type,
	resolve_user_link,
	room_to_fe,
	user_to_fe,
)


STATUS_LABELS = {
	"Active": "Đang sử dụng",
	"Standby": "Sẵn sàng bàn giao",
	"Broken": "Hỏng",
	"PendingDocumentation": "Thiếu biên bản",
}


def _device_specs_dict(doc):
	dt = doc.device_type
	table_map = {
		"laptop": "specs_laptop",
		"monitor": "specs_monitor",
		"printer": "specs_printer",
		"projector": "specs_projector",
		"phone": "specs_phone",
		"tool": "specs_tool",
	}
	rows = doc.get(table_map.get(dt)) or []
	if not rows:
		return {}
	row = rows[0]
	out = {}
	for fn in ("processor", "ram", "storage", "display", "ip", "imei1", "imei2", "phone_number"):
		if hasattr(row, fn):
			out[fn] = getattr(row, fn) or ""
	return out


@frappe.whitelist(allow_guest=False)
def export_devices_excel(device_type=None):
	"""Export Excel — parity exportController.exportDevices."""
	try:
		import openpyxl
		from openpyxl.styles import Alignment, Font, PatternFill
	except ImportError:
		frappe.throw(_("Thiếu openpyxl"))

	dt = normalize_device_type(device_type)
	devices = frappe.get_all(
		"ERP Inventory Device",
		filters={"device_type": dt},
		fields=["name"],
		order_by="name_display asc",
	)
	exported = []
	skipped = 0
	for d in devices:
		doc = frappe.get_doc("ERP Inventory Device", d.name)
		if not doc.assigned_users:
			skipped += 1
			continue
		exported.append(doc)

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = f"Danh sách {dt}"
	headers = [
		"STT", "Tên thiết bị", "Loại thiết bị", "Hãng sản xuất", "Serial", "Năm sản xuất", "Trạng thái",
		"Người sử dụng", "Chức danh", "Phòng",
	]
	ws.append(headers)
	header_fill = PatternFill(start_color="002855", end_color="002855", fill_type="solid")
	for cell in ws[1]:
		cell.font = Font(bold=True, color="FFFFFF")
		cell.fill = header_fill
		cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

	for idx, doc in enumerate(exported, start=1):
		assigned = doc.assigned_users[0] if doc.assigned_users else None
		user = user_to_fe(assigned.user) if assigned else None
		room = room_to_fe(doc.room)
		ws.append([
			idx,
			doc.name_display,
			doc.device_subtype or doc.device_type,
			doc.manufacturer or "",
			doc.serial,
			doc.release_year or "",
			STATUS_LABELS.get(doc.status, doc.status),
			(user or {}).get("fullname", ""),
			(user or {}).get("jobTitle", ""),
			(room or {}).get("room_name") or (room or {}).get("name") or "",
		])

	info_row = len(exported) + 3
	ws.cell(row=info_row, column=1, value=f"Tổng thiết bị đã export: {len(exported)}")

	tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
	wb.save(tmp.name)
	tmp.close()

	frappe.local.response.filename = f"thiet-bi-{dt}-{now_datetime().date()}.xlsx"
	frappe.local.response.filecontent = open(tmp.name, "rb").read()
	frappe.local.response.type = "download"
	os.unlink(tmp.name)
	return


@frappe.whitelist(allow_guest=False)
def download_import_template(device_type=None):
	"""Template import — parity getImportTemplate."""
	try:
		import openpyxl
	except ImportError:
		frappe.throw(_("Thiếu openpyxl"))

	dt = normalize_device_type(device_type)
	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = f"Nhập {dt}"
	cols = ["Tên thiết bị", "Loại thiết bị", "Hãng sản xuất", "Serial", "Năm sản xuất", "Trạng thái", "Người sử dụng", "Chức danh", "Phòng"]
	ws.append(cols)
	ws.append(["Tên thiết bị mẫu", "Laptop" if dt == "laptop" else "", "Dell", "SN-XXXXXX", 2024, "Standby", "Nguyễn Văn A", "", ""])

	guide = wb.create_sheet("Hướng dẫn")
	guide.append(["Cột", "Mô tả", "Bắt buộc", "Ghi chú"])
	guide.append(["Serial", "Số serial duy nhất", "Có", ""])

	tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
	wb.save(tmp.name)
	tmp.close()
	frappe.local.response.filename = f"template-import-{dt}.xlsx"
	frappe.local.response.filecontent = open(tmp.name, "rb").read()
	frappe.local.response.type = "download"
	os.unlink(tmp.name)
