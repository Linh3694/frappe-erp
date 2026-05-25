# Copyright (c) 2026, Wellspring International School
# Helper dùng chung cho module Inventory IT

import json
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint, get_fullname, get_datetime, now_datetime

DEVICE_TYPES = ("laptop", "monitor", "printer", "projector", "phone", "tool")
VALID_STATUSES = ("Active", "Standby", "Broken", "PendingDocumentation")

POPULATED_KEY = {
	"laptop": "populatedLaptops",
	"monitor": "populatedMonitors",
	"printer": "populatedPrinters",
	"projector": "populatedProjectors",
	"phone": "populatedPhones",
	"tool": "populatedTools",
}

SPECS_TABLE = {
	"laptop": "specs_laptop",
	"monitor": "specs_monitor",
	"printer": "specs_printer",
	"projector": "specs_projector",
	"phone": "specs_phone",
	"tool": "specs_tool",
}


def parse_request_data():
	"""Đọc body JSON hoặc form_dict."""
	data = {}
	if frappe.request and frappe.request.data:
		try:
			raw = frappe.request.data
			if isinstance(raw, bytes):
				raw = raw.decode("utf-8")
			if raw and raw.strip():
				data = json.loads(raw) or {}
		except Exception:
			pass
	if not data and frappe.form_dict:
		data = dict(frappe.form_dict)
	return data


def normalize_device_type(device_type: Optional[str]) -> str:
	dt = (device_type or "").strip().lower()
	if dt not in DEVICE_TYPES:
		frappe.throw(_("Loại thiết bị không hợp lệ: {0}").format(device_type))
	return dt


def resolve_user_link(user_hint: Optional[str]) -> Optional[str]:
	"""Map email / username / full_name → User.name."""
	key = (user_hint or "").strip()
	if not key:
		return None
	if frappe.db.exists("User", key):
		return key
	for field in ("email", "username", "full_name"):
		uid = frappe.db.get_value("User", {field: key}, "name")
		if uid:
			return uid
	return None


def resolve_room_link(room_key: Optional[str]) -> Optional[str]:
	"""Map physical_code / title / name → ERP Administrative Room.name."""
	key = (room_key or "").strip()
	if not key:
		return None
	if frappe.db.exists("ERP Administrative Room", key):
		return key
	for field in ("physical_code", "title_vn", "short_title", "title_en", "room_number"):
		rid = frappe.db.get_value("ERP Administrative Room", {field: key}, "name")
		if rid:
			return rid
	return None


def user_to_fe(user_name: Optional[str]) -> Optional[Dict[str, Any]]:
	if not user_name or not frappe.db.exists("User", user_name):
		return None
	u = frappe.db.get_value(
		"User",
		user_name,
		["name", "email", "full_name", "user_image", "department"],
		as_dict=True,
	)
	job_title = frappe.db.get_value("User", user_name, "job_title") or frappe.db.get_value(
		"User", user_name, "designation"
	)
	return {
		"_id": u.name,
		"fullname": u.full_name or u.name,
		"email": u.email,
		"jobTitle": job_title or "",
		"department": u.department or "",
		"avatarUrl": u.user_image or "",
	}


def room_to_fe(room_name: Optional[str]) -> Optional[Dict[str, Any]]:
	if not room_name or not frappe.db.exists("ERP Administrative Room", room_name):
		return None
	r = frappe.db.get_value(
		"ERP Administrative Room",
		room_name,
		[
			"name",
			"title_vn",
			"title_en",
			"short_title",
			"physical_code",
			"room_type",
			"capacity",
			"building_id",
		],
		as_dict=True,
	)
	building_name = ""
	if r.building_id:
		building_name = frappe.db.get_value("ERP Administrative Building", r.building_id, "title_vn") or r.building_id
	return {
		"_id": r.name,
		"name": r.title_vn or r.physical_code or r.name,
		"room_name": r.title_vn or "",
		"short_title": r.short_title or "",
		"physical_code": r.physical_code or "",
		"room_type": r.room_type,
		"capacity": r.capacity,
		"building": building_name,
		"building_name": building_name,
		"building_id": r.building_id,
		"frappeRoomId": r.name,
	}


