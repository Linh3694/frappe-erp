# Copyright (c) 2026, Wellspring International School
# Import Excel migration từ inventory-service Mongo → Frappe

import json
import os
import uuid

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from erp.utils.api_response import error_response, validation_error_response
from erp.api.erp_inventory.inventory_helpers import (
	DEVICE_TYPES,
	VALID_STATUSES,
	apply_specs_to_doc,
	normalize_device_type,
	parse_request_data,
	resolve_room_link,
	resolve_user_link,
	sync_assigned_users,
	sync_current_holder_from_assigned,
)
from erp.api.erp_inventory.migration import _require_migration_role


def _save_uploaded_excel_temp(file_data, filename="import.xlsx"):
	ext = os.path.splitext(filename or "")[1] or ".xlsx"
	path = os.path.join(frappe.get_site_path("private", "files"), f"inv_import_{uuid.uuid4().hex}{ext}")
	os.makedirs(os.path.dirname(path), exist_ok=True)
	content = file_data.stream.read() if hasattr(file_data, "stream") else file_data
	with open(path, "wb") as f:
		f.write(content)
	return path


def _read_excel_sheets(file_path):
	try:
		import pandas as pd
	except ImportError:
		frappe.throw(_("Thiếu pandas/openpyxl"))
	xl = pd.ExcelFile(file_path, engine="openpyxl")
	sheets = {}
	for name in xl.sheet_names:
		df = xl.parse(name)
		df.columns = [str(c).strip() for c in df.columns]
		sheets[name] = df
	return sheets


def _cell_str(val):
	if val is None:
		return ""
	if isinstance(val, float) and str(val) == "nan":
		return ""
	return str(val).strip()


def _find_device_by_legacy_or_serial(mongo_id, serial, device_type):
	if mongo_id:
		name = frappe.db.get_value("ERP Inventory Device", {"legacy_mongo_id": mongo_id}, "name")
		if name:
			return name
	if serial:
		return frappe.db.get_value("ERP Inventory Device", {"serial": serial, "device_type": device_type}, "name")
	return None


