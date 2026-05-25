# Copyright (c) 2026, Wellspring International School
# Đồng bộ migration trực tiếp từ MongoDB inventory-service (không cần Node đang chạy)

import json
import os
import uuid
from datetime import datetime

import frappe
from frappe import _

from erp.utils.api_response import error_response, success_response
from erp.api.erp_inventory.inventory_helpers import DEVICE_TYPES, require_migration_role
from erp.api.erp_inventory.import_excel import (
	import_activities_from_excel_file,
	import_devices_from_excel_file,
	import_inspections_from_excel_file,
)
from erp.api.erp_inventory.handover_file import sync_legacy_files_full


def _get_migration_counts():
	actual = {}
	for dt in DEVICE_TYPES:
		actual[dt] = frappe.db.count("ERP Inventory Device", {"device_type": dt})
	actual["handover"] = frappe.db.count("ERP Inventory Handover Log")
	actual["inspection"] = frappe.db.count("ERP Inventory Inspection")
	actual["activity"] = frappe.db.count("ERP Inventory Activity Log")
	return actual

DEVICE_COLLECTIONS = {
	"laptop": "laptops",
	"monitor": "monitors",
	"printer": "printers",
	"projector": "projectors",
	"phone": "phones",
	"tool": "tools",
}


def _mongodb_uri():
	return (
		frappe.conf.get("inventory_mongodb_uri")
		or frappe.get_site_config().get("inventory_mongodb_uri")
		or "mongodb://127.0.0.1:27017/inventory_service"
	)


def _get_mongo_db():
	try:
		from pymongo import MongoClient
	except ImportError:
		frappe.throw(_("Thiếu pymongo — chạy: bench pip install pymongo"))

	uri = _mongodb_uri()
	client = MongoClient(uri, serverSelectionTimeoutMS=10000)
	# Ping để báo lỗi rõ nếu không kết nối được
	client.admin.command("ping")
	db_name = uri.rsplit("/", 1)[-1].split("?")[0] or "inventory_service"
	return client[db_name]


def _iso_dt(val):
	if not val:
		return ""
	if isinstance(val, datetime):
		return val.isoformat()
	return str(val)


def _oid(val):
	if val is None:
		return ""
	return str(val)


def _load_users_cache(db):
	cache = {}
	for doc in db.users.find():
		cache[str(doc.get("_id"))] = doc
	return cache


def _load_rooms_cache(db):
	cache = {}
	for doc in db.rooms.find():
		cache[str(doc.get("_id"))] = doc
	return cache


def _user_email(users_cache, user_ref):
	if not user_ref:
		return ""
	if isinstance(user_ref, dict):
		return user_ref.get("email") or user_ref.get("frappeUserId") or ""
	uid = _oid(user_ref)
	user = users_cache.get(uid) or {}
	return user.get("email") or user.get("frappeUserId") or ""


def _resolve_room(room_ref, rooms_cache):
	if not room_ref:
		return None
	if isinstance(room_ref, dict):
		return room_ref
	rid = _oid(room_ref)
	return rooms_cache.get(rid)


def _device_specs_row(device, device_type):
	specs = device.get("specs") or {}
	row = {
		"processor": specs.get("processor") or "",
		"ram": specs.get("ram") or "",
		"storage": specs.get("storage") or "",
		"display": specs.get("display") or "",
		"ip": specs.get("ip") or "",
	}
	if device_type == "phone":
		row["imei1"] = device.get("imei1") or ""
		row["imei2"] = device.get("imei2") or ""
		row["phoneNumber"] = device.get("phoneNumber") or ""
	return row