def _specs_from_doc(doc) -> Dict[str, Any]:
	dt = doc.device_type
	table = SPECS_TABLE.get(dt)
	if not table:
		return {}
	rows = doc.get(table) or []
	if not rows:
		return {}
	row = rows[0]
	specs = {}
	for fn in ("processor", "ram", "storage", "display", "ip"):
		if hasattr(row, fn):
			val = getattr(row, fn)
			if val:
				specs[fn] = val
	if dt == "phone":
		for fn in ("imei1", "imei2", "phone_number"):
			val = getattr(row, fn, None)
			if val:
				specs[fn] = val
	return specs


def get_assignment_history(device_name: str) -> List[Dict[str, Any]]:
	rows = frappe.get_all(
		"ERP Inventory Handover Log",
		filters={"device": device_name},
		fields=[
			"name",
			"user",
			"fullname_snapshot",
			"job_title_snapshot",
			"action",
			"start_date",
			"end_date",
			"notes",
			"assigned_by",
			"revoked_by",
			"revoked_reasons",
			"document_file_url",
		],
		order_by="start_date asc",
	)
	out = []
	for r in rows:
		revoked_reason = []
		if r.revoked_reasons:
			try:
				revoked_reason = json.loads(r.revoked_reasons)
			except Exception:
				revoked_reason = [r.revoked_reasons]
		entry = {
			"_id": r.name,
			"user": user_to_fe(r.user),
			"fullnameSnapshot": r.fullname_snapshot or "",
			"userName": r.fullname_snapshot or "",
			"fullname": r.fullname_snapshot or "",
			"jobTitle": r.job_title_snapshot or "",
			"startDate": r.start_date.isoformat() if r.start_date else None,
			"endDate": r.end_date.isoformat() if r.end_date else None,
			"notes": r.notes or "",
			"assignedBy": user_to_fe(r.assigned_by),
			"revokedBy": user_to_fe(r.revoked_by),
			"revokedReason": revoked_reason,
			"document": (r.document_file_url or "").split("/")[-1] if r.document_file_url else "",
		}
		out.append(entry)
	return out


def device_doc_to_fe(doc, include_history: bool = True) -> Dict[str, Any]:
	"""Chuyển ERP Inventory Device → shape FE (Mongo-compatible)."""
	specs = _specs_from_doc(doc)
	assigned = []
	for row in doc.assigned_users or []:
		u = user_to_fe(row.user)
		if u:
			assigned.append(u)

	current_holder = None
	if doc.current_holder_user:
		current_holder = {
			"id": doc.current_holder_user,
			"fullname": doc.current_holder_fullname or "",
			"jobTitle": doc.current_holder_jobtitle or "",
			"department": doc.current_holder_department or "",
			"avatarUrl": frappe.db.get_value("User", doc.current_holder_user, "user_image") or "",
		}

	result = {
		"_id": doc.name,
		"name": doc.name_display,
		"type": doc.device_subtype or doc.device_type,
		"device_type": doc.device_type,
		"manufacturer": doc.manufacturer or "",
		"serial": doc.serial,
		"releaseYear": doc.release_year,
		"status": doc.status,
		"brokenReason": doc.broken_reason,
		"brokenDescription": doc.broken_description,
		"assigned": assigned,
		"room": room_to_fe(doc.room),
		"currentHolder": current_holder,
		"specs": specs,
		"createdAt": doc.creation.isoformat() if doc.creation else None,
		"updatedAt": doc.modified.isoformat() if doc.modified else None,
	}
	if doc.device_type == "phone" and doc.specs_phone:
		row = doc.specs_phone[0]
		result["imei1"] = row.imei1 or ""
		result["imei2"] = row.imei2 or ""
		result["phoneNumber"] = row.phone_number or ""
	if include_history:
		result["assignmentHistory"] = get_assignment_history(doc.name)
	return result