@frappe.whitelist(allow_guest=False)
def import_devices_full(device_type=None, file_url=None):
	"""
	Import migration Excel (Sheet Devices + Sheet AssignmentHistory).
	file_url: URL file đã upload lên Frappe File hoặc multipart upload trực tiếp.
	"""
	try:
		_require_migration_role()
		dt = normalize_device_type(device_type)
		data = parse_request_data()

		file_path = None
		files = frappe.request.files if frappe.request else None
		if files and "file" in files:
			file_path = _save_uploaded_excel_temp(files["file"], files["file"].filename)
		elif file_url or data.get("file_url"):
			url = file_url or data.get("file_url")
			file_path = frappe.get_site_path(url.lstrip("/")) if url.startswith("/private") else None
			if not file_path or not os.path.exists(file_path):
				# Lấy từ File doc
				fname = frappe.db.get_value("File", {"file_url": url}, "name")
				if fname:
					file_doc = frappe.get_doc("File", fname)
					file_path = file_doc.get_full_path()

		if not file_path or not os.path.exists(file_path):
			return validation_error_response(_("Không có file Excel"), {"file": ["required"]})

		sheets = _read_excel_sheets(file_path)
		device_sheet = None
		history_sheet = None
		for name, df in sheets.items():
			lower = name.lower()
			if "device" in lower or "thiết bị" in lower or name == sheets.keys().__iter__().__next__():
				if device_sheet is None:
					device_sheet = df
			if "history" in lower or "assignment" in lower or "bàn giao" in lower:
				history_sheet = df

		if device_sheet is None:
			device_sheet = list(sheets.values())[0]

		errors = []
		created = 0
		updated = 0
		mongo_map = {}

		for idx, row in device_sheet.iterrows():
			excel_row = int(idx) + 2
			mongo_id = _cell_str(row.get("mongo_id") or row.get("legacy_mongo_id") or row.get("_id"))
			serial = _cell_str(row.get("serial") or row.get("Serial"))
			name_display = _cell_str(row.get("name") or row.get("name_display") or row.get("Tên thiết bị"))
			if not serial and not mongo_id:
				continue
			if not name_display:
				name_display = serial or mongo_id

			existing = _find_device_by_legacy_or_serial(mongo_id, serial, dt)
			status = _cell_str(row.get("status") or row.get("Trạng thái")) or "Standby"
			if status not in VALID_STATUSES:
				status = "Standby"

			room_key = _cell_str(row.get("room_name") or row.get("room") or row.get("Phòng") or row.get("frappeRoomId"))
			room_id = resolve_room_link(room_key) if room_key else None

			holder_email = _cell_str(row.get("current_holder_email") or row.get("assigned_user_email") or row.get("Người sử dụng"))
			holder_user = resolve_user_link(holder_email) if holder_email else None

			specs = {}
			for k in ("processor", "ram", "storage", "display", "ip", "imei1", "imei2", "phoneNumber", "phone_number"):
				if k in row and _cell_str(row.get(k)):
					specs[k] = _cell_str(row.get(k))

			try:
				if existing:
					doc = frappe.get_doc("ERP Inventory Device", existing)
					updated += 1
				else:
					doc = frappe.get_doc(
						{
							"doctype": "ERP Inventory Device",
							"device_type": dt,
							"name_display": name_display,
							"serial": serial or name_display,
						}
					)
					created += 1

				doc.device_subtype = _cell_str(row.get("type") or row.get("device_subtype") or row.get("Loại thiết bị"))
				doc.manufacturer = _cell_str(row.get("manufacturer") or row.get("Hãng sản xuất"))
				doc.release_year = cint(row.get("releaseYear") or row.get("release_year") or row.get("Năm sản xuất") or 0) or None
				doc.status = status
				doc.room = room_id
				doc.broken_reason = _cell_str(row.get("brokenReason") or row.get("broken_reason"))
				doc.broken_description = _cell_str(row.get("brokenDescription") or row.get("broken_description"))
				if mongo_id:
					doc.legacy_mongo_id = mongo_id
				apply_specs_to_doc(doc, dt, specs)
				if holder_user:
					sync_assigned_users(doc, [holder_user])
					doc.current_holder_user = holder_user
					doc.current_holder_fullname = frappe.db.get_value("User", holder_user, "full_name") or holder_user
					doc.current_holder_jobtitle = frappe.db.get_value("User", holder_user, "job_title") or ""
					doc.current_holder_department = frappe.db.get_value("User", holder_user, "department") or ""

				if existing:
					doc.save(ignore_permissions=True)
				else:
					doc.insert(ignore_permissions=True)

				if mongo_id:
					mongo_map[mongo_id] = doc.name
				elif serial:
					mongo_map[serial] = doc.name
			except Exception as row_err:
				frappe.db.rollback()
				errors.append({"row": excel_row, "serial": serial, "message": str(row_err)})

		# Sheet 2: assignment history
		history_created = 0
		if history_sheet is not None:
			for idx, row in history_sheet.iterrows():
				excel_row = int(idx) + 2
				mongo_device_id = _cell_str(row.get("mongo_device_id") or row.get("device_mongo_id"))
				device_serial = _cell_str(row.get("device_serial") or row.get("serial"))
				device_name = mongo_map.get(mongo_device_id) or _find_device_by_legacy_or_serial(mongo_device_id, device_serial, dt)
				if not device_name:
					errors.append({"row": excel_row, "message": _("Không map được device: {0}").format(mongo_device_id or device_serial)})
					continue

				user_email = _cell_str(row.get("user_email") or row.get("user") or row.get("Người sử dụng"))
				user_id = resolve_user_link(user_email)
				if not user_id:
					errors.append({"row": excel_row, "message": _("User không tồn tại: {0}").format(user_email)})
					continue

				legacy_log_id = _cell_str(row.get("mongo_history_id") or row.get("legacy_mongo_id"))
				if legacy_log_id and frappe.db.exists("ERP Inventory Handover Log", {"legacy_mongo_id": legacy_log_id}):
					continue

				assigned_by = resolve_user_link(_cell_str(row.get("assigned_by_email") or row.get("assigned_by")))
				revoked_by = resolve_user_link(_cell_str(row.get("revoked_by_email") or row.get("revoked_by")))
				revoked_raw = _cell_str(row.get("revoked_reasons_json") or row.get("revoked_reasons"))
				try:
					revoked_reasons = json.loads(revoked_raw) if revoked_raw else []
				except Exception:
					revoked_reasons = [revoked_raw] if revoked_raw else []

				start_date = row.get("start_date") or row.get("startDate")
				end_date = row.get("end_date") or row.get("endDate")
				try:
					log = frappe.get_doc(
						{
							"doctype": "ERP Inventory Handover Log",
							"device": device_name,
							"action": _cell_str(row.get("action")) or "assigned",
							"user": user_id,
							"fullname_snapshot": _cell_str(row.get("fullname_snapshot") or row.get("userName")) or frappe.db.get_value("User", user_id, "full_name"),
							"job_title_snapshot": _cell_str(row.get("job_title") or row.get("jobTitle")),
							"start_date": get_datetime(start_date) if start_date else now_datetime(),
							"end_date": get_datetime(end_date) if end_date and _cell_str(end_date) else None,
							"notes": _cell_str(row.get("notes")),
							"assigned_by": assigned_by,
							"revoked_by": revoked_by,
							"revoked_reasons": json.dumps(revoked_reasons) if revoked_reasons else None,
							"document_file_url": _cell_str(row.get("document_file_path") or row.get("document")),
							"legacy_mongo_id": legacy_log_id or None,
						}
					)
					log.insert(ignore_permissions=True)
					history_created += 1
				except Exception as row_err:
					errors.append({"row": excel_row, "message": str(row_err)})

		frappe.db.commit()
		try:
			os.remove(file_path)
		except Exception:
			pass

		return {
			"success": len(errors) == 0 or (created + updated) > 0,
			"message": _("Import xong: tạo {0}, cập nhật {1}, handover {2}").format(created, updated, history_created),
			"created_count": created,
			"updated_count": updated,
			"history_created_count": history_created,
			"errors": errors,
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.import_devices_full")
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def import_inspections_full(file_url=None):
	try:
		_require_migration_role()
		data = parse_request_data()
		file_path = None
		files = frappe.request.files if frappe.request else None
		if files and "file" in files:
			file_path = _save_uploaded_excel_temp(files["file"], files["file"].filename)
		if not file_path:
			return validation_error_response(_("Không có file"), {"file": ["required"]})

		sheets = _read_excel_sheets(file_path)
		df = list(sheets.values())[0]
		errors = []
		created = 0
		for idx, row in df.iterrows():
			excel_row = int(idx) + 2
			mongo_id = _cell_str(row.get("mongo_id") or row.get("legacy_mongo_id"))
			device_mongo = _cell_str(row.get("mongo_device_id") or row.get("deviceId"))
			device_name = frappe.db.get_value("ERP Inventory Device", {"legacy_mongo_id": device_mongo}, "name")
			if not device_name:
				device_name = _cell_str(row.get("device") or row.get("device_id"))
			if not device_name or not frappe.db.exists("ERP Inventory Device", device_name):
				errors.append({"row": excel_row, "message": "Device not found"})
				continue
			if mongo_id and frappe.db.exists("ERP Inventory Inspection", {"legacy_mongo_id": mongo_id}):
				continue
			inspector = resolve_user_link(_cell_str(row.get("inspector_email"))) or frappe.session.user
			try:
				doc = frappe.get_doc(
					{
						"doctype": "ERP Inventory Inspection",
						"device": device_name,
						"device_type": frappe.db.get_value("ERP Inventory Device", device_name, "device_type"),
						"inspector": inspector,
						"inspection_date": get_datetime(row.get("inspection_date") or row.get("inspectionDate")) or now_datetime(),
						"overall_assessment": _cell_str(row.get("overall_assessment")),
						"passed": 1 if str(row.get("passed", "1")).lower() not in ("0", "false", "no") else 0,
						"recommendations": _cell_str(row.get("recommendations")),
						"technical_conclusion": _cell_str(row.get("technical_conclusion") or row.get("technicalConclusion")),
						"follow_up_recommendation": _cell_str(row.get("follow_up_recommendation") or row.get("followUpRecommendation")),
						"report_file_url": _cell_str(row.get("report_file_path")),
						"legacy_mongo_id": mongo_id or None,
					}
				)
				sections_raw = _cell_str(row.get("sections_json") or row.get("results_json"))
				if sections_raw:
					try:
						results = json.loads(sections_raw)
						from erp.api.erp_inventory.inspection import _results_to_sections

						for sec in _results_to_sections(results):
							doc.append("sections", sec)
					except Exception:
						pass
				doc.insert(ignore_permissions=True)
				created += 1
			except Exception as row_err:
				errors.append({"row": excel_row, "message": str(row_err)})

		frappe.db.commit()
		return {"success": True, "created_count": created, "errors": errors}
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))