def _build_device_excel(db, device_type, users_cache, rooms_cache):
	"""Tạo file Excel tạm giống export Node → tái sử dụng import_excel."""
	import pandas as pd

	collection = DEVICE_COLLECTIONS[device_type]
	devices_rows = []
	history_rows = []

	for device in db[collection].find().sort("name", 1):
		room = _resolve_room(device.get("room"), rooms_cache)
		assigned_ids = device.get("assigned") or []
		assigned_user = None
		if assigned_ids:
			first = assigned_ids[0]
			if isinstance(first, dict):
				assigned_user = first
			else:
				assigned_user = users_cache.get(_oid(first))

		specs = _device_specs_row(device, device_type)
		devices_rows.append(
			{
				"mongo_id": _oid(device.get("_id")),
				"name": device.get("name") or "",
				"type": device.get("type") or "",
				"manufacturer": device.get("manufacturer") or "",
				"serial": device.get("serial") or "",
				"releaseYear": device.get("releaseYear") or "",
				"status": device.get("status") or "",
				"brokenReason": device.get("brokenReason") or "",
				"brokenDescription": device.get("brokenDescription") or "",
				"frappeRoomId": (room or {}).get("frappeRoomId") or "",
				"room_name": (room or {}).get("room_name") or (room or {}).get("name") or "",
				"current_holder_email": _user_email(users_cache, assigned_user),
				**specs,
				"createdAt": _iso_dt(device.get("createdAt")),
				"updatedAt": _iso_dt(device.get("updatedAt")),
			}
		)

		for h in device.get("assignmentHistory") or []:
			user_ref = h.get("user")
			history_rows.append(
				{
					"mongo_history_id": _oid(h.get("_id")),
					"mongo_device_id": _oid(device.get("_id")),
					"device_serial": device.get("serial") or "",
					"user_email": _user_email(users_cache, user_ref),
					"fullname_snapshot": h.get("fullnameSnapshot") or h.get("userName") or _user_email(users_cache, user_ref),
					"job_title": h.get("jobTitle") or "",
					"action": "revoked" if h.get("endDate") else "assigned",
					"start_date": _iso_dt(h.get("startDate")),
					"end_date": _iso_dt(h.get("endDate")),
					"notes": h.get("notes") or "",
					"assigned_by_email": _user_email(users_cache, h.get("assignedBy")),
					"revoked_by_email": _user_email(users_cache, h.get("revokedBy")),
					"revoked_reasons_json": json.dumps(h.get("revokedReason") or []),
					"document_file_path": h.get("document") or "",
				}
			)

	path = os.path.join(
		frappe.get_site_path("private", "files"),
		f"inv_mongo_{device_type}_{uuid.uuid4().hex}.xlsx",
	)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with pd.ExcelWriter(path, engine="openpyxl") as writer:
		pd.DataFrame(devices_rows).to_excel(writer, sheet_name="Devices", index=False)
		pd.DataFrame(history_rows).to_excel(writer, sheet_name="AssignmentHistory", index=False)
	return path


def _build_inspections_excel(db, users_cache):
	import pandas as pd

	rows = []
	for insp in db.inspects.find().sort("inspectionDate", -1):
		report = insp.get("report") or {}
		rows.append(
			{
				"mongo_id": _oid(insp.get("_id")),
				"mongo_device_id": _oid(insp.get("deviceId")),
				"deviceType": insp.get("deviceType") or "",
				"inspector_email": _user_email(users_cache, insp.get("inspectorId")),
				"inspection_date": _iso_dt(insp.get("inspectionDate")),
				"overall_assessment": insp.get("overallAssessment") or "",
				"passed": 1 if insp.get("passed", True) else 0,
				"recommendations": insp.get("recommendations") or "",
				"technical_conclusion": insp.get("technicalConclusion") or "",
				"follow_up_recommendation": insp.get("followUpRecommendation") or "",
				"results_json": json.dumps(insp.get("results") or {}),
				"report_file_path": report.get("filePath") or report.get("fileName") or "",
			}
		)

	path = os.path.join(frappe.get_site_path("private", "files"), f"inv_mongo_insp_{uuid.uuid4().hex}.xlsx")
	os.makedirs(os.path.dirname(path), exist_ok=True)
	pd.DataFrame(rows).to_excel(path, sheet_name="Inspections", index=False)
	return path