def apply_specs_to_doc(doc, device_type: str, specs: Optional[Dict[str, Any]]):
	if not specs or not isinstance(specs, dict):
		return
	table = SPECS_TABLE.get(device_type)
	if not table:
		return
	row_data = {}
	field_map = {
		"processor": "processor",
		"ram": "ram",
		"storage": "storage",
		"display": "display",
		"ip": "ip",
		"imei1": "imei1",
		"imei2": "imei2",
		"phoneNumber": "phone_number",
		"phone_number": "phone_number",
	}
	for src, dst in field_map.items():
		if specs.get(src) is not None:
			row_data[dst] = specs.get(src)
	if device_type == "phone" and specs.get("imei1"):
		row_data["imei1"] = specs.get("imei1")
	doc.set(table, [])
	if row_data:
		doc.append(table, row_data)


def sync_assigned_users(doc, user_names: List[str]):
	doc.assigned_users = []
	for uid in user_names:
		if not uid:
			continue
		resolved = resolve_user_link(uid) or uid
		if not frappe.db.exists("User", resolved):
			continue
		fullname = frappe.db.get_value("User", resolved, "full_name") or resolved
		doc.append("assigned_users", {"user": resolved, "fullname_snapshot": fullname, "assigned_at": now_datetime()})


def sync_current_holder_from_assigned(doc):
	if doc.assigned_users:
		last = doc.assigned_users[-1]
		doc.current_holder_user = last.user
		doc.current_holder_fullname = last.fullname_snapshot or frappe.db.get_value("User", last.user, "full_name")
		doc.current_holder_jobtitle = frappe.db.get_value("User", last.user, "job_title") or frappe.db.get_value(
			"User", last.user, "designation"
		)
		doc.current_holder_department = frappe.db.get_value("User", last.user, "department") or ""
	else:
		doc.current_holder_user = None
		doc.current_holder_fullname = None
		doc.current_holder_jobtitle = None
		doc.current_holder_department = None


def build_device_filters(device_type: str, params: Dict[str, Any]):
	filters = [["device_type", "=", device_type]]
	search = (params.get("search") or "").strip()
	status = params.get("status")
	manufacturer = params.get("manufacturer")
	subtype = params.get("type")
	release_year = params.get("releaseYear") or params.get("release_year")

	if status:
		status_vals = [s.strip() for s in str(status).split(",") if s.strip()]
		if len(status_vals) == 1:
			filters.append(["status", "=", status_vals[0]])
		else:
			filters.append(["status", "in", status_vals])

	if manufacturer:
		manu_vals = [m.strip() for m in str(manufacturer).split(",") if m.strip()]
		if len(manu_vals) == 1:
			filters.append(["manufacturer", "like", f"%{manu_vals[0]}%"])
		else:
			filters.append(["manufacturer", "in", manu_vals])

	if subtype:
		type_vals = [t.strip() for t in str(subtype).split(",") if t.strip()]
		if len(type_vals) == 1:
			filters.append(["device_subtype", "like", f"%{type_vals[0]}%"])
		else:
			filters.append(["device_subtype", "in", type_vals])

	if release_year:
		filters.append(["release_year", "=", cint(release_year)])

	return filters, search


def paginated_devices_response(device_type: str, devices: List[Dict], page: int, limit: int, total: int):
	total_pages = max(1, (total + limit - 1) // limit) if limit else 1
	key = POPULATED_KEY[device_type]
	return {
		key: devices,
		"pagination": {
			"currentPage": page,
			"totalPages": total_pages,
			"totalItems": total,
			"itemsPerPage": limit,
			"hasNext": page < total_pages,
			"hasPrev": page > 1,
		},
	}