@frappe.whitelist(allow_guest=False)
def import_activities_full(file_url=None):
	try:
		_require_migration_role()
		files = frappe.request.files if frappe.request else None
		if not files or "file" not in files:
			return validation_error_response(_("Không có file"), {"file": ["required"]})
		file_path = _save_uploaded_excel_temp(files["file"], files["file"].filename)
		sheets = _read_excel_sheets(file_path)
		df = list(sheets.values())[0]
		errors = []
		created = 0
		for idx, row in df.iterrows():
			excel_row = int(idx) + 2
			mongo_id = _cell_str(row.get("mongo_id") or row.get("legacy_mongo_id"))
			entity_mongo = _cell_str(row.get("mongo_entity_id") or row.get("entityId"))
			entity = frappe.db.get_value("ERP Inventory Device", {"legacy_mongo_id": entity_mongo}, "name")
			if not entity:
				entity = _cell_str(row.get("entity"))
			if not entity:
				errors.append({"row": excel_row, "message": "Entity not found"})
				continue
			if mongo_id and frappe.db.exists("ERP Inventory Activity Log", {"legacy_mongo_id": mongo_id}):
				continue
			act_type = _cell_str(row.get("type"))
			if act_type not in ("repair", "update"):
				act_type = "update"
			try:
				frappe.get_doc(
					{
						"doctype": "ERP Inventory Activity Log",
						"entity_type": _cell_str(row.get("entity_type") or row.get("entityType")),
						"entity": entity,
						"type": act_type,
						"description": _cell_str(row.get("description")),
						"details": _cell_str(row.get("details")),
						"date": get_datetime(row.get("date")) or now_datetime(),
						"updated_by": resolve_user_link(_cell_str(row.get("updated_by"))) or frappe.session.user,
						"legacy_mongo_id": mongo_id or None,
					}
				).insert(ignore_permissions=True)
				created += 1
			except Exception as row_err:
				errors.append({"row": excel_row, "message": str(row_err)})
		frappe.db.commit()
		return {"success": True, "created_count": created, "errors": errors}
	except Exception as e:
		frappe.db.rollback()
		return error_response(str(e))