def _build_activities_excel(db):
	import pandas as pd

	rows = []
	for act in db.activities.find().sort("date", -1):
		rows.append(
			{
				"mongo_id": _oid(act.get("_id")),
				"entity_type": act.get("entityType") or "",
				"mongo_entity_id": _oid(act.get("entityId")),
				"type": act.get("type") or "",
				"description": act.get("description") or "",
				"details": act.get("details") or "",
				"date": _iso_dt(act.get("date")),
				"updated_by": act.get("updatedBy") or "",
			}
		)

	path = os.path.join(frappe.get_site_path("private", "files"), f"inv_mongo_act_{uuid.uuid4().hex}.xlsx")
	os.makedirs(os.path.dirname(path), exist_ok=True)
	pd.DataFrame(rows).to_excel(path, sheet_name="Activities", index=False)
	return path


def _safe_remove(path):
	if path and os.path.exists(path):
		try:
			os.remove(path)
		except Exception:
			pass


def run_full_sync_from_mongodb(sync_files=True):
	"""Đọc MongoDB → import Frappe → copy file. Không cần inventory-service HTTP."""
	require_migration_role()
	logs = [_("Kết nối MongoDB: {0}").format(_mongodb_uri())]
	steps = {}
	all_errors = []
	db = _get_mongo_db()

	try:
		users_cache = _load_users_cache(db)
		rooms_cache = _load_rooms_cache(db)
		logs.append(_("Đã load {0} user, {1} phòng từ Mongo").format(len(users_cache), len(rooms_cache)))

		for dt in DEVICE_TYPES:
			logs.append(_("Đang import thiết bị: {0}").format(dt))
			frappe.publish_progress(percent=(DEVICE_TYPES.index(dt) + 1) * 8, title=_("Đồng bộ Inventory IT"))
			temp_path = None
			try:
				temp_path = _build_device_excel(db, dt, users_cache, rooms_cache)
				result = import_devices_from_excel_file(temp_path, dt)
				steps[f"devices_{dt}"] = result
				all_errors.extend(result.get("errors") or [])
			finally:
				_safe_remove(temp_path)

		logs.append(_("Đang import kiểm tra thiết bị"))
		frappe.publish_progress(percent=55, title=_("Đồng bộ Inventory IT"))
		temp_path = None
		try:
			temp_path = _build_inspections_excel(db, users_cache)
			insp_result = import_inspections_from_excel_file(temp_path)
			steps["inspections"] = insp_result
			all_errors.extend(insp_result.get("errors") or [])
		finally:
			_safe_remove(temp_path)

		logs.append(_("Đang import nhật ký sửa chữa"))
		frappe.publish_progress(percent=70, title=_("Đồng bộ Inventory IT"))
		temp_path = None
		try:
			temp_path = _build_activities_excel(db)
			act_result = import_activities_from_excel_file(temp_path)
			steps["activities"] = act_result
			all_errors.extend(act_result.get("errors") or [])
		finally:
			_safe_remove(temp_path)

		if sync_files:
			logs.append(_("Đang copy file handover/báo cáo"))
			frappe.publish_progress(percent=85, title=_("Đồng bộ Inventory IT"))
			steps["files"] = sync_legacy_files_full()

		frappe.publish_progress(percent=100, title=_("Hoàn tất"))
		counts = _get_migration_counts()
		ok = len(all_errors) == 0

		return success_response(
			data={
				"ok": ok,
				"source": "mongodb",
				"counts": counts,
				"steps": steps,
				"errors": all_errors[:100],
				"error_count": len(all_errors),
				"logs": logs,
			},
			message=_("Đồng bộ từ MongoDB hoàn tất") if ok else _("Đồng bộ xong với {0} lỗi").format(len(all_errors)),
			logs=logs,
		)
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "erp_inventory.migration_mongo")
		return error_response(str(e), logs=logs)
